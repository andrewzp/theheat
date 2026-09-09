"""Real local source parsing/qualification over explicitly engineered weather."""
from copy import deepcopy
from datetime import date

import pytest

from src.data.temperature_evidence import fingerprint as source_fingerprint
from src.data import ghcn
from src.data.ghcn_format import DailyObs
from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import build_alt_text, chart_title, validate_graphic
from src.media.temperature_graphic_adapter import story_bundle_snapshot, temperature_graphic_spec
from src.two_bot.intern import build_all_time_record_bundle
from tests.ghcn_graphic_helpers import STATION, graphic_bundles, source_archive


@pytest.fixture(scope="module")
def stories():
    return graphic_bundles()


def hashes(bundles):
    return [fingerprint(story_bundle_snapshot(bundle)) for bundle in bundles]


def adapt(bundles, template="temperature_comparator", expected=None):
    return temperature_graphic_spec(template, bundles, expected_bundle_sha256=hashes(bundles) if expected is None else expected, synthetic=True)


def reseal(bundle):
    evidence = bundle.raw_signal_dump["evidence"]
    evidence["revision_id"] = source_fingerprint({key: value for key, value in evidence.items() if key not in {"retrieved_at", "revision_id"}})
    bundle.historical_context["baseline"] = deepcopy(evidence["baseline"])


@pytest.mark.parametrize("direction", ["high", "low"])
@pytest.mark.parametrize("tier", ["all_time", "monthly", "calendar"])
def test_source_qualified_comparison_uses_exact_candidate_and_per_tier_warrant(direction, tier):
    bundles = graphic_bundles(direction=direction, tier=tier)[-1:]
    before = deepcopy(story_bundle_snapshot(bundles[0]))
    spec = adapt(bundles)
    evidence = spec["evidence"]
    baseline = evidence["baseline"]
    assert evidence["points"][0]["value"] == bundles[0].headline_metric["value"]
    assert baseline["point"]["value"] == bundles[0].historical_context["prior_record_c"]
    assert baseline["cutoff"] == "2026-09-07"
    assert baseline["source_missing_count"] == baseline["source_qc_rejected_count"] == 1
    assert baseline["source_calendar_count"] > baseline["accepted_sample_count"]
    assert "accepted GHCN" in baseline["scope"] and "no official record" in baseline["scope"]
    assert "record" not in chart_title(spec["template"], evidence).lower()
    assert evidence["variable"] == ("daily_maximum_temperature" if direction == "high" else "daily_minimum_temperature")
    bound = evidence["input_binding"]["bundles"][0]
    assert bound["bundle"] == before == story_bundle_snapshot(bundles[0])
    assert bound["bundle_sha256"] == fingerprint(before)
    assert bound["source_baseline_payload_sha256"] == fingerprint(before["raw_signal_dump"]["evidence"]["baseline"])
    assert validate_graphic(spec["template"], evidence, expected_evidence_sha256=spec["expected_evidence_sha256"]) == evidence


def test_trajectory_contains_only_six_individually_qualified_consecutive_source_dates(stories):
    spec = adapt(stories, "temperature_trajectory")
    evidence = spec["evidence"]
    assert evidence["baseline"] is None
    assert [point["valid_date"] for point in evidence["points"]] == [story.when for story in stories]
    assert [point["value"] for point in evidence["points"]] == [story.headline_metric["value"] for story in stories]
    assert all("valid_time" not in point and point["evidence_type"] == "observed" for point in evidence["points"])
    assert len(evidence["input_binding"]["bundles"]) == 6
    alt = build_alt_text(spec["template"], evidence)
    assert "reporting interval and timezone are unknown" in alt
    assert "no implied UTC observation time" in alt
    assert "SYNTHETIC DEMONSTRATION; no actual weather" in alt


def test_comparator_mutation_cannot_follow_the_callers_original_trusted_binding(stories):
    original = hashes(stories[:1])
    changed = deepcopy(stories[0])
    changed.raw_signal_dump["old_record_c"] -= 10
    changed.historical_context["prior_record_c"] -= 10
    changed.historical_context["margin_c"] += 10
    changed.raw_signal_dump["evidence"]["baseline"]["variables"]["temperature_2m_max"]["record_values_c"]["all_time"] -= 10
    reseal(changed)
    with pytest.raises(ValueError, match="obsolete input bundle binding"):
        adapt([changed], expected=original)


