"""Milestone A: a qualified Hot10 from provider provenance to an offline automatic post.

A1 provenance and ten unique qualified places (or a hold); A2 the disclosed
universe and every qualification edge; A3 the actual writer request/parser and
every required check behind provider-shaped SDK transports, through admission and
Gist serialization; A4 the real ``python -m src.main leaderboard`` and
``auto_publish_due`` CLI in fresh processes, with an invented X receipt.

Invented values only (catalogue city names resolve to registered places). Named
fake boundaries: see tests/live_content_harness.py. No synthetic provenance
fixture is used: every positive bundle carries the real adapter's evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.data import open_meteo
from src.data.temperature_evidence import FORECAST_PRODUCT
from src.editorial import hot10_contract as contract
from src.state import DEFAULT_STATE
from tests import live_content_harness as h

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)  # Every catalogue zone is on 2026-10-29 here.
EPOCH = "invented-hot10-epoch-0001"
GOOD_COPY = ("Riyadh's forecast high of 39.2°C runs 9.2°C above its October normal, the largest departure "
             "among 14 sampled cities.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    h.trap_network(monkeypatch.setattr)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def city_temps(now: datetime = T0, cities=h.CITIES, **options) -> list:
    return h.city_temps(now, cities, **options)


def normals_for(tmp_path: Path, rows: list[dict]) -> dict:
    path = tmp_path / "normals.csv"
    h.write_normals(path, rows)
    return open_meteo.load_normals(str(path))


# ---------------------------------------------------------------- A2: qualification


def test_universe_is_disclosed_with_every_exclusion_counted(tmp_path):
    result = contract.qualify(city_temps(), normals_for(tmp_path, h.normal_rows(10)), sampled=20, now=T0)
    assert result["complete"] is True and len(result["rows"]) == 10
    universe = result["universe"]
    assert universe["sampled_cities"] == 20 and universe["returned_forecasts"] == 14
    assert universe["qualified_cities"] == 12
    assert universe["excluded"] == {"ambiguous_normal": 1, "missing_normal": 1}
    assert universe["local_days"] == ["2026-10-29"] and universe["scope"] == contract.UNIVERSE_SCOPE
    assert [row["city"] for row in result["rows"]][:3] == ["Riyadh", "Baghdad", "Cairo"]
    assert len({row["place_id"] for row in result["rows"]}) == 10
    leader = result["rows"][0]
    assert leader["forecast"]["source_product"] == FORECAST_PRODUCT and leader["forecast"]["revision_id"]
    assert leader["baseline"]["source_product"] == contract.BASELINE_PRODUCT
    assert leader["baseline"]["period_start"] == 1991 and leader["baseline"]["period_end"] == 2020
    assert leader["row_fingerprint"] == contract.row_fingerprint(leader)


def test_legacy_name_only_normals_qualify_nothing(tmp_path):
    legacy = tmp_path / "legacy.csv"
    legacy.write_text("city,month,avg_high_c\n" + "".join(f"{name},10,30.0\n" for name, _z, _k in h.CITIES))
    result = contract.qualify(city_temps(), open_meteo.load_normals(str(legacy)), sampled=14, now=T0)
    assert result["rows"] == [] and result["complete"] is False
    assert result["universe"]["excluded"] == {"missing_normal": 14}


def test_unqualified_product_and_undated_normals_are_excluded(tmp_path):
    rows = h.normal_rows(10)
    for row in rows[:2]:
        row["retrieved_at"] = "2026-01-15T00:00:00"  # No timezone: not an attributable retrieval.
    normals = normals_for(tmp_path, rows)
    result = contract.qualify(city_temps(), normals, sampled=14, now=T0)
    assert result["universe"]["excluded"]["unqualified_normal"] == 2 and result["complete"] is True
    assert {"Riyadh", "Baghdad"}.isdisjoint(row["city"] for row in result["rows"])


@pytest.mark.parametrize(("mutate", "reason"), [
    (lambda ct: ct.evidence.pop("revision_id"), "forecast_unqualified"),
    (lambda ct: setattr(ct, "temp_high_c", float("nan")), "forecast_unqualified"),
    (lambda ct: ct.evidence.update(source_product="openmeteo-era5-daily-v2"), "forecast_unqualified"),
    (lambda ct: ct.evidence.update(evidence_type="observed"), "forecast_unqualified"),
    (lambda ct: ct.evidence.pop("valid_end"), "missing_valid_time"),
    (lambda ct: setattr(ct, "signal_date", date(2026, 10, 28)), "missing_valid_time"),
    (lambda ct: ct.evidence.update(retrieved_at="2026-10-29T09:00:00"), "forecast_unqualified"),
])
def test_partial_rows_are_excluded_never_repaired(tmp_path, mutate, reason):
    temps = city_temps()
    mutate(temps[0])  # Riyadh, the would-be leader.
    result = contract.qualify(temps, normals_for(tmp_path, h.normal_rows(10)), sampled=14, now=T0)
    assert result["universe"]["excluded"].get(reason) == 1
    assert result["rows"][0]["city"] == "Baghdad"


def test_stale_future_and_wrong_local_day_captures_hold(tmp_path):
    normals = normals_for(tmp_path, h.normal_rows(10))
    # Capture time is checked before any normal: every returned forecast is excluded.
    stale = contract.qualify(city_temps(captured=T0 - timedelta(hours=13)), normals, sampled=14, now=T0)
    assert stale["universe"]["excluded"] == {"stale_capture": 14} and stale["rows"] == []
    future = contract.qualify(city_temps(captured=T0 + timedelta(minutes=30)), normals, sampled=14, now=T0)
    assert future["universe"]["excluded"] == {"future_capture": 14} and future["complete"] is False
    tomorrow = contract.qualify(city_temps(day_shift=1), normals, sampled=14, now=T0)
    assert tomorrow["universe"]["excluded"] == {"wrong_local_day": 14} and tomorrow["rows"] == []
    recent = contract.qualify(city_temps(captured=T0 - timedelta(hours=1)), normals, sampled=14, now=T0)
    assert recent["complete"] is True


def test_mixed_local_dates_are_disclosed_and_scoped(tmp_path):
    late = datetime(2026, 10, 29, 14, 30, tzinfo=UTC)  # Sydney (UTC+11) is already on 2026-10-30.
    cities = [c if c[0] != "Sydney" else ("Sydney", c[1], 7.0) for c in h.CITIES]
    result = contract.qualify(city_temps(late, cities), normals_for(tmp_path, h.normal_rows(10, cities=cities)),
                              sampled=14, now=late)
    assert result["universe"]["local_days"] == ["2026-10-29", "2026-10-30"]
    sydney = next(row for row in result["rows"] if row["city"] == "Sydney")
    assert sydney["valid_date"] == "2026-10-30" and sydney["timezone"] == "Australia/Sydney"
    assert result["rows"][0]["valid_date"] == "2026-10-29"  # Each row keeps its own provider-local day.
    from src.two_bot.intern import build_hot10_bundle
    bundle = build_hot10_bundle(result["rows"], changes=[], event_id="hot10_2026-10-29", universe=result["universe"])
    facts = {fact["label"]: fact["value"] for fact in bundle.current_facts}
    assert "more than one local date" in facts["date_scope"] and facts["valid_dates"] == ["2026-10-29", "2026-10-30"]


@pytest.mark.parametrize("edge", ["ended", "not_started", "reversed"])
def test_qualification_excludes_a_row_outside_its_interval(tmp_path, edge):
    temps = city_temps()
    target = temps[0]
    if edge == "ended":
        target.evidence["valid_end"] = _iso(T0)
    elif edge == "not_started":
        target.evidence["valid_start"] = _iso(T0 + timedelta(seconds=1))
    else:
        target.evidence["valid_start"], target.evidence["valid_end"] = (
            target.evidence["valid_end"], target.evidence["valid_start"])
    result = contract.qualify(temps, normals_for(tmp_path, h.normal_rows(10)), sampled=14, now=T0)
    reason = "missing_valid_time" if edge == "reversed" else "wrong_local_day"
    assert result["universe"]["excluded"][reason] == 1
    assert result["rows"][0]["city"] == "Baghdad" and result["complete"] is True


def test_qualification_excludes_a_day_that_ended_after_retrieval(tmp_path):
    captured = datetime(2026, 10, 29, 12, 55, tzinfo=UTC)
    cities = [c if c[0] != "Sydney" else ("Sydney", c[1], 7.0) for c in h.CITIES]
    result = contract.qualify(city_temps(captured, cities), normals_for(tmp_path, h.normal_rows(10, cities=cities)),
                              sampled=14, now=datetime(2026, 10, 29, 13, 0, tzinfo=UTC))
    assert result["universe"]["excluded"]["wrong_local_day"] == 1
    assert "Sydney" not in {row["city"] for row in result["rows"]}


def test_ties_rank_deterministically_and_duplicates_count_once(tmp_path):
    tied = [(name, zone, 5.0 if isinstance(kind, float) else kind) for name, zone, kind in h.CITIES]
    normals = normals_for(tmp_path, h.normal_rows(10, cities=tied))
    temps = city_temps(cities=tied)
    first = contract.qualify(temps, normals, sampled=14, now=T0)
    second = contract.qualify(list(reversed(temps)), normals, sampled=14, now=T0)
    assert [row["place_id"] for row in first["rows"]] == [row["place_id"] for row in second["rows"]]
    assert [row["place_id"] for row in first["rows"]] == sorted(row["place_id"] for row in first["rows"])
    doubled = contract.qualify(temps + [deepcopy(temps[0])], normals, sampled=14, now=T0)
    assert doubled["universe"]["excluded"]["duplicate_location"] == 1


def test_implausible_and_unregistered_rows_are_excluded(tmp_path):
    temps = city_temps()
    temps[0].temp_high_c = 75.0  # +45 C: a data error, never a leader.
    stray = deepcopy(temps[1])
    stray.city, stray.lat = "Invented Place", 33.9
    result = contract.qualify(temps + [stray], normals_for(tmp_path, h.normal_rows(10)), sampled=15, now=T0)
    excluded = result["universe"]["excluded"]
    assert excluded["implausible_anomaly"] == 1 and excluded["unregistered_location"] == 1
    assert result["rows"][0]["city"] == "Baghdad"


def test_fewer_than_ten_is_incomplete(tmp_path):
    nine = [c for c in h.CITIES if c[0] in {"Riyadh", "Baghdad", "Cairo", "Delhi", "Karachi", "Phoenix", "Madrid",
                                            "Athens", "Lagos"}]
    result = contract.qualify(city_temps(cities=nine), normals_for(tmp_path, h.normal_rows(10, cities=nine)),
                              sampled=9, now=T0)
    assert result["complete"] is False and len(result["rows"]) == 9


# ---------------------------------------------------------------- A1: the retained bulletin


def qualified_bundle(tmp_path, now=T0):
    from src.two_bot.intern import build_hot10_bundle

    result = contract.qualify(city_temps(now), normals_for(tmp_path, h.normal_rows(10)), sampled=14, now=now)
    return build_hot10_bundle(result["rows"], changes=["Riyadh NEW to the Hot 10"], event_id="hot10_2026-10-29",
                              universe=result["universe"])


def test_bundle_carries_actual_provider_provenance_through_the_source_boundary(tmp_path):
    from src.two_bot.evidence_contract import audit_story_bundle

    bundle = qualified_bundle(tmp_path)
    raw = bundle.raw_signal_dump
    assert raw["schema"] == contract.SCHEMA and raw["source_name"] == "Open-Meteo"
    assert raw["source_product"] == FORECAST_PRODUCT and raw["source_url"] == contract.FORECAST_URL
    assert raw["evidence"] == {"domain": "temperature_ranking", "evidence_type": "forecast",
                               "source_product": FORECAST_PRODUCT, "baseline_product": contract.BASELINE_PRODUCT,
                               "aggregation": "local_daily_extreme", "unit": "C", "valid_dates": ["2026-10-29"]}
    assert "baseline" not in raw["evidence"]  # Never an ERA5 record comparison.
    assert contract.validate_bundle(bundle) == [] and contract.current_hold(bundle, T0) is None
    audit = audit_story_bundle(bundle)
    assert audit.prompt_ready, audit.issues
    facts = {fact["label"]: fact["value"] for fact in bundle.current_facts}
    assert facts["sampled_cities"] == 14 and facts["qualified_cities"] == 12 and facts["excluded_cities"] == 2
    assert "not the hottest places on Earth" in facts["claim_limit"]
    assert len(json.dumps(bundle.to_dict()).encode()) < 24_000


@pytest.mark.parametrize("tamper", [
    lambda raw: raw["cities"][3].update(temp_high_c=raw["cities"][3]["temp_high_c"] + 1),
    lambda raw: raw["cities"].reverse(),
    lambda raw: raw["cities"].pop(),
    lambda raw: raw["cities"].__setitem__(4, deepcopy(raw["cities"][3])),
    lambda raw: raw["universe"].update(qualified_cities=9),
    lambda raw: raw.update(source_url="https://example.invalid/forecast"),
    lambda raw: raw["cities"][0]["baseline"].update(source_product="legacy-city-month"),
])
def test_changed_retained_bulletins_fail_their_contract(tmp_path, tamper):
    bundle = qualified_bundle(tmp_path)
    retained = deepcopy(bundle.to_dict())
    tamper(retained["raw_signal_dump"])
    assert contract.validate_bundle(retained)
    assert str(contract.current_hold(retained, T0)).startswith("hot10_contract_invalid:")


def test_final_boundary_holds_an_over_or_stale_local_day(tmp_path):
    bundle = qualified_bundle(tmp_path).to_dict()
    first_ranked_midnight = datetime(2026, 10, 29, 17, 0, tzinfo=UTC)  # Bangkok, before leader Riyadh.
    assert contract.current_hold(bundle, first_ranked_midnight - timedelta(minutes=1)) is None
    assert contract.current_hold(bundle, first_ranked_midnight) == "hot10_local_day_over"
    early = qualified_bundle(tmp_path, now=datetime(2026, 10, 29, 6, 0, tzinfo=UTC)).to_dict()
    assert contract.current_hold(early, datetime(2026, 10, 29, 18, 30, tzinfo=UTC)) == "hot10_capture_stale"
    assert contract.current_hold(None, T0) == "hot10_contract_invalid:bulletin_schema"


@pytest.mark.parametrize("rank", range(10))
@pytest.mark.parametrize(("field", "stamp", "hold"), [
    ("valid_end", T0, "hot10_local_day_over"),
    ("valid_start", T0 + timedelta(seconds=1), "hot10_not_yet_valid"),
    ("retrieved_at", T0 + timedelta(minutes=6), "hot10_not_yet_valid"),
])
def test_every_ranked_row_has_final_interval_and_future_capture_checks(tmp_path, rank, field, stamp, hold):
    retained = qualified_bundle(tmp_path).to_dict()
    row = retained["raw_signal_dump"]["cities"][rank]
    row[field] = _iso(stamp)
    row["row_fingerprint"] = contract.row_fingerprint(row)
    assert contract.validate_bundle(retained) == []
    assert contract.current_hold(retained, T0) == hold


def test_nonleading_old_capture_holds_while_every_local_day_is_current(tmp_path):
    now = datetime(2026, 10, 29, 19, 30, tzinfo=UTC)
    retained = qualified_bundle(tmp_path, now=now).to_dict()
    row = next(row for row in retained["raw_signal_dump"]["cities"] if row["city"] == "Phoenix")
    row["retrieved_at"] = "2026-10-29T07:00:00Z"
    row["row_fingerprint"] = contract.row_fingerprint(row)
    assert contract.validate_bundle(retained) == []
    assert contract.current_hold(retained, now) == "hot10_capture_stale"


# ---------------------------------------------------------------- A1/A3: leaderboard through every check


@pytest.fixture
def world(tmp_path, monkeypatch):
    from freezegun import freeze_time

    world = h.install_hot10_world(tmp_path, monkeypatch, copy=GOOD_COPY)
    with freeze_time(T0, tick=True):
        yield world


def leaderboard(state=None):
    from src.orchestrator import hot10

    state = state if state is not None else deepcopy(DEFAULT_STATE)
    run = {"id": "run-hot10-a", "sources": []}
    hot10.run_leaderboard(state, run)
    return state, run


def test_qualified_leaderboard_reaches_a_pending_draft_through_every_required_check(world):
    state, run = leaderboard()
    assert world.script.stages() == ["writer", "safety", "fact_check", "critic"]
    writer_request = world.script.requests[0][1]
    from src.two_bot.writer import WRITER_MODEL
    assert writer_request["model"] == WRITER_MODEL and writer_request["max_tokens"] == 1024
    assert writer_request["output_config"]["format"]["type"] == "json_schema"
    assert '"schema": "theheat.hot10-bulletin/v1"' in writer_request["messages"][0]["content"]
    assert [d["type"] for d in state["drafts"]] == ["hot10"]
    draft = state["drafts"][0]
    assert draft["text"] == GOOD_COPY and draft["status"] == "pending"
    bundle = draft["review_context"]["two_bot"]["bundle"]
    assert contract.validate_bundle(bundle) == [] and len(bundle["raw_signal_dump"]["cities"]) == 10
    assert draft["review_context"]["two_bot"]["critic"]["verdict"] == "PASS"
    assert draft["review_context"]["two_bot"]["fact_check"]["passed"] is True
    assert [row["city"] for row in draft["hot10_rows"]][:2] == ["Riyadh", "Baghdad"]
    # One candidate, one started writer: the slot is kept, never returned.
    assert world.settled == [("leaderboard", "event:hot10_2026-10-29", True)]
    source = next(row for row in run["sources"] if row["source"] == "leaderboard")
    assert source["status"] == "success" and source["observed"] == 14
    assert {call[1] for call in world.transport.calls} == {h.FORECAST_URL}


def test_pending_draft_survives_ordinary_gist_serialization(world):
    from src import state as state_module

    state, _run = leaderboard()
    assert state_module.write_state(state) is True
    reread = state_module.read_state()
    draft = next(d for d in reread["drafts"] if d["type"] == "hot10")
    assert draft == json.loads(json.dumps(state["drafts"][0]))
    bundle = draft["review_context"]["two_bot"]["bundle"]
    assert contract.validate_bundle(bundle) == []
    assert contract.current_hold(bundle, datetime.now(UTC)) is None
    from src.editorial.revisions import review_is_current
    assert review_is_current(draft)


@pytest.mark.parametrize(("copy", "failure"), [
    ("Riyadh hit 39.2°C today, running 9.2°C above its October normal among 14 sampled cities.",
     "forecast cannot support an observed"),
    ("Riyadh is forecast to reach a record 39.2°C, 9.2°C above normal among 14 sampled cities.",
     "not a record"),
    ("Riyadh is forecast to be the hottest city on Earth today, 9.2°C above normal among 14 sampled cities.",
     "not absolute heat or a global ranking"),
    ("Riyadh's forecast 9.2°C departure among 14 sampled cities could strain hospitals and the power grid.",
     "no human, health"),
    ("Riyadh's forecast high runs 11.0°C above its October normal, the largest departure among 14 sampled cities.",
     "temperature value is not a supplied"),
    ("Riyadh's forecast high runs 9.2°C above its October normal, the largest departure among 40 sampled cities.",
     "city count is not the supplied"),
    ("Riyadh's forecast high of 39.2°C runs 9.2°C above its October normal.", "name the sampled city universe"),
    ("Riyadh's high of 39.2°C runs 9.2°C above its October normal among 14 sampled cities.", "keep forecast status"),
])
def test_false_hot10_copy_is_rejected_before_any_paid_check(world, copy, failure):
    world.script.copy = copy
    state, _run = leaderboard()
    assert state["drafts"] == []
    assert world.script.stages() == ["writer"]  # Local rejection precedes safety, fact check and critic.
    kill = next(row for row in state["suppressions"] if row.get("event_id") == "hot10_2026-10-29")
    assert kill["stage"] == "fact_check" and any(failure in reason for reason in kill["reasons"]), kill["reasons"]
    assert world.settled == [("leaderboard", "event:hot10_2026-10-29", True)]  # The writer ran; the slot is spent.


def test_model_check_failures_hold_the_draft(world):
    world.script.critic = {"verdict": "KILL", "kill_reason": "weak_signal", "revise_instruction": None,
                           "selected_index": None}
    state, _run = leaderboard()
    assert state["drafts"] == [] and world.script.stages() == ["writer", "safety", "fact_check", "critic"]
    world.script.requests.clear()
    world.script.critic = {"verdict": "PASS", "kill_reason": None, "revise_instruction": None, "selected_index": None}
    world.script.safety = "YES"
    # Distinct copy: a completed safety verdict is reused for identical text within five minutes.
    world.script.copy = GOOD_COPY.replace("among 14 sampled", "among 12 qualified of 14 sampled")
    state, _run = leaderboard()
    assert state["drafts"] == [] and world.script.stages() == ["writer", "safety"]


def test_short_slate_holds_before_any_writer_or_budget_slot(world):
    rows = [row for row in h.normal_rows(10) if row["city"] in {"Riyadh", "Baghdad", "Cairo"}]
    h.write_normals(world.normals_csv, rows)
    state, run = leaderboard()
    assert state["drafts"] == [] and world.script.requests == [] and world.settled == []
    source = next(row for row in run["sources"] if row["source"] == "leaderboard")
    assert source["status"] == "degraded" and source["note"].startswith("hot10_short_slate: 3 of 10")
    assert state["last_hot10"] == DEFAULT_STATE["last_hot10"]  # A held bulletin is not a ranking.


def test_unreadable_legacy_normals_hold_production_hot10(world):
    world.normals_csv.write_text("city,month,avg_high_c\nRiyadh,10,30.0\n")
    state, run = leaderboard()
    source = next(row for row in run["sources"] if row["source"] == "leaderboard")
    assert source["status"] == "degraded" and "0 of 10" in source["note"] and world.script.requests == []


# ---------------------------------------------------------------- A4: the real CLI, fresh processes


def _cli_env(home: Path, **extra) -> dict:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
           "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*", "PYTHON_DOTENV_DISABLED": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "GIST_ID": h.GIST_ID, "GITHUB_TOKEN": h.INVENTED_TOKEN, **h.MODEL_ENV, **h.X_ENV,
           "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": EPOCH,
           "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1"}
    env.update(extra)
    return {key: value for key, value in env.items() if value is not None}


@pytest.fixture
def cli(tmp_path):
    for name in ("gist", "home"):
        (tmp_path / name).mkdir()
    (tmp_path / "gist/state.json").write_text(json.dumps(deepcopy(DEFAULT_STATE)))
    h.write_catalogue(tmp_path / "cities.csv")
    h.write_normals(tmp_path / "normals.csv", h.normal_rows(10))
    return {"dir": tmp_path, "runs": 0}


def run_cli(cli, argv, now: datetime, *, env=None, **options) -> dict:
    cli["runs"] += 1
    work = cli["dir"] / f"run-{cli['runs']}"
    work.mkdir()
    config = {"dir": str(cli["dir"]), "record": str(work / "record.json"), "argv": argv, "now": _iso(now),
              "forecasts": h.forecast_table(), "cities_csv": str(cli["dir"] / "cities.csv"),
              "normals_csv": str(cli["dir"] / "normals.csv"), "models": {"copy": GOOD_COPY}, **options}
    (work / "config.json").write_text(json.dumps(config))
    run = subprocess.run([sys.executable, "-m", "tests.live_content_child", str(work / "config.json")], cwd=ROOT,
                         env=_cli_env(cli["dir"] / "home", **(env or {})), capture_output=True, text=True, timeout=300)
    (work / "output.txt").write_text(run.stdout + "\n--- stderr ---\n" + run.stderr)  # Invented data only.
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads((work / "record.json").read_text())


def gist_state(cli) -> dict:
    return json.loads((cli["dir"] / "gist/state.json").read_text())


def hot10_draft(cli) -> dict:
    return next(d for d in gist_state(cli)["drafts"] if d["type"] == "hot10")


def produce(cli) -> dict:
    record = run_cli(cli, ["leaderboard"], T0)
    assert record["exit"] == 0 and record["models"] == ["writer", "safety", "fact_check", "critic"]
    assert record["x"] == [] and record["gist_patches"] >= 1
    draft = hot10_draft(cli)
    assert draft["status"] == "pending" and draft["approval_mode"] == "auto"
    assert draft["autoship_on_critic_pass"] is True
    assert draft["approval_binding"]["publication_epoch"] == EPOCH
    due = datetime.fromisoformat(draft["auto_approve_at"].replace("Z", "+00:00"))
    assert T0 + timedelta(minutes=19) < due <= T0 + timedelta(minutes=31)
    return draft


def test_real_cli_automatically_posts_a_qualified_hot10_once(cli):
    draft = produce(cli)
    early = run_cli(cli, ["auto_publish_due"], T0 + timedelta(minutes=5))
    assert early["x"] == [] and hot10_draft(cli)["status"] == "pending"  # Not yet due.
    sent = run_cli(cli, ["auto_publish_due"], T0 + timedelta(minutes=45))
    assert sent["x"] == [draft["text"]] and sent["models"] == ["safety"]  # Final safety, then one create.
    posted = hot10_draft(cli)
    assert posted["status"] == "posted" and posted["tweet_id"] == "invented-x-1"
    ledger = gist_state(cli)["publish_ledger"]["hot10_2026-10-29"]
    assert ledger["phase"] == "confirmed" and ledger["tweet_id"] == "invented-x-1"
    again = run_cli(cli, ["auto_publish_due"], T0 + timedelta(minutes=90))
    assert again["x"] == [] and hot10_draft(cli)["status"] == "posted"
    rerun = run_cli(cli, ["leaderboard"], T0 + timedelta(minutes=95))
    assert rerun["models"] == [] and rerun["x"] == []  # The posted daily event is never redrafted.


def _held(cli, reason: str, **options) -> dict:
    record = run_cli(cli, ["auto_publish_due"], options.pop("at", T0 + timedelta(minutes=45)), **options)
    draft = hot10_draft(cli)
    assert record["x"] == [] and draft["status"] in ("pending", "approved") and draft.get("tweet_id") is None
    assert draft["approval_mode"] == "manual" and reason in (draft.get("post_error") or ""), draft.get("post_error")
    assert "hot10_2026-10-29" not in gist_state(cli).get("publish_ledger", {})
    return record


def test_paused_policy_holds(cli):
    produce(cli)
    _held(cli, "Automatic approval revoked", env={"THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "0"})


def test_changed_retained_source_holds(cli):
    produce(cli)
    state = gist_state(cli)
    draft = next(d for d in state["drafts"] if d["type"] == "hot10")
    draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["cities"][0]["temp_high_c"] = 45.0
    (cli["dir"] / "gist/state.json").write_text(json.dumps(state))
    _held(cli, "current model review")


def test_ended_local_day_holds_at_the_final_boundary(cli):
    produce(cli)
    record = _held(cli, "Hot10 bulletin needs fresh source review: hot10_local_day_over",
                   at=datetime(2026, 10, 29, 21, 5, tzinfo=UTC))
    assert record["models"] == []  # Held before the paid final safety check.


@pytest.mark.parametrize(("captured", "held"), [
    (datetime(2026, 10, 29, 12, 55, tzinfo=UTC), True),
    (datetime(2026, 10, 29, 14, 30, tzinfo=UTC), False),
])
def test_nonleader_midnight_is_rechecked_by_the_ordinary_due_consumer(cli, captured, held):
    cities = [c if c[0] != "Sydney" else ("Sydney", c[1], 7.0) for c in h.CITIES]
    h.write_normals(cli["dir"] / "normals.csv", h.normal_rows(10, cities=cities))
    copy = "Sydney's forecast high today is 37°C, 7°C above its October normal, among 14 sampled cities."
    produced = run_cli(cli, ["leaderboard"], captured, forecasts=h.forecast_table(cities), models={"copy": copy})
    assert produced["models"] == ["writer", "safety", "fact_check", "critic"] and produced["x"] == []
    draft = hot10_draft(cli)
    assert draft["text"] == copy and draft["status"] == "pending" and draft["approval_mode"] == "auto"
    bundle = draft["review_context"]["two_bot"]["bundle"]
    rows = bundle["raw_signal_dump"]["cities"]
    assert rows[0]["city"] == "Riyadh" and any(row["city"] == "Sydney" for row in rows[1:])
    assert contract.current_hold(bundle, captured) is None
    due = captured + timedelta(minutes=45)
    approved_at = contract.instant(draft["auto_approve_at"])
    assert approved_at is not None and captured + timedelta(minutes=19) < approved_at < due
    consumed = run_cli(cli, ["auto_publish_due"], due)
    if held:
        assert consumed["models"] == [] and consumed["x"] == []
        draft = hot10_draft(cli)
        assert draft["status"] == "pending" and draft["approval_mode"] == "manual"
        assert "hot10_local_day_over" in draft["post_error"]
        assert "hot10_2026-10-29" not in gist_state(cli).get("publish_ledger", {})
    else:
        assert bundle["raw_signal_dump"]["universe"]["local_days"] == ["2026-10-29", "2026-10-30"]
        assert consumed["models"] == ["safety"] and consumed["x"] == [copy]
        assert hot10_draft(cli)["status"] == "posted"


def test_edited_text_without_a_recheck_holds(cli):
    produce(cli)
    state = gist_state(cli)
    draft = next(d for d in state["drafts"] if d["type"] == "hot10")
    draft["text"] = draft["text"].replace("largest", "biggest")
    (cli["dir"] / "gist/state.json").write_text(json.dumps(state))
    _held(cli, "current model review")


def test_unknown_receipt_is_never_resent(cli):
    produce(cli)
    lost = run_cli(cli, ["auto_publish_due"], T0 + timedelta(minutes=45), x_failure="create_lost")
    assert len(lost["x"]) == 1
    ledger = gist_state(cli)["publish_ledger"]["hot10_2026-10-29"]
    assert ledger.get("tweet_id") is None and ledger["phase"] in ("unknown", "submitted")
    again = run_cli(cli, ["auto_publish_due"], T0 + timedelta(minutes=90))
    assert again["x"] == []
    assert hot10_draft(cli).get("tweet_id") is None
