"""Offline source-time/receipt checks; complete invented inputs only."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.data.fire_source_contract import (
    FIRMS_PRODUCTS, FIRMS_PUBLIC_URL, HMS_BASE, HMS_PRODUCT, freshness,
    make_receipt, parse_minute, parse_record, source_minute, validate_days,
    validate_event, validate_receipt,
)
from src.data.source_status import SourceFetchError
from tests.fire_source_fixtures import firms_row, hms_row, source_event

REFERENCE = datetime(2032, 3, 1, 0, 1, 42, tzinfo=UTC)


@pytest.mark.parametrize("clock,expected", [("0", "00:00"), ("1", "00:01"), ("59", "00:59"), ("100", "01:00"), ("410", "04:10"), ("2359", "23:59")])
def test_firms_minute_keeps_utc_and_omitted_leading_zeroes(clock, expected):
    assert source_minute("2032-02-29", clock) == f"2032-02-29T{expected}:00Z"


@pytest.mark.parametrize("day,clock", [
    ("2031-02-29", "0100"), ("2032-2-29", "0100"), ("0000-01-01", "0100"),
    ("2032-02-29", "2400"), ("2032-02-29", "1260"), ("2032-02-29", "-1"),
    ("2032-02-29", "+410"), ("2032-02-29", "4.10"), ("2032-02-29", "4e2"),
    ("2032-02-29", " 410"), ("2032-02-29", "４１０"), ("2032-02-29", "04100"),
    ("2032-02-29", "0410\n"),
])
def test_invalid_calendar_or_time_is_not_guessed(day, clock):
    with pytest.raises(SourceFetchError):
        source_minute(day, clock)


@pytest.mark.parametrize("ordinal,day", [("2024001", "2024-01-01"), ("2024060", "2024-02-29"), ("2024366", "2024-12-31"), ("2025001", "2025-01-01")])
def test_hms_one_based_year_day_boundary(ordinal, day):
    assert source_minute(ordinal, "0410", hms=True) == day + "T04:10:00Z"


@pytest.mark.parametrize("ordinal,clock", [("2024000", "0410"), ("2024367", "0410"), ("2025366", "0410"), ("20240001", "0410"), ("2024001", "410"), ("2024001", "2400")])
def test_hms_ordinal_and_full_hhmm_are_required(ordinal, clock):
    with pytest.raises(SourceFetchError):
        source_minute(ordinal, clock, hms=True)


@pytest.mark.parametrize("product", FIRMS_PRODUCTS)
def test_product_row_retains_minute_precision_and_typed_confidence(product):
    row = parse_record(product, firms_row(product, when=REFERENCE))
    assert row.frp == 500.1234
    assert row.acquired_at == "2032-03-01T00:01:00Z"
    assert row.record["frp"] == "500.1234"
    if product == "MODIS_NRT":
        assert (row.ranking_confidence, row.confidence_kind, row.confidence_value) == (91, "numeric", 91.5)
    else:
        assert (row.ranking_confidence, row.confidence_kind, row.confidence_value) == (95, "categorical", "high")
    assert validate_receipt(make_receipt(row, FIRMS_PUBLIC_URL)) == row


@pytest.mark.parametrize("field,value", [("satellite", "N20"), ("satellite", "N21"), ("instrument", "MODIS"), ("confidence", "95"), ("version", ""), ("version", "\ud800")])
def test_product_metadata_cannot_be_borrowed_from_another_sensor(field, value):
    raw = firms_row(when=REFERENCE)
    raw[field] = value
    with pytest.raises(SourceFetchError):
        parse_record("VIIRS_SNPP_NRT", raw)


@pytest.mark.parametrize("satellite", ["T", "Terra", "A", "Aqua"])
def test_documented_modis_satellite_aliases(satellite):
    raw = firms_row("MODIS_NRT", when=REFERENCE)
    raw["satellite"] = satellite
    assert parse_record("MODIS_NRT", raw).confidence_value == 91.5


@pytest.mark.parametrize("field,value", [
    ("latitude", "90.1"), ("longitude", "-180.1"), ("latitude", "NaN"),
    ("longitude", "inf"), ("frp", "1e999"), ("frp", "-0.1"), ("frp", "-999"),
    ("frp", True), ("frp", "２５０"), ("frp", "1_000"),
])
def test_invalid_coordinates_or_power_do_not_become_measurements(field, value):
    raw = firms_row(when=REFERENCE)
    raw[field] = value
    with pytest.raises(SourceFetchError):
        parse_record("VIIRS_SNPP_NRT", raw)


@pytest.mark.parametrize("value", ["-1", "100.1", "NaN", "inf", "90%", True])
def test_invalid_modis_quality_value(value):
    raw = firms_row("MODIS_NRT", when=REFERENCE)
    raw["confidence"] = value
    with pytest.raises(SourceFetchError):
        parse_record("MODIS_NRT", raw)


def test_hms_missing_frp_is_not_zero_and_confidence_is_not_a_percentage():
    raw = hms_row(when=REFERENCE)
    row = parse_record(HMS_PRODUCT, raw)
    assert (row.ranking_confidence, row.confidence_kind, row.confidence_value) == (80, "unavailable", None)
    raw["FRP"] = "-999.0"
    missing = parse_record(HMS_PRODUCT, raw)
    assert missing.frp is None
    with pytest.raises(SourceFetchError):
        make_receipt(missing, f"{HMS_BASE}/2032/03/hms_fire20320301.txt")


@pytest.mark.parametrize("when,result", [
    ("2032-03-01T00:01:00Z", "fresh"), ("2032-03-01T00:02:00Z", "future"),
    ("2032-02-28T00:00:00Z", "fresh"), ("2032-02-27T23:59:00Z", "stale"),
    ("2032-03-02T00:00:00Z", "future"),
])
def test_freshness_uses_each_source_row_and_utc_calendar_days(when, result):
    row = parse_record("VIIRS_SNPP_NRT", firms_row(when=parse_minute(when)))
    assert freshness(row, REFERENCE) == result
    assert freshness(row, REFERENCE.astimezone(timezone(timedelta(hours=-12)))) == result


def test_naive_processing_reference_is_not_assumed_to_be_utc():
    with pytest.raises(SourceFetchError):
        freshness(parse_record("VIIRS_SNPP_NRT", firms_row(when=REFERENCE)), REFERENCE.replace(tzinfo=None))


@pytest.mark.parametrize("days", [0, 6, -1, True, 1.0, "1", None])
def test_requested_day_range_is_explicit(days):
    with pytest.raises(SourceFetchError):
        validate_days(days)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("source_name", "Other"),
    ("source_product", "VIIRS_NOAA20_NRT"), ("source_url", FIRMS_PUBLIC_URL + "?key=synthetic"),
    ("acquired_at", "2032-03-01T00:02:00Z"), ("precision", "second"),
    ("record_sha256", "0" * 64), ("record", []),
])
def test_receipt_semantic_mutations_reject(field, value):
    receipt = source_event(when=REFERENCE).acquisition_provenance
    receipt[field] = value
    with pytest.raises(SourceFetchError):
        validate_receipt(receipt)


def test_receipt_fields_are_exact_and_detached():
    raw = firms_row(when=REFERENCE)
    row = parse_record("VIIRS_SNPP_NRT", raw)
    receipt = make_receipt(row, FIRMS_PUBLIC_URL)
    raw["frp"] = "900"
    row.record["frp"] = "700"
    assert validate_receipt(receipt).frp == 500.1234
    with pytest.raises(SourceFetchError):
        make_receipt(row, FIRMS_PUBLIC_URL)
    for field in tuple(receipt):
        changed = deepcopy(receipt)
        del changed[field]
        with pytest.raises(SourceFetchError):
            validate_receipt(changed)
    for changed in ({**receipt, "extra": 1}, {**receipt, "record": {**receipt["record"], "extra": "1"}}):
        with pytest.raises(SourceFetchError):
            validate_receipt(changed)


def test_hms_row_time_stays_distinct_from_daily_filename():
    row = parse_record(HMS_PRODUCT, hms_row(when=REFERENCE - timedelta(days=1)))
    receipt = make_receipt(row, f"{HMS_BASE}/2032/03/hms_fire20320301.txt")
    assert validate_receipt(receipt).acquired_at == "2032-02-29T00:01:00Z"
    for url in (f"{HMS_BASE}/2032/02/hms_fire20320301.txt", f"{HMS_BASE}/2031/02/hms_fire20310229.txt", receipt["source_url"] + "?key=synthetic"):
        with pytest.raises(SourceFetchError):
            make_receipt(row, url)


@pytest.mark.parametrize("product", [*FIRMS_PRODUCTS, HMS_PRODUCT])
def test_event_is_bound_to_selected_product_minute_cell_and_measurement(product):
    event = source_event(product, when=REFERENCE)
    assert validate_event(event).acquired_at == "2032-03-01T00:01:00Z"
    changes = {"lat": True, "lon": 11.0, "frp": 500.1, "confidence": True,
               "source_product": "unknown", "acquired_at": "2032-03-01T00:02:00Z",
               "event_id": "fire_35.25_-110.50_2032-02-29_utc1", "source_leg": "wrong",
               "acquisition_provenance": None}
    for field, value in changes.items():
        changed = deepcopy(event)
        setattr(changed, field, value)
        with pytest.raises(SourceFetchError):
            validate_event(changed)


def test_coherent_changed_receipt_is_not_authentication_or_binding_to_old_event():
    event = source_event(when=REFERENCE)
    row = parse_record("VIIRS_SNPP_NRT", {**firms_row(when=REFERENCE), "frp": "900"})
    receipt = make_receipt(row, FIRMS_PUBLIC_URL)
    assert validate_receipt(receipt).frp == 900  # hashes alone cannot prove truth
    event.acquisition_provenance = receipt
    with pytest.raises(SourceFetchError):
        validate_event(event)
    with pytest.raises(SourceFetchError):
        make_receipt(replace(row, frp=901), FIRMS_PUBLIC_URL)
