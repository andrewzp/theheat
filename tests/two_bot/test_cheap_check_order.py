"""Existing scientific rejections avoid downstream calls; local eligibility is not a pass."""

from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from src.two_bot import fact_check, pipeline
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests.two_bot.conftest import _bundle, _state_with_memory
from tests.two_bot.test_pipeline import _monthly_high_bundle

pytestmark = pytest.mark.usefixtures("configured_pipeline_providers")


@pytest.fixture
def calls(monkeypatch):
    safety = Mock(return_value=(True, None))
    factual = Mock(return_value=FactCheckResult(True, [], "offline fixture"))
    critic = Mock(return_value=CriticResult(True, None, "offline fixture"))
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety)
    monkeypatch.setattr(fact_check, "fact_check", factual)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    return safety, factual, critic


def check(text, bundle, state, *, outcome):
    return pipeline._check_safety_honesty_fact(
        text, bundle, state,
        record_kill=lambda stage, reason: outcome.update(stage=stage, reason=reason),
        mark_stage=lambda stage, result: outcome.update(stage_result=(stage, result)),
    )


@pytest.mark.parametrize("text", ["Mali wildfire is 361 MW.",
                                  "Mali thermal detection broke through the convective lid.",
                                  "Mali has a wet-bulb temperature of 35C."])
def test_recognizable_unsupported_claims_use_no_downstream_model(text, calls):
    outcome = {}
    assert check(text, _bundle(), _state_with_memory(), outcome=outcome) is None
    assert outcome["stage"] == "fact_check" and outcome["stage_result"] == ("fact_check", "kill")
    assert all(not model.mock_calls for model in calls)


def test_forecast_comparison_cannot_buy_checks_for_observed_record_wording(calls):
    outcome = {}
    assert check("Conakry recorded its hottest May temperature in 12 years.",
                 _monthly_high_bundle(), _state_with_memory(), outcome=outcome) is None
    assert "temperature" in outcome["reason"] and all(not model.mock_calls for model in calls)


def test_alert_threshold_is_not_an_archive_record_and_costs_no_check_calls(calls):
    bundle = replace(_bundle(), signal_kind="precipitation_extreme",
                     headline_metric={"label": "rainfall", "value": 50, "unit": "mm"})
    outcome = {}
    assert check("Mali set an all-time rainfall record of 50mm.", bundle,
                 _state_with_memory(), outcome=outcome) is None
    assert "unwarranted_record" in outcome["reason"] and all(not m.mock_calls for m in calls)


@pytest.mark.parametrize("text", ["", "x" * 281, "bad \ud800 text"])
def test_invalid_text_is_rejected_before_paid_safety(text, calls):
    outcome = {}
    assert check(text, _bundle(), _state_with_memory(), outcome=outcome) is None
    assert "invalid_tweet" in outcome["reason"] and all(not m.mock_calls for m in calls)


def test_duplicate_shipped_text_is_rejected_before_safety(calls):
    text = "Mali thermal power is 361 MW."
    outcome = {}
    state = _state_with_memory(shipped_tweets=[{"tweet_text": text}])
    assert check(text, _bundle(), state, outcome=outcome) is None
    assert "reuse" in outcome["reason"] and all(not m.mock_calls for m in calls)


def test_broken_bundle_cannot_purchase_safety(calls):
    bundle = _bundle()
    bundle.headline_metric["value"] = float("nan")
    outcome = {}
    assert check("A satellite thermal detection near Mali.", bundle,
                 _state_with_memory(), outcome=outcome) is None
    assert outcome["stage"] == "fact_check" and all(not m.mock_calls for m in calls)


def test_forbidden_scoped_claim_is_rejected_before_safety(calls):
    bundle = replace(_bundle(), signal_kind="regional_anomaly",
                     historical_context={"forbidden_claims": ["Mali's average"]})
    outcome = {}
    assert check("Mali’s average is rising.", bundle, _state_with_memory(), outcome=outcome) is None
    assert outcome["stage"] == "honesty_gate" and all(not m.mock_calls for m in calls)


def test_cross_signal_causation_is_rejected_before_safety(calls):
    bundle = _bundle()
    bundle.related_signals = [Mock()]  # Gate only reads presence; no source claim is certified.
    outcome = {}
    assert check("The same system is behind both events.", bundle,
                 _state_with_memory(), outcome=outcome) is None
    assert outcome["stage"] == "cross_signal" and all(not m.mock_calls for m in calls)


def test_eligible_exact_text_still_runs_every_required_model_in_order(monkeypatch, calls):
    text = "Mali thermal power is 361 MW."
    monkeypatch.setattr(pipeline.writer, "write_tweet",
                        Mock(return_value=WriterResult(text, None, "number", None, None, "fixture")))
    observed = []
    safety, factual, critic = calls
    safety.side_effect = lambda checked: (observed.append(("safety", checked)) or (True, None))
    factual.side_effect = lambda checked, *args: (
        observed.append(("fact_check", checked)) or FactCheckResult(True, [], "fixture")
    )
    critic.side_effect = lambda checked, *args, **kwargs: (
        observed.append(("critic", checked)) or CriticResult(True, None, "fixture")
    )
    draft = pipeline.generate_draft(_bundle(), _state_with_memory())
    assert draft and draft["text"] == text
    assert observed == [("safety", text), ("fact_check", text), ("critic", text)]


def test_locally_eligible_text_does_not_bypass_unavailable_safety(calls):
    calls[0].return_value = (False, "safety_unavailable")
    outcome = {}
    assert check("Mali thermal power is 361 MW.", _bundle(),
                 _state_with_memory(), outcome=outcome) is None
    assert outcome["stage"] == "safety" and calls[0].call_count == 1
    assert not calls[1].mock_calls and not calls[2].mock_calls


def test_no_local_rejection_is_never_returned_as_a_fact_pass(monkeypatch):
    text = "Mali thermal power is 361 MW."
    assert fact_check.local_rejection(text, [], _bundle(), _state_with_memory()) is None
    provider = Mock(return_value=json.dumps({"passed": False, "extracted_claims": [],
                                            "failures": ["Unverified comparison"]}))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    result = fact_check.fact_check(text, [], _bundle(), _state_with_memory())
    assert not result.passed and provider.call_count == 1


def test_full_fact_checker_rechecks_changed_memory_after_early_eligibility(monkeypatch):
    text = "Mali thermal power is 361 MW."
    state = _state_with_memory()
    assert fact_check.local_rejection(text, [], _bundle(), state) is None
    state["memory"]["shipped_tweets"].append({"tweet_text": text})
    provider = Mock(side_effect=AssertionError("No paid request for reused text"))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    result = fact_check.fact_check(text, [], _bundle(), state)
    assert not result.passed and "reuse" in result.failures[0] and not provider.mock_calls


def test_revised_unsupported_text_cannot_buy_another_safety_or_fact_call(monkeypatch, calls):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    monkeypatch.setattr(pipeline.writer, "write_tweet", Mock(side_effect=[
        WriterResult("Mali thermal power is 361 MW.", None, "number", None, None, "fixture"),
        WriterResult("Mali wildfire is 361 MW.", None, "number", None, None, "fixture"),
    ]))
    calls[2].return_value = CriticResult(False, None, "fixture", verdict="REVISE",
                                        revise_instruction="Use the unsupported label")
    outcome = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=outcome) is None
    assert outcome["kill_stage"] == "fact_check"
    assert [model.call_count for model in calls] == [1, 1, 1]
