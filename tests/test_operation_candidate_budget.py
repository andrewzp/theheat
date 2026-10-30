"""O2: one candidate-attempt budget per generation operation, across drains and refill.

Real drains, real source boundary and real pipeline; model stages are explicit
offline stubs behind the real provider boundary (tests/operation_budget_helpers).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.orchestrator import triage_queue
from src.orchestrator.candidate_budget import (
    CandidateBudget, CandidateBudgetConfigError, configured_max_candidates,
)
from src.two_bot import negative_cache
from src.two_bot.types import StoryBundle
from tests.operation_budget_helpers import Spies, enqueue_fires, fires, fresh_state


@pytest.fixture
def spies(monkeypatch):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "50")  # Isolate the operation budget from
    monkeypatch.setenv("THEHEAT_PENDING_TYPE_CAP", "50")  # the unchanged diversity caps.
    for name in ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "THEHEAT_REFILL_ENABLED", "THEHEAT_FUNNEL_TELEMETRY",
                 "THEHEAT_DRAFTS_TARGET_PER_CYCLE", "THEHEAT_REFILL_MAX_ATTEMPTS"):
        monkeypatch.delenv(name, raising=False)
    return Spies().install(monkeypatch)


def drain(state, budget=None, run=None):
    from src.orchestrator.common import _suppression_context
    run = {"id": "run-o2", "sources": []} if run is None else run
    with _suppression_context(state, source="alerts", run_id=run["id"]):  # As run_alerts activates it.
        return triage_queue._drain_and_write_triage_queue(state, run, candidate_budget=budget), run


def budget_cuts(state):
    return [row for row in state["suppressions"] if row.get("stage") == "triage_cap"
            and any(reason.startswith("candidate_budget=") for reason in row.get("reasons", []))]


@pytest.mark.parametrize("raw,expected", [(None, 3), ("", 3), ("1", 1), (" 2 ", 2), ("+4", 4), ("200", 200)],
                         ids=["unset", "empty", "one", "spaces", "plus", "bound"])
def test_configured_maximum_keeps_its_meaning_and_default(raw, expected):
    assert configured_max_candidates({} if raw is None else {"THEHEAT_MAX_DRAFTS_PER_CYCLE": raw}) == expected


@pytest.mark.parametrize("raw,code", [
    ("abc", "max_drafts_per_cycle_not_integer"), ("3.5", "max_drafts_per_cycle_not_integer"),
    ("1_0", "max_drafts_per_cycle_not_integer"), ("３", "max_drafts_per_cycle_not_integer"),
    ("-1", "max_drafts_per_cycle_not_integer"), ("0", "max_drafts_per_cycle_not_positive"),
    ("201", "max_drafts_per_cycle_above_bound"),
], ids=["word", "decimal", "underscore", "fullwidth", "negative", "zero", "above-bound"])
def test_unsafe_configured_maximum_is_refused_not_defaulted(raw, code):
    with pytest.raises(CandidateBudgetConfigError) as caught:
        configured_max_candidates({"THEHEAT_MAX_DRAFTS_PER_CYCLE": raw})
    assert caught.value.code == code
    on = CandidateBudget.for_operation("alerts", {"THEHEAT_TRIAGE_ENABLED": "1", "THEHEAT_MAX_DRAFTS_PER_CYCLE": raw})
    assert (on.limit, on.refusal) == (0, code)
    # Triage-disabled legacy behaviour is unchanged: no operation limit, no refusal.
    off = CandidateBudget.for_operation("alerts", {"THEHEAT_MAX_DRAFTS_PER_CYCLE": raw})
    assert (off.limit, off.refusal) == (None, None)


def test_operation_maxima_are_explicit():
    assert CandidateBudget.for_operation("alerts", {"THEHEAT_TRIAGE_ENABLED": "1"}).limit == 3
    assert CandidateBudget.for_operation("alerts", {}).limit is None  # Legacy: no new limit.
    # Hot10 is one daily candidate whether or not triage is enabled.
    assert CandidateBudget.for_operation("leaderboard", {}).limit == 1
    assert CandidateBudget.for_operation("leaderboard", {"THEHEAT_TRIAGE_ENABLED": "1",
                                                         "THEHEAT_MAX_DRAFTS_PER_CYCLE": "5"}).limit == 1


@pytest.mark.parametrize("raw", ["0", "abc", "999"])
def test_unsafe_configured_maximum_holds_the_operation_visibly(spies, monkeypatch, raw):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", raw)
    state = fresh_state()
    enqueue_fires(state, 2)
    drafted, run = drain(state)
    assert drafted == 0 and spies.calls == [] and state["drafts"] == []
    (row,) = [row for row in run["sources"] if row["source"] == "triage"]
    assert row["status"] == "partial_failure" and row["note"].startswith("candidate_budget_config_invalid")
    assert row["error"].startswith("max_drafts_per_cycle_") and row["details"]["held"] == 2


def test_repeated_drains_share_one_budget_and_a_later_operation_starts_fresh(spies, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2")
    state = fresh_state()
    _enqueue(state, fires(3))
    operation = CandidateBudget.for_operation("alerts")
    assert drain(state, operation)[0] == 2 and len(spies.writer_events()) == 2
    # A second drain inside the same operation cannot buy more attempts.
    second = _enqueue(state, fires(5)[3:])
    drafted, _ = drain(state, operation)
    assert drafted == 0 and len(spies.writer_events()) == 2 and operation.attempts == 2
    cuts = budget_cuts(state)
    assert {row["event_id"] for row in cuts} == set(second)
    assert all(row["reasons"] == ["candidate_budget=2"] for row in cuts)
    # A later, independent operation has its own budget; no limit leaks between them.
    later = _enqueue(state, fires(7)[5:])
    assert drain(state, CandidateBudget.for_operation("alerts"))[0] == 2
    assert set(spies.writer_events()[2:]) == set(later) and len(state["drafts"]) == 4


def _enqueue(state, detections) -> list[str]:
    from src.editorial.scoring import score_fire_event
    from src.orchestrator.common import _review_context
    from src.two_bot.intern.fire import build_fire_bundle
    ids = []
    for fire in detections:
        assert triage_queue._enqueue_story_candidate(
            state, bundle=build_fire_bundle(fire), score=score_fire_event(fire.confidence, fire.frp, region=fire.nearest_city),
            source="firms", legacy_type="fire", event_id=fire.event_id,
            review_context=_review_context(source="Invented FIRMS", source_key="firms", headline="Invented", facts=[]))
        ids.append(fire.event_id)
    return ids


def test_the_same_event_in_two_drains_buys_one_attempt(spies, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "3")
    spies.critic_kill.update(fire.event_id for fire in fires(1))  # Rejected, so it is not a saved duplicate.
    state = fresh_state()
    operation = CandidateBudget.for_operation("alerts")
    _enqueue(state, fires(1))
    drain(state, operation)
    _enqueue(state, fires(1))  # The identical queued story again, later in the same operation.
    drafted, _ = drain(state, operation)
    assert drafted == 0 and spies.writer_events() == [fires(1)[0].event_id] and operation.attempts == 1
    assert any(row.get("stage") == "duplicate_draft" for row in state["suppressions"])


def test_a_rejected_attempt_keeps_its_slot_and_refill_stops_at_the_budget(spies, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")  # Refill target 3, its own ceiling 6.
    detections = fires(5)
    spies.critic_kill.update(fire.event_id for fire in detections)
    state = fresh_state()
    _enqueue(state, detections)
    drafted, run = drain(state)
    assert drafted == 0 and len(spies.writer_events()) == 2  # Two rejections; no refund, no third buy.
    stages = [stage for stage, _ in spies.calls]
    assert stages == ["writer", "safety", "fact_check", "critic"] * 2  # Every required check, each time.
    assert len(budget_cuts(state)) == 3
    assert sum(row.get("stage") == "critic" for row in state["suppressions"]) == 2


def _cache_dead(state, fire):
    from src.two_bot.intern.fire import build_fire_bundle
    bundle = build_fire_bundle(fire)
    sha = negative_cache.bundle_fingerprint(bundle, state)
    now = datetime.now(UTC) - timedelta(minutes=1)
    for delta in (2, 1):
        negative_cache.record_kill(state, fire.event_id, sha, "writer", "invented evidence judgment",
                                   now=now - timedelta(minutes=delta), scope="evidence", code="insufficient_evidence")
    assert negative_cache.should_skip(state, fire.event_id, bundle) is not None


@pytest.mark.parametrize("refill", [False, True], ids=["legacy", "refill"])
def test_cache_only_candidates_spend_nothing_and_changed_facts_reopen(spies, monkeypatch, refill):
    from tests.fire_source_fixtures import fire_event
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    if refill:
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    state = fresh_state()
    dead = fires(1)[0]
    _cache_dead(state, dead)
    # Same event, new (lower-ranked) facts: the cache-dead row is met first in both modes.
    changed = fire_event(lat=dead.lat, lon=dead.lon, frp=150.0, region=dead.nearest_city)
    assert changed.event_id == dead.event_id
    _enqueue(state, [dead, changed])
    drafted, _ = drain(state)
    assert spies.writer_events() == [dead.event_id] and drafted == 1  # The changed-facts row got the slot.
    assert sum(row.get("stage") == "negative_cache" for row in state["suppressions"]) == 1
    assert state["drafts"][0]["status"] == "pending"


def test_a_pre_writer_refusal_returns_its_slot(spies, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    state = fresh_state()
    held = StoryBundle(signal_kind="official_warning", where="Invented Island", when="2026-10-29",
                       event_id="official_warning:invented", headline_metric={"label": "x", "value": 1},
                       current_facts=[])
    _enqueue(state, fires(1))
    first = state["_triage_queue"][0]
    # Inserted directly: the refusal under test happens at the dispatch boundary.
    state["_triage_queue"].insert(0, replace(first, bundle=held, score=replace(first.score, total=99),
                                             event_id=held.event_id, source="official_warning",
                                             legacy_type="official_warning", review_context={}))
    run = {"id": "run-o2", "sources": [{"source": "official_warning"}, {"source": "firms"}]}
    operation = CandidateBudget.for_operation("alerts")
    drafted, run = drain(state, operation, run)
    # No current WarningSource owner: refused before the writer, so its slot went to the fire.
    assert drafted == 1 and spies.writer_events() == [fires(1)[0].event_id]
    assert (operation.attempts, operation.refused_before_writer) == (1, 1)
    warning_row = run["sources"][0]
    assert warning_row.get("writer_attempted", 0) == 0  # Distinguishable: no paid attempt counted.
    assert any(row.get("stage") == "warning_source" for row in state["suppressions"])


def test_a_writer_transport_failure_keeps_its_slot(spies, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")

    def lost(bundle, memory, **kwargs):
        spies.calls.append(("writer", bundle.event_id))
        raise TimeoutError("invented lost writer response")
    from src.two_bot import pipeline
    monkeypatch.setattr(pipeline.writer, "write_tweet", lost)
    state = fresh_state()
    _enqueue(state, fires(3))
    drafted, _ = drain(state)
    assert drafted == 0 and len(spies.writer_events()) == 1  # Unknown outcome: no second purchase.
    assert any(row.get("stage") == "pipeline_error" for row in state["suppressions"])


def test_an_escaping_exception_leaves_the_slot_spent_and_a_later_operation_is_independent(spies, monkeypatch):
    from src.orchestrator import common
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    real = common._try_two_bot_draft

    def explode(*args, **kwargs):
        raise RuntimeError("invented dispatch crash")
    monkeypatch.setattr(common, "_try_two_bot_draft", explode)
    state = fresh_state()
    _enqueue(state, fires(2))
    operation = CandidateBudget.for_operation("alerts")
    with pytest.raises(RuntimeError, match="invented dispatch crash"):
        drain(state, operation)
    assert operation.attempts == 1 and operation.exhausted()
    monkeypatch.setattr(common, "_try_two_bot_draft", real)
    _enqueue(state, fires(4)[2:])
    assert drain(state, CandidateBudget.for_operation("alerts"))[0] == 1


def test_an_empty_queue_spends_nothing(spies):
    operation = CandidateBudget.for_operation("alerts")
    drafted, run = drain(fresh_state(), operation)
    assert drafted == 0 and spies.calls == [] and run["sources"] == [] and operation.summary()["attempts"] == 0
