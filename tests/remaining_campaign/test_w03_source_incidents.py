"""W03: product-level source incidents through the real FIRMS/GPM runners and plan CLI.

Invented HTTP answers only (``requests.adapters.HTTPAdapter.send`` is replaced and
DNS/socket connects are trapped). No real endpoint, key, token or provider body.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from src import state as state_mod
from src.data import _http, firms, source_incident_plan, source_incidents as si
from src.orchestrator.sources import firms as firms_runner
from src.orchestrator.sources import gpm_imerg as gpm_runner
from tests.live_content_harness import trap_network

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "w03_run_history.json"
INVENTED_KEY = "invented-map-key-w03"
HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,frp,daynight"


def _reply(request, status: int, body: str, content_type: str = "text/csv"):
    response = requests.models.Response()
    response.status_code, response.url, response.request = status, request.url, request
    response.reason = "Invented"
    response.headers = CaseInsensitiveDict({"content-type": content_type})
    response.raw, response.encoding = io.BytesIO(body.encode()), "utf-8"
    return response


def _rows(product: str, now: datetime, count: int = 2, frp: float = 12.0) -> str:
    sat = {"VIIRS_NOAA21_NRT": "N21", "VIIRS_NOAA20_NRT": "N20"}[product]
    stamp = now - timedelta(hours=1)
    lines = [HEADER] + [
        f"{-10.5 + i},{20.25 + i},330.1,0.4,0.4,{stamp:%Y-%m-%d},{stamp:%H%M},{sat},VIIRS,h,2.0NRT,{frp},D"
        for i in range(count)
    ]
    return "\n".join(lines) + "\n"


class World:
    """Per-product invented answers: (status, body) or an exception class."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[str] = []

    def send(self, _adapter, request, **_options):
        url = request.url
        assert url.startswith(("https://firms.modaps.eosdis.nasa.gov/", "https://satepsanone.nesdis.noaa.gov/")), url
        self.calls.append(url)
        key = "hms" if "satepsanone" in url else url.split("/")[-3]
        answer = self.answers.get(key, (404, "Not Found"))
        if isinstance(answer, type) and issubclass(answer, Exception):
            raise answer("invented transport failure")
        status, body = answer
        return _reply(request, status, body)


@pytest.fixture
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)
    monkeypatch.setattr(firms, "FIRMS_API_KEY", INVENTED_KEY)
    monkeypatch.setattr(_http, "_sleep_before_retry", lambda *_a, **_k: None)
    monkeypatch.setattr(_http, "_waf_sleep", lambda: None)

    def install(world: World):
        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send",
                            lambda adapter, request, **kw: world.send(adapter, request, **kw))
        return world
    return install


def _run(bot_state, index: int, world_install, answers):
    world = world_install(World(answers))
    run: dict = {"id": f"invented-run-{index}", "started_at": f"2026-10-2{index}T06:00:00Z", "sources": []}
    firms_runner.run_firms(bot_state, run)
    state_mod.finalize_run(bot_state, run)
    entry = next(row for row in run["sources"] if row["source"] == "firms")
    return entry, world


# --- classification --------------------------------------------------------------
@pytest.mark.parametrize(("status", "expected"), [
    (404, "endpoint_missing"), (410, "endpoint_missing"), (401, "access_refused"), (403, "access_refused"),
    (429, "rate_limited"), (503, "provider_error"), (302, "malformed"), (200, None)])
def test_status_classification_never_reads_404_as_no_events(status, expected):
    assert si.classify_status(status) == expected


@pytest.mark.parametrize(("body", "expected"), [
    ("<html><body>Service moved</body></html>", ("malformed", 0)),
    ("Invalid MAP_KEY.", ("access_refused", 0)),
    ("", ("malformed", 0)),
    (HEADER + "\n", ("empty_success", 0)),
    ("latitude,longitude\n1,2\n", ("malformed", 0)),
    (HEADER + "\n1,2,3,4,5,2026-10-29,0100,N21,VIIRS,h,2.0NRT,3,D\n", ("qualified", 1)),
])
def test_body_classification_separates_refusal_malformed_empty_and_rows(body, expected):
    assert si.classify_body(body, required_header=firms.FIRMS_FIELDS) == expected


