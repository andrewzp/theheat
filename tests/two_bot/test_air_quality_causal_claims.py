"""Invented causal-copy counterexamples; no historical text or provider calls."""
from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import Mock

import pytest

from src.data import air_quality
from src.editorial.policy import current_editorial_policy, source_manifest
from src.editorial.revisions import fingerprint
from src.two_bot import check_requests, fact_check, pipeline
from src.two_bot.air_quality_claims import causal_claim_failures
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.air_quality import build_dust_event_bundle, build_pm25_hazard_bundle
from src.two_bot.types import CriticResult, FactCheckResult, RelatedSignal, WriterResult
from tests.air_quality_fixtures import observation
from tests import test_check_executor as execution
from tests.two_bot.conftest import _bundle, _state_with_memory
from tests.two_bot.test_candidate_derivation import packet

CODE = "unsupported_air_quality_causation:"
CAUSAL = "CAMS forecasts dust at 2,000 μg/m³ in Luma, pushing PM10 to a daily mean of 90 μg/m³."
FACTUAL = "CAMS forecasts a PM10 daily mean of 90 μg/m³ in Luma, twice the WHO 24-hour guideline."


def bundle(kind="dust_event"):
    obs = observation(city="Luma", pm25=250., dust=2000., pm10_24h_mean=90.)
    if kind == "air_quality_hazard":
        return build_pm25_hazard_bundle(air_quality.detect_pm25_hazard(obs))
    return build_dust_event_bundle(air_quality.detect_dust_event(obs))


def related_bundle():
    source = bundle()
    host = _bundle()
    host.related_signals = [RelatedSignal(
        event_id=source.event_id, signal_kind=source.signal_kind, where=source.where,
        when=source.when, country=source.country, headline_metric=deepcopy(source.headline_metric),
        air_quality_evidence=deepcopy(source.raw_signal_dump),
    )]
    return host


@pytest.mark.parametrize("text", [
    CAUSAL,
    "Dust pushes PM10 above the WHO guideline.",
    "CAMS predicts dust will drive PM2.5 higher.",
    "Dust raised PM10 to 90 μg/m³.",
    "Dust has lifted particulate concentrations.",
    "Dust boosts the AQI.",
    "Dust is fueling pollution.",
    "Dust fuelled pollution.",
    "Dust worsens air quality.",
    "Dust causes poor visibility.",
    "Dust triggered respiratory symptoms.",
    "Dust increases hospitalizations.",
    "Dust reduces visibility.",
    "Dust cuts visibility.",
    "Dust is impairing breathing.",
    "PM10 degrades air quality.",
    "Dust lowers visibility.",
    "Dust suppresses visibility.",
    "Dust obscures visibility.",
    "Dust threatens health.",
    "Dust contributes to the PM10 peak.",
    "Dust led to higher PM10.",
    "PM2.5 results in respiratory illness.",
    "The PM10 peak is due to dust.",
    "Poor visibility is because of dust.",
    "Visibility fell as a result of dust.",
    "PM10 increased owing to dust.",
    "The PM10 peak was caused by dust.",
    "PM2.5 was driven by dust.",
    "No rain is forecast, but dust is pushing PM10 up.",
    "Dust is not only raising PM10 but reducing visibility.",
    "Dust is not not raising PM10.",
    "Dust is not raising PM10, but dust is reducing visibility.",
    "Dust causes PM10 to rise, but does not cause asthma.",
    "Dust isn't raising PM10; dust boosts AQI.",
    "Dust doesn't raise PM10; dust lifts AQI.",
    "Dust does not raise PM10. Dust boosts AQI.",
    "CAMS says ‘dust is raising PM10’.",
    'CAMS says "dust is raising PM10".',
    "“In general, dust can raise PM10 concentrations.”",
    "In general, dust can raise PM10 concentrations in Luma.",
    "In general, dust can raise PM10 concentrations, and dust is driving AQI higher.",
    "In general, dust can raise PM10 concentrations. Dust is driving AQI higher.",
    "In general, dust can raise PM10 concentrations; dust is driving AQI higher.",
    "Dust may be pushing PM10 higher.",  # Event-specific uncertainty is not background.
    "Dust is projected to raise PM10.",
    "PM₂.₅—driven by dust—is forecast to peak today.",
    "DUST\nIS\tPUSHING\u00a0PM₁₀ higher.",
    "Dust is raising PM2.5 to 90.5 μg/m³.",
])
def test_named_causal_links_are_not_qualified_by_model_values(text):
    source = bundle()
    assert audit_story_bundle(source).prompt_ready
    assert causal_claim_failures(text, source)[0].startswith(CODE)


