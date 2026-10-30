"""W11.3 / W11.4 / W11.5 — candidate→request joins, ceiling semantics, persisted decision rows.

Invented candidates, models and Gist; DNS/connect are trapped.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.orchestrator.candidate_budget import CandidateBudget, writer_started
from src.two_bot import call_inventory as inv
from src.two_bot import trial_budget as limits
from src.two_bot.trial_budget import provider_call
from tests import live_content_harness as h

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
GOOD_COPY = ("Riyadh's forecast high of 39.2°C runs 9.2°C above its October normal, the largest departure "
             "among 14 sampled cities.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    h.trap_network(monkeypatch.setattr)


def _budget(limit="1"):
    return CandidateBudget.for_operation("alerts", {"THEHEAT_TRIAGE_ENABLED": "1", "THEHEAT_MAX_DRAFTS_PER_CYCLE": limit})


def _send_raises(**_kwargs):
    raise TimeoutError("invented lost response")


def test_timeout_after_dispatch_keeps_the_slot_even_if_the_pipeline_reports_unstarted():
    budget = _budget()
    assert budget.reserve("event:invented-a")
    with pytest.raises(TimeoutError):
        provider_call("writer", "anthropic", {"model": "invented"}, _send_raises)
    # Counterexample: a report of writer_started=False cannot refund a dispatched request.
    budget.settle("event:invented-a", writer_started=False)
    assert budget.summary()["attempts"] == 1 and budget.refused_before_writer == 0
    assert budget.joined_requests == 1 and budget.exhausted()
    assert not budget.reserve("event:invented-b")  # Cannot buy another city or a refill.


def test_malformed_returned_response_is_never_a_free_attempt():
    budget = _budget()
    budget.reserve("event:invented-a")
    provider_call("safety", "google", {"model": "invented"}, lambda **_: object())  # Unparseable to the caller.
    budget.settle("event:invented-a", writer_started=writer_started(False, {"writer_started": False}))
    assert budget.summary()["attempts"] == 1 and budget.joined_requests == 1


def test_only_a_proven_unstarted_reservation_is_returned():
    budget = _budget()
    budget.reserve("event:invented-a")
    budget.settle("event:invented-a", writer_started=False)  # No request was joined.
    assert budget.summary()["attempts"] == 0 and budget.refused_before_writer == 1
    assert budget.reserve("event:invented-b")


def test_an_escaped_attempt_cannot_absorb_the_next_candidates_requests():
    budget = _budget("3")
    budget.reserve("event:invented-a")  # Its draft raised before settle; the slot stays reserved.
    budget.reserve("event:invented-b")
    provider_call("writer", "anthropic", {"model": "invented"}, lambda **_: "ok")
    stale = budget._joins["event:invented-a"][0]
    assert stale.closed and stale.dispatched() == 0
    budget.settle("event:invented-b", writer_started=False)
    assert budget.summary()["attempts"] == 2 and budget.joined_requests == 1
    assert inv.current_attempt_join() is None


def test_trial_refuses_a_candidate_the_remaining_allowance_cannot_carry(tmp_path):
    rows: list[dict] = []
    trial = limits.TrialBudget(rows.append, tmp_path / "STOP")
    trial.calls = [{"candidate": "invented-a", "stage": s} for s in ("writer", "safety", "fact_check", "critic", "writer")]
    with pytest.raises(limits.TrialStopped, match="trial_allowance_cannot_cover_candidate"):
        trial.begin_candidate("invented-b")
    assert rows == [] and trial.candidates == set()
    trial = limits.TrialBudget(rows.append, tmp_path / "STOP")
    needed = sum(limits.stage_reserve_usd(s) for s in limits.MODELS)
    trial.estimated_reserved = limits.MAX_ESTIMATED_USD - needed + Decimal("0.000001")
    with pytest.raises(limits.TrialStopped, match="trial_allowance_cannot_cover_candidate"):
        trial.begin_candidate("invented-c")
    # The unchanged limits still carry two complete candidates.
    assert 2 * needed <= limits.MAX_ESTIMATED_USD and 2 * len(limits.MODELS) <= limits.MAX_CALLS


def test_ceiling_kinds_are_distinct_and_none_claims_a_hard_financial_cap():
    kinds = inv.CEILING_KINDS
    assert {k for k, v in kinds.items() if v["financial_cap"] and v["enforced"]} == set()
    assert kinds["invoice_ceiling"]["enforced"] is False and kinds["monthly_budget_watch"]["enforced"] is False
    assert kinds["daily_publication_cap"]["guarantee"] == "gist_state_nontransactional"
    assert kinds["local_spend_allowance"]["guarantee"] == "sqlite_transaction_local_authority"
    assert set(inv.PATH_CEILINGS) == {"ordinary", "manual", "batch", "maintenance"}
    for path, names in inv.PATH_CEILINGS.items():
        assert set(names) <= set(kinds) and "invoice_ceiling" in names, path


def test_local_spend_journal_refuses_when_remaining_allowance_cannot_cover(tmp_path):
    """Credit: the batch/manual SQLite journal already refuses before an over-limit reservation."""
    import inspect
    from src.commands import spend_journal
    text = inspect.getsource(spend_journal.apply)
    assert '"spending_allowance_exhausted"' in text and "totals[total] + amount <= limits[limit]" in text


def test_interrupted_request_is_persisted_with_the_run_and_survives_serialization():
    from src import state as state_module
    run: dict[str, Any] = {"id": "invented-run", "sources": [], "started_at": "2026-10-29T09:00:00Z"}
    budget = _budget()
    with inv.operation_scope("alerts") as join:
        budget.reserve("event:invented-a")
        ticket = inv.consume("writer", provider="anthropic", model="invented")  # Process lost before an outcome.
        assert ticket.outcome == "dispatched"
        budget.settle("event:invented-a", writer_started=True)
    inv.record_operation_cost(run, inv.operation_cost_row("alerts", join=join, candidate_budget=budget))
    state = deepcopy(h_default_state())
    state_module.finalize_run(state, run)
    import json
    reloaded = json.loads(json.dumps(state))
    row = reloaded["run_history"][0]["operation_costs"][0]
    assert row["requests"]["interrupted"] == 1 and row["requests"]["by_outcome"]["dispatched"] == 1
    assert row["candidate_attempts"] == {"limit": 1, "used": 1, "returned_unstarted": 0, "held": 0,
                                         "refusal": None, "joined_requests": 1}
    assert row["another_attempt_allowed"] == {"candidate_attempt": False}
    assert row["actual_cost_known"] is False and row["financial_cap"] is False
    assert "invented-a" not in json.dumps(row)  # Candidate identities are not exposed.


def h_default_state():
    from src.state import DEFAULT_STATE
    return DEFAULT_STATE


@pytest.fixture
def world(tmp_path, monkeypatch):
    from freezegun import freeze_time
    world = h.install_hot10_world(tmp_path, monkeypatch, copy=GOOD_COPY)
    with freeze_time(T0, tick=True):
        yield world


def test_hot10_candidate_joins_every_required_model_request(world):
    from src.orchestrator import hot10
    from src.state import DEFAULT_STATE
    state = deepcopy(DEFAULT_STATE)
    run: dict[str, Any] = {"id": "run-hot10-w11", "sources": []}
    hot10.run_leaderboard(state, run)
    assert world.script.stages() == ["writer", "safety", "fact_check", "critic"]
    row = run["operation_costs"][-1]
    assert row["operation"] == "leaderboard" and row["spend_class"] == "selection"
    assert {k: v["requests"] for k, v in row["requests"]["by_stage"].items()} == {
        "writer": 1, "safety": 1, "fact_check": 1, "critic": 1}
    assert row["requests"]["by_outcome"]["returned"] == 4 and row["requests"]["interrupted"] == 0
    assert row["candidate_attempts"]["used"] == 1 and row["candidate_attempts"]["joined_requests"] == 4
    assert row["another_attempt_allowed"] == {"candidate_attempt": False}
    assert [stage["stage"] for stage in row["may_call"]][:2] == ["source_http_get", "writer"]
    assert world.settled == [("leaderboard", "event:hot10_2026-10-29", True)]
