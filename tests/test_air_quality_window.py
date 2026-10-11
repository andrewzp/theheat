"""Invented source-to-writer window regressions; never call weather or model APIs."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.data import air_quality as source
from src.data import air_quality_contract as contract
from src.data.source_status import SourceFetchError
from src.two_bot import fact_check, writer
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.air_quality import build_dust_event_bundle, build_pm25_hazard_bundle
from src.two_bot.multisignal import attach_related_signals
from src.two_bot.scientific_claims import scientific_claim_failures
from src.two_bot.types import MemorySlice, RelatedSignal
from tests.air_quality_fixtures import payload, observation

DAY = "2026-06-08"
REQUESTED = DAY + "T12:00:00Z"
RETRIEVED = DAY + "T12:00:01Z"


def parse(data, day=DAY):
    return source._parse_single_location(data, "Lahore", "Pakistan", 31.5, 74.3, day,
                                        requested_at=day + "T12:00:00Z", retrieved_at=day + "T12:00:01Z")


def bundles():
    obs = observation(pm25=250., dust=2000., pm10_24h_mean=90.)
    return build_pm25_hazard_bundle(source.detect_pm25_hazard(obs)), build_dust_event_bundle(source.detect_dust_event(obs))


def test_complete_window_retains_hourly_values_and_computed_means():
    data = payload(day=DAY, pm10=90.)
    data["hourly"]["pm2_5"] = list(range(150, 174))
    data["hourly"]["dust"] = list(range(500, 524))
    before = deepcopy(data)
    obs = parse(data)
    assert obs.pm25_24h_mean == 161.5 and obs.dust_daily_max == 523
    event = source.detect_pm25_hazard(obs)
    bundle = build_pm25_hazard_bundle(event)
    assert audit_story_bundle(bundle).prompt_ready
    packet = bundle.raw_signal_dump["forecast_window"]
    assert packet["hours"] == before["hourly"]["time"]
    assert packet["series"]["pm2_5"]["values"] == list(range(150, 174))
    assert packet["valid_start"] == DAY + "T00:00:00Z"
    assert packet["valid_end"] == "2026-06-09T00:00:00Z"
    assert packet["evidence_type"] == "model_forecast"
    facts = {f["label"]: f["value"] for f in bundle.current_facts}
    assert "automatic domain" in facts["data_source"]
    assert "model_resolution_km" not in facts
    assert facts["valid_start"] == packet["valid_start"]
    assert data == before
    data["hourly"]["pm2_5"][0] = 999
    obs.forecast_window["series"]["pm2_5"]["values"][0] = 998
    assert event.forecast_window["series"]["pm2_5"]["values"][0] == 150
    event.forecast_window["series"]["pm2_5"]["values"][0] = 997
    assert packet["series"]["pm2_5"]["values"][0] == 150
    grid = deepcopy(facts["source_grid_location"])
    event.forecast_window["grid_location"][0] = 0
    assert facts["source_grid_location"] == packet["grid_location"] == grid


@pytest.mark.parametrize("case", ["two", "23", "25", "duplicate", "shifted", "yesterday", "tomorrow", "reversed", "suffix", "missing"])
def test_wrong_or_incomplete_day_is_not_redated(case):
    data = payload(day=DAY)
    times = data["hourly"]["time"]
    if case == "two":
        data["hourly"]["time"] = times[:2]
    elif case == "23":
        times.pop()
    elif case == "25":
        times.append("2026-06-09T00:00")
    elif case == "duplicate":
        times[5] = times[4]
    elif case == "shifted":
        times[5] = DAY + "T05:30"
    elif case in {"yesterday", "tomorrow"}:
        data["hourly"]["time"] = [t.replace(DAY, "2026-06-07" if case == "yesterday" else "2026-06-09") for t in times]
    elif case == "reversed":
        times.reverse()
    elif case == "suffix":
        times[0] += "extra"
    else:
        del data["hourly"]["time"]
    assert parse(data) is None


@pytest.mark.parametrize("timezone,offset,start", [
    ("Asia/Kolkata", 19800, "2026-06-07T18:30:00Z"),
    ("Asia/Kathmandu", 20700, "2026-06-07T18:15:00Z"),
    ("Pacific/Kiritimati", 50400, "2026-06-07T10:00:00Z"),
    ("America/New_York", -14400, "2026-06-08T04:00:00Z"),
])
def test_local_day_keeps_its_actual_utc_window(timezone, offset, start):
    obs = parse(payload(day=DAY, timezone=timezone, offset=offset))
    assert obs is not None and obs.forecast_window["valid_start"] == start
    assert obs.date == DAY and obs.forecast_window["timezone"] == timezone


@pytest.mark.parametrize("day,offset", [("2026-03-08", -18000), ("2026-11-01", -14400)])
def test_dst_calendar_day_cannot_be_a_24_hour_window(day, offset):
    assert parse(payload(day=day, timezone="America/New_York", offset=offset), day) is None


@pytest.mark.parametrize("timezone,offset", [("unknown/zone", 0), (None, 0), ("GMT", True), ("GMT", 3600)])
def test_missing_or_inconsistent_timezone_is_withheld(timezone, offset):
    assert parse(payload(day=DAY, timezone=timezone, offset=offset)) is None


@pytest.mark.parametrize("variable", ["pm2_5", "pm10", "dust", "aerosol_optical_depth", "us_aqi"])
@pytest.mark.parametrize("bad", [None, True, float("nan"), float("inf"), -1., "100"])
def test_incomplete_or_invalid_variable_does_not_fabricate_a_daily_value(variable, bad):
    data = payload(day=DAY, pm10=90.)
    data["hourly"][variable][7] = bad
    obs = parse(data)
    assert obs is not None
    values = contract.validate_window(obs.forecast_window)
    assert values[variable] is None
    assert values["dust" if variable != "dust" else "pm2_5"] is not None
    if variable == "pm10":
        event = source.detect_dust_event(obs)
        bundle = build_dust_event_bundle(event)
        assert event.pm10_24h_mean is event.who_pm10_multiple is None
        assert audit_story_bundle(bundle).prompt_ready
        assert "who_pm10_multiple" not in {f["label"] for f in bundle.current_facts}


def test_zero_is_data_but_missing_both_primary_variables_is_unavailable():
    obs = parse(payload(day=DAY, pm25=0., dust=0., pm10=0.))
    assert obs is not None and obs.pm25_24h_mean == obs.dust_daily_max == obs.pm10_24h_mean == 0
    assert source.detect_pm25_hazard(obs) is source.detect_dust_event(obs) is None
    assert parse(payload(day=DAY, pm25=None, dust=None)) is None


@pytest.mark.parametrize("case", ["unit", "short", "long", "missing"])
def test_unavailable_pm10_never_supplies_a_who_comparison(case):
    data = payload(day=DAY, pm10=90.)
    if case == "unit":
        data["hourly_units"]["pm10"] = "mg/m³"
    elif case == "short":
        data["hourly"]["pm10"].pop()
    elif case == "long":
        data["hourly"]["pm10"].append(90.)
    else:
        del data["hourly"]["pm10"]
    event = source.detect_dust_event(parse(data))
    assert event is not None and event.pm10_24h_mean is event.who_pm10_multiple is None


@pytest.mark.parametrize("field", ["date", "hours", "series", "timezone", "grid_location", "retrieved_at", "source_product", "selected_record_sha256"])
def test_packet_alteration_blocks_both_provider_entry_points(field, monkeypatch):
    b, _ = bundles()
    b.raw_signal_dump["forecast_window"][field] = "changed"
    audit = audit_story_bundle(b)
    assert not audit.prompt_ready
    assert "air_quality_window_unqualified" in {i.code for i in audit.issues}
    writer_call, checker_call = Mock(), Mock()
    monkeypatch.setattr(writer, "_call_writer_provider", writer_call)
    monkeypatch.setattr(fact_check, "_call_gemini", checker_call)
    assert writer.write_tweet(b, MemorySlice()).tweet is None
    assert not fact_check.fact_check("A model forecast is available.", [], b, {}).passed
    writer_call.assert_not_called()
    checker_call.assert_not_called()


@pytest.mark.parametrize("field,value", [("pm25_24h_mean", 251.), ("who_multiple", 99.), ("tier", True),
                                        ("date", "2026-06-09"), ("city", "Another City"), ("lat", 1.)])
def test_event_values_cannot_detach_from_window(field, value):
    b, _ = bundles()
    b.raw_signal_dump[field] = value
    assert not audit_story_bundle(b).prompt_ready


def test_legacy_scalar_evidence_remains_retained_but_unqualified():
    b, _ = bundles()
    del b.raw_signal_dump["forecast_window"]
    before = deepcopy(b.to_dict())
    assert not audit_story_bundle(b).prompt_ready
    assert b.to_dict() == before


def test_model_and_station_annotation_never_make_the_forecast_mean_observed():
    event = source.detect_pm25_hazard(observation())
    event = replace(event, evidence_grade="model_corroborated_by_station", station_name="Invented station",
                    station_pm25_ug_m3=160., station_distance_km=4.)
    b = build_pm25_hazard_bundle(event)
    assert audit_story_bundle(b).prompt_ready
    assert any("forecast_as_observation" in x for x in scientific_claim_failures("Lahore recorded 150 μg/m³.", b))
    assert not scientific_claim_failures("CAMS estimates a daily mean of 150 μg/m³.", b)
    assert fact_check.local_rejection("A model forecast is available.", [], b, {}) is None


def test_related_air_quality_keeps_detached_complete_evidence_and_rejects_mutation():
    a, b = bundles()
    queue = [SimpleNamespace(event_id=v.event_id, bundle=v, score=SimpleNamespace(total=80)) for v in (a, b)]
    attach_related_signals(queue)
    assert len(a.related_signals) == 1
    assert a.related_signals[0].air_quality_evidence == b.raw_signal_dump
    assert audit_story_bundle(a).prompt_ready
    b.raw_signal_dump["forecast_window"]["series"]["dust"]["values"][0] = 999
    assert audit_story_bundle(a).prompt_ready  # detached before source mutation
    a.related_signals[0].headline_metric["value"] = 999
    assert not audit_story_bundle(a).prompt_ready


def test_legacy_related_aq_cannot_bypass_the_primary_window_gate():
    a, b = bundles()
    a.related_signals = [RelatedSignal(b.event_id, b.signal_kind, b.where, b.when, b.headline_metric, b.country)]
    assert not audit_story_bundle(a).prompt_ready


@pytest.mark.parametrize("related", [False, True])
def test_legacy_evidence_blocks_direct_model_entry_points(related, monkeypatch):
    a, b = bundles()
    if related:
        a.related_signals = [RelatedSignal(b.event_id, b.signal_kind, b.where, b.when, b.headline_metric, b.country)]
    else:
        del a.raw_signal_dump["forecast_window"]
    writer_call, checker_call = Mock(), Mock()
    monkeypatch.setattr(writer, "_call_writer_provider", writer_call)
    monkeypatch.setattr(fact_check, "_call_gemini", checker_call)
    assert writer.write_tweet(a, MemorySlice()).tweet is None
    assert not fact_check.fact_check("A model forecast is available.", [], a, {}).passed
    writer_call.assert_not_called()
    checker_call.assert_not_called()


def test_rehashed_changed_samples_still_require_matching_aggregates():
    import hashlib

    b, _ = bundles()
    packet = b.raw_signal_dump["forecast_window"]
    packet["series"]["pm2_5"]["values"][0] += 24
    packet["selected_record_sha256"] = hashlib.sha256(contract._encoded(
        {k: v for k, v in packet.items() if k != "selected_record_sha256"}
    )).hexdigest()
    assert contract.validate_window(packet)["pm2_5"] == 251.
    assert not audit_story_bundle(b).prompt_ready


def test_related_window_roundtrips_without_projection_repair():
    from src.two_bot.candidate_derivation import retained_bundle

    a, b = bundles()
    attach_related_signals([SimpleNamespace(event_id=v.event_id, bundle=v) for v in (a, b)])
    restored = retained_bundle(a.to_dict())
    assert restored.to_dict() == a.to_dict()
    assert audit_story_bundle(restored).prompt_ready


def test_batch_reference_date_survives_midnight_and_bad_city_is_contained(monkeypatch):
    class Clock(datetime):
        count = 0

        @classmethod
        def now(cls, tz=None):
            cls.count += 1
            return cls(2026, 6, 8, 23, 59, 59, tzinfo=UTC) if cls.count == 1 else cls(2026, 6, 9, 0, 0, 1, tzinfo=UTC)

    monkeypatch.setattr(source, "datetime", Clock)
    good, bad = payload(day=DAY), payload(day=DAY)
    bad["hourly"]["time"].pop()
    response = Mock()
    response.json.return_value = [bad, good]
    http = Mock(return_value=response)
    monkeypatch.setattr(source, "fetch_with_retry", http)
    cities = [dict(city="Lahore", country="Pakistan", lat=31.5, lon=74.3)] * 2
    values = source.fetch_batch_air_quality(cities)
    assert values[0] is None and values[1].date == DAY
    packet = values[1].forecast_window
    assert packet["requested_at"].startswith(DAY) and packet["retrieved_at"].startswith("2026-06-09")
    params = http.call_args.kwargs["params"]
    assert params["start_date"] == params["end_date"] == DAY
    assert params["timezone"] == params["domains"] == "auto"
    assert "forecast_days" not in params and "past_days" not in params
    http.assert_called_once()


def test_unknown_packet_fields_and_oversized_records_do_not_qualify():
    b, _ = bundles()
    packet = b.raw_signal_dump["forecast_window"]
    packet["unexpected"] = "anything"
    with pytest.raises(SourceFetchError):
        contract.validate_window(packet)
    packet.pop("unexpected")
    packet["requested_location"]["city"] = "x" * contract.LIMIT
    with pytest.raises(SourceFetchError):
        contract.validate_window(packet)


@pytest.mark.parametrize("bad_city", [None, "bad", 42, {"hourly": {"time": ["2020-01-01T00:00"]}}])
@pytest.mark.parametrize("chunk_size", [1, 2])
def test_one_malformed_or_stale_location_does_not_hide_good_cities(bad_city, chunk_size, monkeypatch):
    good = payload()
    responses = []
    for value in ([[bad_city], [good]] if chunk_size == 1 else [[bad_city, good]]):
        response = Mock()
        response.json.return_value = value
        responses.append(response)
    http = Mock(side_effect=responses)
    monkeypatch.setattr(source, "fetch_with_retry", http)
    monkeypatch.setattr(source, "_chunk_pacing_sleep", lambda: None)
    values = source.fetch_batch_air_quality(
        [dict(city="Lahore", country="Pakistan", lat=31.5, lon=74.3)] * 2,
        chunk_size=chunk_size,
    )
    assert values[0] is None and values[1] is not None
    assert http.call_count == len(responses)  # schema/stale evidence is not retried


def test_complete_http_packet_reaches_real_queue_with_exact_window(monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality
    from src.state import DEFAULT_STATE

    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    data = payload(pm25=250., dust=0.)
    response = Mock()
    response.json.return_value = data
    http = Mock(return_value=response)
    monkeypatch.setattr(source, "fetch_with_retry", http)
    state, run = deepcopy(DEFAULT_STATE), {"sources": []}
    run_air_quality(state, run, [dict(city="Lahore", country="Pakistan", lat=31.5, lon=74.3)])
    assert len(state["_triage_queue"]) == 1
    bundle = state["_triage_queue"][0].bundle
    assert audit_story_bundle(bundle).prompt_ready
    assert bundle.raw_signal_dump["forecast_window"]["hours"] == data["hourly"]["time"]
    assert run["sources"][0]["observed"] == 1 and run["sources"][0]["promoted"] == 1
    assert not state["air_quality_pm25_tiers"]
    http.assert_called_once()


def test_all_stale_chunks_preserve_pacing_without_retries(monkeypatch):
    response = Mock()
    response.json.return_value = {"hourly": {"time": ["2020-01-01T00:00"]}}
    http, pacing = Mock(return_value=response), Mock()
    monkeypatch.setattr(source, "fetch_with_retry", http)
    monkeypatch.setattr(source, "_chunk_pacing_sleep", pacing)
    with pytest.raises(SourceFetchError, match="stale data"):
        source.fetch_batch_air_quality(
            [dict(city="Lahore", country="Pakistan", lat=31.5, lon=74.3)] * 3,
            chunk_size=1, recovery_passes=2,
        )
    assert http.call_count == 3 and pacing.call_count == 2


def test_dust_review_context_keeps_zero_aod_and_accurate_model_scope(monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality
    from src.state import DEFAULT_STATE

    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    monkeypatch.setattr(source, "fetch_batch_air_quality", lambda _: [observation(pm25=0., dust=2000., aod=0.)])
    state = deepcopy(DEFAULT_STATE)
    run_air_quality(state, {"sources": []}, [dict(city="Lahore", country="Pakistan", lat=31.5, lon=74.3)])
    facts = {f["label"]: f["value"] for f in state["_triage_queue"][0].review_context["facts"]}
    assert facts["AOD"] == "0.00"
    assert facts["Evidence grade"] == "model_estimated; CAMS automatic domain; resolution unspecified"
