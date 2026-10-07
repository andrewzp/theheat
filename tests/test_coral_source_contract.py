"""Invented wire/receipt failures for DHW points; no source or paid-model calls."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from unittest.mock import Mock

import pytest
import requests

from src.data import coral_dhw, coral_source_contract as contract
from src.data.source_status import SourceFetchError
from src.two_bot import fact_check, writer
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.marine import build_coral_bleaching_bundle
from src.two_bot.types import MemorySlice, StoryBundle
from tests.coral_point_fixtures import csv_bytes, metadata, metadata_bytes, reading, timestamp

STATION = coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"]


def parse(body, meta=None):
    return coral_dhw._reading_from_erddap_csv(
        body,
        STATION,
        metadata=meta or metadata(),
        retrieved_at=contract.now_utc(),
        max_age_days=5,
    )


def bundle(value=8.34):
    return build_coral_bleaching_bundle(coral_dhw.detect_dhw_thresholds([reading(value)], {})[0])


@pytest.mark.parametrize(
    "value,tier",
    [
        (0, None),
        (3.96, None),
        (4, 4),
        (4.001, 4),
        (7.96, 4),
        (8, 8),
        (8.001, 8),
        (11.96, 8),
        (12, 12),
        (12.001, 12),
        (100, 12),
    ],
)
def test_source_precision_controls_threshold_before_any_display_rounding(value, tier):
    r = reading(value)
    assert r.dhw_value == value and contract.qualified_provenance(r)
    events = coral_dhw.detect_dhw_thresholds([r], {})
    assert [e.dhw_tier for e in events] == ([] if tier is None else [tier])
    if events:
        e = events[0]
        assert e.dhw_value == value and contract.qualified_provenance(e)
        assert audit_story_bundle(build_coral_bleaching_bundle(e)).prompt_ready
        assert not coral_dhw.detect_dhw_thresholds([r], {r.region_id: tier})


@pytest.mark.parametrize(
    "variable,attribute",
    [
        ("NC_GLOBAL", "id"),
        ("NC_GLOBAL", "product_version"),
        ("NC_GLOBAL", "processing_level"),
        ("latitude", "units"),
        ("longitude", "units"),
        ("degree_heating_week", "units"),
        ("degree_heating_week", "valid_min"),
        ("degree_heating_week", "valid_max"),
        ("degree_heating_week", "_FillValue"),
        ("NC_GLOBAL", "geospatial_lat_resolution"),
        ("NC_GLOBAL", "geospatial_lon_resolution"),
        ("latitude", "valid_min"),
        ("latitude", "valid_max"),
        ("longitude", "valid_min"),
        ("longitude", "valid_max"),
    ],
)
def test_unrecognized_metadata_attribute_fails(variable, attribute):
    raw = json.loads(metadata_bytes())
    row = next(r for r in raw["table"]["rows"] if r[1:3] == [variable, attribute])
    row[4] = (
        "9"
        if attribute not in ["units", "id", "product_version", "processing_level"]
        else "unsupported"
    )
    with pytest.raises(SourceFetchError):
        contract.decode_metadata(
            json.dumps(raw).encode(), retrieved_at=contract.now_utc(), max_age_days=5
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "columns",
        "row_width",
        "row_type",
        "value_type",
        "invalid_json",
        "duplicate_json_key",
        "too_large",
        "encoding",
        "reverse",
        "future",
        "stale",
        "bad_time",
        "nonfinite_range",
    ],
)
def test_malformed_metadata_never_produces_a_receipt(mutation):
    raw = json.loads(metadata_bytes())
    rows = raw["table"]["rows"]
    if mutation == "missing":
        rows.pop(0)
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "columns":
        raw["table"]["columnNames"].reverse()
    elif mutation == "row_width":
        rows[0].append("extra")
    elif mutation == "row_type":
        rows[0] = "attribute"
    elif mutation == "value_type":
        rows[0][4] = True
    elif mutation in ["reverse", "future", "stale", "bad_time"]:
        attr = "time_coverage_start" if mutation == "reverse" else "time_coverage_end"
        row = next(r for r in rows if r[2] == attr)
        row[4] = {
            "reverse": timestamp(-1),
            "future": timestamp(-1),
            "stale": timestamp(8),
            "bad_time": "2026-02-30T12:00:00Z",
        }[mutation]
    elif mutation == "nonfinite_range":
        next(r for r in rows if r[1:3] == ["degree_heating_week", "valid_max"])[4] = "NaN"
    body = json.dumps(raw).encode()
    if mutation == "invalid_json":
        body = b"{"
    elif mutation == "duplicate_json_key":
        body = body.replace(b'"table":', b'"table":{},"table":', 1)
    elif mutation == "too_large":
        body = b" " * (contract.METADATA_LIMIT + 1)
    elif mutation == "encoding":
        body = b"\xff"
    with pytest.raises(SourceFetchError):
        contract.decode_metadata(body, retrieved_at=contract.now_utc(), max_age_days=5)


@pytest.mark.parametrize("age", [6, 7])
def test_documented_backup_lag_is_inclusive(age):
    meta = metadata(timestamp(age))
    assert parse(csv_bytes(stamp=timestamp(age)), meta).date == timestamp(age)[:10]


def test_requested_larger_lag_is_explicit_and_primary_rule_is_not_changed():
    meta = contract.decode_metadata(
        metadata_bytes(timestamp(8)), retrieved_at=contract.now_utc(), max_age_days=8
    )
    assert contract.decode_point(
        csv_bytes(stamp=timestamp(8)),
        STATION,
        metadata=meta,
        retrieved_at=contract.now_utc(),
        max_age_days=8,
    )
    with pytest.raises(SourceFetchError):
        parse(csv_bytes(stamp=timestamp(8)), meta)


@pytest.mark.parametrize(
    "body",
    [
        lambda b: b.replace(b"time,latitude", b"date,latitude"),
        lambda b: b.replace(b"time,latitude", b"time,time"),
        lambda b: b.replace(b"latitude,longitude", b"longitude,latitude"),
        lambda b: b.replace(b"degree_Celsius_weeks", b"kelvin"),
        lambda b: b.replace(b"UTC,degrees_north,degrees_east,degree_Celsius_weeks\n", b""),
        lambda b: b.splitlines(keepends=True)[0] + b.splitlines(keepends=True)[1],
        lambda b: b + b.splitlines(keepends=True)[-1],
        lambda b: b.rstrip() + b",extra\n",
        lambda b: b.replace(b"-16.075", b""),
        lambda b: b.replace(b"145.975", b""),
        lambda b: b.replace(b"-16.075", b"NaN"),
        lambda b: b.replace(b"145.975", b"inf"),
        lambda b: b.replace(b"-16.075", b"91"),
        lambda b: b.replace(b"145.975", b"181"),
        lambda b: b.replace(b"145.975", b"40.025"),
        lambda b: b.replace(b"-16.075", b"-16.071"),
        lambda b: b.replace(b"T12:00:00Z", b"Tbad"),
        lambda b: b.replace(timestamp().encode(), timestamp(2).encode()),
        lambda b: b.replace(timestamp().encode(), timestamp(-1).encode()),
        lambda b: b.replace(timestamp().encode(), timestamp(8).encode()),
        lambda b: b.replace(b",8.3", b","),
        lambda b: b.replace(b",8.3", b",NaN"),
        lambda b: b.replace(b",8.3", b",inf"),
        lambda b: b.replace(b",8.3", b",-1"),
        lambda b: b.replace(b",8.3", b",-327.68"),
        lambda b: b.replace(b",8.3", b",100.01"),
        lambda b: b.replace(b",8.3", b',"8.3'),
        lambda b: b"\xff",
        lambda b: b + b" " * (contract.CSV_LIMIT + 1),
        lambda b: b"",
    ],
)
def test_complete_csv_contract_rejects_bad_points(body):
    with pytest.raises(SourceFetchError):
        parse(body(csv_bytes()))


def test_source_receipt_is_exact_detached_and_body_free():
    r = reading(8.34)
    e = coral_dhw.detect_dhw_thresholds([r], {})[0]
    b = build_coral_bleaching_bundle(e)
    assert e.provenance == r.provenance and e.provenance is not r.provenance
    assert e.provenance["metadata"] is not r.provenance["metadata"]
    r.provenance["dhw_value"] = 99
    assert e.provenance["dhw_value"] == 8.34
    wire = json.dumps(b.to_dict(), allow_nan=False)
    assert "columnNames" not in wire and "UTC,degrees_north" not in wire
    assert audit_story_bundle(StoryBundle(**json.loads(wire))).prompt_ready
    assert b.raw_signal_dump["provenance"] is not e.provenance
    assert (
        b.raw_signal_dump["provenance"]["response_sha256"]
        == hashlib.sha256(csv_bytes(8.34, e.provenance["product_timestamp"])).hexdigest()
    )


@pytest.mark.parametrize("field", sorted(contract._RECEIPT_KEYS))
def test_each_missing_receipt_field_blocks_writer_and_direct_checker(field, monkeypatch):
    b = bundle()
    b.raw_signal_dump["provenance"].pop(field)
    assert_refused_before_spend(b, monkeypatch)


def assert_refused_before_spend(b, monkeypatch):
    before = deepcopy(b)
    assert not audit_story_bundle(b).prompt_ready
    wc, fc = Mock(), Mock()
    monkeypatch.setattr(writer, "_call_writer_provider", wc)
    monkeypatch.setattr(fact_check, "_call_gemini", fc)
    assert writer.write_tweet(b, MemorySlice()).tweet is None
    assert not fact_check.fact_check(
        "The point has 8.34°C-weeks of accumulated heat stress.", [], b, {}
    ).passed
    wc.assert_not_called()
    fc.assert_not_called()
    assert b == before


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy",
        "extra",
        "schema_bool",
        "schema_unknown",
        "unit",
        "method",
        "product",
        "name",
        "leg",
        "region",
        "region_name",
        "point",
        "point_bool",
        "requested_point",
        "grid",
        "timestamp",
        "date",
        "retrieved",
        "url",
        "fragment",
        "credentials",
        "hash",
        "bytes_bool",
        "bytes_zero",
        "bytes_large",
        "dhw_bool",
        "dhw_mismatch",
        "meta_extra",
        "meta_missing",
        "meta_hash",
        "meta_bytes_bool",
        "meta_url",
        "meta_reversed",
        "meta_retrieved",
        "meta_time",
        "raw_dhw",
        "raw_coords",
        "raw_source",
        "raw_tier",
        "raw_level",
        "raw_id",
        "raw_date",
        "raw_region",
        "raw_extra",
        "headline",
        "facts",
        "duplicate_fact",
        "where",
        "when",
        "event_id",
        "history",
        "remove_identifiers",
    ],
)
def test_altered_or_legacy_point_evidence_blocks_before_spend(mutation, monkeypatch):
    b = bundle()
    p = b.raw_signal_dump["provenance"]
    raw = b.raw_signal_dump
    changes = {
        "extra": ("extra", 0),
        "schema_bool": ("schema_version", True),
        "schema_unknown": ("schema_version", 2),
        "unit": ("unit", "degree_C"),
        "method": ("method", "regional mean"),
        "product": ("source_product", "other"),
        "name": ("source_name", "other"),
        "leg": ("source_leg", "other"),
        "region": ("region_id", "fiji"),
        "region_name": ("region_full_name", "Other"),
        "point": ("sampled_point", [-16.125, 145.975]),
        "point_bool": ("sampled_point", [True, False]),
        "requested_point": ("requested_point", [-16.075, 145.975]),
        "grid": ("native_grid_degrees", 1),
        "timestamp": ("product_timestamp", timestamp(2)),
        "date": ("valid_date", timestamp(2)[:10]),
        "retrieved": ("retrieved_at", timestamp(2)),
        "url": ("source_url", "https://example.invalid/point"),
        "fragment": ("source_url", p["source_url"] + "#ignored"),
        "credentials": ("source_url", p["source_url"].replace("https://", "https://user@")),
        "hash": ("response_sha256", "wrong"),
        "bytes_bool": ("response_bytes", True),
        "bytes_zero": ("response_bytes", 0),
        "bytes_large": ("response_bytes", 8193),
        "dhw_bool": ("dhw_value", True),
        "dhw_mismatch": ("dhw_value", 8.35),
    }
    if mutation in changes:
        k, v = changes[mutation]
        p[k] = v
    elif mutation == "legacy":
        raw.pop("provenance")
    elif mutation == "meta_extra":
        p["metadata"]["extra"] = 0
    elif mutation == "meta_missing":
        p["metadata"].pop("response_bytes")
    elif mutation == "meta_hash":
        p["metadata"]["response_sha256"] = "bad"
    elif mutation == "meta_bytes_bool":
        p["metadata"]["response_bytes"] = True
    elif mutation == "meta_url":
        p["metadata"]["metadata_url"] = "https://example.invalid"
    elif mutation == "meta_reversed":
        p["metadata"]["first_product_time"] = timestamp(-1)
    elif mutation == "meta_retrieved":
        p["metadata"]["retrieved_at"] = timestamp(2)
    elif mutation == "meta_time":
        p["metadata"]["last_product_time"] = timestamp(2)
    elif mutation == "raw_dhw":
        raw["dhw_value"] = 8.35
    elif mutation == "raw_coords":
        raw["lat"] = -16.125
    elif mutation == "raw_source":
        raw["source_name"] = "Other"
    elif mutation == "raw_tier":
        raw["dhw_tier"] = 12
    elif mutation == "raw_level":
        raw["bleaching_level"] = "mortality expected"
    elif mutation == "raw_id":
        raw["event_id"] = "invented"
    elif mutation == "raw_date":
        raw["date"] = timestamp(2)[:10]
    elif mutation == "raw_region":
        raw["region_full_name"] = "Other"
    elif mutation == "raw_extra":
        raw["unknown"] = 1
    elif mutation == "headline":
        b.headline_metric["value"] = 8.35
    elif mutation == "facts":
        next(f for f in b.current_facts if f["label"] == "dhw_value")["value"] = 8.35
    elif mutation == "duplicate_fact":
        b.current_facts.append(deepcopy(b.current_facts[0]))
    elif mutation == "where":
        b.where = "Other"
    elif mutation == "when":
        b.when = timestamp(2)[:10]
    elif mutation == "event_id":
        b.event_id = "invented"
    elif mutation == "history":
        b.historical_context["thresholds_c_weeks"] = [1, 2, 3]
    elif mutation == "remove_identifiers":
        raw["source_leg"] = None
        b.current_facts = [f for f in b.current_facts if f["label"] != "data_source"]
    else:
        raise AssertionError(mutation)
    assert_refused_before_spend(b, monkeypatch)


class Response:
    def __init__(self, body, status=200, error=None):
        self.body, self.status_code, self.error = body, status, error
        self.closed = False

    def iter_content(self, size):
        yield self.body[:size]
        if self.error:
            raise self.error
        for i in range(size, len(self.body), size):
            yield self.body[i : i + size]

    def close(self):
        self.closed = True


def install_transport(monkeypatch, responses):
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return responses[len(calls) - 1]

    monkeypatch.setattr(coral_dhw, "fetch_with_retry", fetch)
    return calls


def test_backup_collection_uses_one_metadata_and_one_pinned_request_per_point(monkeypatch):
    stamp = timestamp()
    responses = [Response(metadata_bytes(stamp))]
    for station in coral_dhw.CRW_ERDDAP_STATIONS.values():
        lat = -89.975 + round((station.lat + 89.975) / 0.05) * 0.05
        lon = -179.975 + round((station.lon + 179.975) / 0.05) * 0.05
        responses.append(Response(csv_bytes(stamp=stamp, lat=lat, lon=lon)))
    calls = install_transport(monkeypatch, responses)
    result = coral_dhw._fetch_coral_dhw_erddap(strict=True)
    assert len(result) == 27 and len(calls) == 28 and calls[0][0] == contract.METADATA_URL
    assert all(contract.qualified_provenance(r) for r in result)
    assert all(stamp in url and "(last)" not in url for url, _ in calls[1:])
    assert all(r.closed for r in responses)
    assert all(
        k["stream"] and k["allow_redirects"] is False and k["attempts"] == 1 and k["timeout"] == 20
        for _, k in calls
    )
    assert len({r.provenance["metadata"]["response_sha256"] for r in result}) == 1


@pytest.mark.parametrize(
    "body,status,error",
    [
        (b"bad", 200, None),
        (metadata_bytes() + b" " * (contract.METADATA_LIMIT + 1), 200, None),
        (metadata_bytes(), 302, None),
        (metadata_bytes(), 200, requests.ConnectionError("synthetic")),
    ],
    ids=["malformed", "oversized", "redirect", "stream_failure"],
)
def test_metadata_failure_closes_response_and_skips_all_points(body, status, error, monkeypatch):
    response = Response(body, status, error)
    calls = install_transport(monkeypatch, [response])
    with pytest.raises(SourceFetchError):
        coral_dhw._fetch_coral_dhw_erddap(strict=True)
    assert response.closed and len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        Response(b"x" * (contract.CSV_LIMIT + 1)),
        Response(b"x", 302),
        Response(b"x", 200, requests.ConnectionError("synthetic")),
    ],
)
def test_point_transport_closes_on_every_failure(response, monkeypatch):
    install_transport(monkeypatch, [response])
    with pytest.raises((SourceFetchError, requests.RequestException)):
        coral_dhw._fetch_erddap_csv(STATION, timestamp())
    assert response.closed


def test_partial_backup_failure_retains_other_points_and_all_failed_is_explicit(monkeypatch):
    monkeypatch.setattr(coral_dhw, "CRW_ERDDAP_STATIONS", {"a": STATION, "b": STATION})
    responses = [Response(metadata_bytes()), Response(b"bad"), Response(csv_bytes())]
    calls = install_transport(monkeypatch, responses)
    assert len(coral_dhw._fetch_coral_dhw_erddap(strict=True)) == 1 and len(calls) == 3
    assert all(r.closed for r in responses)
    responses = [Response(metadata_bytes()), Response(b"bad"), Response(b"bad")]
    install_transport(monkeypatch, responses)
    with pytest.raises(SourceFetchError, match="witness failed"):
        coral_dhw._fetch_coral_dhw_erddap(strict=True)
    assert all(r.closed for r in responses)


def test_primary_bundle_does_not_gain_a_point_receipt():
    r = coral_dhw.CoralDHWReading(
        "gbr_northern", "Northern GBR", timestamp()[:10], 8.34, "Alert Level 1", 3
    )
    event = coral_dhw.detect_dhw_thresholds([r], {})[0]
    b = build_coral_bleaching_bundle(event)
    assert event.dhw_value == 8.34 and "provenance" not in b.raw_signal_dump
    assert not audit_story_bundle(b).prompt_ready  # Legacy primary evidence is no longer qualified.


@pytest.mark.parametrize("field", ["retrieved_at", "metadata_retrieved_at"])
def test_future_receipt_clock_is_not_a_valid_capture(field, monkeypatch):
    b = bundle()
    p = b.raw_signal_dump["provenance"]
    p["retrieved_at"] = timestamp(-2)
    if field == "metadata_retrieved_at":
        p["metadata"]["retrieved_at"] = timestamp(-1)
    assert_refused_before_spend(b, monkeypatch)


@pytest.mark.parametrize(
    "field",
    ["response_sha256", "response_bytes", "metadata_hash", "metadata_bytes", "retrieved_at"],
)
def test_well_shaped_receipt_substitution_cannot_reuse_prior_review_or_approval(field):
    # A self-contained receipt cannot authenticate a perfectly coherent substitute.
    # It is nevertheless different evidence and must obsolete every old decision.
    from src.editorial.revisions import (
        record_human_review,
        authorize_draft,
        review_is_current,
        approval_is_current,
    )

    b = bundle()
    p = b.raw_signal_dump["provenance"]
    earlier = datetime.now(UTC) - timedelta(seconds=10)
    p["retrieved_at"] = p["metadata"]["retrieved_at"] = earlier.strftime("%Y-%m-%dT%H:%M:%SZ")
    d = {
        "id": "synthetic-point",
        "text": "The satellite point has 8.34°C-weeks of accumulated heat stress.",
        "type": "coral_bleaching",
        "event_id": b.event_id,
        "review_context": {"two_bot": {"bundle": b.to_dict()}},
    }
    record_human_review(d)  # Explicit offline approval fixture, not a real human rating.
    authorize_draft(d, "manual")
    assert review_is_current(d) and approval_is_current(d, "manual")
    if field == "metadata_hash":
        p["metadata"]["response_sha256"] = "0" * 64
    elif field == "metadata_bytes":
        p["metadata"]["response_bytes"] += 1
    elif field == "response_sha256":
        p["response_sha256"] = "1" * 64
    elif field == "response_bytes":
        p["response_bytes"] += 1
    else:
        p["retrieved_at"] = (earlier + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert audit_story_bundle(b).prompt_ready  # Binding validation is not authenticity.
    assert not review_is_current(d) and not approval_is_current(d, "manual")


def test_metadata_receipt_rejects_future_capture_and_nonstandard_json():
    with pytest.raises(SourceFetchError):
        contract.decode_metadata(metadata_bytes(), retrieved_at=timestamp(-1), max_age_days=5)
    bad = metadata_bytes().replace(b"{", b'{"unexpected":NaN,', 1)
    with pytest.raises(SourceFetchError):
        contract.decode_metadata(bad, retrieved_at=contract.now_utc(), max_age_days=5)


@pytest.mark.parametrize("kind", ["metadata", "point"])
def test_transport_and_parser_accept_exact_byte_limit_without_sending_bodies_to_receipts(
    kind, monkeypatch
):
    if kind == "metadata":
        base = metadata_bytes()
        body = base + b" " * (contract.METADATA_LIMIT - len(base))
        response = Response(body)
        install_transport(monkeypatch, [response])
        received, at = coral_dhw._fetch_point_bytes(contract.METADATA_URL, contract.METADATA_LIMIT)
        receipt = contract.decode_metadata(received, retrieved_at=at, max_age_days=5)
        assert receipt["response_bytes"] == contract.METADATA_LIMIT
    else:
        base = csv_bytes()
        body = base + b"\n" * (contract.CSV_LIMIT - len(base))
        response = Response(body)
        install_transport(monkeypatch, [response])
        meta = metadata()
        received, at = coral_dhw._fetch_erddap_csv(STATION, meta["last_product_time"])
        receipt = contract.decode_point(
            received, STATION, metadata=meta, retrieved_at=at, max_age_days=5
        )
        assert receipt["response_bytes"] == contract.CSV_LIMIT
    assert response.closed and len(json.dumps(receipt)) < 2048


def test_non_strict_metadata_failure_is_empty_but_never_synthetic_success(monkeypatch):
    response = Response(b"broken")
    calls = install_transport(monkeypatch, [response])
    assert coral_dhw._fetch_coral_dhw_erddap(strict=False) == []
    assert len(calls) == 1 and response.closed
