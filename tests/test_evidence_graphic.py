"""Scientific media boundary tests independent of any plotting dependency."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import build_alt_text, chart_title, validate_graphic

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/evidence_graphics_synthetic.json").read_text())


def validate(template, evidence):
    return validate_graphic(template, evidence, expected_evidence_sha256=fingerprint(evidence))


@pytest.mark.parametrize("template", EXAMPLES)
def test_valid_packets_are_exactly_bound_without_mutation(template):
    evidence = deepcopy(EXAMPLES[template])
    original = deepcopy(evidence)
    validated = validate(template, evidence)
    assert validated == original == evidence
    assert validated is not evidence
    assert "SYNTHETIC DEMONSTRATION" in build_alt_text(template, evidence)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, None, "40.2"])
def test_nonfinite_or_coerced_values_cannot_become_plot_measurements(value):
    evidence = deepcopy(EXAMPLES["temperature_comparator"])
    evidence["points"][0]["value"] = value
    with pytest.raises(ValueError):
        validate("temperature_comparator", evidence)


def test_expected_review_hash_cannot_follow_an_edited_chart_value():
    evidence = deepcopy(EXAMPLES["temperature_comparator"])
    expected = fingerprint(evidence)
    evidence["points"][0]["value"] = 50
    with pytest.raises(ValueError, match="review binding"):
        validate_graphic("temperature_comparator", evidence, expected_evidence_sha256=expected)


@pytest.mark.parametrize("change", ["units", "coverage", "count", "cutoff", "forecast_prior", "prior_outside", "source", "date"])
def test_comparator_requires_compatible_complete_dated_source_evidence(change):
    evidence = deepcopy(EXAMPLES["temperature_comparator"])
    baseline = evidence["baseline"]
    if change == "units":
        baseline["point"]["unit"] = "°F"
    elif change == "coverage":
        baseline["complete"] = False
    elif change == "count":
        baseline["sample_count"] = 7
    elif change == "cutoff":
        baseline["cutoff"] = evidence["points"][0]["valid_time"]
    elif change == "forecast_prior":
        baseline["point"]["evidence_type"] = "forecast"
    elif change == "prior_outside":
        baseline["point"]["valid_time"] = "2026-08-01T00:00:00Z"
    elif change == "source":
        baseline["point"]["source"]["revision_sha256"] = ""
    else:
        evidence["points"][0]["valid_time"] = "2026-09-12"
    with pytest.raises(ValueError):
        validate("temperature_comparator", evidence)


@pytest.mark.parametrize("change", ["out_of_order", "duplicate_time", "future_observed", "reanalysis_mix", "implied_baseline"])
def test_trajectory_cannot_mix_times_or_imply_an_unverified_record(change):
    evidence = deepcopy(EXAMPLES["temperature_trajectory"])
    if change == "out_of_order":
        evidence["points"].reverse()
    elif change == "duplicate_time":
        evidence["points"][1]["valid_time"] = evidence["points"][0]["valid_time"]
    elif change == "future_observed":
        evidence["points"][-1]["evidence_type"] = "observed"
    elif change == "reanalysis_mix":
        evidence["points"][0]["evidence_type"] = "reanalysis"
    else:
        evidence["baseline"] = EXAMPLES["temperature_comparator"]["baseline"]
    with pytest.raises(ValueError):
        validate("temperature_trajectory", evidence)


def test_alt_text_names_exact_values_sources_types_scope_and_cutoff():
    evidence = EXAMPLES["temperature_comparator"]
    alt = build_alt_text("temperature_comparator", evidence)
    assert "40.2°C forecast" in alt and "38.6°C observed" in alt
    assert "2026-09-08T12:00:00Z" in alt
    assert "Synthetic model" in alt and "Synthetic station" in alt
    assert "complete 8 samples" in alt and "Difference +1.6°C" in alt
    assert chart_title("temperature_comparator", evidence) == "40.2°C forecast"
    assert "record" not in chart_title("temperature_comparator", evidence).lower()


def test_synthetic_url_cannot_be_relabelled_as_real_source_evidence():
    evidence = deepcopy(EXAMPLES["temperature_comparator"])
    evidence["synthetic"] = False
    with pytest.raises(ValueError, match="Synthetic source URLs"):
        validate("temperature_comparator", evidence)


@pytest.mark.parametrize("as_of", [None, "2026-09-08", "2026-09-07T12:00:00Z", "2026-09-12T12:00:00Z"])
def test_evidence_cutoff_must_separate_observations_and_forecasts(as_of):
    evidence = deepcopy(EXAMPLES["temperature_trajectory"])
    evidence["evidence_as_of"] = as_of
    with pytest.raises(ValueError):
        validate("temperature_trajectory", evidence)


def test_observed_candidate_is_allowed_only_at_or_before_evidence_cutoff():
    evidence = deepcopy(EXAMPLES["temperature_comparator"])
    evidence["points"][0]["evidence_type"] = "observed"
    with pytest.raises(ValueError, match="after the evidence cutoff"):
        validate("temperature_comparator", evidence)
    evidence["evidence_as_of"] = evidence["points"][0]["valid_time"]
    assert validate("temperature_comparator", evidence) == evidence
    assert chart_title("temperature_comparator", evidence) == "40.2°C observed"


def test_source_url_whitespace_cannot_masquerade_as_provenance():
    evidence = deepcopy(EXAMPLES["temperature_comparator"])
    evidence["points"][0]["source"]["url"] = "https://example.invalid/not a URL"
    with pytest.raises(ValueError, match="Invalid source URL"):
        validate("temperature_comparator", evidence)


def test_variable_semantics_are_explicit_and_unsupported_variables_withheld():
    evidence = deepcopy(EXAMPLES["temperature_trajectory"])
    evidence["variable"] = "daily_minimum_temperature"
    assert validate("temperature_trajectory", evidence) == evidence
    assert "Daily minimum temperature" in chart_title("temperature_trajectory", evidence)
    assert "Variable: Daily minimum temperature" in build_alt_text("temperature_trajectory", evidence)
    evidence["variable"] = "relative_humidity"
    with pytest.raises(ValueError, match="Unsupported temperature variable"):
        validate("temperature_trajectory", evidence)
