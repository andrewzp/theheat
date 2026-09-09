"""Deterministic P06 regressions from forecast and record-progression audit findings."""
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.data import places, open_meteo, ocean, nsidc_snow
from src.data.temperature_evidence import daily_time, forecast_day, temperature_claim_failures
from src.data.world_thresholds import compute_city_thresholds, evaluate_city, CityThresholds
from src.orchestrator import world_cache
from src.two_bot.intern.temperature import build_all_time_record_bundle, build_monthly_high_bundle
from src.two_bot.fact_check import fact_check
from tests.temperature_helpers import provider_payload, snapshot, dated_forecast


@pytest.mark.parametrize("valid,zone,offset,start,end", [
    ("2026-01-01", "Etc/GMT-14", 50400, "2025-12-31T10:00:00Z", "2026-01-01T10:00:00Z"),
    ("2025-12-31", "Etc/GMT+12", -43200, "2025-12-31T12:00:00Z", "2026-01-01T12:00:00Z"),
    ("2024-02-29", "Asia/Kolkata", 19800, "2024-02-28T18:30:00Z", "2024-02-29T18:30:00Z"),
    ("2026-03-08", "America/New_York", -18000, "2026-03-08T05:00:00Z", "2026-03-09T04:00:00Z"),
])
def test_provider_local_day_preserves_year_leap_and_dst_boundaries(valid, zone, offset, start, end):
    result = daily_time(provider_payload({"daily": {"temperature_2m_max": [40]}}, valid, zone, offset), retrieved_at="2026-01-01T00:30:00Z")
    assert result["valid_date"] == valid
    assert result["valid_start"] == start and result["valid_end"] == end
    assert result["timezone"] == zone and result["utc_offset_seconds"] == offset
    assert result["issued_at"] is None and result["model_run"] is None


@pytest.mark.parametrize("change", [{"timezone": None}, {"timezone": "invalid"}, {"utc_offset_seconds": "0"}, {"daily": {"temperature_2m_max": [40]}}, {"daily": {"time": ["2026-02-30"]}}])
def test_missing_or_invalid_provider_time_is_not_retrieval_time(change):
    payload = provider_payload({"daily": {"temperature_2m_max": [40]}}, "2026-07-04")
    payload.update(change)
    with pytest.raises(ValueError):
        forecast_day(payload, retrieved_at="2026-07-04T23:00:00Z")