@pytest.mark.parametrize("change", [
    "no_evidence", "legacy", "forecast", "grid", "unit", "headline_unit", "headline_type", "value",
    "qflag", "qflag_absent", "source_hash", "source_hash_shape", "candidate_accepted", "source_gap",
    "source_cutoff", "calendar_count", "sample_bool", "missing_count", "thin_years", "completeness",
    "prior_value", "prior_date", "prior_year", "future_observed", "timezone", "reporting_interval",
    "event_station", "kind", "historical_projection", "fact_projection", "location", "revision", "boolean_prior",
])
def test_legacy_unqualified_or_contradictory_inputs_are_refused_even_with_a_new_bundle_hash(stories, change):
    bundle = deepcopy(stories[-1])
    raw = bundle.raw_signal_dump
    evidence = raw["evidence"]
    scope = evidence["baseline"]["variables"]["temperature_2m_max"]
    if change == "no_evidence":
        del raw["evidence"]
    elif change == "legacy":
        evidence["baseline"]["schema_version"] = 1
    elif change == "forecast":
        evidence["evidence_type"] = "forecast"
    elif change == "grid":
        evidence["source_product"] = "openmeteo-era5-daily-v2"
    elif change == "unit":
        evidence["unit"] = "F"
    elif change == "headline_unit":
        bundle.headline_metric["unit"] = "F"
    elif change == "headline_type":
        bundle.headline_metric["label"] = "forecast_high_c"
    elif change == "value":
        raw["new_temp_c"] += 1
    elif change == "qflag":
        evidence["variables"]["TMAX"]["qflag"] = "S"
    elif change == "qflag_absent":
        del evidence["variables"]["TMAX"]["qflag"]
    elif change == "source_hash":
        evidence["variables"]["TMAX"]["source_payload_sha256"] = "a" * 64
    elif change == "source_hash_shape":
        evidence["baseline"]["source_payload_sha256"] = "not-a-source-sha"
    elif change == "candidate_accepted":
        scope["candidate_accepted"] = False
    elif change == "source_gap":
        scope["source_coverage_complete"] = False
    elif change == "source_cutoff":
        scope["verified_source_cutoff"] = "2020-09-07"
    elif change == "calendar_count":
        scope["source_calendar_count"] -= 1
    elif change == "sample_bool":
        scope["sample_count"] = True
    elif change == "missing_count":
        scope["source_missing_count"] = 100
    elif change == "thin_years":
        scope["years_with_samples"] = 1
    elif change == "completeness":
        scope["complete"] = True
    elif change == "prior_value":
        raw["old_record_c"] += 1
    elif change == "prior_date":
        scope["record_dates"]["all_time"] = bundle.when
    elif change == "prior_year":
        raw["old_record_year"] -= 1
    elif change == "future_observed":
        evidence["retrieved_at"] = evidence["baseline"]["retrieved_at"] = "2026-09-01T12:00:00Z"
    elif change == "timezone":
        evidence["timezone"] = "UTC"
    elif change == "reporting_interval":
        evidence["valid_start"] = bundle.when + "T00:00:00Z"
    elif change == "event_station":
        bundle.event_id = raw["event_id"] = bundle.event_id.replace("USC99000001", "USC99000002")
    elif change == "kind":
        raw["kind"] = "low"
    elif change == "historical_projection":
        bundle.historical_context["margin_c"] += 2
    elif change == "fact_projection":
        bundle.current_facts.append({"label": "today_temp_c", "value": 55})
    elif change == "location":
        bundle.where = "Another place"
    elif change == "boolean_prior":
        raw["old_record_c"] = True
    if change != "no_evidence":
        reseal(bundle)
    if change == "revision":
        evidence["revision_id"] = "0" * 64
    with pytest.raises(ValueError):
        adapt([bundle])


@pytest.mark.parametrize("tier", ["monthly", "calendar"])
def test_period_coverage_and_calendar_identity_are_qualified_separately(tier):
    bundle = graphic_bundles(tier=tier)[-1]
    scope = bundle.raw_signal_dump["evidence"]["baseline"]["variables"]["temperature_2m_max"]
    key = "09" if tier == "monthly" else "09-08"
    scope[f"{tier}_years"][key] = 1
    reseal(bundle)
    with pytest.raises(ValueError, match="period-specific"):
        adapt([bundle])


