"""P16 staged promotion — counterparts to the red-first late-mutation case.

Every byte is invented and offline. Production SourceRunners come from
``run_alerts`` itself; their real source functions run with only the shared
HTTP session (or the world cache's ``requests``) replaced by explicit fixtures.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
import json
import pathlib
import threading
import time
from types import SimpleNamespace

import pytest
import requests

from src import state
from src.data import _http, co2 as co2_data, last_good, usgs_quakes
from src.editorial.scoring import score_usgs_earthquake
from src.orchestrator import scheduler, staging, suppression, world_cache
from src.orchestrator.scheduler import SourceRunner
from src.orchestrator.telemetry import _record_source_run
from src.orchestrator.triage_queue import _enqueue_story_candidate
from src.state import _fresh_state
from src.two_bot import call_inventory as inv
from src.two_bot import usage_ledger
from src.two_bot.intern import build_usgs_earthquake_bundle
from src.two_bot.trial_budget import provider_call
from tests import live_content_harness as h
from tests.real_closure import p16_fixtures as fx

ROOT = pathlib.Path(__file__).resolve().parents[2]
INVENTED_URL = "https://invented-source.example.test/p16.txt"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.trap_network(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_FUNNEL_TELEMETRY", "1")
    monkeypatch.setattr(co2_data, "_CO2_REVALIDATION_CACHE", {})
    monkeypatch.setattr(inv, "_CANCELLED", {})
    monkeypatch.setattr(inv, "_UNJOINED", {})
    monkeypatch.setattr(usage_ledger, "_BUFFER", [])
    monkeypatch.setattr(staging, "_LATE", [])
    yield
    suppression._clear_suppression_ctx()


def _live():
    return _fresh_state(), {"id": "run_p16", "sources": []}


def _wait_late(owner: staging.Owner, timeout: float = 10) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if any(row["owner"] == owner.token for row in staging._LATE):
            return
        time.sleep(0.01)
    raise AssertionError("late worker left no late evidence")


def _quake_candidate(bs, code: str, *, on_success=None, cap_check=None) -> None:
    [quake] = usgs_quakes._events_from_geojson(json.loads(fx.usgs_geojson(code)))
    _enqueue_story_candidate(
        bs, bundle=build_usgs_earthquake_bundle(quake),
        score=score_usgs_earthquake(quake.magnitude, quake.alert, quake.significance, quake.tsunami),
        source=f"invented_{code}", legacy_type="usgs_earthquake", event_id=quake.event_id,
        review_context={"source": "invented"}, on_draft_success=on_success, annual_cap_check=cap_check)


# --- cancellation, exception and cached results through the real co2 runner ----------------

def test_after_expiry_the_retry_is_refused_and_the_sources_failure_writes_are_discarded(monkeypatch):
    live, run = _live()
    runners = fx.production_runners(monkeypatch, live, run)
    transport = fx.BlockingTransport({co2_data.CO2_URL: [(503, "invented outage", {})]})
    monkeypatch.setattr(_http, "_session", transport)
    calls = inv.runtime_counts().get("source_http_get", 0)

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=[runners["co2"]],
                                         budget_seconds=0.2)
    after_state, after_run = deepcopy(live), deepcopy(run)
    transport.release.set()
    transport.join()
    _wait_late(owner)

    assert fx.changed_keys(after_state, live) == [] and fx.changed_keys(after_run, run) == []
    # The 503 would retry; the retry is refused before egress.
    assert inv.runtime_counts()["source_http_get"] == calls + 1
    assert inv.unjoined_calls()["cancelled_before_egress"] == [{"stage": "source_http_get", "refused_calls": 1}]
    [stage] = owner.stages
    assert stage.disposition == "refused:timeout" and stage.cancel.refused == 1
    assert staging.attach_late_evidence(run, owner) == 1
    [row] = run["late_source_evidence"]
    assert row["late"] is True and row["source"] == "co2" and row["refused_calls"] == 1
    assert row["outcome"] == "returned"  # run_co2 caught the refusal and wrote its failure privately
    assert {"errors", "source_health", "current_run.sources"} <= set(row["discarded_changes"])
    assert [r["status"] for r in live["source_health"]["co2"]["runs"]] == ["failed"]


@pytest.mark.parametrize("cached", ["last_good", "revalidated_304"])
def test_a_cached_or_retained_result_returned_after_the_deadline_is_discarded(monkeypatch, cached):
    live, run = _live()
    yesterday = date.today() - timedelta(days=1)
    if cached == "last_good":
        last_good.write(live, "co2", yesterday, {"date": yesterday.isoformat(), "ppm": 429.91})
        routes = {co2_data.CO2_URL: [(503, "invented outage", {})]}
    else:
        co2_data._CO2_REVALIDATION_CACHE[co2_data.CO2_URL] = ('"invented-v1"', fx.co2_csv())
        routes = {co2_data.CO2_URL: [(304, "", {"ETag": '"invented-v1"'})]}
    cache_before = dict(co2_data._CO2_REVALIDATION_CACHE)
    runners = fx.production_runners(monkeypatch, live, run)
    transport = fx.BlockingTransport(routes)
    monkeypatch.setattr(_http, "_session", transport)

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=[runners["co2"]],
                                         budget_seconds=0.2)
    after_state, after_run = deepcopy(live), deepcopy(run)
    transport.release.set()
    transport.join()
    _wait_late(owner)

    assert fx.changed_keys(after_state, live) == [] and fx.changed_keys(after_run, run) == []
    assert co2_data._CO2_REVALIDATION_CACHE == cache_before  # The raw transport cache is not app state.
    staging.attach_late_evidence(run, owner)
    [row] = run["late_source_evidence"]
    if cached == "last_good":
        # The late worker served last-good as "degraded"; live keeps only the timeout.
        assert "current_run.sources" in row["discarded_changes"]
    else:
        # The revalidated body was parsed and its last-good written — privately.
        assert {"last_good_readings", "suppressions", "_funnel_sink"} <= set(row["discarded_changes"])
    assert [r["status"] for r in live["source_health"]["co2"]["runs"]] == ["failed"]


@pytest.mark.parametrize("late", [True, False])
def test_a_runner_raising_with_finally_writes(monkeypatch, late):
    live, run = _live()
    transport = fx.BlockingTransport({INVENTED_URL: "invented body"}, hold={INVENTED_URL} if late else set())
    monkeypatch.setattr(_http, "_session", transport)

    def runner(bs, current):
        started = time.perf_counter()
        try:
            _http.fetch_with_retry(INVENTED_URL, attempts=1)
            raise RuntimeError("invented failure after the response")
        finally:
            state.log_error(bs, "invented_raise", "finally-block write")
            _record_source_run(current, bs, "invented_raise", started, status="failed", error="finally-block write")

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[SourceRunner("invented_raise", runner)],
                                         budget_seconds=0.2 if late else 10)
    if late:
        after_state, after_run = deepcopy(live), deepcopy(run)
        transport.release.set()
        transport.join()
        _wait_late(owner)
        assert fx.changed_keys(after_state, live) == [] and fx.changed_keys(after_run, run) == []
        assert [r["error"] for r in run["sources"]] == ["budget exceeded (0.2s)"]
        staging.attach_late_evidence(run, owner)
        [row] = run["late_source_evidence"]
        assert row["outcome"] == "raised" and row["error_class"] == "RuntimeError"
        assert {"errors", "source_health", "current_run.sources"} <= set(row["discarded_changes"])
        assert "errors" not in live or all(e["source"] != "invented_raise" for e in live["errors"])
    else:
        # On time: its writes are its result (as when it shared the live state),
        # then the scheduler reports the unhandled error, as before.
        assert owner.stages[0].disposition == "promoted"
        assert [r["error"] for r in run["sources"]] == ["finally-block write", "invented failure after the response"]
        assert live["errors"][-1]["source"] == "invented_raise"
        assert "late_source_evidence" not in run


# --- nested pools ---------------------------------------------------------------------------

def test_nested_pool_threads_inherit_the_stage_and_cannot_buy_or_write_after_expiry(monkeypatch):
    live, run = _live()
    transport = fx.BlockingTransport({INVENTED_URL: "invented body"})
    monkeypatch.setattr(_http, "_session", transport)
    calls = inv.runtime_counts().get("source_http_get", 0)
    seen: dict = {"stages": [], "second": []}

    def nested_fetch(index: int) -> str:
        seen["stages"].append(staging.active_stage())
        body = _http.fetch_with_retry(INVENTED_URL, attempts=1).text
        try:
            _http.fetch_with_retry(INVENTED_URL, attempts=1)
            seen["second"].append("sent")
        except inv.OperationCancelled as exc:
            seen["second"].append(exc.reason)
        return body

    def runner(bs, current):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            bodies = [f.result() for f in [inv.submit_in_context(pool, nested_fetch, i) for i in range(2)]]
        last_good.write(bs, "invented_nested", date.today(), {"bodies": len(bodies)})
        _record_source_run(current, bs, "invented_nested", started, status="success", observed=len(bodies))

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[SourceRunner("invented_nested", runner)],
                                         budget_seconds=0.2)
    after_state, after_run = deepcopy(live), deepcopy(run)
    transport.release.set()
    transport.join()
    _wait_late(owner)

    [stage] = owner.stages
    assert seen["stages"] == [stage, stage]  # The nested threads carry the parent's stage and token.
    assert seen["second"] == ["runner_budget_exceeded", "runner_budget_exceeded"]
    assert inv.runtime_counts()["source_http_get"] == calls + 2 and stage.cancel.refused == 2
    assert fx.changed_keys(after_state, live) == [] and fx.changed_keys(after_run, run) == []


def test_the_four_nested_pools_hand_no_state_or_run_to_their_threads():
    """GHCN/coral/GPM/ocean pools return data to their parent; none passes shared state down."""
    forbidden = {"bot_state", "state", "current_run", "metrics_out", "metrics"}
    for name in ("src/data/ghcn.py", "src/data/coral_dhw.py", "src/data/gpm_imerg.py",
                 "src/data/ocean_sst_anomaly.py"):
        tree = ast.parse((ROOT / name).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "submit_in_context"]
        assert calls, name
        for call in calls:
            names = {n.id for arg in [*call.args, *(k.value for k in call.keywords)]
                     for n in ast.walk(arg) if isinstance(n, ast.Name)}
            assert not names & forbidden, (name, names)


# --- owner restart and the clock boundary ----------------------------------------------------

def test_a_stale_worker_from_an_earlier_owner_never_promotes_into_a_new_one(monkeypatch):
    live, run = _live()
    runners = fx.production_runners(monkeypatch, live, run)
    transport = fx.BlockingTransport({co2_data.CO2_URL: fx.co2_csv(), fx.USGS_URL: fx.usgs_geojson()},
                                     hold={co2_data.CO2_URL})
    monkeypatch.setattr(_http, "_session", transport)

    old = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=[runners["co2"]],
                                       budget_seconds=0.2)
    new = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=[runners["usgs_quakes"]],
                                       budget_seconds=10)
    assert old.closed and new.closed and new.stages[0].disposition == "promoted"
    [queued] = live["_triage_queue"]
    assert queued.event_id == "usgs_eq_inv0001"
    after_state, after_run = deepcopy(live), deepcopy(run)

    transport.release.set()
    transport.join()
    _wait_late(old)
    assert fx.changed_keys(after_state, live) == [] and fx.changed_keys(after_run, run) == []

    stale = old.stages[0]
    third = staging.Owner(live, run)
    batch = third.open_batch()
    assert staging.promote(third, stale, batch) == "refused:stale_owner"
    third.close_batch(batch)
    assert fx.changed_keys(after_state, live) == []
    # Late rows stay with their own owner.
    assert staging.attach_late_evidence(run, new) == 0 and staging.attach_late_evidence(run, old) == 1


@pytest.mark.parametrize("offset,expected", [(0.0, "promoted"), (0.001, "refused:timeout")])
def test_completion_exactly_at_the_deadline_is_on_time_and_after_it_is_late(monkeypatch, offset, expected):
    live, run = _live()
    main = threading.get_ident()
    stamps: dict[int, float] = {}
    monkeypatch.setattr(staging, "clock", lambda: stamps.get(threading.get_ident(), 1000.0))

    def runner(bs, current):
        last_good.write(bs, "invented_boundary", date.today(), {"v": 1})
        stamps[threading.get_ident()] = staging.active_stage().deadline + offset

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[SourceRunner("invented_boundary", runner)],
                                         budget_seconds=30)
    [stage] = owner.stages
    assert main not in stamps and stage.completed_at == stage.deadline + offset
    assert stage.disposition == expected
    if expected == "promoted":
        assert "invented_boundary" in live["last_good_readings"] and run["sources"] == []
    else:
        assert "invented_boundary" not in live.get("last_good_readings", {})
        assert run["sources"][0]["error_class"] == "timeout"


def test_the_main_threads_cancellation_wins_over_an_on_time_stamp():
    live, run = _live()
    owner = staging.Owner(live, run)
    batch = owner.open_batch()
    stage = batch.stage("invented", 30)
    stage.state["invented_key"] = 1
    stage.completed_at = stage.deadline
    stage.cancel.cancel("runner_budget_exceeded")
    assert staging.promote(owner, stage, batch) == "refused:cancelled" and "invented_key" not in live
    owner.close_batch(batch)


# --- independent successful workers, conflicts, callbacks and synthesis ---------------------

def _gated(name: str, gate: threading.Event, done: threading.Event):
    def run(bs, current):
        assert gate.wait(10)
        started = time.perf_counter()
        _quake_candidate(bs, f"inv_{name}")
        state.log_error(bs, f"invented_{name}", "independent write")
        last_good.write(bs, f"invented_{name}", date.today(), {"name": name})
        state.record_synthesis_component(bs, kind="heat", region="Invented Region", event_id=f"heat_{name}")
        _record_source_run(current, bs, f"invented_{name}", started, status="success", observed=1)
        done.set()
    return run


@pytest.mark.parametrize("finish_order", [("alpha", "beta"), ("beta", "alpha")])
def test_two_independent_workers_both_land_in_declaration_order_whatever_finishes_first(finish_order):
    live, run = _live()
    gates = {n: threading.Event() for n in ("alpha", "beta")}
    done = {n: threading.Event() for n in ("alpha", "beta")}
    runners = [SourceRunner(f"invented_{n}", _gated(n, gates[n], done[n])) for n in ("alpha", "beta")]

    def sequence():
        for name in finish_order:
            gates[name].set()
            assert done[name].wait(10)
    helper = threading.Thread(target=sequence)
    helper.start()
    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=runners, budget_seconds=10)
    helper.join(10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert [r["source"] for r in run["sources"]] == ["invented_alpha", "invented_beta"]
    assert [c.event_id for c in live["_triage_queue"]] == ["usgs_eq_inv_alpha", "usgs_eq_inv_beta"]
    assert [e["source"] for e in live["errors"]] == ["invented_alpha", "invented_beta"]
    assert [r["event_id"] for r in live["candidates_log"]] == ["usgs_eq_inv_alpha", "usgs_eq_inv_beta"]
    assert {"invented_alpha", "invented_beta"} <= set(live["last_good_readings"])
    heats = live["synthesis_components"]["heats"]["Invented Region"]
    assert [h["event_id"] for h in heats] == ["heat_alpha", "heat_beta"]


@pytest.mark.parametrize("values", [("alpha", "beta"), ("same", "same")])
def test_a_same_path_scalar_write_by_two_workers_fails_closed_for_the_later_worker(values):
    live, run = _live()

    def writer(name: str, value: str):
        def run_fn(bs, current):
            started = time.perf_counter()
            bs["invented_marker"] = value
            state.log_error(bs, f"invented_{name}", "conflict case")
            _quake_candidate(bs, f"inv_{name}")
            _record_source_run(current, bs, f"invented_{name}", started, status="success")
        return run_fn

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[],
        concurrent_runners=[SourceRunner("invented_alpha", writer("alpha", values[0])),
                            SourceRunner("invented_beta", writer("beta", values[1]))], budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:invented_marker"]
    assert live["invented_marker"] == values[0]
    # Nothing of the later worker lands: not its error row, queue row or success row.
    assert [e["source"] for e in live["errors"]] == ["invented_alpha"]
    assert [c.event_id for c in live["_triage_queue"]] == ["usgs_eq_inv_alpha"]
    assert [(r["source"], r["status"]) for r in run["sources"]] == [("invented_alpha", "success"),
                                                                     ("invented_beta", "failed")]
    assert run["sources"][1]["error"] == "staged result not promoted (conflict:invented_marker)"


def test_promoted_candidate_callbacks_act_on_the_live_state_not_the_staged_copy():
    live, run = _live()
    live["invented_cap_count"] = 0

    def runner(bs, current):
        _quake_candidate(
            bs, "inv_callback",
            on_success=lambda: bs.__setitem__("invented_cap_count", bs.get("invented_cap_count", 0) + 1),
            cap_check=lambda: bs.get("invented_cap_count", 0) >= 2)

    scheduler.run_stage1_sources(live, run, serial_runners=[],
                                 concurrent_runners=[SourceRunner("invented_callback", runner)], budget_seconds=10)
    [row] = live["_triage_queue"]
    live["invented_cap_count"] = 1  # The main thread moved on after promotion.
    assert row.annual_cap_check() is False
    row.on_draft_success()
    assert live["invented_cap_count"] == 2 and row.annual_cap_check() is True


def test_synthesis_sees_exactly_the_promoted_stage1_components():
    live, run = _live()
    release = threading.Event()
    observed: dict = {}

    def component(name: str, kind: str, *, wait: bool = False):
        def run_fn(bs, current):
            if wait:
                assert release.wait(10)
            state.record_synthesis_component(bs, kind=kind, region="Invented Region", event_id=name)
        return run_fn

    def synthesis(bs, current):
        observed["fires"] = [e["event_id"] for e in state.get_synthesis_components(bs, kind="fire", region="Invented Region")]
        observed["heats"] = [e["event_id"] for e in state.get_synthesis_components(bs, kind="heat", region="Invented Region")]

    owner = scheduler.run_stage1_then_synthesis(
        live, run,
        serial_runners=[SourceRunner("invented_fire", component("fire_serial", "fire"))],
        concurrent_runners=[SourceRunner("invented_heat_on_time", component("heat_on_time", "heat")),
                            SourceRunner("invented_heat_late", component("heat_late", "heat", wait=True))],
        synthesis_runner=SourceRunner("synthesis_fire_drought_heat", synthesis), budget_seconds=1.0)
    release.set()
    _wait_late(owner)
    assert observed == {"fires": ["fire_serial"], "heats": ["heat_on_time"]}
    assert [s.disposition for s in owner.stages] == ["promoted", "promoted", "refused:timeout"]
    assert [e["event_id"] for e in live["synthesis_components"]["heats"]["Invented Region"]] == ["heat_on_time"]


# --- usage accounting for a late provider response ------------------------------------------

def test_a_late_provider_response_keeps_its_usage_and_attribution_and_is_counted_late():
    live, run = _live()
    release = threading.Event()

    def send(**_):
        assert release.wait(10)
        usage = SimpleNamespace(input_tokens=11, output_tokens=7, cache_creation_input_tokens=None,
                                cache_read_input_tokens=None)
        return SimpleNamespace(usage=usage, model="invented-model", id="invented-response")

    def runner(bs, current):
        response = provider_call("writer", "anthropic", {"model": "invented-model"}, send)
        usage_ledger.record_writer_response(response, "invented-model", "anthropic")
        bs["invented_after_response"] = True

    with inv.operation_scope("alerts") as join:
        owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                             concurrent_runners=[SourceRunner("invented_writer", runner)],
                                             budget_seconds=0.2)
        release.set()
        _wait_late(owner)

    assert join.dispatched() == 1 and join.rows[0]["outcome"] == "returned"
    [observed] = [row["usage_observation"] for row in usage_ledger._BUFFER if "usage_observation" in row]
    assert observed["attribution"]["status"] == "joined_operation" and observed["attribution"]["operation"] == "alerts"
    assert "invented_after_response" not in live
    staging.attach_late_evidence(run, owner)
    [row] = run["late_source_evidence"]
    assert row["late_responses"] == {"writer": 1} and row["refused_calls"] == 0


# --- the world threshold cache Gist write -----------------------------------------------------

class _GistFixture:
    """Offline stand-in for world_cache's ``requests``; nothing reaches GitHub."""

    def __init__(self, hold: bool, run: dict):
        self.hold = hold
        self.run = run
        self.release = threading.Event()
        self.gets: list = []
        self.patches: list = []

    def get(self, url, headers=None, timeout=None):
        self.gets.append(threading.current_thread())
        if self.hold and len(self.gets) == 1 and not self.release.wait(10):
            raise AssertionError("gist fixture never released")
        return fx.response(url, json.dumps({"files": {}}))

    def patch(self, url, headers=None, json=None, timeout=None):
        self.patches.append({"thread": threading.current_thread(), "rows_at_write": len(self.run["sources"]),
                             "files": sorted((json or {}).get("files", {}))})
        return fx.response(url, "{}")


