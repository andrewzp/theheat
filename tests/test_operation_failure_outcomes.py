"""O4: each generation failure class is distinguishable in existing run/source-health fields.

Every case runs the actual ``src.main.main()`` alerts entrypoint with every real
source runner offline (tests/operation_budget_helpers.offline_world) and an
invented in-memory store. Codes and stage names only: no credential, provider
body or candidate text is recorded by the holds under test.
"""
from __future__ import annotations

import importlib
import json
import sys

import pytest

from src.two_bot import pipeline, retry
from tests.operation_budget_helpers import fresh_state, offline_world


@pytest.fixture
def world(monkeypatch):
    return offline_world(monkeypatch)


def cli(monkeypatch, mode="alerts"):
    saved = []
    monkeypatch.setattr("src.state.read_state", lambda: fresh_state())
    monkeypatch.setattr("src.state.write_state", lambda state: saved.append(state) or True)
    monkeypatch.setattr(sys, "argv", ["src.main", mode])
    importlib.import_module("src.main").main()  # Returns normally: the workflow step is green.
    state = saved[-1]
    return state, state["run_history"][0]


def row(report, source):
    found = [entry for entry in report["sources"] if entry["source"] == source]
    return found[-1] if found else None


def stages(state, *names):
    return [entry for entry in state["suppressions"] if entry.get("stage") in names]


def test_missing_provider_access_stops_the_operation_after_one_preflight(world, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "3")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "50")
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "")
    evaluated = []
    real = pipeline.current_provider_preflight
    monkeypatch.setattr(pipeline, "current_provider_preflight", lambda **k: evaluated.append(1) or real(**k))
    state, report = cli(monkeypatch)
    assert world.spies.calls == [] and state["drafts"] == []
    assert len(evaluated) == 1  # Formerly re-run for every selected candidate.
    hold = row(report, "generation")
    assert hold["status"] == "partial_failure" and hold["error"] == "provider_access_missing"
    assert {entry["stage"] for entry in hold["details"]["blocked_stages"]} == {"safety", "fact_check", "critic"}
    assert hold["details"]["held"] == 2 and report["status"] == "partial_failure"
    assert "invented-no-provider-access" not in json.dumps(hold)  # No credential material.
    assert len(stages(state, "provider_preflight")) == 1


def test_provider_billing_exhaustion_is_a_partial_run_not_a_healthy_one(world, monkeypatch):
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "3")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "50")

    def drained(bundle, memory, **kwargs):
        world.spies.calls.append(("writer", bundle.event_id))
        raise retry.BudgetExhaustedError("writer: provider billing exhausted: invented")
    monkeypatch.setattr(pipeline.writer, "write_tweet", drained)
    state, report = cli(monkeypatch)
    assert len(world.spies.writer_events()) == 1  # The existing breaker stops after one purchase.
    hold = row(report, "generation")
    assert hold["status"] == "partial_failure" and hold["error"] == "provider_billing_exhausted"
    assert hold["details"]["held"] == 2 and report["status"] == "partial_failure"
    assert len(stages(state, "billing_cycle_abort")) == 1 and len(stages(state, "budget_exhausted")) == 1


def test_selector_unavailable_is_its_own_signature(world, monkeypatch):
    monkeypatch.setattr("src.orchestrator.triage.select_survivors",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("invented ranking fault")))
    state, report = cli(monkeypatch)
    assert row(report, "triage")["error"] == "invented ranking fault" and row(report, "generation") is None
    assert report["status"] == "partial_failure" and world.spies.calls == []


def test_writer_and_check_refusals_are_editorial_outcomes_not_holds(world, monkeypatch):
    world.spies.critic_reject_first = 99
    state, report = cli(monkeypatch)
    assert len(stages(state, "critic")) == 1 and state["drafts"] == []
    assert row(report, "triage") is None and row(report, "generation") is None


def test_candidate_budget_reached_is_a_normal_cap_not_a_failure(world, monkeypatch):
    state, report = cli(monkeypatch)  # N=1, three fires: one attempt, the rest capped.
    assert len(world.spies.writer_events()) == 1 and len(state["drafts"]) == 1
    assert row(report, "triage") is None and row(report, "generation") is None
    assert stages(state, "triage_cap")


def test_zero_eligible_candidates_and_unavailable_sources_are_distinguishable(world, monkeypatch):
    from src.data import firms
    monkeypatch.setattr(firms, "fetch_fires", lambda *a, **k: [])
    state, report = cli(monkeypatch)
    assert world.spies.calls == [] and state["drafts"] == []
    firms_row = row(report, "firms")
    assert firms_row["status"] == "success" and firms_row["observed"] == 0  # Zero eligible: nothing to rank.
    assert not stages(state, "triage_error", "triage_cap", "writer", "critic", "provider_preflight")
    assert row(report, "triage") is None and row(report, "generation") is None
    unavailable = [entry["source"] for entry in report["sources"] if entry["status"] == "failed"]
    assert "nws_alerts" in unavailable and report["status"] == "partial_failure"  # Sources, not generation.


def test_unknown_billing_stays_unknown(world, monkeypatch):
    state, report = cli(monkeypatch)
    budget = state["source_health"]["budget"]["runs"][-1]
    assert budget["status"] != "success" and budget.get("error_class") == "accounting_coverage"
