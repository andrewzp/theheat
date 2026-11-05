"""Invented activation through the real builder, evidence gate, drain and checks."""
from dataclasses import asdict, replace

import pytest

from src.orchestrator import triage_queue
from src.orchestrator.sources import copernicus_ems as runner
from src.two_bot import pipeline
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.disasters import build_global_flood_bundle
from src.two_bot.types import WriterResult
from tests.live_content_harness import trap_network
from tests.operation_budget_helpers import Spies, fresh_state
from tests.test_copernicus_ems import _activation


def test_builder_exposes_the_exact_activation_url_as_primary_evidence():
    event = _activation()
    bundle = build_global_flood_bundle(event)
    facts = {row["label"]: row["value"] for row in bundle.current_facts}
    assert facts.get("source_url") == event.copernicus_url
    assert facts["copernicus_url"] == event.copernicus_url
    assert bundle.raw_signal_dump == asdict(event)  # No invented source receipt or numbers.
    assert audit_story_bundle(bundle).prompt_ready


@pytest.mark.parametrize("url", ["", "not a URL", "javascript:alert(1)", "https://user:password@example.invalid"])
def test_unusable_activation_url_does_not_get_a_fabricated_source(url):
    bundle = build_global_flood_bundle(replace(_activation(), copernicus_url=url))
    audit = audit_story_bundle(bundle)
    assert not audit.prompt_ready
    assert "missing_provenance" in {issue.code for issue in audit.issues}


def test_actual_runner_reaches_every_check_and_stays_manual_pending(monkeypatch):
    trap_network(monkeypatch.setattr)
    spies = Spies().install(monkeypatch)
    for name, value in (("THEHEAT_TRIAGE_ENABLED", "1"), ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1"),
                        ("THEHEAT_REFILL_ENABLED", "0"), ("THEHEAT_HAZARD_EPISODES", "0"),
                        ("THEHEAT_MULTISIGNAL_CONTEXT", "0"), ("THEHEAT_NEWS_ENRICH_ENABLED", "0"),
                        ("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")):
        monkeypatch.setenv(name, value)
    event = _activation()
    monkeypatch.setattr(runner, "_fetch_strict", lambda fetch: [event])  # Only acquisition is invented.

    def write(bundle, memory, **kwargs):
        spies._dispatch("writer", "anthropic", bundle.event_id)
        return WriterResult("Flood mapping has been activated for Colombia, Copernicus says.", None,
                            "named_entity", None, None, "Explicit offline model fixture.")

    monkeypatch.setattr(pipeline.writer, "write_tweet", write)
    state = fresh_state()
    run = {"id": "invented-copernicus-admission", "sources": []}
    runner.run_copernicus_ems(state, run)
    assert len(state.get("_triage_queue", [])) == 1
    assert triage_queue._drain_and_write_triage_queue(state, run) == 1
    assert [stage for stage, _ in spies.calls] == ["writer", "safety", "fact_check", "critic"]
    (draft,) = state["drafts"]
    assert draft["event_id"] == event.event_id and draft["status"] == "pending"
    assert draft["approval_policy"]["mode"] == "manual_only"
    assert "approval_binding" not in draft
    assert state["flood_activation_tiers"][event.activation_id] == event.severity
    assert run["sources"][0]["drafted"] == 1
