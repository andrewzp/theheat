"""Sender-stale invented sources never buy an automatic writer attempt."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
import pytest

from src.orchestrator import funnel, posting, triage_queue
from src.orchestrator.candidate_budget import CandidateBudget
from tests import test_scheduled_automatic_preflight as scheduled

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


@pytest.fixture
def world(monkeypatch):
    with freeze_time(NOW):
        spy = scheduled.world.__wrapped__(monkeypatch)
        monkeypatch.delenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", raising=False)
        monkeypatch.setenv("THEHEAT_AUTOSHIP_MAX_AGE_H", "36")
        yield spy


def candidates(world, monkeypatch):
    state, _ = scheduled.manual_slate()
    fresh = scheduled.enqueue_automatic(state, world, monkeypatch)
    row = state["_triage_queue"][-1]
    stale = replace(row, event_id="invented-stale-co2", score=replace(row.score, total=99),
        bundle=replace(row.bundle, event_id="invented-stale-co2", when=(NOW-timedelta(days=3)).isoformat()))
    state["_triage_queue"] = [stale, row]
    return state, stale, fresh


@pytest.mark.parametrize("intent", ["schedule", "explicit"])
@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_stale_top_row_cannot_take_fresh_rows_only_attempt(world, monkeypatch, intent, mode):
    if intent == "explicit":
        monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
        monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0" if mode == "legacy" else "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
    state, stale, fresh = candidates(world, monkeypatch)
    record, sink, budget = scheduled.run(), funnel.new_funnel(), CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=budget, funnel_sink=sink) == 1
    assert world.writer_events() == [fresh]
    assert [stage for stage, _ in world.calls] == ["writer", "safety", "fact_check", "critic"]
    assert budget.attempts == 1 and not budget.seen("event:"+stale.event_id)
    assert sink["_slate_terminal"][stale.event_id] == "autoship_source"
    assert state["drafts"][0]["event_id"] == fresh and state["drafts"][0]["approval_mode"] == "auto"
    report = next(r for r in record["sources"] if r["source"] == "automatic_selection")
    assert report["details"]["source_holds"] == {"autoship_source_stale": 1}
    assert report["details"]["source_ready_count"] == 1


def test_all_stale_has_zero_calls_reservations_or_drafts(world, monkeypatch):
    state, stale, _ = candidates(world, monkeypatch)
    state["_triage_queue"] = [stale]
    budget, record = CandidateBudget("invented", 1), scheduled.run()
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=budget) == 0
    assert world.calls == [] and budget.attempts == 0 and state["drafts"] == []
    assert not budget.seen("event:"+stale.event_id)
    report = next(r for r in record["sources"] if r["source"] == "automatic_selection")
    assert report["status"] == "degraded" and report["observed"] == report["promoted"] == 0


@pytest.mark.parametrize("kind", ["co2_milestone", "ch4_milestone", "all_time_high", "all_time_low", "monthly_high", "monthly_low"])
@pytest.mark.parametrize("field", ["when", "tweet_date"])
@pytest.mark.parametrize("offset,expected", [(1, None), (0, None), (-1, "autoship_source_stale")])
def test_prewriter_boundary_matches_sender_oldest_source_anchor(world, monkeypatch, kind, field, offset, expected):
    state, _, _ = candidates(world, monkeypatch)
    row = state["_triage_queue"][-1]
    boundary = (NOW-timedelta(hours=36)+timedelta(microseconds=offset)).isoformat()
    row = replace(row, legacy_type=kind, bundle=replace(row.bundle, signal_kind=kind,
        when=boundary if field == "when" else NOW.isoformat()),
        tweet_date=boundary if field == "tweet_date" else NOW.isoformat())
    assert triage_queue._automatic_source_hold(row) == expected
    draft = {"type": kind, "created_at": NOW.isoformat(), "tweet_date": row.tweet_date,
             "review_context": {"two_bot": {"bundle": row.bundle.to_dict()}}}
    anchor = posting._autoship_freshness_anchor(draft)
    assert (NOW-anchor > timedelta(hours=36)) is (expected is not None)
    assert world.calls == []


@pytest.mark.parametrize("cap", ["12", "72", "invalid"])
def test_prewriter_uses_existing_configured_ceiling(world, monkeypatch, cap):
    state, _, _ = candidates(world, monkeypatch)
    row = state["_triage_queue"][-1]
    row = replace(row, bundle=replace(row.bundle, when=(NOW-timedelta(hours=37)).isoformat()))
    monkeypatch.setenv("THEHEAT_AUTOSHIP_MAX_AGE_H", cap)
    assert triage_queue._automatic_source_hold(row) == (None if cap == "72" else "autoship_source_stale")
    assert world.calls == []


def test_manual_drain_keeps_existing_stale_generation_behavior(world, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    state, stale, _ = candidates(world, monkeypatch)
    state["_triage_queue"] = [stale]
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(), candidate_budget=CandidateBudget("invented", 1)) == 1
    assert world.writer_events() == [stale.event_id]


def test_autoship_off_keeps_existing_source_preflight(world, monkeypatch):
    state, stale, _ = candidates(world, monkeypatch)
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
    assert triage_queue._automatic_source_hold(stale) is None and world.calls == []


@pytest.mark.parametrize("when,tweet_date", [("unparseable", ""), ("", "unparseable")])
def test_unknown_date_does_not_gain_a_new_freshness_verdict(world, monkeypatch, when, tweet_date):
    state, _, _ = candidates(world, monkeypatch)
    row = state["_triage_queue"][-1]
    row = replace(row, bundle=replace(row.bundle, when=when), tweet_date=tweet_date)
    assert triage_queue._automatic_source_hold(row) is None
    # The evidence audit, required checks and sender still own their decisions.
    assert world.calls == []


def test_stale_only_async_pool_never_reaches_generation_client(world, monkeypatch):
    state, stale, _ = candidates(world, monkeypatch)
    state["_triage_queue"] = [stale]
    class NoCalls:
        def __getattr__(self, name):
            pytest.fail("stale candidate reached generation client: " + name)
    budget = CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(),
        generation_client=NoCalls(), candidate_budget=budget) == 0
    assert world.calls == [] and budget.attempts == 0


def test_completed_month_uses_validated_capture_not_measurement_date(monkeypatch):
    from tests import test_c3s_observed_report as c3s
    with freeze_time(c3s.NOW):
        monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
        monkeypatch.setenv("THEHEAT_AUTOSHIP_MAX_AGE_H", "36")
        spy = scheduled.world.__wrapped__(monkeypatch)
        state, _ = scheduled.manual_slate()
        scheduled.enqueue_automatic(state, spy, monkeypatch)
        original = state["_triage_queue"][-1]
        bundle = c3s.source.build_bundle(c3s.report())
        row = replace(original, legacy_type=bundle.signal_kind, bundle=bundle, event_id=bundle.event_id,
                      tweet_date=bundle.when)
        assert bundle.when == "2026-10-31"
        assert triage_queue._automatic_source_hold(row) is None
        raw = bundle.to_dict()
        raw["raw_signal_dump"]["retrieved_at"] = "2026-10-01T00:00:00Z"
        # A malformed old capture is not exempted by the retrospective type.
        from src.two_bot.types import StoryBundle
        changed = replace(row, bundle=StoryBundle(**raw))
        assert triage_queue._automatic_source_hold(changed) == "autoship_source_stale"
        assert spy.calls == []
