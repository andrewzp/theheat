"""Invented negation-scope controls; no source or model-truth certification."""

from copy import deepcopy
from dataclasses import asdict, replace
import json
from unittest.mock import Mock

import pytest

from src.editorial.policy import current_editorial_policy
from src.two_bot import check_requests, fact_check
from src.two_bot.scientific_claims import scientific_claim_failures
from src.two_bot.types import ExtractedClaim, WriterResult
from tests.test_check_executor import envelope
from tests.two_bot.conftest import _bundle
from tests.two_bot.test_candidate_derivation import packet

MEASUREMENT = "A satellite measured 312 MW near Luma today."
ABSENCE = "No independent incident classification is available to establish vegetation-fire identity"
TEXT = MEASUREMENT + " " + ABSENCE + "."


def bundle():
    return _bundle(region="Luma", frp=312)


def incident_failures(text, value=None):
    return [f for f in scientific_claim_failures(text, value or bundle()) if f.startswith("unverified_incident:")]


@pytest.mark.parametrize("modifier", ["independent", "independently sourced", "independently verified"])
@pytest.mark.parametrize("scope", ["identity", "identity and extent", "identity or cause",
                                  "identity, extent", "identity, extent and cause",
                                  "identity, extent, or cause"])
def test_complete_negative_clause_is_not_affirmative_fire_identity(modifier, scope):
    text = ABSENCE.replace("independent", modifier).replace("identity", scope)
    assert not incident_failures(text)


@pytest.mark.parametrize("boundary", ["", ". ", "; ", ".\t"])
@pytest.mark.parametrize("ending", ["", ".", "; another thermal measurement remains uncertain."])
def test_standalone_clause_boundaries_remain_narrow(boundary, ending):
    text = ("Thermal data" + boundary if boundary else "") + ABSENCE + ending
    assert not incident_failures(text)


@pytest.mark.parametrize("text", [
    ABSENCE.replace("establish", "confirm"),
    ABSENCE.replace("vegetation-fire", "vegetation fire"),
    ABSENCE.replace(" ", "\t"),
    ABSENCE.upper(),
    "No independently verified incident classification is available.",
])
def test_bounded_horizontal_space_and_case_variants(text):
    assert not incident_failures(text)


@pytest.mark.parametrize("text", [
    ABSENCE.replace("No independent", "An independent"),
    ABSENCE.replace("is available", "is unavailable"),
    ABSENCE.replace("No independent", "Not only independent"),
    ABSENCE.replace("incident classification", "incident estimate"),
    ABSENCE.replace("No independent", "No uncertain"),
    ABSENCE.replace("to establish", "to dispute"),
    ABSENCE.replace("identity", "intensity"),
    ABSENCE.replace("identity", "identity in Luma"),
    ABSENCE + " and a wildfire is burning",
    ABSENCE + " because forests are burning",
    "The report says " + ABSENCE,
    "If " + ABSENCE,
    "Warning: " + ABSENCE,
    "Thermal data, " + ABSENCE,
    "Thermal data.\n" + ABSENCE,
    ABSENCE.replace("incident ", "incident\n"),
    ABSENCE + "\n",
    ABSENCE + "\r\n",
    ABSENCE + ".\nAnother sentence.",
    ABSENCE.replace("vegetation-fire", "vegetation–fire"),
    ABSENCE + "?",
    "(" + ABSENCE + ")",
    "No rain fell; a vegetation fire is confirmed.",
    "No independent incident classification is available. A wildfire burns.",
    "Vegetation fires are confirmed. No independent incident classification is available.",
    "A satellite-confirmed fire at 100% confidence.",
    "Seasonal fire weather explains the thermal anomaly.",
])
def test_near_matches_and_affirmative_claims_still_need_a_warrant(text):
    assert incident_failures(text)


@pytest.mark.parametrize("quote", ['"', "'", "‘", "’", "“", "”", "«", "»", "‹", "›"])
def test_quoted_or_ambiguous_text_gets_no_exception(quote):
    assert incident_failures(quote + ABSENCE + quote)
    assert incident_failures("A station" + quote + "s reading. " + ABSENCE)


@pytest.mark.parametrize("positive", ["A wildfire burns", "A vegetation fire is confirmed", "Forests are burning in a fire"])
@pytest.mark.parametrize("boundary", [". ", "; ", ", but "])
def test_negative_clause_never_masks_another_positive_claim(positive, boundary):
    assert incident_failures(positive + boundary + ABSENCE)
    assert incident_failures(ABSENCE + boundary + positive)


