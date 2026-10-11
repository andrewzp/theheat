"""Offline single-source PM2.5 forecast graphics; no fetch, model or approval."""

from __future__ import annotations

from copy import deepcopy
import math

from src.data import air_quality_contract as source
from src.data.air_quality_evidence import validate_bundle
from src.data.source_status import SourceFetchError
from src.editorial.revisions import fingerprint
from src.media.temperature_graphic_adapter import _StoredBundle, story_bundle_snapshot

TEMPLATE = "pm25_forecast_day"
TEMPLATE_VERSION = "p31-pm25-forecast-1"
ADAPTER_VERSION = "p31-cams-pm25-1"
METHODOLOGY = "https://open-meteo.com/en/docs/air-quality-api"


def _require(condition, reason):
    if not condition:
        raise ValueError("PM2.5 graphic withheld: " + reason)


def _project(bundle, expected_bundle_sha256, expected_window_sha256, synthetic):
    _require(type(synthetic) is bool, "synthetic status must be explicit")
    snapshot = story_bundle_snapshot(bundle)
    _require(fingerprint(snapshot) == expected_bundle_sha256, "obsolete bundle binding")
    _require(snapshot["signal_kind"] == "air_quality_hazard", "unsupported signal")
    raw = snapshot["raw_signal_dump"]
    _require(
        raw["evidence_grade"] == "model_estimated", "only an unextended model forecast is supported"
    )
    window = raw["forecast_window"]
    _require(fingerprint(window) == expected_window_sha256, "obsolete selected-window binding")
    totals = source.validate_window(window)
    rebuilt = story_bundle_snapshot(validate_bundle(_StoredBundle(snapshot)))
    _require(
        fingerprint(rebuilt) == fingerprint(snapshot),
        "bundle differs from its single-source reconstruction",
    )
    _require(window["series"]["pm2_5"]["status"] == "complete", "complete PM2.5 samples required")
    return {
        "schema_version": 1,
        "synthetic": synthetic,
        "event_id": snapshot["event_id"],
        "location": snapshot["where"],
        "scope": "Model forecast at the source grid point; not station measurements",
        "variable": "pm2_5",
        "unit": source.UNITS["pm2_5"],
        "evidence_type": "model_forecast",
        "valid_date": window["date"],
        "timezone": window["timezone"],
        "valid_start": window["valid_start"],
        "valid_end": window["valid_end"],
        "evidence_as_of": window["retrieved_at"],
        "requested_location": deepcopy(window["requested_location"]),
        "grid_location": deepcopy(window["grid_location"]),
        "hours": deepcopy(window["hours"]),
        "values": deepcopy(window["series"]["pm2_5"]["values"]),
        "sample_mean": totals["pm2_5"],
        "source_product": source.PRODUCT,
        "source_url": source.SOURCE_URL,
        "methodology_url": METHODOLOGY,
        "input_binding": {
            "adapter_version": ADAPTER_VERSION,
            "synthetic": synthetic,
            "bundles": [{"bundle_sha256": expected_bundle_sha256, "bundle": snapshot}],
            "selected_window_sha256": expected_window_sha256,
        },
    }


def pm25_graphic_spec(bundle, *, expected_bundle_sha256, expected_window_sha256, synthetic):
    """Recompute claims from the intact selected record and retain its full bundle."""
    from src.media.evidence_graphic import validate_graphic

    try:
        evidence = _project(bundle, expected_bundle_sha256, expected_window_sha256, synthetic)
        expected = fingerprint(evidence)
        return {
            "template": TEMPLATE,
            "expected_evidence_sha256": expected,
            "evidence": validate_graphic(TEMPLATE, evidence, expected_evidence_sha256=expected),
        }
    except (
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        UnicodeError,
        RecursionError,
        SourceFetchError,
    ) as exc:
        raise ValueError(
            "PM2.5 graphic withheld: malformed or unsupported forecast warrant"
        ) from exc


def validate_pm25_adapter_binding(evidence):
    try:
        binding = evidence["input_binding"]
        _require(
            binding["adapter_version"] == ADAPTER_VERSION and len(binding["bundles"]) == 1,
            "unsupported adapter or input count",
        )
        row = binding["bundles"][0]
        projected = _project(
            _StoredBundle(row["bundle"]),
            row["bundle_sha256"],
            binding["selected_window_sha256"],
            evidence["synthetic"],
        )
        _require(
            fingerprint(projected) == fingerprint(evidence),
            "graphic differs from retained source inputs",
        )
    except (
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        UnicodeError,
        RecursionError,
        SourceFetchError,
    ) as exc:
        raise ValueError("PM2.5 graphic withheld: malformed adapter input binding") from exc


def concentration(value):
    """One decimal for display; exact source values remain in the bound input."""
    return f"{value:,.1f}"


def forecast_axis(values):
    """Zero-anchored readable ticks without clipping, extrapolation or a health scale."""
    peak = max(values)
    _require(math.isfinite(peak) and peak > 0, "unrenderable concentration axis")
    base = 10.0 ** math.floor(math.log10(peak))
    fraction = peak / base
    step = base / 2 if fraction <= 2 else base if fraction <= 5 else base * 2
    top = math.ceil(peak / step) * step
    _require(math.isfinite(top) and top >= peak, "unrenderable concentration axis")
    return top, [i * step for i in range(round(top / step) + 1)]


def pm25_alt_text(evidence):
    window = evidence["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]
    samples = "; ".join(
        f"{h}: {concentration(v)}" for h, v in zip(evidence["hours"], evidence["values"])
    )
    prefix = "SYNTHETIC DEMONSTRATION; no actual weather. " if evidence["synthetic"] else ""
    return (
        prefix + f"PM2.5 forecast for {evidence['location']} on {evidence['valid_date']}, "
        f"local timezone {evidence['timezone']}. CAMS via Open-Meteo, automatic domain. "
        f"24 instantaneous hourly samples in μg/m³: {samples}. "
        f"Mean of these samples: {concentration(evidence['sample_mean'])} μg/m³. "
        "Displayed concentrations rounded to one decimal; exact values retained in input.json. "
        "Straight segments connect samples on a zero-anchored concentration axis; no interpolation "
        "claim between samples, no extrapolation or hourly safety threshold. "
        f"Requested location: {evidence['requested_location']}; sampled grid [latitude, longitude]: "
        f"{evidence['grid_location']}. Grid-point model forecast, not city-wide measurements or measured exposure. "
        f"Local calendar day corresponds to [{evidence['valid_start']}, {evidence['valid_end']}) UTC. "
        f"Requested {window['requested_at']}; retrieved {window['retrieved_at']}. "
        "Retained selected record, not original HTTP bytes or independent acquisition authentication. "
        "Exact model run and native resolution unknown; hourly samples do not prove hourly native output. "
        "No health-effect, cause, record or persistence claim. Historical private review, not currentness "
        f"or publication approval. Source documentation: {METHODOLOGY}."
    )