def _world_half(monkeypatch, live, run, *, hold: bool) -> tuple[_GistFixture, dict]:
    runners = fx.production_runners(monkeypatch, live, run)
    gist = _GistFixture(hold, run)
    monkeypatch.setattr(world_cache, "GIST_ID", "invented-gist")
    monkeypatch.setattr(world_cache, "GITHUB_TOKEN", "invented-token")
    monkeypatch.setattr(world_cache, "requests", SimpleNamespace(get=gist.get, patch=gist.patch,
                                                                 RequestException=requests.RequestException))
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "both")
    monkeypatch.delenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", raising=False)  # GHCN withheld; no fetch.
    return gist, runners


def test_an_expired_world_half_worker_never_reaches_the_gist_write(monkeypatch):
    live, run = _live()
    gist, runners = _world_half(monkeypatch, live, run, hold=True)
    owner = scheduler.run_stage1_sources(live, run, serial_runners=[runners["open_meteo_extreme_signals"]],
                                         concurrent_runners=[], budget_seconds=0.2)
    after_state, after_run = deepcopy(live), deepcopy(run)
    gist.release.set()
    _wait_late(owner)
    assert gist.patches == [] and len(gist.gets) == 1
    assert fx.changed_keys(after_state, live) == [] and fx.changed_keys(after_run, run) == []
    staging.attach_late_evidence(run, owner)
    [row] = run["late_source_evidence"]
    assert row["dropped_effects"] == ["world_threshold_cache"]


