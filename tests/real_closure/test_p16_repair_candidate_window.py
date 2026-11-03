"""P16-R1 repair: staged promotion keeps the candidate log's own window-prune/dedup contract.

The only writer of ``candidates_log`` is ``state.record_candidate_observation``: it removes the
rows of the key it re-observes, appends the new row at the end, then drops every row dated before
``now - CANDIDATES_WINDOW_DAYS``. After a quiet week that removes every original row, and
re-observing the only logged candidate is remove-then-append; both are log edits, not conflicts.
Anything the writer cannot produce (an in-window row dropped without re-observation, a duplicated
key, a row outside the window) still refuses as ``conflict:candidates_log``.

Every byte is invented and offline. The NWS and USGS SourceRunners are the exact closures
``run_alerts`` builds; their real fetchers, freshness checks, parsers, scoring/evidence audit and
``_enqueue_story_candidate`` run with only the shared HTTP session replaced by an explicit fixture.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
import threading
import time
from typing import Any

import pytest

from src import state
from src.data import _http, co2 as co2_data, nws_alerts
from src.orchestrator import scheduler, staging, suppression
from src.orchestrator.scheduler import SourceRunner
from src.orchestrator.telemetry import _record_source_run
from src.state import _fresh_state
from src.two_bot import call_inventory as inv
from src.two_bot import usage_ledger
from tests import live_content_harness as h
from tests.real_closure import p16_fixtures as fx
from tests.real_closure.test_p16_staged_promotion import _quake_candidate

NWS_ID = "nws_urn:oid:invented-review-warning"
USGS_ID = "usgs_eq_inv0001"
EVENT = {"nws_alerts": NWS_ID, "usgs_quakes": USGS_ID}
ORDERS = [pytest.param(("nws_alerts", "usgs_quakes"), id="nws_first"),
          pytest.param(("usgs_quakes", "nws_alerts"), id="usgs_first")]


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


def _live() -> tuple[Any, dict]:
    return _fresh_state(), {"id": "run_p16_repair", "sources": []}


def _utc_today() -> date:
    # record_candidate_observation dates rows on the UTC clock, never the host zone.
    return datetime.now(UTC).date()


def _row(event_id: str, day: date | str) -> dict:
    return {"event_id": event_id, "category": "", "type": "", "city": "", "where": "",
            "date": day if isinstance(day, str) else day.isoformat()}


def _nws_body() -> str:
    """One invented extreme NWS warning that passes the real freshness, score and evidence gates."""
    now = datetime.now(UTC)
    return json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": None, "properties": {
            "id": "urn:oid:invented-review-warning", "event": "Extreme Wind Warning",
            "areaDesc": "Invented County, FL", "severity": "Extreme",
            "headline": "Invented extreme wind warning", "description": "Invented official warning",
            "sent": now.isoformat(), "effective": now.isoformat(), "onset": now.isoformat(),
            "expires": (now + timedelta(hours=2)).isoformat(), "status": "Actual",
            "messageType": "Alert", "category": "Met", "certainty": "Observed",
            "urgency": "Immediate", "senderName": "NWS Invented Office", "parameters": {},
        },
    }]})


def _real_runners(monkeypatch, live: dict, run: dict) -> dict:
    runners = fx.production_runners(monkeypatch, live, run)
    monkeypatch.setattr(_http, "_session", fx.BlockingTransport(
        {nws_alerts.NWS_URL: _nws_body(), fx.USGS_URL: fx.usgs_geojson()}, hold=set()))
    return runners


def _source_rows(run: dict, names) -> list[tuple]:
    return [(r["source"], r["status"], r.get("error")) for r in run["sources"] if r["source"] in names]


def _assert_both_landed(live: dict, run: dict, owner: staging.Owner, order: tuple[str, ...]) -> None:
    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert [c.event_id for c in live["_triage_queue"]] == [EVENT[s] for s in order]
    assert _source_rows(run, order) == [(s, "success", None) for s in order]
    for source in order:
        assert live["source_health"][source]["runs"][-1]["status"] == "success"


# --- (a) every original row expired: both real sources land ------------------------------------

@pytest.mark.parametrize("order", ORDERS)
def test_after_every_logged_candidate_expired_both_real_sources_land(monkeypatch, order):
    live, run = _live()
    live["candidates_log"] = [_row("invented_expired", "2020-01-01")]
    runners = _real_runners(monkeypatch, live, run)

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[runners[s] for s in order], budget_seconds=10)

    _assert_both_landed(live, run, owner, order)
    # The expired row stays removed; each source's row once, in declaration order.
    assert [r["event_id"] for r in live["candidates_log"]] == [EVENT[s] for s in order]
    assert {r["date"] for r in live["candidates_log"]} <= {_utc_today().isoformat(),
                                                          (_utc_today() + timedelta(days=1)).isoformat()}


# --- (b) the only logged candidate is re-observed while another source adds one -----------------

@pytest.mark.parametrize("order", ORDERS)
def test_reobserving_the_only_logged_candidate_while_another_source_adds_one(monkeypatch, order):
    live, run = _live()
    earlier = _utc_today() - timedelta(days=2)
    live["candidates_log"] = [_row(USGS_ID, earlier)]
    runners = _real_runners(monkeypatch, live, run)

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[runners[s] for s in order], budget_seconds=10)

    _assert_both_landed(live, run, owner, order)
    # Like serial in declaration order: the re-observed row moved to its source's place, re-dated.
    assert [r["event_id"] for r in live["candidates_log"]] == [EVENT[s] for s in order]
    assert all(r["date"] > earlier.isoformat() for r in live["candidates_log"])


# --- the retained two-row base, now through the real runners -------------------------------------

@pytest.mark.parametrize("order", ORDERS)
def test_two_row_base_with_one_reobserved_row_lands_like_serial(monkeypatch, order):
    live, run = _live()
    earlier = _utc_today() - timedelta(days=2)
    live["candidates_log"] = [_row("invented_old", earlier), _row(USGS_ID, earlier)]
    runners = _real_runners(monkeypatch, live, run)

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[],
                                         concurrent_runners=[runners[s] for s in order], budget_seconds=10)

    _assert_both_landed(live, run, owner, order)
    assert [r["event_id"] for r in live["candidates_log"]] == ["invented_old", *(EVENT[s] for s in order)]
    assert live["candidates_log"][0] == _row("invented_old", earlier)


# --- (c) an unrelated replacement of an in-window row still refuses ------------------------------

def _replacer(rows: list[dict]):
    def run_fn(bs, current):
        started = time.perf_counter()
        bs["candidates_log"] = [dict(r) for r in rows]
        _record_source_run(current, bs, "invented_replacer", started, status="success")
    return run_fn


@pytest.mark.parametrize("replacer_first", [False, True], ids=["replacer_second", "replacer_first"])
def test_an_unrelated_fresh_replacement_of_an_in_window_row_still_conflicts(monkeypatch, replacer_first):
    live, run = _live()
    kept = _row("invented_in_window", _utc_today() - timedelta(days=2))
    unrelated = [_row("invented_unrelated_a", _utc_today()), _row("invented_unrelated_b", _utc_today())]
    live["candidates_log"] = [dict(kept)]
    runners = _real_runners(monkeypatch, live, run)
    replacer = SourceRunner("invented_replacer", _replacer(unrelated))
    order = [replacer, runners["nws_alerts"]] if replacer_first else [runners["nws_alerts"], replacer]

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=order, budget_seconds=10)

    # The first declared stage is the only writer so far and lands; the second cannot merge onto it.
    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:candidates_log"]
    loser = order[1].source
    assert _source_rows(run, [loser]) == [(loser, "failed", "staged result not promoted (conflict:candidates_log)")]
    if replacer_first:
        assert live["candidates_log"] == unrelated and live.get("_triage_queue", []) == []
    else:
        assert live["candidates_log"][0] == kept
        assert [r["event_id"] for r in live["candidates_log"]] == ["invented_in_window", NWS_ID]
        assert [c.event_id for c in live["_triage_queue"]] == [NWS_ID]


def _dropper(drop: str, add: str):
    """Drops an in-window row it never re-observed, then records a new candidate with the real writer."""
    def run_fn(bs, current):
        started = time.perf_counter()
        bs["candidates_log"] = [r for r in bs["candidates_log"] if r["event_id"] != drop]
        state.record_candidate_observation(bs, event_id=add, category="", legacy_type="", city="", where="")
        _record_source_run(current, bs, "invented_dropper", started, status="success")
    return run_fn


def test_an_in_window_row_dropped_without_reobservation_conflicts_even_when_another_row_survives(monkeypatch):
    live, run = _live()
    earlier = _utc_today() - timedelta(days=2)
    live["candidates_log"] = [_row("invented_dropped", earlier), _row("invented_survivor", earlier)]
    runners = _real_runners(monkeypatch, live, run)

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[], budget_seconds=10,
        concurrent_runners=[runners["nws_alerts"], SourceRunner("invented_dropper", _dropper("invented_dropped",
                                                                                              "invented_new"))])

    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:candidates_log"]
    assert [r["event_id"] for r in live["candidates_log"]] == ["invented_dropped", "invented_survivor", NWS_ID]


# --- duplicate-key appends from two sources -------------------------------------------------------

def _second_quake_source(bs, current):
    """Another source admitting the same invented quake through the real enqueue boundary."""
    started = time.perf_counter()
    _quake_candidate(bs, "inv0001")
    _record_source_run(current, bs, "invented_second_quake", started, status="success", promoted=1)


@pytest.mark.parametrize("real_first", [True, False], ids=["usgs_first", "second_source_first"])
def test_the_same_key_appended_by_two_sources_is_logged_once_like_serial(monkeypatch, real_first):
    live, run = _live()
    earlier = _utc_today() - timedelta(days=2)
    live["candidates_log"] = [_row("invented_old", earlier)]
    runners = _real_runners(monkeypatch, live, run)
    second = SourceRunner("invented_second_quake", _second_quake_source)
    order = [runners["usgs_quakes"], second] if real_first else [second, runners["usgs_quakes"]]

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=order, budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    names = [r.source for r in order]
    assert _source_rows(run, names) == [(n, "success", None) for n in names]
    # Serial enqueues twice and logs once: the later writer re-observes and its row is last.
    assert [c.event_id for c in live["_triage_queue"]] == [USGS_ID, USGS_ID]
    assert [r["event_id"] for r in live["candidates_log"]] == ["invented_old", USGS_ID]
    assert live["candidates_log"][-1] is owner.stages[1].state["candidates_log"][-1]


# --- synthesis order ---------------------------------------------------------------------------------

def _observing_synthesis(runners: dict, seen: dict) -> SourceRunner:
    def run_fn(bs, current):
        seen["log"] = [r["event_id"] for r in bs.get("candidates_log", [])]
        seen["queue"] = [c.event_id for c in bs.get("_triage_queue", [])]
        runners["__synthesis__"].run(bs, current)
    return SourceRunner("synthesis_fire_drought_heat", run_fn)


@pytest.mark.parametrize("order", ORDERS)
def test_synthesis_sees_both_real_candidates_after_a_full_prune(monkeypatch, order):
    live, run = _live()
    live["candidates_log"] = [_row("invented_expired", "2020-01-01")]
    runners = _real_runners(monkeypatch, live, run)
    seen: dict = {}

    owner = scheduler.run_stage1_then_synthesis(
        live, run, serial_runners=[], concurrent_runners=[runners[s] for s in order],
        synthesis_runner=_observing_synthesis(runners, seen), budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert seen == {"log": [EVENT[s] for s in order], "queue": [EVENT[s] for s in order]}


def test_synthesis_sees_only_the_promoted_side_of_an_unrelated_replacement(monkeypatch):
    live, run = _live()
    live["candidates_log"] = [_row("invented_in_window", _utc_today() - timedelta(days=2))]
    runners = _real_runners(monkeypatch, live, run)
    seen: dict = {}

    owner = scheduler.run_stage1_then_synthesis(
        live, run, serial_runners=[],
        concurrent_runners=[runners["nws_alerts"],
                            SourceRunner("invented_replacer", _replacer([_row("invented_unrelated", _utc_today())]))],
        synthesis_runner=_observing_synthesis(runners, seen), budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:candidates_log"]
    assert seen == {"log": ["invented_in_window", NWS_ID], "queue": [NWS_ID]}


# --- the clock: window edge, stage observation time, promotion time ------------------------------
# The writer is the real record_candidate_observation with an explicit ``now``. Staging's wall clock is
# the fixture's, per thread: batch and stage start are stamped on the main thread, completion on the
# worker. Once both stages exist, the main thread's clock moves past midnight, so every promotion below
# happens after midnight; only the stages' own observation times may decide a removal.

BEFORE_MIDNIGHT = datetime(2026, 11, 2, 23, 59, 59, 500000, tzinfo=UTC)
AFTER_MIDNIGHT = datetime(2026, 11, 3, 0, 0, 0, 500000, tzinfo=UTC)
EDGE = (BEFORE_MIDNIGHT - timedelta(days=state.CANDIDATES_WINDOW_DAYS)).date()  # In the window until midnight.


class _Wall:
    def __init__(self, main: datetime):
        self.main = main
        self.by_thread: dict[int, datetime] = {}

    def __call__(self) -> datetime:
        return self.by_thread.get(threading.get_ident(), self.main)


@pytest.fixture
def wall(monkeypatch) -> _Wall:
    clock = _Wall(BEFORE_MIDNIGHT)
    monkeypatch.setattr(staging, "wall_clock", clock)
    return clock


def _observers(wall: _Wall, *specs: tuple[str, datetime, str | None]) -> list[SourceRunner]:
    """One runner per (event id, observation time, row it drops without re-observing or None)."""
    both_started = threading.Barrier(len(specs))

    def observer(event_id: str, at: datetime, drop: str | None):
        def run_fn(bs, current):
            wall.by_thread[threading.get_ident()] = at
            both_started.wait(10)  # Every stage exists before the main clock moves (raises on timeout).
            wall.main = AFTER_MIDNIGHT
            if drop is not None:  # Not the writer: an in-window row removed without re-observation.
                bs["candidates_log"] = [r for r in bs["candidates_log"] if r["event_id"] != drop]
            state.record_candidate_observation(bs, event_id=event_id, category="", legacy_type="", city="",
                                               where="", now=at)
        return SourceRunner(event_id, run_fn)

    return [observer(*spec) for spec in specs]


@pytest.mark.parametrize("age_days,kept", [(state.CANDIDATES_WINDOW_DAYS, True),
                                           (state.CANDIDATES_WINDOW_DAYS + 1, False)])
def test_a_row_exactly_at_the_window_edge_is_kept_and_one_day_older_is_pruned(wall, age_days, kept):
    live, run = _live()
    live["candidates_log"] = [_row("invented_edge", (BEFORE_MIDNIGHT - timedelta(days=age_days)).date())]

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[], budget_seconds=10,
        concurrent_runners=_observers(wall, ("invented_a", BEFORE_MIDNIGHT, None),
                                      ("invented_b", BEFORE_MIDNIGHT, None)))

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    # Serial at those observation times keeps the edge row; promoting after midnight does not prune it
    # (the next real write will).
    assert [r["event_id"] for r in live["candidates_log"]] == (["invented_edge"] if kept else []) + [
        "invented_a", "invented_b"]


@pytest.mark.parametrize("pruner_first", [False, True], ids=["pruner_second", "pruner_first"])
def test_a_stage_that_observed_after_midnight_may_prune_the_edge_row(wall, pruner_first):
    live, run = _live()
    live["candidates_log"] = [_row("invented_edge", EDGE)]
    keeper = ("invented_keeper", BEFORE_MIDNIGHT, None)
    pruner = ("invented_pruner", AFTER_MIDNIGHT, None)  # Started before midnight, observed after it.
    order = _observers(wall, *([pruner, keeper] if pruner_first else [keeper, pruner]))

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=order, budget_seconds=10)

    assert [s.disposition for s in owner.stages] == ["promoted", "promoted"]
    assert [s.started_wall for s in owner.stages] == [BEFORE_MIDNIGHT, BEFORE_MIDNIGHT]
    assert [r["event_id"] for r in live["candidates_log"]] == [r.source for r in order]


@pytest.mark.parametrize("dropper_first", [False, True], ids=["dropper_second", "dropper_first"])
def test_dropping_the_edge_row_before_midnight_conflicts_though_it_expires_before_promotion(wall, dropper_first):
    live, run = _live()
    live["candidates_log"] = [_row("invented_edge", EDGE)]
    keeper = ("invented_keeper", BEFORE_MIDNIGHT, None)
    dropper = ("invented_dropper", BEFORE_MIDNIGHT, "invented_edge")
    order = _observers(wall, *([dropper, keeper] if dropper_first else [keeper, dropper]))

    owner = scheduler.run_stage1_sources(live, run, serial_runners=[], concurrent_runners=order, budget_seconds=10)

    # The removal happened while the row was in the window; the promotion clock does not excuse it.
    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:candidates_log"]
    expected = ["invented_dropper"] if dropper_first else ["invented_edge", "invented_keeper"]
    assert [r["event_id"] for r in live["candidates_log"]] == expected


# --- shapes the writer cannot produce still refuse -----------------------------------------------

def _shape_writer(kind: str, today: date):
    def run_fn(bs, current):
        log = bs["candidates_log"]
        if kind == "duplicated_kept_key":  # Appended a key it kept, without removing the old row.
            log.append(_row("invented_kept", today))
        elif kind == "duplicated_tail_key":
            log.extend([_row("invented_twice", today), _row("invented_twice", today)])
        elif kind == "appended_outside_window":
            log.append(_row("invented_stale", "2020-01-01"))
        elif kind == "kept_outside_window":  # Changed the log yet kept a row the writer would prune.
            bs["candidates_log"] = [*log, _row("invented_fresh", today)]
    return run_fn


@pytest.mark.parametrize("kind", ["duplicated_kept_key", "duplicated_tail_key", "appended_outside_window",
                                  "kept_outside_window"])
def test_log_edits_the_writer_cannot_make_conflict(monkeypatch, kind):
    live, run = _live()
    today = _utc_today()
    live["candidates_log"] = [_row("invented_kept", today - timedelta(days=2))]
    if kind == "kept_outside_window":
        live["candidates_log"].insert(0, _row("invented_expired", "2020-01-01"))
    base = [dict(r) for r in live["candidates_log"]]
    runners = _real_runners(monkeypatch, live, run)

    owner = scheduler.run_stage1_sources(
        live, run, serial_runners=[], budget_seconds=10,
        concurrent_runners=[runners["nws_alerts"], SourceRunner("invented_shape", _shape_writer(kind, today))])

    assert [s.disposition for s in owner.stages] == ["promoted", "conflict:candidates_log"]
    pruned = [r for r in base if r["date"] >= (today - timedelta(days=state.CANDIDATES_WINDOW_DAYS)).isoformat()]
    assert live["candidates_log"][:-1] == pruned and live["candidates_log"][-1]["event_id"] == NWS_ID
