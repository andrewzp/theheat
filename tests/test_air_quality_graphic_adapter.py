"""Invented forecast-to-chart claims and adversarial bindings; no provider calls."""

from copy import deepcopy
import hashlib
import json
import math

import pytest

from src.editorial.revisions import fingerprint
from src.media.air_quality_graphic_adapter import TEMPLATE, forecast_axis, pm25_graphic_spec
from src.media.evidence_graphic import build_alt_text, validate_graphic
from src.media.temperature_graphic_adapter import _StoredBundle
from tests.air_quality_graphic_helpers import graphic_bundle


def adapt(bundle, **changes):
    return pm25_graphic_spec(
        bundle,
        **{
            "expected_bundle_sha256": fingerprint(bundle.to_dict()),
            "expected_window_sha256": fingerprint(bundle.raw_signal_dump["forecast_window"]),
            "synthetic": True,
            **changes,
        },
    )


def reseal(window):
    core = {k: v for k, v in window.items() if k != "selected_record_sha256"}
    window["selected_record_sha256"] = hashlib.sha256(
        json.dumps(
            core, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def test_exact_sample_mean_and_distinct_grid_local_time_are_retained():
    bundle = graphic_bundle([140.1, 300.9] * 12)
    before = deepcopy(bundle)
    spec = adapt(bundle)
    e = spec["evidence"]
    assert e["values"] == [140.1, 300.9] * 12 and e["sample_mean"] == pytest.approx(220.5)
    assert e["valid_start"] == "2026-06-07T18:15:00Z"
    assert e["valid_end"] == "2026-06-08T18:15:00Z"
    assert e["grid_location"] == [27.75, 85.25]
    assert e["requested_location"]["lat"] == 27.7 and e["evidence_type"] == "model_forecast"
    alt = build_alt_text(TEMPLATE, e)
    for phrase in [
        "24 instantaneous",
        "220.5",
        "23:00",
        "not city-wide",
        "not original HTTP",
        "native resolution unknown",
        "SYNTHETIC",
        "CAMS via Open-Meteo",
    ]:
        assert phrase in alt
    assert bundle == before
    e["values"][0] = 999
    e["input_binding"]["bundles"][0]["bundle"]["where"] = "mutated"
    assert bundle == before


@pytest.mark.parametrize(
    "values",
    [
        [150.0] * 24,
        list(range(150, 174)),
        [0.0, 600.0] * 12,
        [3500.0] * 24,
        [999.9] * 24,
        [1e308] * 24,
    ],
)
def test_axis_contains_zero_and_every_sample_without_health_threshold(values):
    top, ticks = forecast_axis(values)
    assert math.isfinite(top) and top >= max(values)
    assert ticks[0] == 0 and ticks[-1] == top
    assert all(a < b for a, b in zip(ticks, ticks[1:]))
    assert len(ticks) <= 6


@pytest.mark.parametrize("field", ["expected_bundle_sha256", "expected_window_sha256"])
def test_independent_obsolete_hash_is_refused(field):
    with pytest.raises(ValueError, match="obsolete"):
        adapt(graphic_bundle(), **{field: "a" * 64})


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "null",
        "negative",
        "bool",
        "unit",
        "23hours",
        "25hours",
        "date",
        "timezone",
        "grid",
        "city",
        "mean",
        "tier",
        "kind",
    ],
)
def test_invalid_or_detached_source_cannot_become_a_chart_even_after_rehash(change):
    bundle = graphic_bundle()
    raw = bundle.raw_signal_dump
    w = raw["forecast_window"]
    if change == "missing":
        w["series"]["pm2_5"] = {"status": "missing", "unit": "μg/m³", "values": None}
    elif change in {"null", "negative", "bool"}:
        w["series"]["pm2_5"]["values"][0] = {"null": None, "negative": -1, "bool": True}[change]
    elif change == "unit":
        w["series"]["pm2_5"]["unit"] = "mg/m³"
    elif change == "23hours":
        w["hours"].pop()
    elif change == "25hours":
        w["hours"].append("2026-06-09T00:00")
    elif change == "date":
        w["hours"][0] = "2026-06-07T00:00"
    elif change == "timezone":
        w["timezone"] = "America/New_York"
    elif change == "grid":
        w["grid_location"][0] = 95
    elif change == "city":
        w["requested_location"]["city"] = "Different City"
    elif change == "mean":
        raw["pm25_24h_mean"] += 1
    elif change == "tier":
        raw["tier"] = 3
    else:
        bundle.signal_kind = "dust_event"
    reseal(w)
    with pytest.raises(ValueError):
        adapt(bundle)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "150"])
def test_nonfinite_or_string_source_is_not_coerced(value):
    bundle = graphic_bundle()
    bundle.raw_signal_dump["forecast_window"]["series"]["pm2_5"]["values"][0] = value
    with pytest.raises(ValueError):
        adapt(bundle)


@pytest.mark.parametrize(
    "field,value",
    [
        ("values", [500.0] * 24),
        ("sample_mean", 500.0),
        ("evidence_type", "observed"),
        ("timezone", "GMT"),
        ("grid_location", [0, 0]),
        ("source_product", "station readings"),
        ("scope", "Whole city exposure"),
    ],
)
def test_rehashed_plot_projection_does_not_override_the_retained_window(field, value):
    e = adapt(graphic_bundle())["evidence"]
    e[field] = value
    with pytest.raises(ValueError, match="differs from retained"):
        validate_graphic(TEMPLATE, e, expected_evidence_sha256=fingerprint(e))


@pytest.mark.parametrize("change", ["extension", "related", "station", "station_grade"])
def test_only_exact_unextended_single_source_bundle_is_supported(change):
    from src.two_bot.types import RelatedSignal

    bundle = graphic_bundle()
    if change == "related":
        bundle.related_signals = [
            RelatedSignal(
                "other",
                "dust_event",
                bundle.where,
                bundle.when,
                {"label": "dust", "value": 2000, "unit": "μg/m³"},
            )
        ]
    elif change in {"station", "station_grade"}:
        raw = bundle.raw_signal_dump
        raw.update(
            evidence_grade="model_corroborated_by_station",
            station_name="Invented station",
            station_pm25_ug_m3=170.0,
            station_distance_km=5.0,
        )
        if change == "station_grade":
            raw["evidence_grade"] = "model_estimated"
    else:
        snapshot = bundle.to_dict()
        snapshot["unreviewed_context"] = "additional claim"
        bundle = _StoredBundle(snapshot)
    with pytest.raises(ValueError):
        adapt(bundle)


@pytest.mark.parametrize("synthetic", [None, 0, "false"])
def test_synthetic_status_cannot_be_guessed(synthetic):
    with pytest.raises(ValueError, match="synthetic"):
        adapt(graphic_bundle(), synthetic=synthetic)


def test_cli_is_offline_and_refuses_replacement_and_wrong_binding(tmp_path):
    from scripts.build_pm25_graphic_spec import main

    b = graphic_bundle()
    source = tmp_path / "bundle.json"
    output = tmp_path / "spec.json"
    source.write_text(json.dumps(b.to_dict()))
    args = [
        "--bundle",
        str(source),
        "--expected-bundle-sha256",
        fingerprint(b.to_dict()),
        "--expected-window-sha256",
        fingerprint(b.raw_signal_dump["forecast_window"]),
        "--synthetic",
        "true",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    before = output.read_bytes()
    assert main(args) == 2 and output.read_bytes() == before
    args[3] = "a" * 64
    assert main(args) == 2 and output.read_bytes() == before