def test_an_on_time_world_half_worker_writes_the_cache_on_the_main_thread_after_promotion(monkeypatch):
    live, run = _live()
    gist, runners = _world_half(monkeypatch, live, run, hold=False)
    rows_before = len(run["sources"])
    owner = scheduler.run_stage1_sources(live, run, serial_runners=[runners["open_meteo_extreme_signals"]],
                                         concurrent_runners=[], budget_seconds=10)
    assert owner.stages[0].disposition == "promoted"
    [write] = gist.patches
    assert write["thread"] is threading.current_thread() and write["files"] == ["world_threshold_cache.json"]
    assert write["rows_at_write"] == rows_before + 1  # After the promoted source row: an ordering change in staged mode only.


def test_the_serial_production_path_writes_the_cache_inline_exactly_as_before(monkeypatch):
    from src.orchestrator.sources import open_meteo as source

    live, run = _live()
    gist, _ = _world_half(monkeypatch, live, run, hold=False)
    rows_before = len(run["sources"])
    source.run_extreme_signals(live, run, [], {}, {})
    [write] = gist.patches
    assert write["thread"] is threading.current_thread() and write["rows_at_write"] == rows_before
    assert run["sources"][-1]["source"] == "open_meteo_extreme_signals"


def test_the_only_world_cache_write_from_a_source_goes_through_the_staging_boundary():
    for path in (ROOT / "src/orchestrator/sources").glob("*.py"):
        text = path.read_text()
        assert "write_cache(" not in text, path
    text = (ROOT / "src/orchestrator/sources/open_meteo.py").read_text()
    assert text.count('defer_or_run("world_threshold_cache", world_cache.write_cache, cache)') == 1


