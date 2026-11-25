"""Context-format preference through real collection, selection and paid boundaries.

HTTP bytes and SDK responses are invented. Actual source qualification, writer,
safety/fact/critic interpreters and admission run; no sender or live service runs.
These tests establish selection behavior, not reader preference or weather truth.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from freezegun import freeze_time
import pytest

from src.data import awc_observed as awc
from src.data import coastal_observed as coastal
from src.data import water_levels as wl
from src.orchestrator.candidate_budget import CandidateBudget
from src.orchestrator.sources import co_ops
from src.orchestrator.sources.awc_observed import run_awc_observed
from src.orchestrator.suppression import _suppression_context
from src.orchestrator.triage import select_survivors
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from tests.test_awc_observed_automatic import Transport as AirportTransport
from tests.test_awc_ordinary_selection_competition import DatedTransport
from tests.test_coastal_observed_automatic import COPY as COASTAL_COPY
from tests.test_coastal_observed_automatic import Transport as CoastalTransport
from tests.test_coastal_observed_provenance import NOW, STATION
from tests.test_observed_copy_guard_journey import COPY as AIRPORT_COPY
from tests.test_observed_copy_guard_journey import REQUIRED, _models
from tests.test_triage import _candidate

PAIR_COPY = AIRPORT_COPY.replace("12:00", "07:24").replace("Nov 15", "Nov 13")
EVENT_COPY = COASTAL_COPY.replace("2.1 m", "0.7 m")


class MixedTransport(DatedTransport):
    """The existing airport and coastal HTTP fixtures, with one shared trap.

    Each existing reader handles only its own fixed source endpoints; the
    outer transport retains the socket trap and any forbidden-write counters.
    """

    def __init__(self, initial):
        super().__init__(initial)
        self._coastal = CoastalTransport()
        self.observed, self.predicted = self._coastal.observed, self._coastal.predicted
        self.coastal_calls = self._coastal.coastal_calls

    def send(self, _adapter, request, **options):
        parts = urlsplit(request.url)
        if f"{parts.scheme}://{parts.netloc}{parts.path}" == wl.COOPS_URL:
            return self._coastal.send(_adapter, request, **options)
        return super().send(_adapter, request, **options)


def stage(monkeypatch, state, *, mode="triage", pair=True, event=True, event_age=timedelta(0)):
    models = _models(monkeypatch, copies={awc.KIND: PAIR_COPY, coastal.KIND: EVENT_COPY})
    for key, value in {
        "THEHEAT_TRIAGE_ENABLED": "0" if mode == "legacy" else "1",
        "THEHEAT_AWC_OBSERVED_GUST": "0", "THEHEAT_PORTFOLIO_SELECTION": "0",
        "GITHUB_EVENT_NAME": "schedule", "THEHEAT_AUTOMATIC_SELECTION_ONLY": "0",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(wl, "STATIONS", [STATION])
    transport = MixedTransport(AirportTransport())
    for row in transport.rows:
        row[0] = row[0].replace("151200Z", "130724Z")
        row[2] = "2026-11-13T07:24:00Z"
    transport.observed["data"][-1]["v"] = "1.700"
    transport.install(monkeypatch.setattr)
    run = {"id": "invented-context-selection", "mode": "alerts", "sources": []}
    with freeze_time(NOW):
        if pair:
            run_awc_observed(state, run)
        if event:
            for payload, key in ((transport.observed, "data"), (transport.predicted, "predictions")):
                for row in payload[key]:
                    at = datetime.fromisoformat(row["t"]) - event_age
                    row["t"] = at.strftime("%Y-%m-%d %H:%M")
            with freeze_time(NOW - event_age):
                co_ops.run_water_levels(state, run)
    queued = state.get("_triage_queue", [])
    assert len(queued) == int(pair) + int(event), run
    by_kind = {c.bundle.signal_kind: c for c in queued}
    if pair:
        assert by_kind[awc.KIND].score.total == 80
    if event:
        assert by_kind[coastal.KIND].score.total == 64
    assert models.stages() == []
    if mode == "refill":
        # Source nomination stays under its required no-refill settings. Only
        # this offline drain exercises the already existing optional branch.
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    return transport, models, run, by_kind


def drain(state, run, *, limit=1):
    budget = CandidateBudget(operation="alerts", limit=limit)
    with freeze_time(NOW + timedelta(minutes=1), tick=True), _suppression_context(
            state, source="alerts", run_id=run["id"]):
        count = _drain_and_write_triage_queue(state, run, candidate_budget=budget)
    return count, budget


def assert_private_pending(transport, models, state, budget, kind):
    assert models.stages() == REQUIRED
    assert budget.attempts == 1
    [draft] = state["drafts"]
    assert draft["type"] == kind and draft["status"] == "pending"
    assert draft["review_binding"]["kind"] == "model"
    assert draft["approval_binding"]["mode"] == "auto"
    assert "tweet_id" not in draft and "posted_at" not in draft
    assert len(draft["text"]) <= 200
    assert transport.x_posts == [] and transport.gist_patches == 0
    assert state.get("publish_ledger", {}) == {}
    return draft


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
@pytest.mark.parametrize("reverse", [False, True])
def test_lower_scored_observed_event_precedes_pair_before_the_only_writer_attempt(
        monkeypatch, fresh_state, mode, reverse):
    transport, models, run, candidates = stage(monkeypatch, fresh_state, mode=mode)
    if reverse:
        fresh_state["_triage_queue"].reverse()
    count, budget = drain(fresh_state, run)
    assert count == 1, fresh_state.get("suppressions")
    saved = assert_private_pending(transport, models, fresh_state, budget, coastal.KIND)
    assert saved["text"] == EVENT_COPY + "\n" + coastal.citation(STATION[0])
    assert saved["review_context"]["two_bot"]["bundle"] == candidates[coastal.KIND].bundle.to_dict()
    assert len(transport.coastal_calls) == 8  # nomination, snapshot, writer, admission
    assert len(transport.awc_calls) == 2  # no source reread for the unselected pair
    assert not budget.seen(CandidateBudget.key_for(candidates[awc.KIND]))
    if mode == "triage":
        [held] = [r for r in fresh_state["suppressions"] if r["event_id"] == candidates[awc.KIND].event_id]
        assert held["stage"] == "triage_cap"
        assert held["reasons"] == ["global_cap=1", "context_comparison_fallback"]


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_pair_alone_remains_eligible_through_all_actual_checks(monkeypatch, fresh_state, mode):
    transport, models, run, _ = stage(monkeypatch, fresh_state, mode=mode, event=False)
    count, budget = drain(fresh_state, run)
    assert count == 1, fresh_state.get("suppressions")
    saved = assert_private_pending(transport, models, fresh_state, budget, awc.KIND)
    assert saved["text"] == PAIR_COPY + "\n" + awc.citation(["TAAA", "TBBB"], "2026-11-13T07:24:00Z")
    assert len(transport.awc_calls) == 6


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_chosen_weak_story_does_not_purchase_a_comparison_refill(monkeypatch, fresh_state, mode):
    transport, models, run, candidates = stage(monkeypatch, fresh_state, mode=mode)
    models.critic = {"verdict": "KILL", "kill_reason": "weak_signal", "revise_instruction": None,
                     "selected_index": None}
    count, budget = drain(fresh_state, run)
    assert count == 0 and fresh_state["drafts"] == []
    assert models.stages() == REQUIRED and budget.attempts == 1
    assert budget.seen(CandidateBudget.key_for(candidates[coastal.KIND]))
    assert not budget.seen(CandidateBudget.key_for(candidates[awc.KIND]))
    assert transport.x_posts == [] and transport.gist_patches == 0


def test_cap_attribution_requires_an_actual_change_from_old_score_order(monkeypatch, fresh_state):
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "2")
    pair = _candidate(signal_kind=awc.KIND, total=80, event_id="pair")
    stronger_event = _candidate(signal_kind="fire", total=90, event_id="event")
    assert select_survivors(fresh_state, [pair, stronger_event], global_cap=1) == [stronger_event]
    assert fresh_state["suppressions"][0]["reasons"] == ["global_cap=1"]


def test_blocked_pair_in_unexamined_bulk_tail_has_no_false_preference_reason(monkeypatch, fresh_state):
    monkeypatch.setenv("THEHEAT_PENDING_TYPE_CAP", "1")
    fresh_state["drafts"] = [{"id": "pending", "type": awc.KIND, "status": "pending"}]
    events = [_candidate(signal_kind=k, total=score, event_id=k)
              for k, score in [("fire", 95), ("drought", 90), ("snow_extreme", 85)]]
    pair = _candidate(signal_kind=awc.KIND, total=80, event_id="pair")
    assert select_survivors(fresh_state, [pair, *events], global_cap=2) == events[:2]
    held = next(row for row in fresh_state["suppressions"] if row["event_id"] == "pair")
    assert held["reasons"] == ["global_cap=2"]


def test_country_capped_event_leaves_a_slot_for_a_comparison(monkeypatch, fresh_state):
    monkeypatch.setenv("THEHEAT_PER_COUNTRY_CAP", "1")
    first = _candidate(signal_kind="fire", total=90, country="NO", event_id="first")
    blocked = _candidate(signal_kind="drought", total=70, country="NO", event_id="blocked")
    pair = _candidate(signal_kind=awc.KIND, total=80, event_id="pair")
    assert select_survivors(fresh_state, [pair, blocked, first], global_cap=2) == [first, pair]
    [held] = fresh_state["suppressions"]
    assert held["event_id"] == "blocked" and held["reasons"] == ["per_country_cap=1"]


def test_kind_classifier_never_generalizes_to_gusts_or_mismatched_wrappers():
    from src.editorial.format_spacing import is_context_comparison
    pair = _candidate(signal_kind=awc.KIND)
    gust = _candidate(signal_kind="observed_metar_gust")
    assert is_context_comparison(pair)
    assert not is_context_comparison(gust)
    assert not is_context_comparison(replace(pair, legacy_type=gust.legacy_type))
    assert not is_context_comparison(replace(gust, legacy_type=pair.legacy_type))


def test_event_and_comparison_classes_keep_score_time_and_stable_exact_ties(fresh_state):
    pairs = [_candidate(signal_kind=awc.KIND, total=s, event_id=e, created_at=t)
             for s, e, t in [(80, "older", "2026-05-17T10:00:00Z"),
                              (80, "newer", "2026-05-17T11:00:00Z")]]
    events = [_candidate(signal_kind=k, total=s, event_id=e, created_at=t)
              for k, s, e, t in [("fire", 65, "low", "2026-05-17T12:00:00Z"),
                                 ("snow_extreme", 70, "tie1", "2026-05-17T11:00:00Z"),
                                 ("drought", 70, "tie2", "2026-05-17T11:00:00Z")]]
    queue = [pairs[0], *events, pairs[1]]
    assert select_survivors(fresh_state, queue, refill=True) == [events[1], events[2], events[0], pairs[1], pairs[0]]
    assert fresh_state.get("suppressions", []) == []
    assert select_survivors(fresh_state, pairs, refill=True) == list(reversed(pairs))
    assert select_survivors(fresh_state, events, refill=True) == [events[1], events[2], events[0]]


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
@pytest.mark.parametrize("blocked", ["stale", "invalid", "manual-type", "pending-event", "negative-cache"])
def test_free_refusal_of_the_alternative_preserves_the_comparisons_only_attempt(
        monkeypatch, fresh_state, mode, blocked):
    transport, models, run, candidates = stage(monkeypatch, fresh_state, mode=mode,
        event_age=coastal.MAX_AGE + timedelta(minutes=6) if blocked == "stale" else timedelta(0))
    event = candidates[coastal.KIND]
    prior = None
    if blocked == "invalid":
        event.bundle.raw_signal_dump["evidence"]["observed_m"] = 9.0
    elif blocked == "manual-type":
        fresh_state["_triage_queue"][1] = replace(event, legacy_type="invented_manual_only")
    elif blocked == "pending-event":
        prior = {"id": "invented-pending-event", "type": coastal.KIND,
                 "status": "pending", "event_id": event.event_id}
        fresh_state["drafts"].append(prior.copy())
    elif blocked == "negative-cache":
        from src.two_bot import negative_cache as cache
        with freeze_time(NOW + timedelta(minutes=1)):
            fingerprint = cache.bundle_fingerprint(event.bundle, fresh_state)
            for minutes in (2, 1):
                cache.record_kill(fresh_state, event.event_id, fingerprint, "writer", "invented prior judgment",
                    scope="evidence", code="insufficient_evidence",
                    now=NOW + timedelta(minutes=1 - minutes))
            assert cache.should_skip(fresh_state, event.event_id, event.bundle) is not None
    count, budget = drain(fresh_state, run)
    assert count == 1 and budget.attempts == 1, fresh_state.get("suppressions")
    assert models.stages() == REQUIRED
    assert not budget.seen(CandidateBudget.key_for(event))
    [saved] = [d for d in fresh_state["drafts"] if d["event_id"] == candidates[awc.KIND].event_id]
    assert saved["text"] == PAIR_COPY + "\n" + awc.citation(["TAAA", "TBBB"], "2026-11-13T07:24:00Z")
    assert saved["status"] == "pending" and "tweet_id" not in saved
    if prior:
        assert fresh_state["drafts"][0] == prior
    assert len(transport.coastal_calls) == 4  # no writer-bound refresh of the blocked alternative
    assert len(transport.awc_calls) == 6
    assert transport.x_posts == [] and transport.gist_patches == 0
    assert fresh_state.get("publish_ledger", {}) == {}
    assert not any("context_comparison_fallback" in r.get("reasons", [])
                   for r in fresh_state.get("suppressions", []))


def test_pending_type_cap_still_admits_the_fallback(monkeypatch, fresh_state):
    monkeypatch.setenv("THEHEAT_PENDING_TYPE_CAP", "1")
    fresh_state["drafts"] = [{"id": "pending-event", "type": "fire", "status": "pending"}]
    pair = _candidate(signal_kind=awc.KIND, total=80, event_id="pair")
    event = _candidate(signal_kind="fire", total=64, event_id="event")
    assert select_survivors(fresh_state, [pair, event], global_cap=1) == [pair]
    [held] = fresh_state["suppressions"]
    assert held["event_id"] == "event" and held["reasons"] == ["pending_type_cap=1"]


def test_unlimited_legacy_retains_original_input_order(monkeypatch, fresh_state):
    transport, models, run, candidates = stage(monkeypatch, fresh_state, mode="legacy")
    # The normal legacy policy has no operation cap; this change must not
    # silently turn it into default-triage ordering or alter callback order.
    count, budget = drain(fresh_state, run, limit=None)
    assert count == 2 and budget.attempts == 2
    assert [d["type"] for d in fresh_state["drafts"]] == [awc.KIND, coastal.KIND]
    assert models.stages() == REQUIRED * 2
    assert all(budget.seen(CandidateBudget.key_for(c)) for c in candidates.values())
    assert transport.x_posts == [] and transport.gist_patches == 0


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_live_source_change_after_critic_still_holds_without_buying_a_replacement(
        monkeypatch, fresh_state, mode):
    transport, models, run, candidates = stage(monkeypatch, fresh_state, mode=mode)
    original = models.google_text

    def correct_source_after_reply(request):
        stage_name, text = original(request)
        if stage_name == "critic":
            transport.observed["data"][-1]["v"] = "1.800"
        return stage_name, text

    monkeypatch.setattr(models, "google_text", correct_source_after_reply)
    count, budget = drain(fresh_state, run)
    assert count == 0 and budget.attempts == 1 and fresh_state["drafts"] == []
    assert models.stages() == REQUIRED
    assert not budget.seen(CandidateBudget.key_for(candidates[awc.KIND]))
    assert transport.x_posts == [] and transport.gist_patches == 0


def test_mismatched_airport_identity_cannot_escape_source_refusal(monkeypatch, fresh_state):
    transport, models, run, candidates = stage(monkeypatch, fresh_state)
    pair = candidates[awc.KIND]
    fresh_state["_triage_queue"][0] = replace(pair, legacy_type=coastal.KIND)
    count, budget = drain(fresh_state, run)
    assert count == 1
    assert_private_pending(transport, models, fresh_state, budget, coastal.KIND)
    [held] = [r for r in fresh_state["suppressions"] if r["event_id"] == pair.event_id]
    assert held["stage"] == "awc_source" and "awc_source_identity_changed" in str(held)


@pytest.mark.parametrize("mode", ["triage", "refill"])
def test_enabled_portfolio_receives_the_original_pool_and_keeps_its_actual_choice(
        monkeypatch, fresh_state, mode):
    from copy import deepcopy
    from src.orchestrator import portfolio_selection as portfolio
    transport, models, run, candidates = stage(monkeypatch, fresh_state, mode=mode)
    original_pool = list(fresh_state["_triage_queue"])
    full = mode == "refill"
    # The real planner holds these source-valid packets for missing importance
    # dimensions. Neither a fixed source score nor the new format preference
    # may manufacture those dimensions or replace that empty selection.
    expected = portfolio.select(deepcopy(fresh_state), original_pool,
                                cap=None if full else 1, full=full)
    assert expected == []
    original_select = portfolio.select
    observed = []

    def observe_real_selection(state, pool, *, cap, full=False):
        observed.append(list(pool))
        return original_select(state, pool, cap=cap, full=full)

    monkeypatch.setenv(portfolio.FLAG, "1")
    monkeypatch.setattr(portfolio, "select", observe_real_selection)
    count, budget = drain(fresh_state, run)
    assert count == 0 and budget.attempts == 0 and fresh_state["drafts"] == []
    assert len(observed) == 1
    assert all(actual is prior for actual, prior in zip(observed[0], original_pool, strict=True))
    assert models.stages() == []
    assert not any(budget.seen(CandidateBudget.key_for(c)) for c in candidates.values())
    assert transport.x_posts == [] and transport.gist_patches == 0
