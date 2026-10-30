"""Invented AQ forecasts: a negative disclaimer never licenses observed claims."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from src.data import air_quality
from src.two_bot import fact_check
from src.two_bot.intern.air_quality import build_dust_event_bundle, build_pm25_hazard_bundle
from src.two_bot.scientific_claims import scientific_claim_failures
from tests.air_quality_fixtures import observation


@pytest.fixture(params=("dust", "pm25"))
def forecast(request):
    value = observation(city="Invented City", pm25=250., dust=2000., pm10_24h_mean=90.)
    if request.param == "dust":
        bundle = build_dust_event_bundle(air_quality.detect_dust_event(value))
        quantity = "dust peak of 2,000 μg/m³"
    else:
        bundle = build_pm25_hazard_bundle(air_quality.detect_pm25_hazard(value))
        quantity = "PM2.5 daily mean of 250 μg/m³"
    return bundle, f"CAMS forecasts Invented City's {quantity} on June 8"


@pytest.fixture(params=("scientific", "local_rejection"))
def failures(request):
    def check(text, bundle):
        if request.param == "scientific":
            return scientific_claim_failures(text, bundle)
        result = fact_check.local_rejection(text, [], bundle, {})
        return [] if result is None else result.failures
    return check


@pytest.mark.parametrize("disclaimer", [
    "model-estimated, not station-measured.",
    "model-estimated, not station measured.",
    "MODEL-ESTIMATED, NOT STATION-MEASURED.",
    "not station-measured; model output.",
])
def test_explicit_negative_measurement_disclaimer_can_reach_required_checks(forecast, failures, disclaimer):
    bundle, text = forecast
    before = deepcopy(bundle.to_dict())
    assert failures(text + "; " + disclaimer, bundle) == []
    assert bundle.to_dict() == before


@pytest.mark.parametrize("assertion", [
    "Invented City measured 250 μg/m³.",
    "Invented City observed 250 μg/m³.",
    "Invented City recorded 250 μg/m³.",
    "Invented City has broken the record.",
    "Invented City broke the record.",
    "Invented City set a new record.",
])
@pytest.mark.parametrize("position", ("before", "after"))
def test_disclaimer_does_not_hide_any_other_affirmative_claim(forecast, failures, assertion, position):
    bundle, text = forecast
    negative = text + "; model-estimated, not station-measured."
    candidate = assertion + " " + negative if position == "before" else negative + " " + assertion
    assert any(reason.startswith("forecast_as_observation:") for reason in failures(candidate, bundle))


@pytest.mark.parametrize("near_miss", [
    "not-station-measured.",
    "not only station-measured.",
    "not station-measured as an observation.",
    "not not station-measured.",
    "No claim is intended; station-measured.",
    "not station measured?",
    '"model-estimated, not station-measured."',
    "'model-estimated, not station-measured.'",
    "“model-estimated, not station-measured.”",
    "‘model-estimated, not station-measured.’",
])
def test_distant_negation_quotation_and_near_misses_stay_conservative(forecast, failures, near_miss):
    bundle, text = forecast
    assert any(reason.startswith("forecast_as_observation:") for reason in failures(text + "; " + near_miss, bundle))


def test_disclaimer_does_not_change_other_source_or_causality_checks(forecast, failures):
    bundle, text = forecast
    disclaimer = "; model-estimated, not station-measured."
    causal = text + disclaimer + " Dust drove PM10 higher."
    assert any(reason.startswith("unsupported_air_quality_causation:") for reason in failures(causal, bundle))
    changed = deepcopy(bundle)
    changed.raw_signal_dump["forecast_window"]["valid_end"] = "invalid"
    source_failures = failures(text + ".", changed)
    assert source_failures
    assert failures(text + disclaimer, changed) == source_failures


def test_none_is_only_permission_to_continue_to_the_required_fact_checker(forecast, monkeypatch):
    bundle, text = forecast
    candidate = text + "; model-estimated, not station-measured."
    checker = Mock(return_value=json.dumps({"passed": False, "extracted_claims": [],
        "failures": ["Invented downstream refusal remains authoritative"]}))
    monkeypatch.setattr(fact_check, "_call_gemini", checker)
    assert fact_check.local_rejection(candidate, [], bundle, {}) is None
    checker.assert_not_called()
    result = fact_check.fact_check(candidate, [], bundle, {})
    checker.assert_called_once()
    assert result.passed is False
    assert "Invented downstream refusal remains authoritative" in result.failures