# --- structure: no runner closure captures the live objects ---------------------------------

def test_no_production_runner_closure_captures_the_live_state_or_run(monkeypatch):
    live, run = _live()
    runners = fx.production_runners(monkeypatch, live, run)
    sources = runners["__serial__"] + runners["__concurrent__"]
    assert len(sources) == 29  # 3 serial + 26 concurrent, as run_alerts builds them
    for runner in [runners[s] for s in sources] + [runners["__synthesis__"]]:
        cells = [c.cell_contents for c in (runner.run.__closure__ or ())]
        assert not any(cell is live or cell is run for cell in cells), runner.source
        assert runner.run.__code__.co_argcount == 2


# --- queued work and the retained-supply seam -------------------------------------------------

def test_a_queued_runner_whose_deadline_passed_before_it_started_never_runs():
    live, run = _live()
    release, ran = threading.Event(), []

    def first(bs, current):
        assert release.wait(10)
        ran.append("first")

    def second(bs, current):
        ran.append("second")
        bs["invented_second"] = True

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[], max_workers=1, budget_seconds=0.2,
        concurrent_runners=[SourceRunner("invented_first", first), SourceRunner("invented_second", second)])
    release.set()
    _wait_late(owner)
    time.sleep(0.2)  # Room for the single pool worker to pick up anything still queued.
    assert ran == ["first"] and "invented_second" not in live
    assert [s.disposition for s in owner.stages] == ["refused:timeout", "refused:timeout"]
    assert owner.stages[1].completed_at is None
    assert [r["error_class"] for r in run["sources"]] == ["timeout", "timeout"]


