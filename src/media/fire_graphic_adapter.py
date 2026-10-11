"""Offline MODIS selected-pixel graphics; no incident inference or publication."""

from __future__ import annotations

import math
from types import SimpleNamespace

from src.data.fire_evidence import fire_bundle_failures, validate_bundle
from src.data.fire_source_contract import FIRMS_PUBLIC_URL, validate_receipt
from src.data.source_status import SourceFetchError
from src.editorial.revisions import fingerprint
from src.media.temperature_graphic_adapter import _StoredBundle, story_bundle_snapshot

TEMPLATE = "modis_thermal_detections"
TEMPLATE_VERSION = "p31-modis-thermal-1"
ADAPTER_VERSION = "p31-firms-modis-1"
METHODOLOGY = "https://firms.modaps.eosdis.nasa.gov/descriptions/FIRMS_MODIS_Firehotspots.html"
_PLATFORMS = {"T": "Terra", "Terra": "Terra", "A": "Aqua", "Aqua": "Aqua"}
_BUNDLE_KEYS = {
    "signal_kind", "where", "when", "event_id", "headline_metric", "current_facts",
    "historical_context", "raw_signal_dump", "country", "related_signals",
}
_RELATED_KEYS = {
    "signal_kind", "where", "when", "event_id", "headline_metric", "country",
    "acquisition_evidence",
}


def _require(condition, reason):
    if not condition:
        raise ValueError("MODIS graphic withheld: " + reason)


def _project(bundle, expected_bundle_sha256, expected_receipt_sha256, synthetic):
    _require(type(synthetic) is bool, "synthetic status must be explicit")
    snapshot = story_bundle_snapshot(bundle)
    _require(fingerprint(snapshot) == expected_bundle_sha256, "obsolete bundle binding")
    _require(set(snapshot) <= _BUNDLE_KEYS and snapshot["signal_kind"] == "fire",
             "unsupported or extended story")
    related = snapshot.get("related_signals", [])
    _require(type(related) is list and len(related) <= 3, "one to four retained detections required")
    _require(all(type(r) is dict and set(r) == _RELATED_KEYS and r["signal_kind"] == "fire"
                 for r in related), "only receipt-bound related thermal signals are supported")
    _require(type(expected_receipt_sha256) is list and len(expected_receipt_sha256) == 1 + len(related),
             "independent receipt bindings must cover every detection in order")
    # The stored JSON contains dictionaries, while the source validator consumes
    # attribute-bearing related signals. Preserve every supplied field explicitly.
    source_view = SimpleNamespace(**{**snapshot, "related_signals": [SimpleNamespace(**r) for r in related]})
    _require(not fire_bundle_failures(source_view), "source measurement or summary does not match receipt")
    primary = validate_bundle(_StoredBundle(snapshot))
    receipts = [snapshot["raw_signal_dump"]["acquisition_provenance"],
                *[r["acquisition_evidence"] for r in related]]
    rows = [primary, *[validate_receipt(receipt) for receipt in receipts[1:]]]
    _require(all(fingerprint(receipt) == expected for receipt, expected in zip(receipts, expected_receipt_sha256)),
             "obsolete selected-receipt binding")
    _require(all(row.source_product == "MODIS_NRT" for row in rows), "only MODIS measurements are supported")
    platforms = [_PLATFORMS[row.record["satellite"]] for row in rows]
    _require(len(set(platforms)) == 1 and len({row.acquired_at for row in rows}) == 1,
             "all detections must share platform and reported UTC minute")
    identities = [snapshot["event_id"], *[r["event_id"] for r in related]]
    coordinates = [(row.lat, row.lon) for row in rows]
    _require(len(set(identities)) == len(rows) and len(set(coordinates)) == len(rows)
             and len(set(expected_receipt_sha256)) == len(rows), "duplicate or conflicting detections")
    points = [{
        "label": chr(65 + i), "role": "primary" if i == 0 else "related", "event_id": identities[i],
        "lat": row.lat, "lon": row.lon, "frp_source": row.frp,
        "source_confidence": row.confidence_value, "source_version": row.record["version"],
        "receipt_sha256": expected_receipt_sha256[i],
    } for i, row in enumerate(rows)]
    return {
        "schema_version": 1, "synthetic": synthetic, "event_id": snapshot["event_id"],
        "source_product": "MODIS_NRT", "source_url": FIRMS_PUBLIC_URL, "methodology_url": METHODOLOGY,
        "satellite": platforms[0], "instrument": "MODIS", "acquired_at": primary.acquired_at,
        "acquisition_precision": "minute", "variable": "pixel_frp", "unit": "MW",
        "scope": "Selected satellite pixel-center detections, not fire perimeters or separate-fire counts",
        "points": points,
        "input_binding": {
            "adapter_version": ADAPTER_VERSION, "synthetic": synthetic,
            "bundles": [{"bundle_sha256": expected_bundle_sha256, "bundle": snapshot}],
            "selected_receipt_sha256": list(expected_receipt_sha256),
        },
    }


