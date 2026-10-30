"""O1: a failed or untrustworthy triage selection holds with zero writer calls.

Real drain, real source boundary, real pipeline; only model stages are explicit
offline stubs behind the real provider boundary (tests/operation_budget_helpers).
"""
from __future__ import annotations

import pytest

from src.orchestrator import triage_queue
from tests.operation_budget_helpers import Spies, enqueue_fires, fresh_state


@pytest.fixture
def triage(monkeypatch):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    for name in ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "THEHEAT_REFILL_ENABLED", "THEHEAT_FUNNEL_TELEMETRY"):
        monkeypatch.delenv(name, raising=False)
    return Spies().install(monkeypatch)


def _run(state, current_run=None):
    current_run = {"id": "run-o1", "sources": []} if current_run is None else current_run
    return triage_queue._drain_and_write_triage_queue(state, current_run), current_run


def _held(state, current_run, note):
    row = next(row for row in current_run["sources"] if row["source"] == "triage")
    assert row["status"] == "partial_failure" and row["note"].startswith(note), row
    assert row["writer_attempted"] == 0 and row["drafted"] == 0
    assert row["details"]["writer_attempts"] == 0 and row["details"]["held"] >= 1
    errors = [s for s in state["suppressions"] if s.get("stage") == "triage_error"]
    assert len(errors) == 1 and errors[0]["source"] == "triage"
    health = state["source_health"]["triage"]
    assert health.get("degraded", 0) + health.get("failed", 0) >= 1
    return row


def test_successful_ranked_selection_writes_one_candidate_through_every_check(triage, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    state = fresh_state()
    ids = enqueue_fires(state, 3)
    drafted, run = _run(state)
    (chosen,) = triage.writer_events()  # One distinct candidate: the highest-ranked survivor.
    assert drafted == 1 and chosen in ids
    assert [stage for stage, _ in triage.calls] == ["writer", "safety", "fact_check", "critic"]
    (draft,) = state["drafts"]
    assert draft["event_id"] == chosen and draft["status"] == "pending"
    assert "approval_binding" not in draft  # Pending review; nothing is approved.
    assert not [row for row in run["sources"] if row["source"] == "triage"]  # Success needs no hold row.


def test_selector_exception_holds_with_zero_writer_calls(triage, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("invented selector outage")
    monkeypatch.setattr("src.orchestrator.triage.select_survivors", boom)
    state = fresh_state()
    enqueue_fires(state, 3)
    drafted, run = _run(state)
    assert drafted == 0 and triage.calls == [] and state["drafts"] == []
    row = _held(state, run, "selector_unavailable")
    assert "invented selector outage" in row["error"] and row["details"]["held"] == 3
    assert "invented selector outage" in state["source_health"]["triage"]["last_error"]
    assert "_triage_queue" not in state


def _not_from_slate(state, queue, **kwargs):
    from copy import copy
    return [copy(queue[0])]  # An equal-looking object the drain never queued.


@pytest.mark.parametrize("selector,code", [
    (lambda state, queue, **kwargs: None, "selector_result_not_list"),
    (lambda state, queue, **kwargs: {"survivors": queue[:1]}, "selector_result_not_list"),
    (lambda state, queue, **kwargs: ["invented"], "selector_out_of_slate"),
    (_not_from_slate, "selector_out_of_slate"),
    (lambda state, queue, **kwargs: [queue[0], queue[0]], "selector_duplicate_candidate"),
    (lambda state, queue, **kwargs: list(queue), "selector_over_cap"),
], ids=["none", "mapping", "foreign", "copy", "duplicate", "over-cap"])
def test_untrustworthy_selection_holds_with_zero_writer_calls(triage, monkeypatch, selector, code):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2")
    monkeypatch.setattr("src.orchestrator.triage.select_survivors", selector)
    state = fresh_state()
    enqueue_fires(state, 3)
    drafted, run = _run(state)
    assert drafted == 0 and triage.calls == [] and state["drafts"] == []
    assert _held(state, run, "selector_invalid")["error"] == code


def test_refill_ranking_failure_also_holds(triage, monkeypatch):
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    monkeypatch.setattr("src.orchestrator.triage.select_survivors",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("invented refill ranking outage")))
    state = fresh_state()
    enqueue_fires(state, 3)
    drafted, run = _run(state)
    assert drafted == 0 and triage.calls == []
    _held(state, run, "selector_unavailable")


def test_explicit_legacy_mode_still_writes_every_candidate(triage, monkeypatch):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    state = fresh_state()
    ids = enqueue_fires(state, 3)
    drafted, run = _run(state)
    assert drafted == 3 and triage.writer_events() == ids  # Queue order, no selector.
    assert [d["status"] for d in state["drafts"]] == ["pending"] * 3
