"""Real admission/drain/pipeline; invented evidence and offline model stages only."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from src.orchestrator import funnel, triage_queue
from src.orchestrator.candidate_budget import CandidateBudget
from src.two_bot.evidence_contract import audit_story_bundle
from tests.operation_budget_helpers import Spies, enqueue_fires, fresh_state


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    for key in ("THEHEAT_REFILL_ENABLED", "THEHEAT_MULTISIGNAL_CONTEXT", "THEHEAT_NEWS_ENRICH_ENABLED",
                "THEHEAT_PORTFOLIO_SELECTION", "THEHEAT_NEWSWORTHINESS_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    return Spies().install(monkeypatch)


def slate():
    state = fresh_state()
    ids = enqueue_fires(state, 2)
    first = state["_triage_queue"][0]
    state["_triage_queue"][0] = replace(first, score=replace(first.score, total=99))
    return state, ids


def invalidate(candidate):
    # Admission already checked the original bundle; optional enrichment runs later.
    candidate.bundle.human_impact = [{"claim": "Unwarranted invented consequence", "value": 1}]
    assert not audit_story_bundle(candidate.bundle).prompt_ready


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_invalidated_evidence_leaves_valid_candidate_its_only_attempt(world, monkeypatch, mode):
    if mode == "legacy":
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    if mode == "refill":
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    state, (invalid, eligible) = slate()
    invalidate(state["_triage_queue"][0])
    budget = CandidateBudget("invented", 1)
    run = {"id": "invented-evidence-recheck", "sources": [
        {"source": "firms", "triaged_in": 0, "triaged_out": 0, "writer_attempted": 0, "drafted": 0}]}
    sink = funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(
        state, run, candidate_budget=budget, funnel_sink=sink) == 1
    assert world.writer_events() == [eligible]
    assert [stage for stage, _ in world.calls] == ["writer", "safety", "fact_check", "critic"]
    assert budget.attempts == 1 and not budget.seen("event:" + invalid)
    (held,) = [row for row in state["suppressions"] if row["event_id"] == invalid]
    assert held["stage"] == "evidence_contract"
    assert held["evidence_readiness"]["status"] == "needs_evidence_repair"
    assert "invalid_impact_provenance" in {row["code"] for row in held["evidence_readiness"]["issues"]}
    assert sink["_slate_terminal"][invalid] == "evidence_contract"
    assert sink["_slate_terminal"][eligible] == "drafted"
    row = next(row for row in run["sources"] if row["source"] == "firms")
    assert row["triaged_in"] == row["triaged_out"] == 2
    assert row["writer_attempted"] == row["drafted"] == 1
    assert state["drafts"][0]["status"] == "pending"
    assert "approval_binding" not in state["drafts"][0]


def test_all_invalid_evidence_reserves_nothing_and_calls_nothing(world):
    state, ids = slate()
    for candidate in state["_triage_queue"]:
        invalidate(candidate)
    budget = CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}, candidate_budget=budget) == 0
    assert world.calls == [] and budget.attempts == 0 and budget.refused_before_writer == 0
    assert all(not budget.seen("event:" + event) for event in ids)
    assert len(state["suppressions"]) == 2


def test_invalid_same_event_copy_does_not_block_valid_changed_evidence(world):
    state, (first_id, _) = slate()
    original = deepcopy(state["_triage_queue"][0])
    invalidate(state["_triage_queue"][0])
    state["_triage_queue"] = [state["_triage_queue"][0], original]
    sink = funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}, funnel_sink=sink) == 1
    assert world.writer_events() == [first_id]
    assert sink["_slate_terminal"][first_id] == "evidence_contract"  # First terminal stays.


def test_warning_only_evidence_still_reaches_all_required_stages(world):
    state, _ = slate()
    state["_triage_queue"] = state["_triage_queue"][:1]
    audit = audit_story_bundle(state["_triage_queue"][0].bundle)
    assert audit.prompt_ready and any(issue.severity == "warning" for issue in audit.issues)
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}) == 1
    assert [stage for stage, _ in world.calls] == ["writer", "safety", "fact_check", "critic"]


def test_enrichment_is_checked_before_selection(world, monkeypatch):
    state, (_, eligible) = slate()
    monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")

    def enrich(queue, news):
        invalidate(queue[0])
        return 1

    monkeypatch.setattr("src.editorial.newsworthiness.attach_human_impact", enrich)
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}) == 1
    assert world.writer_events() == [eligible]


def test_later_evidence_mutation_still_refuses_at_independent_pipeline_audit(world, monkeypatch):
    from src.orchestrator import triage
    state, _ = slate()
    original = triage.select_survivors

    def select_then_change(*args, **kwargs):
        chosen = original(*args, **kwargs)
        invalidate(chosen[0])
        return chosen

    monkeypatch.setattr(triage, "select_survivors", select_then_change)
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}) == 0
    assert world.calls == [] and state["drafts"] == []


def test_audit_exception_holds_evidence_without_raw_error_or_provider_call(world, monkeypatch):
    state, _ = slate()
    state["_triage_queue"] = state["_triage_queue"][:1]
    invalidate(state["_triage_queue"][0])

    def broken_audit(_bundle):
        raise ValueError("invented private diagnostic must not leak")

    monkeypatch.setattr("src.two_bot.evidence_contract.audit_story_bundle", broken_audit)
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}) == 0
    assert world.calls == []
    assert state["suppressions"][0]["stage"] == "evidence_contract"
    assert state["suppressions"][0]["reasons"] == ["pre-writer: evidence_audit_unavailable"]


def test_malformed_related_signal_does_not_take_the_only_slot(world):
    state, (_, eligible) = slate()
    state["_triage_queue"][0].bundle.related_signals = [object()]
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}) == 1
    assert world.writer_events() == [eligible]
    assert state["suppressions"][0]["stage"] == "evidence_contract"


def test_unchanged_admitted_packets_do_not_repeat_the_source_audit(world, monkeypatch):
    state, _ = slate()
    # The independent pipeline audit keeps its original binding. Only the new
    # optional-enrichment check uses this module lookup during the drain.
    monkeypatch.setattr("src.two_bot.evidence_contract.audit_story_bundle",
                        lambda bundle: pytest.fail("unchanged admission needlessly re-audited"))
    assert triage_queue._drain_and_write_triage_queue(state, {"sources": []}) == 1


@pytest.mark.parametrize("refill", [False, True])
def test_async_submission_reserves_only_the_valid_candidate(world, monkeypatch, refill):
    from src.orchestrator import common, two_bot_dispatch

    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", str(int(refill)))
    monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "1")
    state, (invalid, eligible) = slate()
    invalidate(state["_triage_queue"][0])
    calls = []

    class Client:
        def submit(self, bundle, **save):
            calls.append(save["event_id"])
            return {"generation_status": "queued", "job_id": "invented-pending-generation"}

    monkeypatch.setattr(common, "_try_two_bot_draft", two_bot_dispatch._try_two_bot_draft)
    budget = CandidateBudget("invented", 1)
    sink = funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(
        state, {"sources": []}, generation_client=Client(), candidate_budget=budget, funnel_sink=sink) == 0
    assert calls == [eligible] and world.calls == [] and not state["drafts"]
    assert budget.attempts == 1 and not budget.seen("event:" + invalid)
    assert sink["_slate_terminal"][eligible] == "generation_queued"
