"""Qualified NOAA-20/NOAA-21 VIIRS centers in a bounded locator; no network or incident inference.

This is its own explicit VIIRS projection. VIIRS evidence never passes through the
MODIS validator or carries a MODIS label. Locator geometry, basemap and palette
are reused from the MODIS map adapter; both shared modules are bound by exact
bytes in the evidence, so a shared-code change obsoletes every dependent binding.
Suomi NPP (retiring), NOAA HMS, mixed products/platforms/minutes and incomplete
receipts stay held. Rendering never qualifies source freshness or publication.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.data.fire_evidence import fire_bundle_failures, validate_bundle
from src.data.fire_source_contract import FIRMS_PUBLIC_URL, validate_receipt
from src.data.source_status import SourceFetchError
from src.editorial.revisions import fingerprint
from src.media import fire_map_graphic_adapter as locator
from src.media.temperature_graphic_adapter import _StoredBundle, story_bundle_snapshot

TEMPLATE = "viirs_thermal_detection_map"
TEMPLATE_VERSION = "p31-viirs-locator-1"
ADAPTER_VERSION = "p31-firms-viirs-map-1"
METHODOLOGY = "https://www.earthdata.nasa.gov/data/instruments/viirs/viirs-i-band-375-m-active-fire-data"
# Product -> (retained FIRMS satellite code, display platform). SNPP is deliberately absent.
PLATFORMS = {"VIIRS_NOAA20_NRT": ("N20", "NOAA-20"), "VIIRS_NOAA21_NRT": ("N21", "NOAA-21")}
# Retained source spelling -> exact category produced by the unchanged source contract.
CATEGORIES = {"l": "low", "n": "nominal", "h": "high"}
# Two more full-width header rows (confidence) than the MODIS map, so a shorter frame.
MAP_FRAME = (112, 354, 1032, 610)
SCOPE = "Selected satellite pixel-center detections, not fire perimeters or separate-fire counts"
_BUNDLE_KEYS = {
    "signal_kind", "where", "when", "event_id", "headline_metric", "current_facts",
    "historical_context", "raw_signal_dump", "country", "related_signals",
}
_RELATED_KEYS = {
    "signal_kind", "where", "when", "event_id", "headline_metric", "country",
    "acquisition_evidence",
}
_SHARED_CODE = ("fire_map_graphic_adapter.py", "fire_graphic_adapter.py")


def _require(condition, reason):
    if not condition:
        raise ValueError("VIIRS graphic withheld: " + reason)


def _source(bundle, expected_bundle_sha256, expected_receipt_sha256, synthetic):
    """Reconstruct every selected source row from the full retained story, in order."""
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
    # Stored JSON holds dictionaries; the unchanged source validator consumes
    # attribute-bearing related signals. Preserve every supplied field explicitly.
    source_view = SimpleNamespace(**{**snapshot, "related_signals": [SimpleNamespace(**r) for r in related]})
    _require(not fire_bundle_failures(source_view), "source measurement or summary does not match receipt")
    primary = validate_bundle(_StoredBundle(snapshot))
    receipts = [snapshot["raw_signal_dump"]["acquisition_provenance"],
                *[r["acquisition_evidence"] for r in related]]
    rows = [primary, *[validate_receipt(receipt) for receipt in receipts[1:]]]
    _require(all(fingerprint(receipt) == expected for receipt, expected in zip(receipts, expected_receipt_sha256)),
             "obsolete selected-receipt binding")
    products = {row.source_product for row in rows}
    _require(len(products) == 1 and next(iter(products)) in PLATFORMS,
             "only one NOAA-20 or NOAA-21 VIIRS product is supported")
    product = primary.source_product
    code, platform = PLATFORMS[product]
    # The source contract already enforces these; restate them so this display
    # never depends on a looser future parse of another instrument.
    _require(all(row.record["instrument"] == "VIIRS" and row.record["satellite"] == code
                 and row.confidence_kind == "categorical"
                 and CATEGORIES.get(row.record["confidence"]) == row.confidence_value
                 for row in rows), "unsupported VIIRS instrument, platform or confidence class")
    _require(len({row.acquired_at for row in rows}) == 1,
             "all detections must share product, platform and reported UTC minute")
    identities = [snapshot["event_id"], *[r["event_id"] for r in related]]
    coordinates = [(row.lat, row.lon) for row in rows]
    _require(len(set(identities)) == len(rows) and len(set(coordinates)) == len(rows)
             and len(set(expected_receipt_sha256)) == len(rows), "duplicate or conflicting detections")
    points = [{
        "label": chr(65 + i), "role": "primary" if i == 0 else "related", "event_id": identities[i],
        "lat": row.lat, "lon": row.lon, "frp_source": row.frp,
        "confidence_category": row.confidence_value, "source_confidence_code": row.record["confidence"],
        "source_version": row.record["version"], "receipt_sha256": expected_receipt_sha256[i],
    } for i, row in enumerate(rows)]
    return {
        "schema_version": 1, "synthetic": synthetic, "event_id": snapshot["event_id"],
        "source_product": product, "source_url": FIRMS_PUBLIC_URL, "methodology_url": METHODOLOGY,
        "satellite": platform, "satellite_code": code, "instrument": "VIIRS",
        "acquired_at": primary.acquired_at, "acquisition_precision": "minute",
        "variable": "pixel_frp", "unit": "MW", "confidence_kind": "categorical",
        "scope": SCOPE, "points": points,
        "input_binding": {
            "adapter_version": ADAPTER_VERSION, "synthetic": synthetic,
            "bundles": [{"bundle_sha256": expected_bundle_sha256, "bundle": snapshot}],
            "selected_receipt_sha256": list(expected_receipt_sha256),
        },
    }


def _project(bundle, bundle_sha, receipts, synthetic):
    try:
        value = _source(bundle, bundle_sha, receipts, synthetic)
    except (KeyError, TypeError, AttributeError, OverflowError, UnicodeError, RecursionError, SourceFetchError) as exc:
        raise ValueError("VIIRS graphic withheld: malformed or unsupported source warrant") from exc
    _, retained = locator.basemap()
    try:
        geometry = locator.geometry(value["points"], frame=MAP_FRAME)
    except locator.MapQualificationError:
        raise
    except ValueError as exc:
        # The shared axis helper words its refusal for MODIS; never relabel VIIRS.
        raise ValueError("VIIRS graphic withheld: unrenderable or all-zero FRP scale") from exc
    value["map"] = {
        **geometry,
        "frame": list(MAP_FRAME),
        "basemap": retained,
        "shared_code_sha256": {name: locator.digest(locator.resource(name, 128 * 1024))
                               for name in _SHARED_CODE},
    }
    return value


def viirs_map_graphic_spec(bundle, *, expected_bundle_sha256, expected_receipt_sha256, synthetic):
    """Retain one full story and reconstruct its selected primary/related VIIRS rows."""
    value = _project(bundle, expected_bundle_sha256, expected_receipt_sha256, synthetic)
    return dict(template=TEMPLATE, expected_evidence_sha256=fingerprint(value), evidence=value)


def validate_viirs_map_binding(evidence):
    try:
        binding = evidence["input_binding"]
        _require(binding["adapter_version"] == ADAPTER_VERSION and len(binding["bundles"]) == 1,
                 "unsupported adapter or input count")
        row = binding["bundles"][0]
        expected = _project(_StoredBundle(row["bundle"]), row["bundle_sha256"],
                            binding["selected_receipt_sha256"], evidence["synthetic"])
        if fingerprint(expected) != fingerprint(evidence):
            raise ValueError("Map differs from retained source or renderer resources")
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise ValueError("Malformed map evidence binding") from exc


def confidence_row(evidence):
    """Exact retained categories in source order; never the internal ranking numbers."""
    return " · ".join(f"{p['label']} {p['confidence_category']}" for p in evidence["points"])


def viirs_alt_text(evidence):
    map_ = evidence["map"]
    prefix = "SYNTHETIC DEMONSTRATION; no actual weather. " if evidence["synthetic"] else ""
    points = "; ".join(
        f"{p['label']} ({p['role']}): pixel center latitude {p['lat']}, longitude {p['lon']}; "
        f"source FRP {p['frp_source']} MW; detection confidence category {p['confidence_category']} "
        f"(source code {p['source_confidence_code']}); source version {p['source_version']}"
        for p in evidence["points"]
    )
    return (
        prefix + f"Satellite heat detections, NASA FIRMS {evidence['source_product']}, "
        f"{evidence['satellite']}/VIIRS (satellite code {evidence['satellite_code']}). "
        f"Reported acquisition {evidence['acquired_at']} at minute precision, not measured seconds. "
        + points + ". Equal-size markers retain exact source centers; A-D retain primary/related source "
        "order, not a fire ranking. Blue-to-yellow colors show pixel FRP linearly from zero to "
        + str(map_["axis_max"])
        + " MW. The exact primary A value is visible as the lead; it is not a maximum selection or a "
        "hazard classification. All exact source FRP values, confidence categories and pixel-center "
        "coordinates are listed in this description and retained input. Visible axis edge captions "
        "round to four decimals. FRP is pixel-integrated fire radiative power in megawatts from the "
        "source's hybrid 375 m/750 m VIIRS retrieval, not temperature, burned area, physical-fire "
        "intensity, severity or impact; values are never combined into a total. Detection confidence "
        "is the source's categorical low, nominal or high class shown exactly as retained; it is not a "
        "percentage, probability, numeric quality score, severity or incident/cause/impact certainty. "
        "Pixel centers of approximately 375 m nadir pixels are not exact flame locations; scan/track "
        "dimensions and exact pixel footprints are not retained. No perimeter or count of separate "
        "fires is established. Same source minute and platform do not establish simultaneity, the same "
        "overpass or a common incident. No cause, human impact or geocoder-location certification. "
        "Retained selected-row receipts, not original HTTP bytes or independent source authentication. "
        "Historical local preview, not a source-freshness claim, semantic review or publication approval. "
        f"Source documentation: {evidence['methodology_url']}. "
        "Plate carree longitude-latitude locator, not a distance or area map. "
        + (
            "Coordinate close-up: coarse coastlines omitted; world inset supplies location only. "
            if map_["context_mode"] == "coordinate_closeup"
            else "Coarse Natural Earth land outlines, not exact local boundaries. "
        )
        + ("Viewport crosses the dateline. " if map_["dateline_crossing"] else "")
        + "Natural Earth 110m land4.1.0, public domain. Small islands may be absent; absence is not "
        "evidence of water. The world inset shows location or the geographic viewport, not physical "
        "fire area. Markers are not pixel footprints or fire perimeters. Unreadable overlaps are "
        "withheld, never displaced."
    )
