"""P16 repair: staged promotion keeps the count-capped logs' own append-then-keep-last-N contract.

Two shared state lists are truncated by their writers and written by concurrent SourceRunners:

* ``errors``: ``state.log_error`` appends one row, then keeps the last 50;
* ``suppressions``: every writer (``_record_suppression``, ``_record_downstream_suppression``,
  ``_record_triage_error_suppression``, ``_record_billing_cycle_abort_suppression``, triage's cap row)
  appends one row under ``_SUPPRESSIONS_LOCK``, then keeps the last ``MAX_SUPPRESSIONS``.

Neither dedups. Serial in declaration order is ``(base + first's rows + second's rows)[-N:]``. A stage
whose own rows push out every base row is that writer, not a replacement; two stages appending to a full
log must keep N rows, not N+1. Anything the writer cannot produce still refuses.

Every byte is invented and offline. The NWS and USGS SourceRunners are the exact closures ``run_alerts``
builds: real fetchers, parsers, scoring with the real ``_should_draft`` near-miss suppression, the real
evidence audit in ``_enqueue_story_candidate`` and the real ``log_error`` failure path; only the HTTP session
is an explicit fixture. No real concurrent source logs 50 errors in one run (each failure path logs one row;
``run_fire_footprint`` logs per complex only when a complex raises), so that boundary uses the real
``state.log_error`` on the staged states.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import time
from typing import Any

import pytest

from src import state
from src.data import _http, co2 as co2_data, nws_alerts
from src.editorial.scoring import score_usgs_earthquake
from src.orchestrator import scheduler, staging, suppression
from src.orchestrator.scheduler import SourceRunner
from src.state import _fresh_state
from src.two_bot import call_inventory as inv
from src.two_bot import usage_ledger
from tests import live_content_harness as h
from tests.real_closure import p16_fixtures as fx

NWS_ID = "nws_urn:oid:invented-cap-warning"
USGS_ID = "usgs_eq_inv0001"
ORDERS = [pytest.param(("nws_alerts", "usgs_quakes"), id="nws_first"),
          pytest.param(("usgs_quakes", "nws_alerts"), id="usgs_first")]
ERRORS_CAP = 50
SUPPRESSIONS_CAP = state.MAX_SUPPRESSIONS


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.trap_network(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_FUNNEL_TELEMETRY", "1")
    monkeypatch.delenv("SUPPRESSION_NEAR_MISS_GAP", raising=False)
    monkeypatch.setattr(co2_data, "_CO2_REVALIDATION_CACHE", {})
    monkeypatch.setattr(inv, "_CANCELLED", {})
    monkeypatch.setattr(inv, "_UNJOINED", {})
    monkeypatch.setattr(usage_ledger, "_BUFFER", [])
    monkeypatch.setattr(staging, "_LATE", [])
    yield
    suppression._clear_suppression_ctx()


def _live() -> tuple[Any, dict]:
    return _fresh_state(), {"id": "run_p16_capped", "sources": []}


def _old_suppressions(n: int) -> list[dict]:
    return [{"id": f"supp_invented_old_{i:03d}", "ts": "2026-10-01T00:00:00Z", "run_id": "invented_old",
             "source": "invented_old", "stage": "score_gate", "event_id": f"invented_old_{i:03d}"} for i in range(n)]


def _old_errors(n: int) -> list[dict]:
    return [{"source": "invented_old", "ts": f"2026-10-01T00:00:{i:02d}.{i:06d}Z", "msg": f"invented old error {i}"}
            for i in range(n)]


# --- invented offline feeds for the real runners -------------------------------------------------------

def _nws_feature(alert_id: str, *, area: str = "Invented County, FL") -> dict:
    now = datetime.now(UTC)
    return {"type": "Feature", "geometry": None, "properties": {
        "id": alert_id, "event": "Extreme Wind Warning", "areaDesc": area, "severity": "Extreme",
        "headline": "Invented extreme wind warning", "description": "Invented official warning",
        "sent": now.isoformat(), "effective": now.isoformat(), "onset": now.isoformat(),
        "expires": (now + timedelta(hours=2)).isoformat(), "status": "Actual", "messageType": "Alert",
        "category": "Met", "certainty": "Observed", "urgency": "Immediate",
        "senderName": "NWS Invented Office", "parameters": {}}}


def _nws_body(*, refused: int = 0) -> str:
    """One admitted warning, plus ``refused`` area-less ones the real evidence audit suppresses."""
    features = [_nws_feature("urn:oid:invented-cap-warning")]
    features += [_nws_feature(f"urn:oid:invented-no-area-{i}", area="") for i in range(refused)]
    return json.dumps({"type": "FeatureCollection", "features": features})


def _quake(code: str, *, near_miss: bool) -> dict:
    now = int(time.time() * 1000) - 3_600_000
    mag, alert, sig, tsunami = (6.5, "green", 700, 0) if near_miss else (7.4, "orange", 1100, 1)
    return {"type": "Feature", "id": code,
            "properties": {"mag": mag, "place": f"120 km S of Invented Bay {code}", "time": now, "updated": now,
                           "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{code}", "alert": alert,
                           "sig": sig, "tsunami": tsunami, "title": f"M {mag} - Invented Bay"},
            "geometry": {"type": "Point", "coordinates": [150.1, -10.2, 30.0]}}


def _usgs_body(*, near_misses: int = 0) -> str:
    """One admitted quake plus ``near_misses`` the real score gate records as near-miss suppressions."""
    now = int(time.time() * 1000) - 3_600_000
    features = [_quake("inv0001", near_miss=False)] + [_quake(f"near{i:03d}", near_miss=True)
                                                       for i in range(near_misses)]
    return json.dumps({"type": "FeatureCollection", "metadata": {"generated": now}, "features": features})


def _real_runners(monkeypatch, live: dict, run: dict, routes: dict) -> dict:
    runners = fx.production_runners(monkeypatch, live, run)
    monkeypatch.setattr(_http, "_session", fx.BlockingTransport(routes, hold=set()))
    return runners


def _source_rows(run: dict, names) -> list[tuple]:
    return [(r["source"], r["status"]) for r in run["sources"] if r["source"] in names]


def _new_rows(stage: staging.WorkerStage, key: str, base: list) -> list:
    """The rows a stage appended (its private list minus the base rows it kept)."""
    rows = stage.state[key]
    kept = [row for row in rows if row in base]
    return rows[len(kept):]


def _serial(base: list, owner: staging.Owner, key: str, cap: int) -> list:
    rows = list(base)
    for stage in owner.stages:
        rows = (rows + _new_rows(stage, key, base))[-cap:]
    return rows


# --- (a) one real source's own suppressions push out every base row -------------------------------------

@pytest.mark.parametrize("order", ORDERS)
def test_one_real_source_pushing_out_every_base_suppression_does_not_discard_the_other(monkeypatch, order):
    live, run = _live()
    base = _old_suppressions(SUPPRESSIONS_CAP)
    live["suppressions"] = [dict(r) for r in base]
    runners = _real_runners(monkeypatch, live, run, {nws_alerts.NWS_URL: _nws_body(refused=1),
                                                     fx.USGS_URL: _usgs_body(near_misses=SUPPRESSIONS_CAP)})

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[runners[s] for s in order], budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert _source_rows(run, order) == [(s, "success") for s in order]
    assert [c.event_id for c in live["_triage_queue"]] == [{"nws_alerts": NWS_ID, "usgs_quakes": USGS_ID}[s]
                                                           for s in order]
    by_source = {s.source: _new_rows(s, "suppressions", base) for s in owner.stages}
    assert len(by_source["usgs_quakes"]) == SUPPRESSIONS_CAP  # Its own rows left no base row.
    assert [r["stage"] for r in by_source["nws_alerts"]] == ["evidence_contract"]
    assert live["suppressions"] == _serial(base, owner, "suppressions", SUPPRESSIONS_CAP)
    assert len(live["suppressions"]) == SUPPRESSIONS_CAP
    expected_tail = by_source["usgs_quakes"] if order[0] == "nws_alerts" else (
        by_source["usgs_quakes"][1:] + by_source["nws_alerts"])
    assert live["suppressions"] == expected_tail


# --- (b) two real sources each append to a log already at its cap ---------------------------------------

@pytest.mark.parametrize("order", ORDERS)
def test_two_real_sources_appending_to_a_full_suppression_log_keep_the_serial_last_n(monkeypatch, order):
    live, run = _live()
    base = _old_suppressions(SUPPRESSIONS_CAP)
    live["suppressions"] = [dict(r) for r in base]
    runners = _real_runners(monkeypatch, live, run, {nws_alerts.NWS_URL: _nws_body(refused=1),
                                                     fx.USGS_URL: _usgs_body(near_misses=1)})

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[runners[s] for s in order], budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert _source_rows(run, order) == [(s, "success") for s in order]
    first, second = (_new_rows(s, "suppressions", base) for s in owner.stages)
    assert len(first) == len(second) == 1
    # Serial: N rows, the two oldest gone; not N+1.
    assert live["suppressions"] == base[2:] + first + second


@pytest.mark.parametrize("order", ORDERS)
def test_two_real_failing_sources_on_a_full_error_log_keep_the_serial_last_50(monkeypatch, order):
    live, run = _live()
    base = _old_errors(ERRORS_CAP)
    live["errors"] = [dict(r) for r in base]
    runners = _real_runners(monkeypatch, live, run, {nws_alerts.NWS_URL: "invented malformed body",
                                                     fx.USGS_URL: "invented malformed body"})

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[runners[s] for s in order], budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert _source_rows(run, order) == [(s, "failed") for s in order]
    first, second = (_new_rows(s, "errors", base) for s in owner.stages)
    assert [r["source"] for r in first + second] == list(order)
    assert live["errors"] == base[2:] + first + second


@pytest.mark.parametrize("order", ORDERS)
def test_synthesis_sees_the_serial_suppression_log(monkeypatch, order):
    live, run = _live()
    base = _old_suppressions(SUPPRESSIONS_CAP)
    live["suppressions"] = [dict(r) for r in base]
    runners = _real_runners(monkeypatch, live, run, {nws_alerts.NWS_URL: _nws_body(refused=1),
                                                     fx.USGS_URL: _usgs_body(near_misses=SUPPRESSIONS_CAP)})
    seen: dict = {}

    def observe(bs, current):
        seen["suppressions"] = [r["id"] for r in bs["suppressions"]]
        runners["__synthesis__"].run(bs, current)

    owner = scheduler.run_stage1_then_synthesis(
        live, run, serial_runners=[], concurrent_runners=[runners[s] for s in order],
        synthesis_runner=SourceRunner("synthesis_fire_drought_heat", observe), budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert seen["suppressions"] == [r["id"] for r in _serial(base, owner, "suppressions", SUPPRESSIONS_CAP)]


# --- (a)/(b) for errors with the real writer on the staged states --------------------------------------

def _logger(name: str, count: int):
    def run_fn(bs, current):
        for i in range(count):
            state.log_error(bs, name, f"{name} error {i}")
    return SourceRunner(name, run_fn)


@pytest.mark.parametrize("base_rows", [ERRORS_CAP, 30, ERRORS_CAP + 5], ids=["full", "partial", "oversize"])
@pytest.mark.parametrize("busy_first", [True, False], ids=["busy_first", "quiet_first"])
@pytest.mark.parametrize("busy_rows", [ERRORS_CAP, ERRORS_CAP + 7, 1], ids=["cap", "over_cap", "one"])
def test_error_appends_from_two_stages_land_exactly_like_serial(base_rows, busy_first, busy_rows):
    live, run = _live()
    base = _old_errors(base_rows)
    live["errors"] = [dict(r) for r in base]
    busy, quiet = _logger("invented_busy", busy_rows), _logger("invented_quiet", 1)

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], budget_seconds=10,
                                         concurrent_runners=[busy, quiet] if busy_first else [quiet, busy])

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    serial: Any = {"errors": [dict(r) for r in base]}
    for runner in ([busy, quiet] if busy_first else [quiet, busy]):
        runner.run(serial, None)  # The same writer, one after the other on one state.
    assert [(r["source"], r["msg"]) for r in live["errors"]] == [(r["source"], r["msg"]) for r in serial["errors"]]
    assert len(live["errors"]) == min(len(base) + busy_rows + 1, ERRORS_CAP)  # Never cap + 1.


# --- shapes the writers cannot make still refuse ---------------------------------------------------------

def _shape(kind: str):
    def run_fn(bs, current):
        rows = bs["errors"]
        if kind == "short_replacement":  # No base row kept, and fewer rows than the cap.
            bs["errors"] = [{"source": "invented_shape", "ts": "t", "msg": "only"}]
        elif kind == "middle_removed":
            del rows[5]
            rows.append({"source": "invented_shape", "ts": "t", "msg": "after a middle removal"})
        elif kind == "head_drop_below_cap":  # Dropped head rows although the log is under its cap.
            bs["errors"] = rows[2:] + [{"source": "invented_shape", "ts": "t", "msg": "early truncation"}]
        elif kind == "reordered":
            rows.reverse()
            rows.append({"source": "invented_shape", "ts": "t", "msg": "after a reorder"})
        elif kind == "over_cap":
            rows.extend({"source": "invented_shape", "ts": "t", "msg": f"untruncated {i}"} for i in range(60))
        elif kind == "drop_without_append":
            del rows[0]
    return run_fn


@pytest.mark.parametrize("kind", ["short_replacement", "middle_removed", "head_drop_below_cap", "reordered",
                                  "over_cap", "drop_without_append"])
def test_error_log_edits_the_writer_cannot_make_conflict(monkeypatch, kind):
    live, run = _live()
    base = _old_errors(ERRORS_CAP if kind == "short_replacement" else 20)
    live["errors"] = [dict(r) for r in base]
    runners = _real_runners(monkeypatch, live, run, {nws_alerts.NWS_URL: "invented malformed body"})

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[], budget_seconds=10,
        concurrent_runners=[runners["nws_alerts"], SourceRunner("invented_shape", _shape(kind))])

    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:errors"]
    nws_rows = _new_rows(owner.stages[0], "errors", base)
    assert [r["source"] for r in nws_rows] == ["nws_alerts"]
    assert live["errors"] == (base + nws_rows)[-ERRORS_CAP:]


# --- the registered caps are the real writers' caps ---------------------------------------------------

def test_the_capped_log_registry_is_exactly_what_the_real_writers_keep():
    caps = staging.capped_logs()
    assert caps == {"errors": ERRORS_CAP, "suppressions": SUPPRESSIONS_CAP}

    bs: Any = {}
    for i in range(caps["errors"] + 9):
        state.log_error(bs, "invented_cap", f"error {i}")
    assert len(bs["errors"]) == caps["errors"] and bs["errors"][-1]["msg"] == f"error {caps['errors'] + 8}"

    score = score_usgs_earthquake(6.5, "green", 700, 0)  # A real near-miss score.
    assert not score.passes
    writers = [
        lambda s, i: suppression._record_suppression(bot_state=s, source="invented_cap", run_id="r",
                                                     event_id=f"e{i}", score=score, summary=None),
        lambda s, i: suppression._record_downstream_suppression(
            bot_state=s, source="invented_cap", run_id="r", event_id=f"e{i}", score=score,
            kill_stage="evidence_contract", kill_reason="invented", summary=None),
        lambda s, i: suppression._record_triage_error_suppression(s, f"invented triage error {i}"),
    ]
    for write in writers:
        bs = {}
        for i in range(caps["suppressions"] + 9):
            write(bs, i)
        assert len(bs["suppressions"]) == caps["suppressions"]
