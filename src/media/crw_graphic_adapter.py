"""Offline CRW sample-to-graphic warrant. No fetch, model, store or approval.

Only the existing primary ERDDAP warm-anomaly event is supported. Retained source
bytes must match the bundle; their acquisition times are separate caller assertions,
not authentication of the later transfer reported by the production bundle.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math

from src.data import crw_contract as source
from src.data.ocean_sst_anomaly import (
    REGION_REGISTRY,
    RegionalSSTAnomalyEvent,
    _build_url,
    _detect_tier,
)
from src.data.source_status import SourceFetchError
from src.editorial.revisions import fingerprint
from src.media.temperature_graphic_adapter import _StoredBundle, story_bundle_snapshot
from src.two_bot.intern.marine import build_regional_sst_anomaly_bundle

TEMPLATE = "crw_regional_anomaly"
TEMPLATE_VERSION = "p31-crw-anomaly-1"
ADAPTER_VERSION = "p31-crw-erddap-1"
PACKET_LIMIT = 500_000
METHODOLOGY = "https://coralreefwatch.noaa.gov/product/5km/methodology.php"
CLIMATOLOGY = "CRW daily climatology: 1985–1990 + 1993 reference"


def _require(condition, reason):
    if not condition:
        raise ValueError("CRW graphic withheld: " + reason)


def _packet(packet, expected_sha):
    _require(
        isinstance(packet, dict)
        and set(packet)
        == {
            "schema_version",
            "csv_utf8",
            "metadata_utf8",
            "csv_retrieved_at",
            "metadata_retrieved_at",
        },
        "retained source packet fields differ",
    )
    _require(
        type(packet["schema_version"]) is int and packet["schema_version"] == 1,
        "unsupported retained source packet",
    )
    _require(
        len(json.dumps(packet, allow_nan=False, ensure_ascii=False).encode("utf-8"))
        <= PACKET_LIMIT,
        "retained source packet exceeds byte bound",
    )
    _require(fingerprint(packet) == expected_sha, "obsolete retained source packet binding")
    bodies = []
    for name, limit in (("csv_utf8", 400_000), ("metadata_utf8", 100_000)):
        _require(isinstance(packet[name], str), "source bodies must be UTF-8 text")
        body = packet[name].encode("utf-8")
        _require(0 < len(body) <= limit, "source body exceeds byte bound")
        bodies.append(body)
    return bodies


def _project(bundle, packet, expected_bundle_sha256, expected_packet_sha256, synthetic):
    snapshot = story_bundle_snapshot(bundle)
    _require(fingerprint(snapshot) == expected_bundle_sha256, "obsolete bundle binding")
    _require(snapshot["signal_kind"] == "regional_sst_anomaly", "unsupported signal")
    csv_body, metadata_body = _packet(packet, expected_packet_sha256)
    event = RegionalSSTAnomalyEvent(**deepcopy(snapshot["raw_signal_dump"]))
    _require(
        event.source_leg is None and source.qualified_provenance(event),
        "only a qualified primary ERDDAP regional event is supported",
    )
    p = event.provenance
    assert p is not None  # Required by qualified_provenance, never a fallback.
    region = next(r for r in REGION_REGISTRY if r.slug == event.region_slug)
    sample = source.decode_csv(csv_body.decode("utf-8"), region)
    metadata = source.metadata_contract(metadata_body)
    metadata.update(
        response_bytes=len(metadata_body), retrieved_at=p["primary_metadata"]["retrieved_at"]
    )
    _require(
        fingerprint(metadata) == fingerprint(p["primary_metadata"]),
        "retained metadata differs from bundle provenance",
    )
    stamp = source.product_time(sample.timestamp)
    _require(
        source.product_time(metadata["first_product_time"])
        <= stamp
        <= source.product_time(metadata["last_product_time"]),
        "sample time is outside retained metadata",
    )
    _require(
        stamp
        <= source.product_time(packet["metadata_retrieved_at"])
        <= source.product_time(packet["csv_retrieved_at"]),
        "invalid retained acquisition order",
    )
    _require(len(sample.cells) >= 10, "insufficient valid sample")
    weights = [math.cos(math.radians(lat)) for lat, _ in sample.cells]
    mean = math.fsum(
        value * weight for (_, value), weight in zip(sample.cells, weights)
    ) / math.fsum(weights)
    _require(
        type(event.tier) is int and event.tier == _detect_tier(mean),
        "sample does not qualify for its warm-anomaly event tier",
    )
    _require(
        event.event_id == f"sst_anom_{region.slug}_tier{event.tier}_{sample.timestamp[:10]}",
        "event identity differs from the sampled region/date/tier",
    )
    reconstructed = source.provenance(
        body=csv_body,
        url=_build_url(region),
        retrieved_at=p["retrieved_at"],
        timestamp=sample.timestamp,
        region=region,
        mean=round(mean, 2),
        valid_cells=len(sample.cells),
        total_cells=sample.total_cells,
        sampled_bounds=sample.sampled_bounds,
        leg="coastwatch_erddap",
        metadata=metadata,
    )
    _require(
        fingerprint(reconstructed) == fingerprint(p),
        "source bytes/calculation differ from the retained claim",
    )
    rebuilt = story_bundle_snapshot(build_regional_sst_anomaly_bundle(event))
    _require(
        fingerprint(rebuilt) == fingerprint(snapshot),
        "bundle changes source-derived claims or includes unsupported context",
    )
    return {
        "schema_version": 1,
        "synthetic": synthetic,
        "event_id": event.event_id,
        "location": region.display_name,
        "scope": "Latitude-weighted sample; not a full-grid regional average",
        "variable": "sea_surface_temperature_anomaly",
        "unit": "°C",
        "evidence_type": "satellite_analysis",
        "valid_date": event.date,
        "product_timestamp": sample.timestamp,
        "reporting_interval_known": False,
        "evidence_as_of": p["retrieved_at"],
        "value": round(mean, 2),
        "climatology": CLIMATOLOGY,
        "methodology_url": METHODOLOGY,
        "requested_bounds": p["requested_bounds"],
        "sampled_bounds": sample.sampled_bounds,
        "sample_stride_degrees": 1,
        "valid_cells": len(sample.cells),
        "total_cells": sample.total_cells,
        "excluded_cells": sample.total_cells - len(sample.cells),
        "source_product": source.PRODUCT,
        "source_url": p["source_url"],
        "input_binding": {
            "adapter_version": ADAPTER_VERSION,
            "synthetic": synthetic,
            "bundles": [{"bundle_sha256": expected_bundle_sha256, "bundle": snapshot}],
            "source_packet_sha256": expected_packet_sha256,
            "source_packet": deepcopy(packet),
        },
    }


def crw_graphic_spec(
    bundle, source_packet, *, expected_bundle_sha256, expected_packet_sha256, synthetic
):
    """Recompute exact source claims and retain both complete inputs for review."""
    from src.media.evidence_graphic import validate_graphic

    try:
        _require(type(synthetic) is bool, "synthetic status must be explicit")
        evidence = _project(
            bundle, source_packet, expected_bundle_sha256, expected_packet_sha256, synthetic
        )
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
        StopIteration,
        SourceFetchError,
    ) as exc:
        raise ValueError("CRW graphic withheld: malformed or unsupported source warrant") from exc


def validate_crw_adapter_binding(evidence):
    try:
        binding = evidence["input_binding"]
        _require(
            binding["adapter_version"] == ADAPTER_VERSION and len(binding["bundles"]) == 1,
            "unsupported adapter or input count",
        )
        row = binding["bundles"][0]
        projected = _project(
            _StoredBundle(row["bundle"]),
            binding["source_packet"],
            row["bundle_sha256"],
            binding["source_packet_sha256"],
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
        StopIteration,
        SourceFetchError,
    ) as exc:
        raise ValueError("CRW graphic withheld: malformed adapter input binding") from exc


def signed_anomaly(value):
    """Two decimals, explicit sign, no spurious minus sign for rounded zero."""
    rounded = round(value, 2)
    return f"{rounded:+.2f}" if rounded else "0.00"


def anomaly_axis_limit(value):
    return max(5, math.ceil(abs(value)))


def anomaly_alt_text(evidence):
    prefix = "SYNTHETIC DEMONSTRATION; no actual weather. " if evidence["synthetic"] else ""
    packet = evidence["input_binding"]["source_packet"]
    return (
        prefix
        + f"Sea-surface temperature anomaly: {signed_anomaly(evidence['value'])}°C for {evidence['location']} "
        f"on product date {evidence['valid_date']}. Satellite analysis from NOAA Coral Reef Watch v3.1. "
        f"{evidence['climatology']}; not the 1991–2020 average. "
        f"Cos-latitude-weighted mean of {evidence['valid_cells']} valid / {evidence['total_cells']} sampled cells; "
        f"{evidence['excluded_cells']} excluded (missing, masked or outside the accepted range; classes unresolved). "
        f"Every twentieth native 0.05-degree grid cell, a 1-degree stride; no interpolation or full-grid regional mean. "
        f"Requested bounds [south,north,west,east]: {evidence['requested_bounds']}; "
        f"sampled centers: {evidence['sampled_bounds']}, degrees north/east. "
        f"Bar extends from zero on a symmetric ±{anomaly_axis_limit(evidence['value'])}°C axis. "
        "Anomaly is relative to the product's daily climatology, not absolute SST, a historical record or an ENSO classification. "
        f"Product timestamp {evidence['product_timestamp']} is not a verified measurement interval. "
        f"Bundle reports retrieval {evidence['evidence_as_of']}; retained matching CSV acquired {packet['csv_retrieved_at']}, "
        f"metadata {packet['metadata_retrieved_at']}. Acquisition times are caller-supplied, not transfer attestations. "
        f"Historical review only; source freshness and pixel truth are not independently certified. {evidence['methodology_url']}"
    )