@pytest.mark.parametrize("change", ["value", "prior", "scope", "cutoff", "unit", "synthetic", "station", "input", "binding", "version", "instant", "binding_removed"])
def test_renderer_replays_adapter_projection_even_when_chart_hash_is_recomputed(stories, change):
    evidence = adapt(stories[-1:])["evidence"]
    if change == "value":
        evidence["points"][0]["value"] += 1
    elif change == "prior":
        evidence["baseline"]["point"]["value"] -= 1
    elif change == "scope":
        evidence["scope"] = "An official national record"
    elif change == "cutoff":
        evidence["baseline"]["cutoff"] = "2026-09-06"
    elif change == "unit":
        evidence["unit"] = evidence["points"][0]["unit"] = evidence["baseline"]["point"]["unit"] = "°F"
    elif change == "synthetic":
        evidence["synthetic"] = False
    elif change == "station":
        evidence["station_id"] = "USC99000002"
    elif change == "input":
        evidence["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["old_record_c"] -= 10
    elif change == "binding":
        evidence["input_binding"]["bundles"][0]["bundle_sha256"] = "f" * 64
    elif change == "version":
        evidence["input_binding"]["adapter_version"] = "later-unreviewed-adapter"
    elif change == "binding_removed":
        del evidence["input_binding"]
    else:
        evidence["points"][0]["valid_time"] = "2026-09-08T00:00:00Z"
    with pytest.raises(ValueError):
        validate_graphic("temperature_comparator", evidence, expected_evidence_sha256=fingerprint(evidence))


@pytest.mark.parametrize("indexes", [[0], [1, 0], [0, 0], [0, 2], list(range(6)) + [5, 5, 5]])
def test_trajectory_refuses_counts_gaps_duplicates_reordering_or_excess_points(stories, indexes):
    with pytest.raises(ValueError):
        adapt([stories[index] for index in indexes], "temperature_trajectory")


def test_trajectory_refuses_same_station_different_variables(stories):
    low = graphic_bundles(direction="low")[1]
    with pytest.raises(ValueError, match="variable or location changed"):
        adapt([stories[0], low], "temperature_trajectory")


@pytest.mark.parametrize("revised", [False, True])
def test_trajectory_refuses_mixed_retrieval_snapshots_and_real_source_corrections(stories, revised):
    lines = source_archive().decode().splitlines()
    if revised:
        for index, line in enumerate(lines):
            if line.startswith(STATION["station_id"] + "202609TMAX"):
                offset = 21 + 2 * 8  # September 3 cell, exact source format.
                assert line[offset:offset + 5] == "  402"
                lines[index] = line[:offset] + "  400" + line[offset + 5:]
                break
    snapshot = ghcn._archive_snapshot(STATION["station_id"], "\n".join(lines).encode(), "2026-09-09T12:05:00Z")
    observations = [DailyObs(STATION["station_id"], date(2026, 9, 4), "TMAX", 40.6)]
    thresholds, checked = ghcn._thresholds_from_verified_archive(STATION["station_id"], observations, snapshot)
    event = ghcn._detect_signals_for_station(STATION, checked, thresholds).all_time_high
    second = build_all_time_record_bundle(event, source="ghcn")
    assert second.raw_signal_dump["old_record_c"] == (40.0 if revised else 40.2)
    assert stories[0].headline_metric["value"] == 40.2
    with pytest.raises(ValueError, match="shared archive payload and retrieval snapshot"):
        adapt([stories[0], second], "temperature_trajectory")


def test_missing_last_baseline_day_remains_an_exclusion_with_two_distinct_cutoffs():
    lines = source_archive().decode().splitlines()
    for index, line in enumerate(lines):
        if line.startswith(STATION["station_id"] + "202609TMAX"):
            offset = 21 + 6 * 8  # Missing September7 cell in an otherwise complete source calendar.
            lines[index] = line[:offset] + "-9999" + line[offset + 5:]
            break
    snapshot = ghcn._archive_snapshot(STATION["station_id"], "\n".join(lines).encode(), "2026-09-09T12:00:00Z")
    obs = [DailyObs(STATION["station_id"], date(2026, 9, 8), "TMAX", 42.2)]
    thresholds, checked = ghcn._thresholds_from_verified_archive(STATION["station_id"], obs, snapshot)
    event = ghcn._detect_signals_for_station(STATION, checked, thresholds).all_time_high
    spec = adapt([build_all_time_record_bundle(event, source="ghcn")])
    baseline = spec["evidence"]["baseline"]
    assert baseline["cutoff"] == "2026-09-07"
    assert baseline["accepted_sample_cutoff"] == baseline["point"]["valid_date"] == "2026-09-06"
    assert baseline["source_missing_count"] == 2
    alt = build_alt_text(spec["template"], spec["evidence"])
    assert "Latest accepted sample: 2026-09-06; verified source-calendar cutoff: 2026-09-07" in alt


@pytest.mark.parametrize("kind", ["record_streak", "heat_records_cluster", "simultaneous_records", "country_high", "anomaly_hot"])
def test_unsupported_legacy_reductions_do_not_supply_a_graph(stories, kind):
    bundle = deepcopy(stories[0])
    bundle.signal_kind = kind
    with pytest.raises(ValueError):
        adapt([bundle])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "42.2", None])
def test_nonfinite_coerced_or_missing_candidate_refused(stories, value):
    bundle = deepcopy(stories[0])
    bundle.headline_metric["value"] = value
    with pytest.raises(ValueError):
        adapt([bundle])