def test_identity_keeps_product_window_region_and_parser_distinct():
    a = si.incident_key("firms.noaa_hms", window="current_utc_day_file", region="north_america", parser_contract="p")
    b = si.incident_key("firms.noaa_hms", window="current_utc_day_file", region="north_america", parser_contract="q")
    assert a != b
    with pytest.raises(ValueError):
        si.attempt("firms.not_a_product", "qualified", window="w", region="r", parser_contract="p")
    with pytest.raises(ValueError):
        si.attempt("firms.noaa_hms", "fine", window="w", region="r", parser_contract="p")


# --- real runner journey: 404 → HMS 404 → reachable-unqualified → qualified recovery ---
def test_firms_runner_incident_journey_reaches_run_history_and_projection(offline):
    bot_state = state_mod._fresh_state()
    now = datetime.now(UTC)

    entry, world = _run(bot_state, 1, offline, {"VIIRS_NOAA21_NRT": (404, "Not Found")})
    incident = entry["details"]["incident"]
    assert entry["status"] == "failed"
    assert [(a["product_id"], a["outcome"], a["http_status"]) for a in incident["attempts"]] == [
        ("firms.viirs_noaa21_nrt", "endpoint_missing", 404)]
    assert incident["product_state"] == "unavailable"  # one leg named; HMS was never reached
    assert len(world.calls) == 1  # 404 is not witness-eligible: no guessed replacement or fallback crawl

    entry, _ = _run(bot_state, 2, offline, {p: (503, "busy") for p in ("VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT")})
    outcomes = [(a["product_id"], a["outcome"]) for a in entry["details"]["incident"]["attempts"]]
    assert outcomes == [("firms.viirs_noaa21_nrt", "provider_error"), ("firms.viirs_noaa20_nrt", "provider_error"),
                        ("firms.modis_nrt", "provider_error"), ("firms.noaa_hms", "endpoint_missing")]
    # The fixed public text names neither the key nor the URL.
    assert INVENTED_KEY not in json.dumps(bot_state["source_health"]) + json.dumps(bot_state["run_history"])

    entry, _ = _run(bot_state, 3, offline, {p: (200, HEADER + "\n") for p in ("VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT")})
    assert entry["status"] == "success" and entry["details"]["incident"]["product_state"] == "reachable_unqualified"
    rows = {r["product_id"]: r for r in si.project_incidents(bot_state["run_history"], source="firms")}
    assert rows["firms.viirs_noaa21_nrt"]["state"] == "reachable_unqualified"  # transport cleared ≠ recovery

    entry, _ = _run(bot_state, 4, offline, {"VIIRS_NOAA21_NRT": (200, _rows("VIIRS_NOAA21_NRT", now))})
    assert entry["details"]["incident"]["product_state"] == "primary_qualified"
    rows = {r["product_id"]: r for r in si.project_incidents(bot_state["run_history"], source="firms")}
    primary = rows["firms.viirs_noaa21_nrt"]
    assert primary["state"] == "recovered" and primary["recovered_at"] == "2026-10-24T06:00:00Z"
    assert primary["failures"] == 3 and primary["first_failure"] == "2026-10-21T06:00:00Z"
    assert primary["failure_outcomes"] == ["endpoint_missing", "provider_error", "empty_success"]
    assert rows["firms.noaa_hms"]["state"] == "open"  # its own leg; FIRMS recovery does not close it


