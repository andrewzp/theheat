"""O5: discovery and content-quality protections survive the operation budget.

The cap sits downstream of scientific discovery: every source still observes,
scores, audits and queues its candidates under their own identities, and every
attempted candidate still faces the required safety, factual and critic checks
and source-currentness holds. Invented data and offline stage stubs only; an
invented verdict says nothing about real copy quality.
"""
from __future__ import annotations

import importlib

import pytest

from src.editorial.revisions import approval_is_current, review_is_current
from src.editorial.scoring import EditorialScore
from src.two_bot.types import FactCheckResult
from tests.operation_budget_helpers import fires, fresh_state, offline_world

alerts_mod = importlib.import_module("src.orchestrator.run_alerts")


@pytest.fixture
def world(monkeypatch):
    return offline_world(monkeypatch)


def run_alerts(*, warning_source=None, score=80):
    state, run = fresh_state(), {"id": "run-o5", "sources": []}
    extra = {}
    if warning_source is not None:
        extra = {"warning_source": warning_source, "warning_score": EditorialScore(
            "official_warning", score, score, score, score, score, 0, score, 60, ["Explicit invented nomination."])}
    alerts_mod.run_alerts(state, run, **extra)
    return state, run


def test_the_cap_does_not_truncate_discovery_or_rewrite_identities(world):
    from tests.warning_journey_helpers import source
    state, run = run_alerts(warning_source=source())
    firms_row = next(row for row in run["sources"] if row["source"] == "firms")
    assert firms_row["observed"] == firms_row["promoted"] == 3 and firms_row["triaged_in"] == 3
    logged = {row["event_id"] for row in state["candidates_log"]}
    assert {fire.event_id for fire in fires(3)} <= logged  # The sources' own event identities.
    assert len([event for event in logged if event.startswith("official_warning:")]) == 1 and len(logged) == 4
    # Every candidate the cap held is recorded under its own, unchanged identity.
    held = {row["event_id"] for row in state["suppressions"] if row.get("stage") == "triage_cap"}
    attempted = set(world.spies.writer_events())
    assert held | attempted == logged and not held & attempted and len(attempted) == 1


@pytest.mark.parametrize("stage", ["safety", "fact_check", "critic"])
def test_required_refusals_stay_effective_and_are_not_replaced(world, monkeypatch, stage):
    from src.two_bot import pipeline
    if stage == "safety":
        monkeypatch.setattr(pipeline, "run_safety_pipeline",
                            lambda text: (world.spies._dispatch("safety", "google", ""), (False, "Invented refusal."))[1])
    elif stage == "fact_check":
        def refuse(tweet, claims, bundle, *args, **kwargs):
            world.spies._dispatch("fact_check", "google", bundle.event_id)
            return FactCheckResult(False, ["Explicit invented factual refusal."], "offline")
        monkeypatch.setattr(pipeline.fact_check, "fact_check", refuse)
    else:
        world.spies.critic_reject_first = 99
    state, run = run_alerts()
    assert len(world.spies.writer_events()) == 1 and state["drafts"] == []
    assert sum(row.get("stage") == stage for row in state["suppressions"]) == 1
    order = [name for name, _ in world.spies.calls]
    assert order == ["writer", "safety", "fact_check", "critic"][: order.index(stage) + 1]  # Nothing after.


@pytest.mark.parametrize("refill", [False, True], ids=["refill-off", "refill-on"])
def test_a_source_change_before_the_paid_attempt_still_holds(world, monkeypatch, refill):
    from src.editorial.warning_runtime import SuppliedWarning, WarningSource
    from tests.warning_helpers import NOW, encode, nomination, packet
    if refill:
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    metadata, raw = packet()
    original = SuppliedWarning(encode(metadata), raw, nomination(encode(metadata), raw))
    revised = dict(metadata, revision="r2")
    corrected = SuppliedWarning(encode(revised), raw, nomination(encode(revised), raw))
    current = {"value": original}
    real_drain = alerts_mod._drain_and_write_triage_queue

    def drain_after_correction(*args, **kwargs):
        current["value"] = corrected  # The issuer revised its warning after admission, before any paid call.
        return real_drain(*args, **kwargs)
    monkeypatch.setattr(alerts_mod, "_drain_and_write_triage_queue", drain_after_correction)
    state, run = run_alerts(warning_source=WarningSource(lambda: current["value"], clock=lambda: NOW), score=99)
    warning_events = [event for event in world.spies.writer_events() if event.startswith("official_warning:")]
    assert warning_events == [] and not any(d["event_id"].startswith("official_warning:") for d in state["drafts"])
    assert any(row.get("stage") == "warning_source" for row in state["suppressions"])
    assert len(world.spies.writer_events()) <= 1  # Still within N=1.


def test_a_clean_eligible_candidate_reaches_the_writer_and_every_check_and_stays_unapproved(world):
    state, run = run_alerts()
    assert [stage for stage, _ in world.spies.calls] == ["writer", "safety", "fact_check", "critic"]
    (draft,) = state["drafts"]
    assert draft["status"] == "pending"
    assert "approval_binding" not in draft and not approval_is_current(draft)
    # Only the pipeline's own model-check binding exists; no human review is invented.
    assert review_is_current(draft) and draft["review_binding"]["kind"] == "model"