@pytest.mark.parametrize("text", [
    FACTUAL,
    "CAMS forecasts dust at 2,000 μg/m³, with PM10 averaging 90 μg/m³.",
    "Dust and PM10 are forecast to peak today.",
    "PM10 is forecast to rise above the WHO guideline.",
    "PM10 crosses the guideline as dust reaches 2,000 μg/m³.",
    "The PM10 forecast is due tomorrow. Dust forecasts follow.",
    "The PM10 forecast is due to be published with dust data.",
    "Dust is not raising PM10.",
    "Dust does not necessarily raise PM10.",
    "Dust has never directly raised PM10.",
    "Dust cannot raise PM10.",
    "Dust can't raise PM10.",
    "Dust won’t raise PM10.",
    "Dust isn’t raising PM10.",
    "Dust did not cause the PM10 peak.",
    "Dust would not be pushing PM10 higher.",
    "The PM10 peak is not due to dust.",
    "The PM10 peak was not caused by dust.",
    "These forecast values do not establish causation.",
    "In general, dust can raise PM10 concentrations.",
    "In general, dust may increase particulate levels.",
    "In general, dust can raise PM2.5 levels. PM10 is forecast at 90 μg/m³.",
    "PM10 is high. A fundraiser raises money for health.",
    "The visibility forecast follows; dust is high and a fundraiser raises money.",
    "Dust is high; a driver reports PM10 values.",
    "Stardust causes camera problems; PM10 is forecast at 90 μg/m³.",
])
def test_factual_threshold_and_narrow_negative_background_controls_still_need_checks(text):
    assert causal_claim_failures(text, bundle()) == []  # Never a check pass.


@pytest.mark.parametrize("source", [bundle(), bundle("air_quality_hazard"), related_bundle()])
def test_direct_checker_refuses_primary_and_related_links_without_calls(source, monkeypatch):
    before = deepcopy(source.to_dict())
    provider = Mock(side_effect=AssertionError("No checker call for unsupported causation"))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    result = fact_check.fact_check(CAUSAL, [], source, {})
    assert not result.passed and any(f.startswith(CODE) for f in result.failures)
    provider.assert_not_called()
    assert source.to_dict() == before


def test_new_rule_does_not_change_other_domains_or_accept_an_unqualified_packet():
    assert causal_claim_failures(CAUSAL, _bundle()) == []
    legacy = bundle()
    legacy.raw_signal_dump.pop("forecast_window")
    failure = fact_check.local_rejection(FACTUAL, [], legacy, {})
    assert failure and not failure.passed
    assert any(f.startswith("air_quality_window_unqualified:") for f in failure.failures)


def test_purported_causal_metadata_never_invents_a_warrant():
    source = bundle()
    source.raw_signal_dump["causal_warrant"] = {"verified": True, "source": "invented"}
    assert causal_claim_failures(CAUSAL, source)[0].startswith(CODE)