def test_alternate_product_serves_but_is_not_corroboration_or_primary_recovery(offline):
    bot_state = state_mod._fresh_state()
    now = datetime.now(UTC)
    entry, _ = _run(bot_state, 1, offline, {"VIIRS_NOAA21_NRT": (503, "busy"),
                                            "VIIRS_NOAA20_NRT": (200, _rows("VIIRS_NOAA20_NRT", now, frp=400.0))})
    incident = entry["details"]["incident"]
    assert entry["status"] == "degraded" and entry["note"] == "served via VIIRS_NOAA20_NRT"
    assert incident["product_state"] == "alternate_served"
    assert incident["served_product_ids"] == ["firms.viirs_noaa20_nrt"]
    assert incident["independent_source_upper_bound"] == 1
    assert si.run_incident("firms", [*incident["attempts"], si.attempt(
        "firms.noaa_hms", "qualified", window="current_utc_day_file", region="north_america",
        parser_contract="fire_source_contract.hms_text")])["independent_source_upper_bound"] == 1


def test_html_and_refusal_bodies_fail_as_malformed_and_access(offline):
    bot_state = state_mod._fresh_state()
    entry, _ = _run(bot_state, 1, offline, {"VIIRS_NOAA21_NRT": (200, "Invalid MAP_KEY.")})
    assert [a["outcome"] for a in entry["details"]["incident"]["attempts"]] == ["access_refused"]
    entry, _ = _run(bot_state, 2, offline, {"VIIRS_NOAA21_NRT": (200, "<html>maintenance</html>")})
    assert [a["outcome"] for a in entry["details"]["incident"]["attempts"]] == ["malformed"]
    assert entry["status"] == "failed"


# --- GPM / Earthdata owner-access boundary ----------------------------------------
class _Trace:
    def __init__(self, doc):
        self.doc = doc

    def export(self):
        return self.doc


def test_gpm_trace_maps_gate_refusal_granule_and_partial_batch():
    expired = gpm_runner._trace_details(_Trace({"schema": "x", "primary_gate": "credential_expired", "product": "late",
                                                "legs": []}))
    assert [a["outcome"] for a in expired["incident"]["attempts"]] == ["access_expired"]
    assert expired["incident"]["product_state"] == "access_hold"
    refused = si.gpm_attempts({"legs": [{"leg": "imerg_late_opendap", "outcome": "not_finished",
                                         "dispositions": "fp", "failure_signatures": {"HTTP 401": 1}}]})
    assert [a["outcome"] for a in refused] == ["access_refused"]
    missing = si.gpm_attempts({"legs": [{"leg": "imerg_late_grid_datapool", "outcome": "unavailable",
                                         "reason": "not_found"}]})
    assert [a["outcome"] for a in missing] == ["granule_missing"]
    partial = si.gpm_attempts({"legs": [{"leg": "imerg_late_opendap", "outcome": "served", "dispositions": "rrfrf",
                                         "failure_signatures": {"Timeout": 2}}]})
    assert partial[0]["outcome"] == "qualified" and partial[0]["detail"] == {"failed_members": 2, "read_members": 3}


def test_earthdata_hold_is_named_without_loop_and_attestation_does_not_requalify():
    history = json.loads(FIXTURE.read_text())["run_history"]
    # Before the qualified grid run: a named owner hold.
    earlier = [run for run in history if run["started_at"] < "2026-10-24"]
    hold = si.earthdata_access_hold(si.project_incidents(earlier))
    assert hold is not None
    assert hold["stage"] == "access_refused" and hold["login_loop"] is False
    assert hold["credential_search"] == "not_performed" and hold["requalifies_prior_observations"] is False
    attestation = {"schema": si.ATTESTATION_SCHEMA, "provider": "earthdata", "action": "token_renewed",
                   "attested_at": "2026-10-23T12:00:00Z", "attested_by": "owner",
                   "evidence_reference": "owner note 2026-10-23"}
    attested = si.earthdata_access_hold(si.project_incidents(earlier), attestation=attestation)
    assert attested is not None
    assert attested["stage"] == "renewal_attested_awaiting_qualified_run"
    assert attested["requalifies_prior_observations"] is False
    # A later qualified GES DISC result establishes access; nothing earlier changes.
    assert si.earthdata_access_hold(si.project_incidents(history)) is None
    for bad in ({**attestation, "token": "x"}, {**attestation, "attested_by": "claude"},
                {**attestation, "evidence_reference": "Bearer " + "A" * 60 + " token"}):
        with pytest.raises(ValueError):
            si.validate_access_attestation(bad)