def test_atmospheric_cause_gate_still_reads_original_text():
    text = ABSENCE + ". A convective lid caused the thermal anomaly."
    failures = scientific_claim_failures(text, bundle())
    assert not any(f.startswith("unverified_incident:") for f in failures)
    assert any(f.startswith("unwarranted_fire_cause:") for f in failures)


def test_existing_frp_metric_exception_remains_separate():
    assert scientific_claim_failures("Fire radiative power: 312 MW. " + ABSENCE, bundle()) == []
    assert incident_failures("Fire radiative power: 312 MW. A wildfire burns. " + ABSENCE)


@pytest.mark.parametrize("field,value", [("target_event_id", "different"), ("valid_date", "2020-01-01"),
                                        ("source_url", "javascript:bad")])
def test_invalid_warrant_is_not_rescued_by_negative_clause(field, value):
    source = bundle()
    incident = dict(source_product="invented-registry", revision_id="r1", source_url="https://example.invalid/incident",
                    valid_date=source.when, target_event_id=source.event_id,
                    evidence_type="verified_incident", classification="vegetation_fire")
    source.raw_signal_dump["evidence"] = {"incident": incident}
    text = "A vegetation fire is confirmed. " + ABSENCE
    assert not incident_failures(text, source)
    incident[field] = value
    assert incident_failures(text, source)


def raw_result(*, claims=None, failures=()):
    inventory = [ExtractedClaim("312 MW", "number"), ExtractedClaim("Luma", "named_entity")]
    return json.dumps(dict(passed=not failures, failures=list(failures),
                          extracted_claims=[asdict(c) for c in (inventory if claims is None else claims)]))


@pytest.mark.parametrize("failures", [(), ("Invented checker: assertion lacks source support.",)])
def test_sync_and_retained_check_paths_agree_and_preserve_exact_inputs(monkeypatch, failures):
    source = bundle()
    original = deepcopy(source.to_dict())
    raw = raw_result(failures=failures)
    provider = Mock(return_value=raw)
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    assert fact_check.local_rejection(TEXT, [], source, {}) is None  # Not a completed check.
    sync = fact_check.fact_check(TEXT, [], source, {})
    provider.assert_called_once_with(TEXT, source, retry_suffix="")
    saved = packet(dict(candidate=asdict(WriterResult(
        tweet=TEXT, kill_reason=None, angle_chosen="synthetic", era_anchor_used=None,
        peer_comparison_used=None, reasoning="Invented parser control.")),
        candidate_id="e" * 64, bundle=source.to_dict(), policy=current_editorial_policy()))
    before = deepcopy(saved)
    outcome = check_requests.interpret_observation(saved, "fact_check",
        {"complete": True, "http_status": 200}, envelope(raw))
    assert outcome["execution_status"] == "completed"
    assert outcome["verdict"] == ("reject" if failures else "pass")
    assert outcome["result"] == sync.to_dict()
    assert sync.passed == (not failures) and sync.failures == list(failures)
    assert saved == before and source.to_dict() == original and provider.call_count == 1


@pytest.mark.parametrize("claims", [[], [ExtractedClaim("312 MW", "number")], [ExtractedClaim("Luma", "named_entity")]])
def test_missing_inventory_remains_blocking(monkeypatch, claims):
    provider = Mock(return_value=raw_result(claims=claims))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    result = fact_check.fact_check(TEXT, [], bundle(), {})
    assert not result.passed and any("claim" in f for f in result.failures)
    assert provider.call_count == 1


def test_unavailable_or_invalid_checker_never_becomes_a_pass(monkeypatch):
    provider = Mock(return_value="")
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    result = fact_check.fact_check(TEXT, [], bundle(), {})
    assert not result.passed and result.failures
    assert provider.call_count == fact_check.JSON_PARSE_RETRY_BUDGET + 1


@pytest.mark.parametrize("text", ["A wildfire burns. " + ABSENCE, ABSENCE + ", but a vegetation fire is confirmed."])
def test_affirmative_claim_is_still_rejected_before_provider(monkeypatch, text):
    provider = Mock(side_effect=AssertionError("Provider must not run"))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    result = fact_check.fact_check(text, [], bundle(), {})
    assert not result.passed and any(f.startswith("unverified_incident:") for f in result.failures)
    provider.assert_not_called()