def fire_graphic_spec(bundle, *, expected_bundle_sha256, expected_receipt_sha256, synthetic):
    """Retain one full story and reconstruct its selected primary/related source rows."""
    from src.media.evidence_graphic import validate_graphic

    try:
        evidence = _project(bundle, expected_bundle_sha256, expected_receipt_sha256, synthetic)
        expected = fingerprint(evidence)
        return {"template": TEMPLATE, "expected_evidence_sha256": expected,
                "evidence": validate_graphic(TEMPLATE, evidence, expected_evidence_sha256=expected)}
    except (KeyError, TypeError, AttributeError, OverflowError, UnicodeError, RecursionError, SourceFetchError) as exc:
        raise ValueError("MODIS graphic withheld: malformed or unsupported source warrant") from exc


def validate_fire_adapter_binding(evidence):
    try:
        binding = evidence["input_binding"]
        _require(binding["adapter_version"] == ADAPTER_VERSION and len(binding["bundles"]) == 1,
                 "unsupported adapter or input count")
        row = binding["bundles"][0]
        projected = _project(_StoredBundle(row["bundle"]), row["bundle_sha256"],
                             binding["selected_receipt_sha256"], evidence["synthetic"])
        _require(fingerprint(projected) == fingerprint(evidence), "graphic differs from retained source inputs")
    except (KeyError, TypeError, AttributeError, OverflowError, UnicodeError, RecursionError, SourceFetchError) as exc:
        raise ValueError("MODIS graphic withheld: malformed adapter input binding") from exc


def frp_axis(values):
    """A zero-based pixel-power scale, not a severity scale or total-fire estimate."""
    peak = max(values)
    _require(math.isfinite(peak) and peak > 0, "unrenderable or all-zero FRP scale")
    base = 10.0 ** math.floor(math.log10(peak))
    _require(base > 0, "unrenderable FRP scale")
    fraction = peak / base
    top = base * (1 if fraction <= 1 else 2 if fraction <= 2 else 5 if fraction <= 5 else 10)
    _require(math.isfinite(top) and top >= peak, "unrenderable FRP scale")
    return top


def frp_label(value):
    return f"{value:,.1f} MW"


def coordinate_label(point):
    lat, lon = point["lat"], point["lon"]
    return f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"


def fire_alt_text(evidence):
    prefix = "SYNTHETIC DEMONSTRATION; no actual weather. " if evidence["synthetic"] else ""
    points = "; ".join(
        f"{p['label']} ({p['role']}): pixel center latitude {p['lat']}, longitude {p['lon']}; "
        f"source FRP {p['frp_source']} MW; detection confidence estimate {p['source_confidence']}%; "
        f"source version {p['source_version']}"
        for p in evidence["points"]
    )
    return (
        prefix + f"Satellite heat detections, NASA FIRMS MODIS_NRT, {evidence['satellite']}/MODIS. "
        f"Reported acquisition {evidence['acquired_at']} at minute precision, not measured seconds. "
        + points + ". Bars begin at zero in retained primary/related order; no ranking of physical fires. "
        "FRP is pixel-integrated radiative power in megawatts, not temperature, burned area or "
        "total physical-fire intensity. Bar lengths use exact source values; visible FRP labels are "
        "rounded to one decimal and pixel-center coordinates to four decimals. Exact source spelling "
        "remains in the bound input. Pixel centers are not exact flame locations; scan/track dimensions "
        "and exact pixel footprints are unavailable. No perimeter or count of separate fires is established. "
        "Same source minute and platform do not establish simultaneity, the same overpass or a common incident. "
        "Detection confidence is a source quality estimate, not incident/cause/impact certainty. "
        "No cause, human impact or geocoder-location certification. Retained selected-row receipts, "
        "not original HTTP bytes or independent source authentication. Historical local preview, "
        "not a source-freshness claim, semantic review or publication approval. "
        f"Source documentation: {METHODOLOGY}."
    )
