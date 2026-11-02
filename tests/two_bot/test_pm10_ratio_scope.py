"""Invented co-reported PM10 ratios; local non-rejection is not factual approval."""
from copy import deepcopy

import pytest

from src.two_bot import fact_check
from src.two_bot.air_quality_claims import dust_comparison_failures
from tests.two_bot.test_dust_comparison_scope import CODE, _source


INDEPENDENT = [
    "PM10 averaging about twice the WHO 24-hour guideline",
    "PM10 averaging ~2× the WHO 24-hour guideline",
    "PM10 is forecast to average approximately 2 times the WHO 24-hour guideline",
    "PM10's daily mean is roughly 2x the WHO guideline",
    "PM10's 24-hour mean around double the WHO guideline",
    "PM10 forecast daily mean about 2 times the WHO 24-hour guideline",
]


@pytest.mark.parametrize("comparison", INDEPENDENT)
def test_independent_supplied_pm10_ratio_reaches_required_checkers(comparison):
    text = "Luma's forecast dust peak is 2,000 µg/m³, with " + comparison + "."
    source = _source()
    before = deepcopy(source.to_dict())
    assert dust_comparison_failures(text, source) == []
    assert fact_check.local_rejection(text, [], source, {}) is None
    assert source.to_dict() == before


@pytest.mark.parametrize("text", [
    "Dust and PM10 average twice the WHO 24-hour guideline.",
    "Dust—and PM10 average 90 µg/m³, twice the WHO 24-hour guideline.",
    "Dust—PM10 average 90 µg/m³, twice the WHO 24-hour guideline.",
    "Dust with PM10 averaging ~2× the WHO 24-hour guideline.",
    "Dust concentrations and PM10 average twice the WHO 24-hour guideline.",
    "Dust levels and PM10 average ~2× the WHO 24-hour guideline.",
    "Dust's peak and PM10 average twice the WHO 24-hour guideline.",
    "Dust's daily peak and PM10 average twice the WHO 24-hour guideline.",
    "Dust's daily peak, with PM10 averaging twice the WHO 24-hour guideline.",
    "Dust's daily concentration near PM10 averaging twice the WHO 24-hour guideline.",
    "Dust's peak at 2,000 µg/m³ and PM10 average twice the WHO 24-hour guideline.",
    "Dust's daily peak Monday — PM10 averaging twice the WHO 24-hour guideline.",
    "Dust and a 24-hour PM10 mean averaging twice the WHO daily guideline.",
    "Dust's daily mean is 2,000 µg/m³ Monday, with a PM10 24-hour mean forecast at twice the WHO guideline.",
    "Dust is forecast at 2,000 µg/m³ Monday, with a 24-hour mean PM10 around twice the WHO guideline and dust at 44×.",
    "Dust readings along with PM10 average twice the WHO guideline.",
    "Dust, PM10's daily mean is roughly 2x the WHO guideline.",
    "Dust is 44× the WHO guideline, with PM10 averaging twice the WHO guideline.",
    "Dust peaks at 44× the WHO guideline (PM10's mean averages twice the WHO guideline).",
    "Dust peaks near 2,000 µg/m³, with PM10 in the legend, 44× the WHO guideline.",
    "Dust peaks near 2,000 µg/m³, with PM10 averaging twice the WHO guideline and dust at 44×.",
    "Dust is forecast at 2× its daily average.",
    "Dust is forecast at 2× its modeled baseline.",
])
def test_shared_incidental_and_remaining_dust_comparisons_still_hold(text):
    source = _source()
    assert any(reason.startswith(CODE) for reason in dust_comparison_failures(text, source))
    result = fact_check.local_rejection(text, [], source, {})
    assert result is not None and not result.passed
    assert any(reason.startswith(CODE) for reason in result.failures)


@pytest.mark.parametrize("mutation", ["absent", "wrong-unit", "missing-hour", "altered-anchor"])
def test_ratio_exemption_requires_an_intact_supplied_pm10_window(mutation):
    source = _source(pm10=None if mutation == "absent" else 90.0)
    if mutation == "wrong-unit":
        source.raw_signal_dump["forecast_window"]["series"]["pm10"]["unit"] = "mg/m³"
    elif mutation == "missing-hour":
        source.raw_signal_dump["forecast_window"]["series"]["pm10"]["values"].pop()
    elif mutation == "altered-anchor":
        next(row for row in source.current_facts if row["label"] == "who_pm10_multiple")["value"] = 200.0
    before = deepcopy(source.to_dict())
    text = "Luma's dust could peak at 2,000 µg/m³, with PM10 averaging about twice the WHO 24-hour guideline."
    assert any(reason.startswith(CODE) for reason in dust_comparison_failures(text, source))
    result = fact_check.local_rejection(text, [], source, {})
    assert result is not None and not result.passed
    assert source.to_dict() == before


def test_pm10_ratio_does_not_exempt_dust_causation():
    source = _source()
    text = "Dust drives pollution in Luma, with PM10 averaging about twice the WHO 24-hour guideline."
    result = fact_check.local_rejection(text, [], source, {})
    assert result is not None and any(reason.startswith("unsupported_air_quality_causation:") for reason in result.failures)


def test_dust_only_dash_preservation_does_not_split_a_causal_claim():
    source = _source()
    text = "Dust drives — PM10 pollution in Luma."
    result = fact_check.local_rejection(text, [], source, {})
    assert result is not None and any(reason.startswith("unsupported_air_quality_causation:") for reason in result.failures)


@pytest.mark.parametrize("text", [
    "Luma: dust is forecast to peak near 2,000 µg/m³ Monday, with PM10 averaging ~2× the WHO 24-hour guideline.",
    "Luma: dust is forecast to peak near 2,000 µg/m³ Sunday evening, with PM10 averaging ~2× the WHO 24-hour guideline across the day.",
    "Luma: dust is forecast to peak near 2,000 µg/m³ Sunday, with a PM10 24-hour mean forecast at ~2× the WHO guideline.",
    "Luma: dust is forecast to peak near 2,000 µg/m³ Sunday, with PM10 averaging ~2× the WHO 24-hour guideline.",
    "Luma: dust is forecast to peak near 2,000 µg/m³ Sunday, with a 24-hour mean PM10 around 2× the WHO guideline.",
    "Luma: dust is forecast to peak near 2,000 µg/m³ Sunday, with a 24-hour PM10 mean averaging ~2× the WHO daily guideline.",
    "Luma: dust is forecast to peak near 2,000 µg/m³ Saturday — PM10 averaging ~2× the WHO 24-hour guideline.",
])
def test_invented_retained_grammar_shapes_reach_the_mandatory_checkers(text):
    # Only grammar is retained: place, quantities and evidence are invented.
    # Neither the original rejected text nor its old check gets promoted.
    source = _source()
    before = deepcopy(source.to_dict())
    assert dust_comparison_failures(text, source) == []
    assert fact_check.local_rejection(text, [], source, {}) is None
    assert source.to_dict() == before
