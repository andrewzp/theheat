"""Offline adversarial boundary tests, distinct from semantic truth certification."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.two_bot import fact_check as checker
from src.two_bot import writer
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.json_utils import loads_model_json
from src.two_bot.strict_contract import bundle_schema_issues
from src.two_bot.types import ExtractedClaim, MemorySlice
from tests.two_bot.conftest import _bundle, _state_with_memory


def response(tweet="Paris: 40 C.", claims=None):
    if claims is None:
        claims = [{"text": "Paris", "kind": "named_entity"}, {"text": "40 C", "kind": "number"}]
    return json.dumps({"passed": True, "failures": [], "extracted_claims": claims})


def writer_payload():
    return {"tweet": "Paris: 40 C.", "kill_reason": None, "angle_chosen": "plain_number",
            "era_anchor_used": None, "peer_comparison_used": None, "reasoning": "Supported source comparison."}


@pytest.mark.parametrize("when", ["not-a-date", "2026-02-30", "2026-09-09T12:30:00", "2026-09-09T25:00:00Z", "2026-09", None])
def test_invalid_valid_time_never_reaches_model(when, monkeypatch):
    call = MagicMock(return_value=response())
    monkeypatch.setattr(checker, "_call_gemini", call)
    result = checker.fact_check("Paris: 40 C.", [], replace(_bundle(), when=when), {})
    assert not result.passed
    assert any("invalid_valid_time" in reason for reason in result.failures)
    call.assert_not_called()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), {"nested": float("nan")}])
def test_nonfinite_evidence_cannot_be_approved_anywhere(value, monkeypatch):
    bundle = _bundle()
    bundle.historical_context = {"comparison": value}
    call = MagicMock(return_value=response())
    monkeypatch.setattr(checker, "_call_gemini", call)
    assert not audit_story_bundle(bundle).prompt_ready
    result = checker.fact_check("Paris: 40 C.", [], bundle, {})
    assert not result.passed
    assert any("invalid_evidence_json" in failure for failure in result.failures)
    call.assert_not_called()


@pytest.mark.parametrize("raw", [{"event_id": "FIRMS-123", "resource_description": "NOAA"}, {"source_name": " "}, {"source_url": "javascript:alert(1)"}, {"source_url": "https://user:password@example.test"}])
def test_generated_ids_substrings_and_invalid_urls_are_not_provenance(raw):
    bundle = replace(_bundle(), raw_signal_dump=raw)
    assert "missing_provenance" in {issue[0] for issue in bundle_schema_issues(bundle)}


@pytest.mark.parametrize("raw", [
    {"related_news": [{"url": "https://example.test/article"}]},
    {"related_event": {"source_product": "another-measurement"}},
    {"evidence": {"related_news": [{"source_name": "a newspaper"}]}},
])
def test_unrelated_nested_source_cannot_stand_in_for_primary_measurement(raw):
    assert "missing_provenance" in {issue[0] for issue in bundle_schema_issues(replace(_bundle(), raw_signal_dump=raw))}


@pytest.mark.parametrize("field", ["evidence", "provenance", "source"])
def test_explicit_primary_source_metadata_is_a_minimum_identity(field):
    assert bundle_schema_issues(replace(_bundle(), raw_signal_dump={field: {"source_product": "synthetic-measurement"}})) == []


@pytest.mark.parametrize("value", [True, None, " ", [], {}])
def test_wrong_headline_types_fail_the_direct_factual_boundary(value):
    bundle = replace(_bundle(), headline_metric={"label": "FRP", "value": value, "unit": "MW"})
    assert "invalid_headline_value" in {issue[0] for issue in bundle_schema_issues(bundle)}


def test_nested_dates_checked_and_explicitly_unknown_issue_time_preserved():
    bundle = _bundle()
    bundle.raw_signal_dump["evidence"] = {"source_product": "synthetic", "valid_date": date(2026, 4, 30), "issued_at": None, "model_run": None}
    assert bundle_schema_issues(bundle) == []
    bundle.current_facts.append({"label": "valid_date", "value": "2026-02-30"})
    assert "invalid_evidence_date" in {issue[0] for issue in bundle_schema_issues(bundle)}


@pytest.mark.parametrize("field,value", [("tweet", " "), ("tweet", []), ("tweet", 7), ("angle_chosen", "Bad Label"), ("reasoning", False), ("cited_impact", "true"), ("era_anchor_used", "a phrase not in the tweet"), ("peer_comparison_used", [])])
def test_wrong_model_output_types_cannot_become_a_writer_result(field, value):
    payload = writer_payload()
    payload[field] = value
    with pytest.raises(ValueError):
        writer._parse_writer_json(json.dumps(payload))


def test_writer_requires_all_fields_and_exclusive_nonblank_outcome():
    payload = writer_payload()
    del payload["angle_chosen"]
    with pytest.raises(ValueError):
        writer._parse_writer_json(json.dumps(payload))
    payload = writer_payload()
    payload.update(tweet=None, kill_reason="Insufficient evidence", angle_chosen="")
    assert writer._parse_writer_json(json.dumps(payload)).kill_reason == "Insufficient evidence"
    payload["kill_reason"] = " "
    with pytest.raises(ValueError):
        writer._parse_writer_json(json.dumps(payload))


@pytest.mark.parametrize("raw", ['{"passed":true,"passed":false}', '{"number":NaN}', '{"number":Infinity}', '{"number":1e999}'])
def test_ambiguous_and_nonfinite_json_cannot_be_salvaged_from_a_later_object(raw):
    with pytest.raises(ValueError):
        loads_model_json(raw + '\n{"passed":true,"failures":[],"extracted_claims":[]}', expected="object")


@pytest.mark.parametrize("claims", [[], [{"text": "Paris", "kind": "named_entity"}], [{"text": "40 C", "kind": "number"}], [{"text": "Lyon", "kind": "named_entity"}, {"text": "40 C", "kind": "number"}], [{"text": "Paris", "kind": "factual_assertion"}, {"text": "40 C", "kind": "number"}]])
def test_incomplete_wrong_or_unknown_claim_inventory_cannot_approve(claims, monkeypatch):
    raw = response(claims=claims)
    monkeypatch.setattr(checker, "_call_gemini", lambda *a, **k: raw)
    result = checker.fact_check("Paris: 40 C.", [], _bundle(), {})
    assert not result.passed
    assert result.raw_response == raw


def test_even_lowercase_claim_requires_nonempty_inventory(monkeypatch):
    monkeypatch.setattr(checker, "_call_gemini", lambda *a, **k: response(claims=[]))
    assert not checker.fact_check("the city burned", [], _bundle(), {}).passed


def test_complete_literal_inventory_can_pass_and_wrong_requested_text_cannot(monkeypatch):
    monkeypatch.setattr(checker, "_call_gemini", lambda *a, **k: response())
    assert checker.fact_check("Paris: 40 C.", [], _bundle(), {}).passed
    assert not checker.fact_check("Lyon: 40 C.", [], _bundle(), {}).passed


@pytest.mark.parametrize("tweet", [None, [], "", " ", "x" * 281])
def test_invalid_tweet_never_calls_checker(tweet, monkeypatch):
    call = MagicMock(return_value=response())
    monkeypatch.setattr(checker, "_call_gemini", call)
    assert not checker.fact_check(tweet, [], _bundle(), {}).passed
    call.assert_not_called()


@pytest.mark.parametrize("change", [{"when": "2026-02-30"}, {"raw_signal_dump": {}}, {"headline_metric": {"label": "FRP", "value": float("nan")}}])
def test_direct_writer_entry_point_blocks_invalid_evidence_before_spending(change, monkeypatch):
    call = MagicMock(return_value=json.dumps(writer_payload()))
    monkeypatch.setattr(writer, "_call_writer_provider", call)
    result = writer.write_tweet(replace(_bundle(), **change), MemorySlice())
    assert result.tweet is None and "Evidence requires repair" in result.kill_reason
    call.assert_not_called()


@pytest.mark.parametrize("claims", [None, []])
def test_prior_extractor_cannot_excuse_missing_or_empty_checker_inventory(claims, monkeypatch):
    payload = {"passed": True, "failures": []}
    if claims is not None:
        payload["extracted_claims"] = claims
    monkeypatch.setattr(checker, "_call_gemini", lambda *a, **k: json.dumps(payload))
    result = checker.fact_check("Paris: 40 C.", [ExtractedClaim("Paris: 40 C.", "comparison")], _bundle(), {})
    assert not result.passed


def test_unsupported_preextracted_claim_is_retained_as_failed_diagnostic(monkeypatch):
    call = MagicMock()
    monkeypatch.setattr(checker, "_call_gemini", call)
    result = checker.fact_check("Paris: 40 C.", [ExtractedClaim("Paris", "factual_assertion")], _bundle(), {})
    assert not result.passed
    assert "factual_assertion" in result.raw_response
    call.assert_not_called()


@pytest.mark.parametrize("passed,failures", [(True, ["known error"]), (False, []), (True, [None])])
def test_contradictory_check_result_is_rejected(passed, failures):
    with pytest.raises(ValueError):
        checker._parse_fact_check_json(json.dumps({"passed": passed, "failures": failures, "extracted_claims": []}))


def test_rejected_candidate_retains_exact_evidence_and_actionable_repair_reason():
    from src.orchestrator.triage_queue import _enqueue_story_candidate
    from tests.test_triage import _score

    bundle = _bundle()
    bundle.raw_signal_dump.pop("source_product")
    original = deepcopy(bundle.to_dict())
    state = _state_with_memory()
    assert not _enqueue_story_candidate(state, bundle=bundle, score=_score(), source="firms", legacy_type="fire", event_id=bundle.event_id, review_context={})
    row = state["suppressions"][-1]
    assert row["event_id"] == bundle.event_id and row["stage"] == "evidence_contract"
    detail = row["evidence_readiness"]
    assert detail["candidate_bundle"] == original
    assert detail["issues"][0]["code"] == "missing_provenance"
    assert "event ID" in detail["issues"][0]["message"]
    assert state.get("_triage_queue", []) == []
    json.dumps(state, allow_nan=False)


def test_nonfinite_rejected_candidate_is_persistable_without_repairing_it():
    from src.orchestrator.triage_queue import _enqueue_story_candidate
    from tests.test_triage import _score

    bundle = _bundle()
    bundle.raw_signal_dump["temperature"] = float("nan")
    state = _state_with_memory()
    assert not _enqueue_story_candidate(state, bundle=bundle, score=_score(), source="firms", legacy_type="fire", event_id=bundle.event_id, review_context={})
    detail = state["suppressions"][-1]["evidence_readiness"]
    assert detail["candidate_bundle"]["raw_signal_dump"]["temperature"] == {"__nonfinite_number__": "nan"}
    assert detail["status"] == "needs_evidence_repair"
    json.dumps(state, allow_nan=False)


@pytest.mark.parametrize("module,fn,schema", [(writer, "_call_google", writer.WRITER_OUTPUT_SCHEMA), (checker, "_call_gemini", checker.FACT_CHECK_OUTPUT_SCHEMA)])
def test_gemini_requests_constrained_output_in_the_same_call(module, fn, schema, monkeypatch):
    from google import genai
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(text=response(), usage_metadata=None)
    monkeypatch.setattr(genai, "Client", lambda **kwargs: client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setattr(module, "call_with_retries", lambda _, call: call())
    if module is writer:
        getattr(module, fn)("synthetic prompt")
    else:
        getattr(module, fn)("Paris: 40 C.", _bundle())
    assert client.models.generate_content.call_count == 1
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == schema


HISTORICAL_CASES = json.loads((Path(__file__).parents[1] / "fixtures/historical_scientific_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case_id,signal,tweet,evidence", [
    ("alert_threshold_is_not_a_rain_record", "precipitation_extreme", "Paris broke its 150 mm rainfall record.", {"alert_threshold_mm": 150, "previous_record_mm": 150}),
    ("forecast_is_not_an_observed_record", "temperature", "Paris set a new record at 40 C.", {"evidence_type": "forecast"}),
    ("humidity_requires_moisture_evidence", "temperature", "Paris has a wet-bulb burden at 40 C.", {"evidence_type": "forecast"}),
    ("forecast_landfall_is_not_completed_landfall", "cyclone_landfall", "Bavi made landfall in China.", {"landfall": {"status": "forecast"}}),
    ("thermal_detection_is_not_verified_wildfire", "fire", "A Congo wildfire burns at 300 MW.", {"evidence_type": "thermal_detection", "confidence": 95}),
])
def test_targeted_historical_failure_classes_block_before_model(case_id, signal, tweet, evidence, monkeypatch):
    # Synthetic regression shapes are not replayed historical source packets.
    case = next(case for case in HISTORICAL_CASES if case["case_id"] == case_id)
    assert case["evidence_limit"]
    bundle = replace(_bundle(), signal_kind=signal)
    bundle.raw_signal_dump["evidence"] = evidence
    call = MagicMock(return_value=response(claims=[{"text": tweet, "kind": "comparison"}]))
    monkeypatch.setattr(checker, "_call_gemini", call)
    result = checker.fact_check(tweet, [], bundle, {})
    assert not result.passed
    call.assert_not_called()


def test_all_eight_historical_cases_keep_their_evidence_limits():
    assert len(HISTORICAL_CASES) == 8
    cases = {case["case_id"]: case for case in HISTORICAL_CASES}
    assert cases["thermal_detection_is_not_verified_wildfire"]["verdict"] == "strong_suspicion"
    assert cases["material_precipitation_product_disagreement"]["verdict"] == "unreconciled_discrepancy"
    assert "generation-memory-only" in cases["editorial_region_must_not_override_country"]["evidence_limit"]
    assert "does not establish when" in cases["record_progression_and_later_quality_revision"]["evidence_limit"]


@pytest.mark.parametrize("tweet", ["Forecast uncertainty remains. Bavi made landfall in China.", "No rain fell, but Bavi made landfall in China."])
def test_unrelated_forecast_or_negative_clause_cannot_authorize_landfall(tweet, monkeypatch):
    bundle = replace(_bundle(), signal_kind="cyclone_landfall")
    call = MagicMock()
    monkeypatch.setattr(checker, "_call_gemini", call)
    result = checker.fact_check(tweet, [], bundle, {})
    assert not result.passed and any("unconfirmed_landfall" in failure for failure in result.failures)
    call.assert_not_called()


@pytest.mark.parametrize("tweet", ["Bavi is expected to make landfall in China.", "Bavi has not made landfall in China.", "Bavi may make landfall in China."])
def test_forecast_or_negated_landfall_is_not_completed_landfall(tweet):
    from src.two_bot.scientific_claims import scientific_claim_failures
    assert scientific_claim_failures(tweet, replace(_bundle(), signal_kind="cyclone_landfall")) == []


def test_typed_incident_warrant_is_bound_to_current_candidate_and_date():
    from src.two_bot.scientific_claims import scientific_claim_failures
    bundle = _bundle()
    incident = {"source_product": "synthetic-incident-registry", "revision_id": "source-revision-1",
                "source_url": "https://example.test/incident/one", "valid_date": bundle.when,
                "target_event_id": bundle.event_id, "evidence_type": "verified_incident", "classification": "vegetation_fire"}
    bundle.raw_signal_dump["evidence"] = {"incident": incident}
    assert scientific_claim_failures("A wildfire burns.", bundle) == []
    incident["target_event_id"] = "other-incident"
    assert scientific_claim_failures("A wildfire burns.", bundle)
    incident["target_event_id"] = bundle.event_id
    incident["valid_date"] = "2020-01-01"
    assert scientific_claim_failures("A wildfire burns.", bundle)


def test_diagnostic_copy_cannot_be_reintroduced_as_repaired_source_evidence():
    from src.two_bot.strict_contract import review_snapshot
    from src.two_bot.types import StoryBundle
    original = _bundle()
    original.raw_signal_dump["bad_value"] = float("nan")
    diagnostic = review_snapshot(original.to_dict())
    assert "diagnostic_snapshot_not_evidence" in {issue[0] for issue in bundle_schema_issues(StoryBundle(**diagnostic))}


def test_temperature_only_cannot_masquerade_as_calculated_moisture_warrant():
    from src.two_bot.scientific_claims import scientific_claim_failures
    bundle = _bundle()
    diagnostic = {"source_product": "synthetic-weather", "revision_id": "source-revision-1",
                  "source_url": "https://example.test/weather/one", "valid_date": bundle.when,
                  "target_event_id": bundle.event_id, "evidence_type": "calculated_diagnostic",
                  "diagnostic": "wet_bulb_temperature", "value": 30, "unit": "C", "method": "fixture-method",
                  "inputs": {"temperature_c": 40}}
    bundle.raw_signal_dump["evidence"] = {"moisture_diagnostic": diagnostic}
    assert scientific_claim_failures("A wet-bulb diagnostic.", bundle)
    diagnostic["inputs"]["relative_humidity_pct"] = 60
    assert scientific_claim_failures("A wet-bulb diagnostic.", bundle) == []
    diagnostic["inputs"]["relative_humidity_pct"] = 150
    assert scientific_claim_failures("A wet-bulb diagnostic.", bundle)


def test_t46_classification_only_without_causal_ending_still_requires_incident_warrant(monkeypatch):
    # The historical packet is incomplete; this is the claim's regression shape.
    # A 100% satellite confidence field is not independent fire classification.
    tweet = "A very-high-intensity fire in Congo, satellite-confirmed at 100% confidence."
    call = MagicMock()
    monkeypatch.setattr(checker, "_call_gemini", call)
    result = checker.fact_check(tweet, [], _bundle(), {})
    assert any("unverified_incident" in failure for failure in result.failures)
    call.assert_not_called()


def test_thermal_measurement_and_ordinary_rain_observation_do_not_claim_records_or_fire_identity():
    from src.two_bot.scientific_claims import scientific_claim_failures
    assert scientific_claim_failures("A thermal anomaly: fire radiative power 300 MW, reported satellite confidence 100%.", _bundle()) == []
    assert scientific_claim_failures("Paris recorded 180 mm of rain.", replace(_bundle(), signal_kind="precipitation_extreme")) == []


def test_actual_model_fallback_grade_cannot_be_written_as_recorded_rain(monkeypatch):
    bundle = replace(_bundle(), signal_kind="precipitation_extreme")
    bundle.current_facts.append({"label": "evidence_grade", "value": "model_fallback"})
    call = MagicMock()
    monkeypatch.setattr(checker, "_call_gemini", call)
    result = checker.fact_check("Paris recorded 180 mm of rain.", [], bundle, {})
    assert any("forecast_as_observation" in failure for failure in result.failures)
    call.assert_not_called()


def test_unknown_fire_adapter_leg_does_not_invent_a_nasa_source():
    from src.two_bot.intern import build_fire_bundle
    from tests.two_bot.conftest import _fire_event
    fire = _fire_event()
    fire.source_leg = "unregistered-witness"
    assert "missing_provenance" in {issue[0] for issue in bundle_schema_issues(build_fire_bundle(fire))}


@pytest.mark.parametrize("parser", [writer._parse_writer_json, checker._parse_fact_check_json])
def test_invalid_model_response_is_not_printed_or_included_in_failure_reason(parser, capsys):
    raw = "Private unpublished draft: never emit this to public Actions logs."
    with pytest.raises(ValueError) as raised:
        parser(raw)
    assert raw not in str(raised.value)
    assert "response_sha256=" in str(raised.value)
    assert raw not in capsys.readouterr().out


def test_writer_parse_failure_keeps_private_raw_diagnostic(monkeypatch):
    raw = "Private malformed writer response"
    monkeypatch.setattr(writer, "_call_writer_provider", lambda *a, **k: raw)
    result = writer.write_tweet(_bundle(), MemorySlice())
    assert result.tweet is None
    assert result.failure_diagnostic["raw_response"] == raw
    assert result.failure_diagnostic["truncated"] is False
    assert raw not in result.kill_reason


def test_model_diagnostic_storage_is_bounded_and_keeps_full_response_digest():
    from src.two_bot.strict_contract import model_failure_snapshot
    from src.two_bot.json_utils import model_response_diagnostic
    raw = "x" * 100000
    snapshot = model_failure_snapshot("writer", raw)
    assert snapshot["truncated"] is True
    assert len(snapshot["raw_response"]) == 65536
    assert snapshot["diagnostic"] == model_response_diagnostic(raw)


@pytest.mark.parametrize("stage", ["writer", "fact_check"])
def test_failed_model_response_survives_real_dispatch_suppression_without_public_log(stage, monkeypatch, capsys):
    from src.orchestrator import two_bot_dispatch as dispatch
    from src.two_bot import pipeline
    from src.two_bot.types import FactCheckResult, WriterResult
    from tests.test_triage import _score

    raw = f"Private {stage} malformed response"
    state = _state_with_memory()
    monkeypatch.setattr(dispatch, "_current_suppression_ctx", lambda: {"bot_state": state, "source": "firms", "run_id": "offline"})
    monkeypatch.setattr(pipeline, "run_safety_pipeline", lambda text: (True, ""))
    if stage == "writer":
        monkeypatch.setattr(writer, "_call_writer_provider", lambda *a, **k: raw)
    else:
        monkeypatch.setattr(writer, "write_tweet", lambda *a, **k: WriterResult("Paris: 40 C.", None, "plain_number", None, None, ""))
        monkeypatch.setattr(checker, "fact_check", lambda *a, **k: FactCheckResult(False, ["Invalid response"], raw))
    assert not dispatch._try_two_bot_draft(_bundle(), state, _score(), legacy_type="fire", event_id="offline", review_context={})
    row = state["suppressions"][-1]
    assert row["stage"] == stage
    assert row["model_diagnostics"][0]["raw_response"] == raw
    assert raw not in capsys.readouterr().out
    json.dumps(state, allow_nan=False)


def test_wrong_decoded_writer_output_never_spends_a_repair_call(monkeypatch):
    payload = writer_payload()
    payload["tweet"] = ["Paris: 40 C."]
    call = MagicMock(return_value=json.dumps(payload))
    monkeypatch.setattr(writer, "_call_writer_provider", call)
    result = writer.write_tweet(_bundle(), MemorySlice())
    assert result.tweet is None and "output contract rejected" in result.kill_reason
    assert result.failure_diagnostic["raw_response"] == json.dumps(payload)
    call.assert_called_once()


@pytest.mark.parametrize("claims", [[], [{"text": "Paris", "kind": "invented_kind"}], [{"text": "Paris", "kind": "named_entity"}]])
def test_invalid_or_incomplete_claim_inventory_never_spends_a_repair_call(claims, monkeypatch):
    call = MagicMock(return_value=response(claims=claims))
    monkeypatch.setattr(checker, "_call_gemini", call)
    assert not checker.fact_check("Paris: 40 C.", [], _bundle(), {}).passed
    call.assert_called_once()


def test_self_referencing_dataclass_in_rejected_evidence_keeps_a_persistable_diagnostic():
    from dataclasses import dataclass
    from src.two_bot.evidence_contract import evidence_rejection_details

    @dataclass
    class RecursiveInput:
        child: object = None

    item = RecursiveInput()
    item.child = item
    bundle = _bundle()
    bundle.raw_signal_dump["invalid_source_record"] = item
    audit = audit_story_bundle(bundle)
    assert not audit.prompt_ready
    detail = evidence_rejection_details(bundle, audit)
    assert "__unsupported_type__" in detail["candidate_bundle"]["raw_signal_dump"]["invalid_source_record"]
    json.dumps(detail, allow_nan=False)
