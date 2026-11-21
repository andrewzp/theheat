"""NIFC WFIGS reported incident size, separate from a mapped burn perimeter.

Complements FIRMS thermal detections with an attributed agency size report.
The source is a point-location layer, not measured burn-perimeter geometry.

Historical source decision (2026-04-20): GWIS (https://gwis.jrc.ec.europa.eu/) was
evaluated first per the plan. Recon confirmed GWIS publishes only WMS map
layers — there is no public JSON/GeoJSON endpoint suitable for programmatic
per-complex burn-area queries. Pivoted to NIFC (National Interagency Fire
Center) WFIGS API per the plan's explicit fallback guidance. NIFC is
US-only coverage. This historical note does not verify current GWIS access;
global fire-footprint onboarding remains separate.

TODO: revisit GWIS if they publish a JSON API for per-complex burned area.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

# Hectare thresholds for per-fire-complex tweet dedup. A complex is
# eligible for a draft each time it crosses into a higher tier. Integer
# indices (not hectare values) are stored in state so we can tune the
# ladder later without retroactively re-tweeting.
TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]


@dataclass
class FireComplex:
    complex_id: str
    name: str | None
    country: str
    region: str
    hectares: float
    start_date: date | None
    tier: int
    event_id: str
    evidence: dict | None = None


def _classify_tier(hectares: float) -> int:
    """Return the highest ladder index whose threshold is <= hectares.

    Returns -1 if below the floor (not tweet-worthy). Clamps at the top
    tier for megafires beyond 1M ha.
    """
    tier = -1
    for i, threshold in enumerate(TIERS_HECTARES):
        if hectares >= threshold:
            tier = i
    return tier


# Name kept as GWIS_URL for plan-import compatibility; actual source is NIFC WFIGS.
GWIS_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services"
    "/WFIGS_Incident_Locations_Current/FeatureServer/0/query"
    "?where=IncidentTypeCategory%3D%27WF%27+AND+ActiveFireCandidate%3D1"
    "&outFields=IncidentName,CpxName,IsCpxChild,IncidentSize,POOState"
    ",FireDiscoveryDateTime,ModifiedOnDateTime_dt,UniqueFireIdentifier,IrwinID"
    ",IncidentTypeCategory,ActiveFireCandidate"
    "&f=json"
    "&resultRecordCount=2000"
    "&orderByFields=IncidentSize+DESC"
)

HECTARES_FLOOR = TIERS_HECTARES[0]

_ACRES_PER_HECTARE = 2.47105
SOURCE_PRODUCT = "nifc-wfigs-reported-incident-size-v1"
KIND = "reported_fire_incident_size"
REPORT_SCHEMA = "nifc-incident-size-capture-v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_AGE_DAYS = 4
IDENTITY_SCHEMA = "nifc-source-memory/v1"


def report_record_identity(attrs: dict) -> dict:
    """One source-declared namespace, not physical-incident continuity.

    Keep the parser's existing preference and normalization. An invalid truthy
    preferred identifier must not silently borrow the fallback identifier.
    """
    identifier = attrs.get("UniqueFireIdentifier") or attrs.get("IrwinID")
    if type(identifier) is not str or not identifier.strip() or len(identifier) > 100:
        raise ValueError("identity")
    identifier = identifier.strip().strip("{}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", identifier):
        raise ValueError("identity")
    return {"schema": IDENTITY_SCHEMA, "issuer": "nifc-wfigs", "event_type": "WF",
            "identifier_kind": "UniqueFireIdentifier" if attrs.get("UniqueFireIdentifier") else "IrwinID",
            "source_event_id": identifier}


def _report_key(identity: dict) -> str:
    # Include the exact product as well as the memory identity. Neither ID
    # prefixes nor case folding can merge different full source identifiers.
    return "nifc_report_v1_" + _canonical_sha({"source_product": SOURCE_PRODUCT, **identity})


def report_tracking_key(fc: FireComplex) -> str:
    packet = validated_report(fc)
    if packet is None:
        raise ValueError("nifc_report_unverified")
    return _report_key(report_record_identity(packet["source_record"]))


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _instant(raw: Any) -> datetime | None:
    if type(raw) not in (int, float) or not math.isfinite(raw) or raw <= 0:
        return None
    try:
        return datetime.fromtimestamp(raw / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _record_values(attrs: dict, captured: datetime) -> dict:
    """Interpret this one report; another row's clock or name grants nothing."""
    if attrs.get("IsCpxChild") == 1:
        raise ValueError("child")
    if attrs.get("IncidentTypeCategory") != "WF" or type(attrs.get("ActiveFireCandidate")) is not int or attrs["ActiveFireCandidate"] != 1:
        raise ValueError("inactive_or_other_type")
    size = attrs.get("IncidentSize")
    if type(size) not in (int, float) or not math.isfinite(size) or size <= 0:
        raise ValueError("invalid_size")
    hectares = size / _ACRES_PER_HECTARE
    if hectares < HECTARES_FLOOR:
        raise ValueError("below_floor")
    identity = report_record_identity(attrs)
    identifier = identity["source_event_id"]
    region = attrs.get("POOState")
    if type(region) is not str or not region.startswith("US-"):
        raise ValueError("region")
    region = region.removeprefix("US-")
    # Reuse canonical state/territory identity, only in the collector/parser.
    from src.data.ghcn import expand_us_state
    if expand_us_state(region, "US") is None:
        raise ValueError("region")
    modified = _instant(attrs.get("ModifiedOnDateTime_dt"))
    if modified is None or modified > captured:
        raise ValueError("report_clock")
    if (captured.date() - modified.date()).days > MAX_AGE_DAYS:
        raise ValueError("stale")
    started = None
    if attrs.get("FireDiscoveryDateTime") is not None:
        started = _instant(attrs["FireDiscoveryDateTime"])
        if started is None or started > modified:
            raise ValueError("discovery_clock")
    name = attrs.get("IncidentName")
    if name is not None and (type(name) is not str or len(name) > 200 or any(ord(c) < 32 for c in name)):
        raise ValueError("name")
    name = name.strip() or None if isinstance(name, str) else None
    tier = _classify_tier(hectares)
    return {"complex_id": identifier, "name": name, "country": "US", "region": region,
            "hectares": hectares, "start_date": started.date() if started is not None else None,
            "tier": tier, "event_id": f"{_report_key(identity)}_tier{tier}"}


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validated_report(fc: FireComplex) -> dict | None:
    """Capture-time consistency, not a claim of current source or provider truth."""
    packet = fc.evidence
    try:
        if not isinstance(packet, dict) or packet.get("schema") != REPORT_SCHEMA or packet.get("source_product") != SOURCE_PRODUCT:
            return None
        if packet.get("source_url") != GWIS_URL or packet.get("measurement_interval_known") is not False:
            return None
        if packet.get("value_kind") != "reported_incident_size" or packet.get("original_unit") != "acres":
            return None
        if packet.get("evidence_type") != "official_reported_incident_size":
            return None
        if type(packet.get("source_payload_bytes")) is not int or not 0 < packet["source_payload_bytes"] <= MAX_RESPONSE_BYTES:
            return None
        digest = packet.get("source_payload_sha256")
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return None
        captured = datetime.fromisoformat(packet["retrieved_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None or captured.utcoffset() is None:
            return None
        attrs = packet["source_record"]
        if not isinstance(attrs, dict) or packet.get("source_record_sha256") != _canonical_sha(attrs):
            return None
        expected = _record_values(attrs, captured.astimezone(timezone.utc))
        if any(getattr(fc, key) != value for key, value in expected.items()):
            return None
        modified = _instant(attrs["ModifiedOnDateTime_dt"])
        if modified is None or packet.get("record_modified_at") != _utc_iso(modified):
            return None
        return deepcopy(packet)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
        return None


def _report_bundle_hold(bundle, *, historical: bool) -> str | None:
    try:
        raw = bundle.raw_signal_dump
        packet = raw["evidence"]
        captured = datetime.fromisoformat(packet["retrieved_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None or captured.utcoffset() is None:
            return "nifc_report_unverified"
        fc = FireComplex(**_record_values(packet["source_record"], captured), evidence=packet)
        if validated_report(fc) is None:
            return "nifc_report_unverified"
        # This lazy import is a pure projection, never a source fetch. It keeps
        # capture-time field semantics identical after JSON restore or expiry.
        from src.two_bot.intern.fire import build_fire_footprint_bundle
        expected = build_fire_footprint_bundle(fc)
        if historical and bundle.event_id == f"fire_footprint_{fc.complex_id}_tier{fc.tier}":
            # Exact old projection only, confined to the read-only memory
            # reader. Every other field is rebuilt and compared as before.
            expected.event_id = bundle.event_id
            expected.raw_signal_dump["event_id"] = bundle.event_id
        if any(getattr(bundle, key) != getattr(expected, key) for key in (
            "signal_kind", "event_id", "where", "when", "headline_metric", "current_facts",
            "historical_context", "country", "raw_signal_dump",
        )):
            return "nifc_report_binding_changed"
        return None
    except (TypeError, KeyError, AttributeError, ValueError, OverflowError, RecursionError):
        return "nifc_report_unverified"


def report_bundle_hold(bundle) -> str | None:
    """Current admission/check boundary; legacy IDs cannot grant authority."""
    return _report_bundle_hold(bundle, historical=False)


def historical_report_bundle_hold(bundle) -> str | None:
    """Qualified old report context only; never use for source admission."""
    return _report_bundle_hold(bundle, historical=True)


def fetch_active_fire_perimeters(*, strict: bool = False, metrics_out: dict | None = None) -> list["FireComplex"]:
    """Fetch current NIFC reported incident sizes above the existing floor.

    Source: NIFC (National Interagency Fire Center) WFIGS ArcGIS Feature
    Service. US-only coverage. Open API, no authentication required.

    Strict mode raises for an invalid/unavailable envelope. Individual rows
    cannot borrow freshness or identity; holds remain in optional diagnostics.
    """
    try:
        resp = fetch_with_retry(GWIS_URL, timeout=30, attempts=3, backoff_base=1.0, allow_redirects=False)
        wire = resp.content
        if resp.status_code != 200 or resp.url != GWIS_URL or type(wire) is not bytes or not 0 < len(wire) <= MAX_RESPONSE_BYTES:
            raise ValueError("response_identity_or_size")
        data = resp.json()
        if not isinstance(data, dict) or "error" in data or not isinstance(data.get("features"), list) or len(data["features"]) > 2000:
            raise ValueError("response_envelope")
    except Exception as exc:
        if strict:
            raise SourceFetchError("Fire footprint fetch failed: source response unavailable or invalid") from exc
        return []
    captured = datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    complexes: list[FireComplex] = []
    for feature in data.get("features", []) or []:
        try:
            attrs = feature.get("attributes") if isinstance(feature, dict) else None
            if not isinstance(attrs, dict):
                raise ValueError("record_shape")
            values = _record_values(attrs, captured)
            modified = _instant(attrs["ModifiedOnDateTime_dt"])
            assert modified is not None
            evidence = {"schema": REPORT_SCHEMA, "source_product": SOURCE_PRODUCT,
                        "source_url": GWIS_URL, "retrieved_at": _utc_iso(captured),
                        "record_modified_at": _utc_iso(modified), "measurement_interval_known": False,
                        "evidence_type": "official_reported_incident_size",
                        "value_kind": "reported_incident_size", "original_unit": "acres",
                        "source_record": deepcopy(attrs), "source_record_sha256": _canonical_sha(attrs),
                        "source_payload_sha256": hashlib.sha256(wire).hexdigest(),
                        "source_payload_bytes": len(wire)}
            complexes.append(FireComplex(**values, evidence=evidence))
        except Exception as exc:  # One malformed row cannot lend facts to another.
            reason = str(exc) if type(exc) is ValueError else "record_invalid"
            if reason not in {"child", "inactive_or_other_type", "invalid_size", "below_floor", "identity", "region", "report_clock", "discovery_clock", "stale", "name", "record_shape"}:
                reason = "record_invalid"
            counts[reason] = counts.get(reason, 0) + 1
            continue
    held = sum(value for key, value in counts.items() if key not in {"child", "inactive_or_other_type", "below_floor"})
    if metrics_out is not None:
        metrics_out.update(raw_rows=len(data["features"]), qualified_rows=len(complexes), held_rows=held,
                           row_holds=counts, coverage_truncated=bool(data.get("exceededTransferLimit")))
    if counts.get("stale") and not complexes:
        raise SourceFetchError("fire_footprint stale data: no eligible current incident report")
    return complexes


def detect_tier_crossings(
    complexes: list[FireComplex],
    state: dict,
    *,
    tracking_holds: list[str] | None = None,
) -> list[FireComplex]:
    """Return reports above the last successfully SAVED draft tier.

    No migration or ownership is inferred from legacy bare keys. Missing or
    malformed tracking and visible ambiguous legacy history hold before writing.
    This loaded-state guard is not a distributed lock on Gist.
    """
    crossings: list[FireComplex] = []
    for fc in complexes:
        if fc.tier < 0:
            continue
        previous, hold = _previous_report_tier(fc, state)
        if hold is not None:
            if tracking_holds is not None:
                tracking_holds.append(hold)
            continue
        if fc.tier > previous:
            crossings.append(fc)
    return crossings


def _previous_report_tier(fc: FireComplex, state: dict) -> tuple[int, str | None]:
    try:
        key = report_tracking_key(fc)
    except (ValueError, TypeError, KeyError):
        return -1, "nifc_report_unverified"
    tiers = state.get("fire_complex_tiers")
    if type(tiers) is not dict:
        return -1, "nifc_tier_tracking_unavailable"
    if fc.complex_id in tiers:
        return -1, "nifc_legacy_tier_namespace_ambiguous"
    legacy_prefix = f"fire_footprint_{fc.complex_id}_tier"
    current_prefix = f"{key}_tier"
    posted = state.get("posted_events")
    drafts = state.get("drafts")
    memory = state.get("memory")
    ledger = state.get("publish_ledger")
    if (type(posted) is not list or type(drafts) is not list or type(memory) is not dict
            or type(ledger) is not dict):
        return -1, "nifc_tier_tracking_unavailable"
    if any(type(event) is not str or not event for event in posted) or any(type(event) is not str or not event for event in ledger):
        return -1, "nifc_tier_tracking_unavailable"
    event_ids = list(posted) + list(ledger)
    for rows in (drafts, memory.get("shipped_tweets"), memory.get("ongoing_events"), list(ledger.values())):
        if type(rows) is not list:
            return -1, "nifc_tier_tracking_unavailable"
        for row in rows:
            if type(row) is not dict:
                return -1, "nifc_tier_tracking_unavailable"
            event = row.get("event_id")
            family = row.get("type", row.get("signal_kind"))
            if family in (KIND, "fire_footprint") and (type(event) is not str or not event):
                return -1, "nifc_tier_tracking_unavailable"
            event_ids.append(event)
    if any(isinstance(event, str) and event.startswith(legacy_prefix) for event in event_ids):
        return -1, "nifc_legacy_event_namespace_ambiguous"
    if key not in tiers:
        if any(isinstance(event, str) and event.startswith(current_prefix) for event in event_ids):
            return -1, "nifc_saved_tier_missing"
        return -1, None
    previous = tiers[key]
    if type(previous) is not int or not 0 <= previous < len(TIERS_HECTARES):
        return -1, "nifc_saved_tier_invalid"
    return previous, None
