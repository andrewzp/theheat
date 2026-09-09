"""Cross-domain failures must be retained before either paid boundary."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.two_bot import fact_check, writer
from src.two_bot.evidence_contract import audit_story_bundle, evidence_rejection_details
from src.two_bot.types import MemorySlice
from tests.two_bot.conftest import _bundle


@pytest.mark.parametrize("evidence", [
    ["malformed"],
    {"domain": "temperature", "baseline": ["malformed"]},
    {"domain": "temperature", "baseline": {"variable": []}},
    {"domain": "temperature", "baseline": {"variables": ["malformed"]}},
    {"domain": "temperature", "baseline": {"variables": {"temperature_2m_max": False}}},
    {"domain": "temperature", "baseline": {"members": False}},
    {"domain": "temperature", "baseline": {"members": [{"evidence": ["malformed"]}]}},
    {"domain": "temperature", "baseline": {"variables": {"temperature_2m_max": {"verified_source_cutoff": ["invalid"]}}}},
])
def test_malformed_temperature_evidence_retained_without_model_calls(evidence, monkeypatch):
    packet = {"source_product": "synthetic-contract-fixture", "evidence": evidence}
    bundle = replace(_bundle(), raw_signal_dump=packet)
    audit = audit_story_bundle(bundle)
    assert not audit.prompt_ready
    retained = evidence_rejection_details(bundle, audit)
    assert retained["candidate_bundle"]["raw_signal_dump"]["evidence"] == evidence
    assert any(issue["code"] in {"invalid_evidence_structure", "invalid_evidence_date"} for issue in retained["issues"])
    writer_call, checker_call = Mock(), Mock()
    monkeypatch.setattr(writer, "_call_writer_provider", writer_call)
    monkeypatch.setattr(fact_check, "_call_gemini", checker_call)
    assert writer.write_tweet(bundle, MemorySlice()).tweet is None
    assert not fact_check.fact_check("Paris: 40 C.", [], bundle, {}).passed
    writer_call.assert_not_called()
    checker_call.assert_not_called()


def test_invalid_signal_kind_survives_projection_for_actionable_audit(monkeypatch):
    bundle = replace(_bundle(), signal_kind=[])
    call = Mock()
    monkeypatch.setattr(writer, "_call_writer_provider", call)
    audit = audit_story_bundle(bundle)
    assert not audit.prompt_ready
    assert "missing_signal_kind" in {issue.code for issue in audit.issues}
    assert writer.write_tweet(bundle, MemorySlice()).tweet is None
    call.assert_not_called()