# --- shared projection fixture (Python ↔ dashboard parity) --------------------------
def test_projection_matches_shared_fixture_expectations():
    fixture = json.loads(FIXTURE.read_text())
    rows = {r["key"]: r for r in si.project_incidents(fixture["run_history"])}
    assert set(rows) == set(fixture["expected"])
    for key, expected in fixture["expected"].items():
        assert {k: rows[key][k] for k in expected} == expected
    summary = si.recovery_summary(list(rows.values()))
    assert summary["states"]["recovered"] == ["firms.viirs_noaa21_nrt"]


# --- offline plan CLI ---------------------------------------------------------------
def _cli(*args: str) -> subprocess.CompletedProcess:
    code = ("import socket\n"
            "def refuse(*a, **k):\n    raise AssertionError('network trapped')\n"
            "socket.getaddrinfo = socket.create_connection = refuse\n"
            "socket.socket.connect = socket.socket.connect_ex = refuse\n"
            "import runpy, sys\nsys.argv = sys.argv[1:]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n")
    return subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts/source_incident_plan.py"), *args],
                          capture_output=True, text=True, cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                          timeout=60, check=False)


def test_plan_cli_names_exact_next_actions_offline(tmp_path):
    fixture = json.loads(FIXTURE.read_text())
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"run_history": fixture["run_history"]}))
    result = _cli("plan", "--state", str(state_path))
    assert result.returncode == 1, result.stderr
    plan = json.loads(result.stdout)
    assert plan["network"] == "not_used" and plan["self_heal"]["paid_repair"] == "not_invoked_by_this_plan"
    by_product = {a["product_id"]: a for a in plan["actions"]}
    assert by_product["firms.noaa_hms"]["action"] == "operator_endpoint_confirmation_required"
    assert by_product["firms.viirs_noaa20_nrt"]["state"] == "reachable_unqualified"
    assert "firms.viirs_noaa21_nrt" not in by_product  # recovered by a qualified result

    same = {"schema": source_incident_plan.CONFIRMATION_SCHEMA, "product_id": "firms.noaa_hms",
            "endpoint_template": source_incident_plan.CURRENT_ENDPOINTS["firms.noaa_hms"],
            "confirmed_at": "2026-10-29T09:00:00Z", "confirmed_by": "operator",
            "evidence_reference": "provider product page read by operator"}
    path = tmp_path / "confirm.json"
    path.write_text(json.dumps(same))
    assert _cli("validate-input", "--endpoint-confirmation", str(path)).returncode == 0
    plan = json.loads(_cli("plan", "--state", str(state_path), "--endpoint-confirmation", str(path)).stdout)
    assert {a["product_id"]: a for a in plan["actions"]}["firms.noaa_hms"]["action"] == "confirmed_endpoint_still_missing"
    path.write_text(json.dumps({**same, "endpoint_template": "https://example.invalid/fire/{yyyymmdd}.txt"}))
    plan = json.loads(_cli("plan", "--state", str(state_path), "--endpoint-confirmation", str(path)).stdout)
    assert {a["product_id"]: a for a in plan["actions"]}["firms.noaa_hms"]["action"] == "code_change_review_required"

    leaked = {**same, "endpoint_template": "https://firms.example.invalid/api/" + "a1b2c3d4" * 4 + "/x"}
    path.write_text(json.dumps(leaked))
    refused = _cli("validate-input", "--endpoint-confirmation", str(path))
    assert refused.returncode == 2 and "credential_like" in refused.stdout
    assert _cli("plan").returncode == 64