@pytest.mark.usefixtures("configured_pipeline_providers")
@pytest.mark.parametrize("text", [CAUSAL, FACTUAL])
def test_pipeline_retains_exact_inputs_and_requires_all_checks_for_factual_copy(text, monkeypatch):
    source = bundle()
    before = deepcopy(source.to_dict())
    writer_result = WriterResult(text, None, "number", None, None, "Invented fixture")
    monkeypatch.setattr(pipeline.writer, "write_tweet", Mock(return_value=writer_result))
    calls = []
    safety = Mock(side_effect=lambda checked: (calls.append(("safety", checked)) or (True, None)))
    factual = Mock(side_effect=lambda checked, *args: (
        calls.append(("fact_check", checked)) or FactCheckResult(True, [], "Offline fixture")
    ))
    critic = Mock(side_effect=lambda checked, *args, **kwargs: (
        calls.append(("critic", checked)) or CriticResult(True, None, "Offline fixture")
    ))
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety)
    monkeypatch.setattr(fact_check, "fact_check", factual)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    outcome = {}
    draft = pipeline.generate_draft(source, _state_with_memory(), result_out=outcome)
    if text == CAUSAL:
        assert draft is None and outcome["kill_stage"] == "fact_check" and not calls
        assert CODE in outcome["kill_reason"]
        rejected = outcome["rejected_candidate"]
        assert rejected["verdict"]["check_path"] == "local_precheck"
        assert rejected["text"] == text and rejected["bundle"] == before
    else:
        assert draft and draft["text"] == text
        assert calls == [(stage, text) for stage in ("safety", "fact_check", "critic")]
    assert source.to_dict() == before


def test_locally_eligible_text_can_still_fail_the_required_model(monkeypatch):
    source = bundle()
    provider = Mock(return_value=json.dumps(dict(
        passed=False, failures=["Invented independent checker rejection"], extracted_claims=[],
    )))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    assert fact_check.local_rejection(FACTUAL, [], source, {}) is None
    result = fact_check.fact_check(FACTUAL, [], source, {})
    assert not result.passed and "Invented independent checker rejection" in result.failures
    provider.assert_called_once_with(FACTUAL, source, retry_suffix="")


@pytest.mark.parametrize("text", [CAUSAL, FACTUAL])
@pytest.mark.parametrize("related", [False, True])
def test_retained_deterministic_check_shares_the_rule_without_changing_receipts(text, related):
    source = related_bundle() if related else bundle()
    saved = packet(dict(candidate=asdict(WriterResult(text, None, "number", None, None, "Invented fixture")),
                        candidate_id="c" * 64, bundle=source.to_dict(), policy=current_editorial_policy()))
    before = deepcopy(saved)
    result = check_requests.deterministic_result(saved)
    assert any(f.startswith(CODE) for f in result["failures"]) == (text == CAUSAL)
    assert result["passed"] == (text == FACTUAL)
    assert saved == before


store, inputs = execution.store, execution.inputs


@pytest.mark.usefixtures("configured_pipeline_providers")
def test_real_retained_executor_withholds_before_any_paid_stage(store, inputs, monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    source = bundle()
    inputs.update(bundle=source, bundle_sha256=fingerprint(source.to_dict()), policy=current_editorial_policy())
    pair, grant = execution.batches.started(store, inputs)
    rows = execution.batches.rows(pair)
    candidate = json.loads(rows[0]["result"]["message"]["content"][0]["text"])
    candidate["tweet"] = CAUSAL
    rows[0]["result"]["message"]["content"][0]["text"] = json.dumps(candidate)
    receipt = execution.batches.retain(store, grant, execution.batches.contract.raw_rows(rows))
    payload = dict(job_id=pair[1]["job_id"], owner="worker-one", fence=1,
                   receipt_id=receipt["receipt_id"], current_context=execution.batches.contract.context(pair[0]),
                   custom_id=json.loads(pair[0])["requests"][0]["custom_id"], bundle=source.to_dict(),
                   memory=inputs["memory"].to_dict(), checker_state=deepcopy(store.read()[1]))
    check_set = store.candidate_checks("intake", payload, now=execution.NOW)
    case = dict(store=store, identity=check_set["check_set_id"], payload=payload)
    sent, _ = execution.provider(monkeypatch, [])
    before = deepcopy(store.read())
    result = execution.run(case)
    assert not result["required_checks_completed"] and not sent
    assert result["checks"]["stages"]["deterministic"] == "rejected"
    repeated = execution.run(case)
    assert not repeated["required_checks_completed"] and not sent
    assert store.read() == before
    assert execution.saved(case)["packet"]["bundle"] == source.to_dict()


def test_causal_rule_participates_in_approval_policy_identity():
    manifest = source_manifest()
    assert "src/two_bot/air_quality_claims.py" in manifest["files"]
