"""Complete invented station evidence stays lossless, bounded and detached."""

from copy import deepcopy
from datetime import date
import json

import pytest

from src.two_bot.bundle_capture import BundleCaptureError, capture_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.ghcn_readable_warrant import (
    ReadableBundle,
    WarrantError,
    decode_wire,
    encode_full,
    has_readable_marker,
    prepare_bundle,
    retained_bundle,
)
from src.two_bot.types import RelatedSignal, StoryBundle
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.test_ghcn_publication_observation_set import paired_variants as paired_variants


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


@pytest.fixture(scope="module")
def variants():
    return {
        (direction, tier): graphic_bundles(direction=direction, tier=tier)[-1]
        for direction in ("high", "low")
        for tier in ("all_time", "monthly", "calendar")
    }


@pytest.mark.parametrize(
    "key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar")]
)
def test_native_full_source_has_real_size_hold_then_losslessly_fits(variants, key):
    source = variants[key]
    original = deepcopy(source)
    with pytest.raises(BundleCaptureError, match="bundle_capture_too_large"):
        capture_bundle(source)
    prepared = prepare_bundle(source)
    assert isinstance(prepared, ReadableBundle) and prepare_bundle(prepared) is prepared
    assert audit_story_bundle(prepared).prompt_ready
    wire = capture_bundle(prepared).payload()
    full = decode_wire(wire)
    expected = json.loads(json.dumps(source.to_dict(), default=lambda value: value.isoformat()))
    assert canonical(full) == canonical(expected)
    assert source == original
    assert has_readable_marker(wire)
    assert len(capture_bundle(prepared).serialized.encode()) <= 32768
    restored = retained_bundle(wire)
    assert audit_story_bundle(restored).prompt_ready
    assert canonical(restored.to_dict()) == canonical(wire)
    assert not audit_story_bundle(StoryBundle(**deepcopy(wire))).prompt_ready
    # Returned views share neither original source nor each other's dictionaries.
    full["historical_context"]["baseline"]["station_id"] = "invented-change"
    assert decode_wire(wire)["historical_context"]["baseline"]["station_id"] != "invented-change"
    assert wire["historical_context"]["baseline"].keys() == {
        "same_document_baseline",
        "full_baseline_sha256",
    }


def test_pair_observation_metadata_and_all_unselected_calendar_cells_survive(paired_variants):
    for draft in paired_variants.values():
        full = draft["review_context"]["two_bot"]["bundle"]
        wire = encode_full(full)
        assert canonical(decode_wire(wire)) == canonical(full)
        assert set(decode_wire(wire)["raw_signal_dump"]["evidence"]["variables"]) == {
            "TMAX",
            "TMIN",
        }
        assert len(wire["raw_signal_dump"]["evidence"]["baseline"]["calendar_table"]["rows"]) == 366


def test_enrichment_is_not_hidden_by_cached_wire(variants):
    prepared = prepare_bundle(variants["high", "all_time"])
    first = capture_bundle(prepared)
    prepared.human_impact.append(
        {
            "claim": "Invented impact",
            "value": 2,
            "source_name": "Invented",
            "url": "https://example.invalid/impact",
            "as_of": "2026-09-09",
        }
    )
    prepared.related_signals.append(
        RelatedSignal(
            "invented-related", "invented", "Elsewhere", "2026-09-08", {"value": 2, "unit": "C"}
        )
    )
    second = capture_bundle(prepared)
    assert first != second
    assert decode_wire(second.payload())["human_impact"][0]["value"] == 2
    assert decode_wire(second.payload())["related_signals"][0]["event_id"] == "invented-related"
    assert "human_impact" not in first.payload() and "related_signals" not in first.payload()


@pytest.mark.parametrize(
    "optional,value", [("country", ""), ("related_signals", []), ("human_impact", [])]
)
def test_explicit_empty_optional_presence_survives_restore(variants, optional, value):
    full = prepare_bundle(variants["high", "all_time"]).full_tree()
    full[optional] = value
    wire = encode_full(full)
    assert optional in retained_bundle(wire).to_dict()
    assert canonical(decode_wire(wire)) == canonical(full)


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_schema",
        "profile_extra",
        "alias_path",
        "alias_hash",
        "duplicate_day",
        "reversed_rows",
        "bad_day",
        "extra_column",
        "extra_cell",
        "partial_null",
        "all_absent",
        "bool_year",
        "zero_year",
        "too_few_samples",
        "wrong_month_day",
        "bad_date",
        "bool_temperature",
        "string_temperature",
        "mixed_maps",
        "unknown_variable",
        "missing_scalar",
        "extra_scalar",
    ],
)
def test_malformed_wire_is_refused_without_repair(variants, fault):
    wire = prepare_bundle(variants["high", "all_time"]).to_dict()
    baseline = wire["raw_signal_dump"]["evidence"]["baseline"]
    table = baseline["calendar_table"]
    scope = baseline["variables"]["temperature_2m_max"]
    if fault == "unknown_schema":
        baseline["schema_version"] += "-unknown"
    elif fault == "profile_extra":
        baseline["wire_profile"]["accepted"] = True
    elif fault == "alias_path":
        wire["historical_context"]["baseline"]["same_document_baseline"] = "https://example.invalid"
    elif fault == "alias_hash":
        wire["historical_context"]["baseline"]["full_baseline_sha256"] = "0" * 64
    elif fault == "duplicate_day":
        table["rows"].insert(0, deepcopy(table["rows"][0]))
    elif fault == "reversed_rows":
        table["rows"].reverse()
    elif fault == "bad_day":
        table["rows"][0][0] = "02-30"
    elif fault == "extra_column":
        table["columns"].append("unknown")
    elif fault == "extra_cell":
        table["rows"][0].append(0)
    elif fault == "partial_null":
        table["rows"][0][1] = None
    elif fault == "all_absent":
        table["rows"][0][1:] = [None] * 8
    elif fault == "bool_year":
        table["rows"][0][1] = True
    elif fault == "zero_year":
        table["rows"][0][1] = 0
    elif fault == "too_few_samples":
        table["rows"][0][2] = 1
    elif fault == "wrong_month_day":
        table["rows"][0][3] = "2020-02-02"
    elif fault == "bad_date":
        table["rows"][0][3] = "2020-02-30"
    elif fault == "bool_temperature":
        table["rows"][0][4] = True
    elif fault == "string_temperature":
        table["rows"][0][4] = "28.0"
    elif fault == "mixed_maps":
        scope["calendar_years"] = {}
    elif fault == "unknown_variable":
        table["variables"][0] = "unknown"
    elif fault == "missing_scalar":
        del scope["source_gap_count"]
    else:
        scope["unknown"] = 1
    original = deepcopy(wire)
    with pytest.raises(WarrantError):
        decode_wire(wire)
    assert wire == original


