"""Invented source→drain→checks fixtures; no provider/platform/network calls."""
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.editorial.approval import AUTOSHIP_ALLOWLIST
from src.orchestrator import funnel, triage_queue
from src.orchestrator.candidate_budget import CandidateBudget
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.types import WriterResult
from tests.operation_budget_helpers import Spies, enqueue_fires, fresh_state


@pytest.fixture
def world(monkeypatch):
    spy = Spies().install(monkeypatch)
    for key, value in {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main",
            "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-release-20261105",
            "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1", "THEHEAT_TRIAGE_ENABLED": "1",
            "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1"}.items():
        monkeypatch.setenv(key, value)
    for flag in ("THEHEAT_REFILL_ENABLED", "THEHEAT_PORTFOLIO_SELECTION", "THEHEAT_NEWS_ENRICH_ENABLED",
                 "THEHEAT_MULTISIGNAL_CONTEXT", "THEHEAT_PM25_FORECAST_AUTO_TEXT", "THEHEAT_DUST_FORECAST_AUTO_TEXT",
                 "THEHEAT_NHC_ADVISORY_AUTO_TEXT", "THEHEAT_NWS_WARNING_AUTO_TEXT", "THEHEAT_OFFICIAL_WARNING_AUTO_TEXT"):
        monkeypatch.delenv(flag, raising=False)
    return spy


def manual_slate():
    state = fresh_state()
    event = enqueue_fires(state, 1)[0]
    row = state["_triage_queue"][0]
    state["_triage_queue"][0] = replace(row, score=replace(row.score, total=99))
    return state, event


def run():
    return {"id": "invented-auto-selection", "mode": "alerts", "sources": [
        {"source": source, "triaged_in": 0, "triaged_out": 0, "writer_attempted": 0, "drafted": 0}
        for source in ("firms", "co2")]}


def enqueue_automatic(state, world, monkeypatch):
    from src.data.co2 import CO2Milestone
    from src.orchestrator.common import _review_context
    from src.two_bot.intern import build_co2_milestone_bundle
    day = datetime.now(UTC).date().isoformat()
    bundle = build_co2_milestone_bundle(CO2Milestone(450, 450.4, day, "invented-co2-450"))
    # Explicit synthetic provenance; this does not qualify the production CO2 builder.
    bundle.current_facts.append({"label": "source_url", "value": "https://example.test/invented-co2"})
    assert audit_story_bundle(bundle).prompt_ready
    score = replace(state["_triage_queue"][0].score, category="co2_milestone", total=80)
    assert triage_queue._enqueue_story_candidate(state, bundle=bundle, score=score, source="co2",
        legacy_type="co2_milestone", event_id=bundle.event_id,
        review_context=_review_context(source="Invented CO2 source", source_key="co2", headline="Invented threshold", facts=[]))
    original = world.writer
    def write(value, memory, **kwargs):
        if value.signal_kind != "co2_milestone":
            return original(value, memory, **kwargs)
        world._dispatch("writer", "anthropic", value.event_id)
        return WriterResult("CO2 at Mauna Loa crossed 450 ppm, reaching 450.4 ppm in this invented reading.",
                            None, "number", None, None, "Explicit offline response.")
    monkeypatch.setattr("src.two_bot.pipeline.writer.write_tweet", write)
    return bundle.event_id


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_manual_type_cannot_take_automatic_cycles_only_writer_slot(world, monkeypatch, mode):
    if mode == "legacy":
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    if mode == "refill":
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    state, manual = manual_slate()
    eligible = enqueue_automatic(state, world, monkeypatch)
    sink, operation, record = funnel.new_funnel(), CandidateBudget("invented", 1), run()
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=operation, funnel_sink=sink) == 1
    assert world.writer_events() == [eligible]
    assert [stage for stage, _ in world.calls] == ["writer", "safety", "fact_check", "critic"]
    assert operation.attempts == 1 and not operation.seen("event:" + manual)
    assert sink["_slate_terminal"][manual] == "automatic_policy" and sink["_slate_terminal"][eligible] == "drafted"
    assert state["drafts"][0]["event_id"] == eligible and state["drafts"][0]["status"] == "pending"
    assert state["drafts"][0]["approval_mode"] == "auto"  # Existing checks/save_draft, not preflight, armed it.
    source = next(row for row in record["sources"] if row["source"] == "firms")
    assert source["triaged_in"] == source["triaged_out"] == 1
    assert source["writer_attempted"] == source["drafted"] == 0