def baseline(city="Chennai", country="India", valid="2026-07-04", high=40.0):
    point = places.resolve_place(city, country)
    end = date.fromisoformat(valid) - timedelta(days=5)
    start = end.replace(year=end.year - 1) + timedelta(days=1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    daily = {"time": dates, "temperature_2m_max": [high] * len(dates), "temperature_2m_min": [20] * len(dates),
        "_provenance": {"requested_start": start.isoformat(), "requested_end": end.isoformat(), "timezone": "Asia/Kolkata", "retrieved_at": "2026-07-04T20:00:00Z"}}
    return point, compute_city_thresholds(city, daily, as_of=valid, years_of_data=1, country=country, lat=point["lat"], lon=point["lon"])



def test_date_and_scope_survive_forecast_detector_intern_and_review_hash():
    point, cached = baseline()
    forecast = forecast_day(provider_payload({"daily": {"temperature_2m_max": [40.3]}}, "2026-07-04", "Asia/Kolkata", 19800), retrieved_at="2026-07-03T23:30:00Z")
    result = evaluate_city("Chennai", "India", forecast, cached, lat=point["lat"], lon=point["lon"], today=date(2026, 7, 3))
    assert result.signal_date == date(2026, 7, 4)
    assert result.monthly_high.month == 7
    assert result.all_time_high.event_id.endswith("_2026-07-04")
    bundle = build_monthly_high_bundle(result.monthly_high)
    assert bundle.when == "2026-07-04"
    assert bundle.raw_signal_dump["evidence"]["timezone"] == "Asia/Kolkata"
    assert bundle.historical_context["baseline"]["variables"]["temperature_2m_max"]["cutoff"] == "2026-06-29"
    assert bundle.historical_context["baseline"]["variables"]["temperature_2m_max"]["complete"] is True
    assert result.monthly_high.years_of_data == 1  # one sampled year is not a complete 30-year record


@pytest.mark.parametrize("city,country,new,old,valid,text", [
    ("Chennai", "India", 40.3, 40.0, "2026-07-04", "Chennai, India hit 40.3°C (105°F) on July 4 — a new July high in 30 years of records, 0.3°C above the 2025 mark. July is peak monsoon season; when heat exceeds 40°C in that humidity, the wet-bulb load compounds the raw temperature far beyond what the number alone suggests."),
    ("Bishkek", "Kyrgyzstan", 40.2, 40.1, "2026-07-17", "Bishkek, Kyrgyzstan hit 40.2°C (104°F) on July 17 — edging the previous 30-year archive high of 40.1°C set earlier this same year. A Central Asian capital in a continental interior basin: the Tian Shan ring the city and trap summer heat with little airflow to release it."),
])
def test_exact_retained_forecast_to_observed_copies_fail_before_any_model(city, country, new, old, valid, text, monkeypatch):
    point, cached = baseline(city, country, valid, old)
    forecast = dated_forecast({"max_c": new}, valid)
    event = evaluate_city(city, country, forecast, cached, lat=point["lat"], lon=point["lon"]).all_time_high
    bundle = build_all_time_record_bundle(event)
    model = Mock(side_effect=AssertionError("known evidence-type defect must not reach model"))
    monkeypatch.setattr("src.two_bot.fact_check._call_gemini", model)
    result = fact_check(text, [], bundle, {})
    assert not result.passed and any("forecast" in row for row in result.failures)
    model.assert_not_called()
    # Numerical observations and publication-time payloads were not recovered;
    # this synthetic comparator fixture proves evidence-type refusal only.
    assert not temperature_claim_failures(f"Forecast high for {city}: {new}°C on {valid}.", bundle)


def test_missing_low_samples_never_borrow_high_coverage_or_zero_baseline():
    point = places.resolve_place("Chennai", "India")
    dates = [f"2025-07-{day:02d}" for day in range(1, 32)]
    archive = {"time": dates, "temperature_2m_max": [30.0] * 31, "temperature_2m_min": [None] * 31}
    cached = compute_city_thresholds("Chennai", archive, as_of="2026-07-04", country="India", lat=point["lat"], lon=point["lon"])
    assert cached.monthly_mean["07"] == (30.0, None, 31, 0)
    result = evaluate_city("Chennai", "India", dated_forecast({"max_c": 48, "min_c": -20}, "2026-07-04"), cached, lat=point["lat"], lon=point["lon"])
    assert result.anomaly_hot is not None
    assert result.anomaly_cold is None and result.all_time_low is None


def test_nonfinite_and_future_archive_values_cannot_set_comparator():
    cached = compute_city_thresholds("X", {"time": ["2025-07-01", "2025-07-02", "2026-07-04", "2027-07-01"], "temperature_2m_max": [40, float("nan"), 99, 999]}, as_of="2026-07-04")
    assert cached.all_time_max == (40, 2025)
    assert cached.baseline["variables"]["temperature_2m_max"]["sample_count"] == 1


def test_extreme_forecast_then_cooling_never_changes_accepted_archive():
    point, cached = baseline()
    key = places.cache_key(point["city"], point["country"], point["lat"], point["lon"])
    cache = {key: cached.to_dict()}
    original = deepcopy(cache)
    for value in (48, 38):
        result = evaluate_city(point["city"], point["country"], dated_forecast({"max_c": value}, "2026-07-04"), cached, lat=point["lat"], lon=point["lon"])
        world_cache.apply_provisional(cache, result, today="2026-07-04")
        world_cache.apply_provisional_preserving_as_of(cache, result, today="2026-07-04", advance_as_of=True, ttl_days=30)
    assert cache == original


def test_corrected_whole_archive_can_move_down_and_survives_reverse_merge():
    point, base = baseline()
    key = places.cache_key(point["city"], point["country"], point["lat"], point["lon"])
    before = base.to_dict()
    later = snapshot({**before, "all_time_max": [39, 2025]})
    later["baseline"]["retrieved_at"] = "2026-07-04T21:00:00Z"
    a = world_cache.merge_caches({key: before}, {key: later})
    b = world_cache.merge_caches({key: later}, {key: before})
    assert a == b and a[key]["all_time_max"] == [39, 2025]
    assert a["_meta"]["baseline_revisions"]


def test_same_time_conflicting_archives_quarantine_until_later_source_read():
    point, base = baseline()
    key = places.cache_key(point["city"], point["country"], point["lat"], point["lon"])
    before = base.to_dict()
    other = snapshot({**before, "all_time_max": [39, 2025]})
    other["baseline"]["retrieved_at"] = before["baseline"]["retrieved_at"]
    conflicted = world_cache.merge_caches({key: before}, {key: other})
    assert key not in conflicted
    assert key not in world_cache.merge_caches(conflicted, {key: before})
    later = deepcopy(other)
    later["baseline"]["retrieved_at"] = "2026-07-04T21:00:00Z"
    assert world_cache.merge_caches(conflicted, {key: later})[key] == later


def test_country_mixed_local_dates_and_missing_variable_are_not_one_record():
    rows = [open_meteo.ExtremeSignalBundle(city=city, country="Spain", today_max_c=45, archive_max_c=40, archive_max_year=2020,
        signal_date=day) for city, day in (("Madrid", date(2026, 7, 1)), ("Barcelona", date(2026, 6, 30)))]
    assert open_meteo.detect_country_records(rows) == []
    rows[1].signal_date = rows[0].signal_date
    rows[1].archive_max_c = None
    assert open_meteo.detect_country_records(rows) == []


def test_hot10_uses_each_city_provider_month_and_rejects_undated_reading():
    point = places.resolve_place("Chennai", "India")
    row = open_meteo.CityTemp(point["city"], point["country"], point["lat"], point["lon"], 40, signal_date=date(2026, 2, 28))
    key = places.event_location_key(point["city"], point["country"], point["lat"], point["lon"])
    assert open_meteo.compute_anomalies([row], {key: {1: 10, 2: 30}})[0].anomaly_c == 10
    row.signal_date = None
    assert open_meteo.compute_anomalies([row], {key: {1: 10, 2: 30}}) == []


def test_incomplete_high_and_current_low_are_qualified_independently():
    point, cached = baseline()
    cached.baseline["variables"]["temperature_2m_max"]["complete"] = False
    result = evaluate_city(point["city"], point["country"], dated_forecast({"max_c": 48, "min_c": 0}, "2026-07-04"), cached, lat=point["lat"], lon=point["lon"])
    assert result.all_time_high is None and result.archive_max_c is None
    assert result.all_time_low is not None and result.archive_min_c == 20
    assert result.evidence["comparison"]["high"]["reason"] == "incomplete_variable_archive"


def test_complete_but_stale_archive_does_not_skip_intervening_accepted_values():
    point, cached = baseline(valid="2026-07-04")
    result = evaluate_city(point["city"], point["country"], dated_forecast({"max_c": 48}, "2026-07-17"), cached, lat=point["lat"], lon=point["lon"])
    assert result.all_time_high is None and result.monthly_high is None
    assert result.evidence["comparison"]["high"]["reason"] == "unreconciled_archive_cutoff"
    # A new source snapshot reconciles the intervening value. No tweet is required
    # for an accepted record to enter the comparator.
    _, current = baseline(valid="2026-07-17", high=49)
    result = evaluate_city(point["city"], point["country"], dated_forecast({"max_c": 48}, "2026-07-17"), current, lat=point["lat"], lon=point["lon"])
    assert result.all_time_high is None and result.archive_max_c == 49


def test_record_wording_requires_named_reanalysis_and_exact_cutoff():
    point, cached = baseline()
    event = evaluate_city(point["city"], point["country"], dated_forecast({"max_c": 41}, "2026-07-04"), cached, lat=point["lat"], lon=point["lon"]).all_time_high
    bundle = build_all_time_record_bundle(event)
    assert temperature_claim_failures("Chennai is forecast to reach a new archive high of 41°C.", bundle)
    assert not temperature_claim_failures("Chennai's forecast high of 41°C would exceed the ERA5 reanalysis archive high through 2026-06-29; the intervening days remain unverified.", bundle)
    assert temperature_claim_failures("Chennai's forecast 41°C would set a national record in ERA5 reanalysis through 2026-06-29.", bundle)


def test_returned_grid_is_retained_separately_from_requested_point():
    payload = provider_payload({"latitude": 13.0, "longitude": 80.25, "elevation": 24,
        "daily_units": {"temperature_2m_max": "°C"}, "daily": {"temperature_2m_max": [41]}}, "2026-07-04")
    forecast = forecast_day(payload)
    point, cached = baseline()
    result = evaluate_city(point["city"], point["country"], forecast, cached, lat=point["lat"], lon=point["lon"])
    assert result.evidence["provider_grid"] == {"latitude": 13.0, "longitude": 80.25, "elevation": 24}
    assert result.evidence["requested_sampling_point"] == {"latitude": point["lat"], "longitude": point["lon"]}
    assert result.evidence["provider_units"] == {"temperature_2m_max": "°C"}
    assert result.evidence["uncertainty"] is None


@pytest.mark.parametrize("field,value", [("variables", None), ("variables", []), ("retrieved_at", 17), ("requested_end", "not a date"), ("revision_id", None)])
def test_malformed_baseline_is_quarantined_idempotently(field, value):
    point, cached = baseline()
    row = cached.to_dict()
    row["baseline"][field] = value
    key = places.cache_key(point["city"], point["country"], point["lat"], point["lon"])
    original = deepcopy(row)
    once = world_cache.migrate_cache({key: row})
    assert key not in once and once["_meta"]["quarantined_count"] == 1
    assert once == world_cache.migrate_cache(once) and row == original


def test_pre_p06_identity_qualified_but_forecast_mutable_cache_is_not_certified():
    point, cached = baseline()
    row = cached.to_dict()
    row.pop("baseline")
    row["identity"]["source_product"] = "openmeteo-archive-daily-v1"
    key = places.cache_key(point["city"], point["country"], point["lat"], point["lon"])
    assert key not in world_cache.migrate_cache({key: row})


def test_three_concurrent_archive_conflicts_keep_every_version():
    point, cached = baseline()
    key = places.cache_key(point["city"], point["country"], point["lat"], point["lon"])
    a = cached.to_dict()
    b, c = deepcopy(a), deepcopy(a)
    b["baseline"]["revision_id"], c["baseline"]["revision_id"] = "b" * 64, "c" * 64
    b["all_time_max"], c["all_time_max"] = [39, 2025], [38, 2025]
    ab = world_cache.merge_caches({key: a}, {key: b})
    ac = world_cache.merge_caches({key: a}, {key: c})
    merged = world_cache.merge_caches(ab, ac)
    assert key not in merged
    assert len(merged["_meta"]["baseline_conflicts"][key]["versions"]) == 3
    assert merged == world_cache.merge_caches(ac, ab)


@pytest.mark.parametrize("status,unknown", [("posted", False), ("approved", True)])
def test_world_source_revision_links_preserve_published_and_unknown_objects(status, unknown):
    from src.data.world_temperature_history import record_baseline_revision
    point, cached = baseline()
    old = cached.to_dict()
    new = deepcopy(old)
    new["all_time_max"] = [39, 2025]
    new["baseline"]["revision_id"] = "a" * 64
    draft = {"id": "d", "event_id": "e", "status": status, "text": "Exact original copy", "review_context": {"two_bot": {"bundle": {"raw_signal_dump": {"evidence": {"baseline": old["baseline"], "valid_date": "2026-07-04"}}}}}}
    if status == "posted":
        draft["tweet_id"] = "receipt"
    state = {"drafts": [draft], "publish_ledger": {"e": {"phase": "unknown", "text": draft["text"]}} if unknown else {}}
    original = deepcopy(state)
    record_baseline_revision(state, "point", old, new)
    assert state["drafts"] == original["drafts"] and state["publish_ledger"] == original["publish_ledger"]
    assert {r["kind"] for r in state["temperature_history"].values()} == {"baseline_revision", "affected_claim"}
    first = deepcopy(state["temperature_history"])
    record_baseline_revision(state, "point", old, new)
    assert state["temperature_history"] == first


def test_marine_provider_date_survives_fetch_detection_and_intern(monkeypatch):
    from src.two_bot.intern.marine import build_extreme_wave_bundle
    payload = provider_payload({"daily": {"wave_height_max": [14], "sea_surface_temperature_mean": [26]}}, "2026-01-01", "Etc/GMT-14", 50400)
    monkeypatch.setattr(ocean, "OCEAN_POINTS", [(0, 179, "Date Line", "Pacific")])
    monkeypatch.setattr(ocean, "fetch_with_retry", lambda *args, **kwargs: SimpleNamespace(json=lambda: payload))
    reading = ocean.fetch_ocean_conditions(strict=True)[0]
    event = ocean.detect_extreme_waves([reading])[0]
    bundle = build_extreme_wave_bundle(event)
    assert bundle.when == "2026-01-01" and bundle.event_id.endswith("_2026-01-01")
    assert bundle.raw_signal_dump["evidence"]["valid_start"] == "2025-12-31T10:00:00Z"
    assert {r["label"]: r["value"] for r in bundle.current_facts}["evidence_type"] == "forecast"


@pytest.mark.parametrize("valid", [None, "2026-02-30"])
def test_snow_missing_or_invalid_valid_date_never_becomes_retrieval_today(monkeypatch, valid):
    from src.data.source_status import SourceFetchError
    payload = {"metadata": {"last_date_with_data": valid}, "data": [{"name": "Snow point", "lat": 40, "lon": -110}]}
    monkeypatch.setattr(nsidc_snow, "fetch_with_cache_revalidation", lambda *args, **kwargs: SimpleNamespace(json=lambda: payload))
    with pytest.raises(SourceFetchError, match="provider valid date"):
        nsidc_snow.fetch_snow_today(strict=True)


def test_normals_actual_period_survives_to_per_city_hot10_evidence(tmp_path):
    import csv
    point = places.resolve_place("Chennai", "India")
    path = tmp_path / "qualified_normals.csv"
    row = {**point, "month": 7, "avg_high_c": 30, "source_product": "meteostat-normals-point-v1", "period_start": 1961, "period_end": 1990, "retrieved_at": "2026-07-04T00:00:00Z"}
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    normals = open_meteo.load_normals(str(path))
    reading = open_meteo.CityTemp(point["city"], point["country"], point["lat"], point["lon"], 40, signal_date=date(2026, 7, 4), evidence=dated_forecast({"max_c": 40}, "2026-07-04")["evidence"])
    result = open_meteo.compute_anomalies([reading], normals)[0]
    assert result.anomaly_c == 10
    assert result.evidence["baseline"]["period_start"] == 1961
    assert result.evidence["baseline"]["period_end"] == 1990
    assert result.evidence["baseline"]["coverage_fraction"] is None


def test_aggregate_member_forecast_evidence_is_preserved_but_not_certified(monkeypatch):
    from src.orchestrator.sources.open_meteo import _cluster_member_row
    from src.two_bot.intern.temperature import build_simultaneous_records_bundle
    from src.two_bot.evidence_contract import audit_story_bundle

    point, cached = baseline()
    event = evaluate_city(point['city'], point['country'], dated_forecast({'max_c': 41}, '2026-07-04'), cached, lat=point['lat'], lon=point['lon']).all_time_high
    row = _cluster_member_row(event, 'all_time', '2026-07-04')
    assert row['evidence'] == event.evidence
    row['evidence']['comparison']['high']['eligible'] = False
    assert event.evidence['comparison']['high']['eligible'] is True
    bundle = build_simultaneous_records_bundle([row], event_id='simultaneous_test', when='2026-07-04')
    assert bundle.raw_signal_dump['stations'][0]['evidence']['evidence_type'] == 'forecast'
    assert bundle.raw_signal_dump['temperature_aggregate_review']['status'] == 'withheld'
    audit = audit_story_bundle(bundle)
    assert not audit.prompt_ready
    assert 'temperature_aggregate_unqualified' in {issue.code for issue in audit.issues}
    model = Mock(side_effect=AssertionError('unqualified aggregate must not reach model'))
    monkeypatch.setattr('src.two_bot.fact_check._call_gemini', model)
    assert not fact_check('Chennai hit a new record of 41°C.', [], bundle, {}).passed
    model.assert_not_called()
    # Removing the visible projection cannot turn missing aggregation evidence
    # into authorization; readiness rechecks the source structure.
    bundle.raw_signal_dump.pop('temperature_aggregate_review')
    assert not audit_story_bundle(bundle).prompt_ready


@pytest.mark.parametrize('kind,raw', [
    ('record_streak', {'event_id': 'streak', 'consecutive_days': 3, 'peak_temp_c': 41}),
    ('heat_records_cluster', {'event_id': 'cluster', 'stations': [{'observed': True}]}),
    ('synthesis_fire_drought_heat', {'event_id': 'synth', 'components': [{'kind': 'heat', 'peak_value_c': 41}]}),
])
def test_reduced_temperature_aggregates_withhold_before_writing_with_retained_reason(kind, raw):
    from src.two_bot.types import StoryBundle
    from src.orchestrator.triage_queue import _enqueue_story_candidate
    from src.state import _fresh_state
    bundle = StoryBundle(kind, 'Somewhere', '2026-07-04', raw['event_id'], {'label': 'count', 'value': 3}, [{'label': 'count', 'value': 3}], raw_signal_dump=raw)
    state = _fresh_state()
    assert not _enqueue_story_candidate(state, bundle=bundle, score={'total': 80, 'threshold': 70}, source='open_meteo_extreme_signals', legacy_type=kind, event_id=bundle.event_id, review_context={})
    assert not state.get('_triage_queue')
    assert bundle.raw_signal_dump['temperature_aggregate_review']['reasons']
    assert any(issue["code"] == "temperature_aggregate_unqualified" for row in state["suppressions"] for issue in row.get("evidence_readiness", {}).get("issues", []))


def test_temperature_aggregate_containment_does_not_relabel_unrelated_reanalysis_or_marine():
    from src.two_bot.types import StoryBundle
    from src.data.temperature_evidence import temperature_aggregate_failures
    for kind, raw in [
        ('regional_anomaly', {'evidence': {'domain': 'temperature', 'evidence_type': 'reanalysis', 'source_product': 'ERA5'}}),
        ('synthesis_marine_compound', {'components': [{'kind': 'coral'}, {'kind': 'sst_anomaly'}]}),
    ]:
        bundle = StoryBundle(kind, 'Region', '2026-07-04', 'e', {'label': 'value', 'value': 1}, [{'label': 'value', 'value': 1}], raw_signal_dump=raw)
        assert not temperature_aggregate_failures(bundle)
        assert 'temperature_aggregate_review' not in bundle.raw_signal_dump


def test_sparse_wetbulb_baseline_does_not_borrow_high_low_qualification():
    point, cached = baseline()
    cached.wetbulb_max = (30, 2025)
    wet = cached.baseline['variables']['wet_bulb_temperature_2m_max']
    wet.update(sample_count=1, years_with_samples=1, cutoff='2026-06-29', complete=False)
    result = evaluate_city(point['city'], point['country'], dated_forecast({'max_c': 40, 'tw_max_c': 33}, '2026-07-04'), cached, lat=point['lat'], lon=point['lon'])
    event = result.wet_bulb_extreme
    assert event.daily_max_tw_c == 33  # Qualified current absolute tier remains.
    assert event.archive_max_tw_c is event.archive_max_year is event.archive_years is None
    assert result.evidence['comparison']['withheld_record_variables']['wet_bulb_temperature_2m_max'] == 'incomplete_variable_archive'


def test_anomaly_archive_years_remain_independent_for_high_and_low():
    point, cached = baseline()
    cached.baseline['requested_years'] = 30
    cached.years_of_data = 30
    cached.baseline['variables']['temperature_2m_max']['years_with_samples'] = 30
    cached.baseline['variables']['temperature_2m_min']['years_with_samples'] = 1
    cached.monthly_mean['07'] = (30, 20, 900, 31)
    result = evaluate_city(point['city'], point['country'], dated_forecast({'max_c': 48, 'min_c': 0}, '2026-07-04'), cached, lat=point['lat'], lon=point['lon'])
    assert result.anomaly_hot.years_of_data == 30
    assert result.anomaly_cold.years_of_data == 1


def test_sampled_network_country_record_requires_member_source_cutoffs_and_scoped_wording():
    from src.two_bot.intern.temperature import build_country_record_bundle
    rows = []
    for city, station, cutoff in [('A', 'station1', '2026-06-23'), ('B', 'station2', '2026-06-24')]:
        rows.append(open_meteo.ExtremeSignalBundle(city=city, country='US', station_id=station, signal_date=date(2026, 6, 25), today_max_c=40, archive_max_c=35, archive_max_year=2020,
            evidence={'domain': 'temperature', 'evidence_type': 'observed', 'source_product': 'noaa-ghcn-daily-v2', 'valid_date': '2026-06-25', 'baseline': {'variables': {'temperature_2m_max': {'verified_source_cutoff': cutoff, 'years_with_samples': 20}}}}))
    event = open_meteo.detect_country_records(rows)[0]
    bundle = build_country_record_bundle(event)
    assert temperature_claim_failures('The US hit an official national record of 40°C.', bundle)
    assert temperature_claim_failures('The sampled network of GHCN stations hit an archive high of 40°C in accepted GHCN observations through 2026-06-24.', bundle)
    assert not temperature_claim_failures('The sampled network of GHCN stations hit an archive high of 40°C in accepted GHCN observations through 2026-06-23 and 2026-06-24.', bundle)


@pytest.mark.parametrize('change,expected_invalidated', [('complete_revision', True), ('missing_source_cell', False), ('unknown_grid', False), ('advancing_interval', False)])
def test_world_comparator_findings_revoke_only_verified_same_source_revisions(change, expected_invalidated):
    from src.data.world_temperature_history import record_baseline_revision
    point, cached = baseline()
    old = cached.to_dict()
    old['baseline']['provider_grid'] = {'latitude': 13.0, 'longitude': 80.25}
    new = deepcopy(old)
    new['all_time_max'] = [39, 2025]
    new['baseline']['revision_id'] = 'b' * 64
    new['baseline']['retrieved_at'] = '2026-07-04T21:00:00Z'
    if change == 'missing_source_cell':
        new['baseline']['variables']['temperature_2m_max']['complete'] = False
    elif change == 'unknown_grid':
        old['baseline']['provider_grid'] = new['baseline']['provider_grid'] = None
    elif change == 'advancing_interval':
        new['baseline']['requested_end'] = '2026-06-30'
    draft = {'id': 'd', 'event_id': 'e', 'status': 'approved', 'text': 'Exact original copy', 'review_context': {'two_bot': {'bundle': {'raw_signal_dump': {'evidence': {'baseline': deepcopy(old['baseline']), 'valid_date': '2026-07-04'}}}}}}
    state = {'drafts': [deepcopy(draft)], 'publish_ledger': {}}
    record_baseline_revision(state, 'point', old, new)
    assert (state['drafts'][0]['status'] == 'pending') is expected_invalidated
    assert state['drafts'][0]['text'] == draft['text']
    findings = [row for row in state['temperature_history'].values() if row['kind'] == 'affected_claim']
    assert len(findings) == 1
    if not expected_invalidated:
        assert state['drafts'] == [draft]
        assert findings[0]['details']['historical_correctness'] == 'not_determined'


def test_qualified_wetbulb_comparator_uses_its_own_coverage_years():
    point, cached = baseline()
    cached.wetbulb_max = (30, 2025)
    cached.baseline['requested_years'] = 30
    cached.baseline['variables']['temperature_2m_max']['years_with_samples'] = 30
    cached.baseline['variables']['wet_bulb_temperature_2m_max'] = {
        **deepcopy(cached.baseline['variables']['temperature_2m_min']), 'years_with_samples': 1,
    }
    result = evaluate_city(point['city'], point['country'], dated_forecast({'max_c': 40, 'tw_max_c': 33}, '2026-07-04'), cached, lat=point['lat'], lon=point['lon'])
    event = result.wet_bulb_extreme
    assert event.archive_max_tw_c == 30 and event.archive_max_year == 2025
    assert event.archive_years == 1