class _SupplyDouble:
    """Duck-typed stand-in for a capture-mode ScientificSupplySession (no database)."""

    def __init__(self):
        self.captures = 0

    def validate(self, *, mode):
        assert mode == "capture"

    def capture(self, bundles, countries, metrics, *, orchestrator_run_id=None):
        self.captures += 1
        return SimpleNamespace(snapshot_id="invented-snapshot", canonical_sha256="0" * 64), bundles, countries, None


@pytest.mark.parametrize("late", [True, False])
def test_an_expired_worker_never_starts_a_retained_supply_write(monkeypatch, late):
    from src.orchestrator.sources import open_meteo as source

    monkeypatch.delenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", raising=False)  # GHCN withheld; no fetch.
    live, run = _live()
    supply, gate, metrics = _SupplyDouble(), threading.Event(), {}

    def runner(bs, current):
        if late:
            assert gate.wait(10)  # Stands in for the GHCN fetch still in flight at the deadline.
        source._verified_ghcn_signals(bs, metrics, ghcn_supply=supply, current_run=current)

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[SourceRunner("invented_supply", runner)],
                                         concurrent_runners=[], budget_seconds=0.2 if late else 10)
    if late:
        gate.set()
        _wait_late(owner)
        assert supply.captures == 0 and metrics["supply_retention"] == "unavailable"
    else:
        assert supply.captures == 1 and metrics["supply_retention"] == "retained"


