"""Invented dust/PM10 comparison scopes; no captured copy or model/source calls."""
from copy import deepcopy

import pytest

from src.data import air_quality
from src.two_bot import fact_check
from src.two_bot.air_quality_claims import dust_comparison_failures
from src.two_bot.intern.air_quality import build_dust_event_bundle, build_pm25_hazard_bundle
from tests.air_quality_fixtures import observation


CODE = "dust_peak_comparison:"
FALSE_COMPARISONS = [
    "Luma's forecast dust peak is 2,000 µg/m³, 44 times the WHO 24-hour guideline, with PM10 also forecast at 90 µg/m³.",
    "Luma's forecast dust peak is 2,000 µg/m³, 44 times the WHO guideline, and PM10 is forecast at 90 µg/m³.",
    "Luma's forecast dust peak is 2,000 µg/m³—44 times the WHO guideline—with PM10 also forecast at 90 µg/m³.",
    "Luma's forecast dust peak is 2,000 µg/m³, with PM10 listed in the legend, 44 times the WHO guideline.",
    "Luma's forecast dust peak is 2,000 µg/m³, with 'PM10' merely a chart label, 44 times the WHO guideline.",
    'Luma\'s forecast dust peak is 2,000 µg/m³, "with PM10 forecast at 90", 44 times the WHO guideline.',
    "Luma's forecast dust is a 24-hour average of 2,000 µg/m³, with PM10 also forecast at 90 µg/m³.",
    "Luma's forecast dust peak is not a daily mean, but is 44 times the WHO guideline, with PM10 forecast at 90 µg/m³.",
    "Luma's forecast dust peak, with PM10 forecast at 90 µg/m³, is 2,000 µg/m³ and 44 times the WHO guideline.",
]
SHARED_SUBJECT_COMPARISONS = [
    "Dust and PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    "Dust and PM10 cross the WHO guideline.",
    "Dust or PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    "Dust plus PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    "Dust with PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    "Dust as well as PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    "Dust along with PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    "Dust, PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    "Dust/PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
    '"Dust" and PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.',
    "'Dust', PM10 cross the WHO guideline.",
    "Dust, PM2.5 and PM10 average 2,000 µg/m³, 44 times the WHO 24-hour guideline.",
]
CONTROLS = [
    "Luma's forecast dust peak is 2,000 µg/m³.",
    "Luma's dust is forecast to peak near 2,000 µg/m³ (a peak, not a daily mean).",
    "Luma's dust peak is 2,000 µg/m³, not a 24-hour average, with PM10 also forecast at 90 µg/m³.",
    "Luma's forecast dust peak is 2,000 µg/m³; PM10 is forecast to average 90 µg/m³, twice the WHO 24-hour guideline.",
    "Luma's forecast dust peak is 2,000 µg/m³. PM10's forecast daily mean is 90 µg/m³, twice the WHO guideline.",
    "PM10 crosses the guideline as dust reaches 2,000 µg/m³.",
    "Dust is forecast at 2,000 µg/m³ while PM10 is forecast to average 90 µg/m³, twice the WHO 24-hour guideline.",
    "Dust is forecast at 2,000 µg/m³ and PM10 is forecast to average 90 µg/m³, twice the WHO 24-hour guideline.",
    "Luma's forecast dust peak is 2,000 µg/m³, with PM10 listed in the legend.",
]


def _source(pm10=90.0):
    obs = observation(city="Luma", day="2026-10-30", pm25=250.0, dust=2000.0, pm10_24h_mean=pm10)
    event = air_quality.detect_dust_event(obs)
    assert event is not None
    return build_dust_event_bundle(event)


def _failures(consumer, text, source):
    if consumer == "guard":
        return dust_comparison_failures(text, source)
    result = fact_check.local_rejection(text, [], source, {})
    return result.failures if result is not None else []


@pytest.mark.parametrize("consumer", ["guard", "local-rejection"])
@pytest.mark.parametrize("text", FALSE_COMPARISONS)
def test_pm10_elsewhere_never_exempts_the_dust_peak_comparison(consumer, text):
    source = _source()
    before = deepcopy(source.to_dict())
    assert any(code.startswith(CODE) for code in _failures(consumer, text, source))
    assert source.to_dict() == before  # Exact source/window, units and evidence stay bound.


@pytest.mark.parametrize("consumer", ["guard", "local-rejection"])
@pytest.mark.parametrize("text", SHARED_SUBJECT_COMPARISONS)
def test_a_coordinated_dust_subject_retains_its_shared_comparison(consumer, text):
    source = _source()
    before = deepcopy(source.to_dict())
    assert any(code.startswith(CODE) for code in _failures(consumer, text, source))
    assert source.to_dict() == before


@pytest.mark.parametrize("consumer", ["guard", "local-rejection"])
def test_an_incidental_pm10_mention_without_a_supplied_anchor_does_not_exempt_dust(consumer):
    source = _source(pm10=None)
    assert not any(fact["label"] == "who_pm10_multiple" for fact in source.current_facts)
    assert any(code.startswith(CODE) for code in _failures(consumer, FALSE_COMPARISONS[0], source))


@pytest.mark.parametrize("text", CONTROLS)
def test_separate_pm10_anchor_and_narrow_negated_mean_still_need_the_normal_checkers(text):
    source = _source()
    before = deepcopy(source.to_dict())
    assert dust_comparison_failures(text, source) == []
    assert fact_check.local_rejection(text, [], source, {}) is None  # Not a completed factual pass.
    assert source.to_dict() == before


def test_unit_corruption_is_not_fixed_or_exempted_by_a_valid_pm10_clause():
    source = _source()
    source.raw_signal_dump["forecast_window"]["series"]["dust"]["unit"] = "mg/m³"
    before = deepcopy(source.to_dict())
    result = fact_check.local_rejection(CONTROLS[3], [], source, {})
    assert result is not None and not result.passed
    assert any(code.startswith("air_quality_window_unqualified:") for code in result.failures)
    assert source.to_dict() == before


def test_the_dust_peak_rule_does_not_expand_to_a_pm25_story():
    obs = observation(city="Luma", day="2026-10-30", pm25=250.0, dust=2000.0, pm10_24h_mean=90.0)
    event = air_quality.detect_pm25_hazard(obs)
    assert event is not None
    assert dust_comparison_failures(FALSE_COMPARISONS[0], build_pm25_hazard_bundle(event)) == []