@pytest.mark.parametrize(
    "invalid", [float("nan"), float("inf"), 9007199254740992, b"opaque", "\ud800"]
)
def test_unsupported_native_scalar_refuses_before_encoding(variants, invalid):
    full = prepare_bundle(variants["high", "all_time"]).full_tree()
    full["headline_metric"]["extra"] = invalid
    with pytest.raises(WarrantError):
        encode_full(full)


def test_native_date_uses_existing_codec_without_constructor_projection(variants):
    full = prepare_bundle(variants["high", "all_time"]).full_tree()
    full["raw_signal_dump"]["signal_date"] = date(2026, 9, 8)
    restored = decode_wire(encode_full(full))
    assert restored["raw_signal_dump"]["signal_date"] == "2026-09-08"


def test_full_baseline_equality_is_typed_not_python_numeric_coercion(variants):
    full = prepare_bundle(variants["high", "all_time"]).full_tree()
    full["historical_context"]["baseline"]["schema_version"] = 2.0
    with pytest.raises(WarrantError, match="ghcn_readable_baseline_changed"):
        encode_full(full)


@pytest.mark.parametrize(
    "key,value",
    [
        ("comparison_before", "2026-02-30"),
        ("reconciled", 1),
        ("source_payload_sha256", "not-a-hash"),
        ("retrieved_at", "2026-02-30T00:00:00Z"),
        ("retrieved_at", "2026-09-09T12:00:00"),
        ("station_id", "../outside"),
    ],
)
def test_unsupported_original_baseline_cannot_be_encoded(variants, key, value):
    full = prepare_bundle(variants["high", "all_time"]).full_tree()
    full["raw_signal_dump"]["evidence"]["baseline"][key] = value
    full["historical_context"]["baseline"][key] = value
    with pytest.raises(WarrantError):
        encode_full(full)


@pytest.mark.parametrize("kind", ["deep", "nodes", "bytes", "cycle", "enlarged_wire"])
def test_work_and_byte_limits_refuse_before_unbounded_conversion(variants, kind):
    full = prepare_bundle(variants["high", "all_time"]).full_tree()
    if kind == "deep":
        value = None
        for _ in range(34):
            value = [value]
    elif kind == "nodes":
        value = [None] * 65536
    elif kind == "bytes":
        value = "x" * 262145
    elif kind == "cycle":
        value = []
        value.append(value)
    else:
        value = "x" * 4000
    full["headline_metric"]["extra"] = value
    with pytest.raises(WarrantError):
        encode_full(full)


@pytest.mark.parametrize(
    "product,signal,reference",
    [
        ("era5", "open_meteo_archive_high", False),
        ("noaa-ghcn-daily-v2", "anomaly_hot", False),
        ("noaa-ghcn-daily-v2", "monthly_high", True),
    ],
)
def test_unrelated_and_genuine_reference_paths_do_not_gain_serialization_calls(
    product, signal, reference
):
    class Unchanged:
        signal_kind = signal
        historical_context = {}
        raw_signal_dump = {"evidence": {"source_product": product}}
        if reference:
            raw_signal_dump["ghcn_claim_view"] = {}

        def to_dict(self):
            raise AssertionError("Unrelated preparation must not serialize this object")

    original = Unchanged()
    assert prepare_bundle(original) is original


def test_discarded_original_context_is_preserved_but_never_buys_a_generation():
    from src.data import ghcn
    from src.data.ghcn_format import DailyObs
    from src.two_bot.intern import build_all_time_record_bundle
    from tests.ghcn_graphic_helpers import AS_OF, STATION, source_archive

    station = STATION["station_id"]
    snapshot = ghcn._archive_snapshot(station, source_archive(), AS_OF)
    inputs = [
        DailyObs(station, date(2026, 9, 8), "TMAX", 42.2),
        DailyObs(station, date(2026, 9, 8), "TMIN", -21.2),
    ]
    thresholds, checked = ghcn._thresholds_from_verified_archive(station, inputs, snapshot)
    signals = ghcn._detect_signals_for_station(STATION, checked, thresholds)
    assert signals is not None and signals.all_time_high is not None
    native = build_all_time_record_bundle(signals.all_time_high, source="ghcn")
    assert audit_story_bundle(native).prompt_ready
    # Format integrity is not generation or publication eligibility.
    full = json.loads(json.dumps(native.to_dict(), default=lambda value: value.isoformat()))
    wire = encode_full(full)
    assert decode_wire(wire) == full
    for source in (native, retained_bundle(wire)):
        with pytest.raises(WarrantError, match="ghcn_readable_context_incomplete"):
            prepare_bundle(source)