def test_a_reobserved_candidate_and_a_new_one_from_two_workers_both_land_like_serial():
    """Remove-then-append dedup (the real candidate log) is a log edit, not a conflict."""
    live, run = _live()
    earlier = (date.today() - timedelta(days=2)).isoformat()
    live["candidates_log"] = [{"event_id": "invented_old", "category": "", "type": "", "city": "", "where": "",
                               "date": earlier},
                              {"event_id": "invented_seen", "category": "", "type": "", "city": "", "where": "",
                               "date": earlier}]

    def observe(event_id: str):
        def run_fn(bs, current):
            state.record_candidate_observation(bs, event_id=event_id, category="", legacy_type="", city="", where="")
        return run_fn

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[], budget_seconds=10,
        concurrent_runners=[SourceRunner("invented_new", observe("invented_new")),
                            SourceRunner("invented_seen", observe("invented_seen"))])
    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert [r["event_id"] for r in live["candidates_log"]] == ["invented_old", "invented_new", "invented_seen"]
    assert live["candidates_log"][-1]["date"] == date.today().isoformat()


def test_a_worker_replacing_a_list_that_live_also_changed_is_a_conflict():
    live, run = _live()
    live["invented_rows"] = ["a", "b"]

    def append(bs, current):
        bs["invented_rows"].append("c")

    def replace(bs, current):
        bs["invented_rows"] = ["z"]

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[], budget_seconds=10,
        concurrent_runners=[SourceRunner("invented_append", append), SourceRunner("invented_replace", replace)])
    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:invented_rows"]
    assert live["invented_rows"] == ["a", "b", "c"]