def test_all_manual_spends_nothing_and_reports_policy_supply_hold(world):
    state, event = manual_slate()
    operation, record, sink = CandidateBudget("invented", 1), run(), funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=operation, funnel_sink=sink) == 0
    assert world.calls == [] and operation.attempts == operation.held == 0
    assert not operation.seen("event:" + event) and state["drafts"] == []
    assert sink["_slate_terminal"][event] == "automatic_policy"
    row = next(row for row in record["sources"] if row["source"] == "automatic_selection")
    assert row["status"] == "degraded" and row["observed"] == row["promoted"] == 0
    assert row["details"]["policy_only"] is True and row["details"]["held_manual_types"] == 1
    assert row["details"]["candidate_count"] == 1 and row["details"]["potential_type_count"] == 0


@pytest.mark.parametrize("change", ["dispatch", "pull_request", "branch", "no_run", "no_mode", "pause", "bad_epoch", "retired", "autoship_off"])
def test_non_automatic_contexts_keep_manual_generation(world, monkeypatch, change):
    state, event = manual_slate()
    record = run()
    if change in {"dispatch", "pull_request"}:
        monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch" if change == "dispatch" else change)
    elif change == "branch":
        monkeypatch.setenv("GITHUB_REF", "refs/heads/invented-branch")
    elif change == "no_run":
        record = None
    elif change == "no_mode":
        record.pop("mode")
    elif change == "pause":
        monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    elif change == "bad_epoch":
        monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "bad")
    elif change == "retired":
        state["publication_control"] = {"retired_epochs": ["invented-release-20261105"]}
    else:
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=CandidateBudget("invented", 1)) == 1
    assert world.writer_events() == [event] and state["drafts"][0]["approval_mode"] == "manual"


@pytest.mark.parametrize("kind", sorted(AUTOSHIP_ALLOWLIST) + ["oscillation_transition"])
def test_existing_arming_branches_are_potential_routes(world, kind):
    assert triage_queue._automatic_type_may_arm(kind, 80) is True


@pytest.mark.parametrize("kind", ["anomaly_hot", "anomaly_cold", "record", "country_high", "ozone_hole_peak", "unknown",
                                 "fire", "dust_event", "air_quality_hazard", "nhc_advisory", "severe_weather", "official_warning"])
def test_suggested_auto_and_flag_off_families_are_not_automatic_routes(world, kind):
    assert triage_queue._automatic_type_may_arm(kind, 99) is False


@pytest.mark.parametrize("kind,flag", [("dust_event", "THEHEAT_DUST_FORECAST_AUTO_TEXT"),
    ("air_quality_hazard", "THEHEAT_PM25_FORECAST_AUTO_TEXT"), ("nhc_advisory", "THEHEAT_NHC_ADVISORY_AUTO_TEXT"),
    ("severe_weather", "THEHEAT_NWS_WARNING_AUTO_TEXT"), ("official_warning", "THEHEAT_OFFICIAL_WARNING_AUTO_TEXT")])
def test_existing_family_opt_in_is_potential_only(world, monkeypatch, kind, flag):
    monkeypatch.setenv(flag, "1")
    assert triage_queue._automatic_type_may_arm(kind, 80) is True and world.calls == []


def test_later_critic_rejection_never_buys_a_removed_manual_story(world, monkeypatch):
    state, _ = manual_slate()
    event = enqueue_automatic(state, world, monkeypatch)
    world.critic_kill.add(event)
    operation = CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, run(), candidate_budget=operation) == 0
    assert world.writer_events() == [event] and operation.attempts == 1 and state["drafts"] == []


def test_async_manual_hold_never_calls_generation_client(world):
    state, _ = manual_slate()
    class NoCalls:
        def __getattr__(self, key):
            pytest.fail("generation client reached for manual-only type: " + key)
    operation = CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, run(), generation_client=NoCalls(), candidate_budget=operation) == 0
    assert world.calls == [] and operation.attempts == 0


def test_classifier_failure_holds_without_provider_or_private_error(world, monkeypatch):
    state, _ = manual_slate()
    def fail(*args, **kwargs):
        raise RuntimeError("invented private context")
    monkeypatch.setattr(triage_queue, "_automatic_type_may_arm", fail)
    operation, record = CandidateBudget("invented", 1), run()
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=operation) == 0
    assert world.calls == [] and operation.attempts == 0
    assert any(row.get("error") == "automatic_policy_unavailable" for row in record["sources"])
    assert "invented private context" not in str(state["suppressions"])
