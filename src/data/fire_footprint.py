"""GWIS fire footprint data — cumulative burned area per fire complex.

Complements FIRMS (point detections, "is there a fire at lat/lon?") by
answering the scale question: "how many hectares has this complex burned?"

Source decision (2026-04-20): GWIS (https://gwis.jrc.ec.europa.eu/) was
evaluated first per the plan. Recon confirmed GWIS publishes only WMS map
layers — there is no public JSON/GeoJSON endpoint suitable for programmatic
per-complex burn-area queries. Pivoted to NIFC (National Interagency Fire
Center) WFIGS API per the plan's explicit fallback guidance. NIFC is
US-only coverage; global fire footprints deferred until GWIS publishes a
JSON endpoint.

TODO: revisit GWIS if they publish a JSON API for per-complex burned area.
"""

import requests

from dataclasses import dataclass
from datetime import date, datetime, timezone

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
    ",FireDiscoveryDateTime,UniqueFireIdentifier,IrwinID"
    "&f=json"
    "&resultRecordCount=2000"
)

HECTARES_FLOOR = TIERS_HECTARES[0]

_ACRES_PER_HECTARE = 2.47105


def _safe_float(value) -> float:
    """Convert value to float, returning 0.0 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_start_date(raw) -> date | None:
    """Parse FireDiscoveryDateTime (Unix milliseconds epoch) to a date.

    ArcGIS returns timestamps as integer milliseconds since epoch.
    Returns None if value is missing, zero, or unparseable.
    """
    if not raw:
        return None
    try:
        ms = float(raw)
        if ms <= 0:
            return None
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def fetch_active_fire_perimeters() -> list["FireComplex"]:
    """Fetch active wildfire complexes from NIFC WFIGS with burn area >= floor.

    Source: NIFC (National Interagency Fire Center) WFIGS ArcGIS Feature
    Service. US-only coverage. Open API, no authentication required.

    Returns [] on any network, parse, or shape error — a source failure
    must never take the alert cycle down.
    """
    try:
        resp = requests.get(GWIS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    complexes: list[FireComplex] = []
    for feature in data.get("features", []) or []:
        try:
            attrs = feature.get("attributes", {}) or {}

            # complex_id: prefer UniqueFireIdentifier, fall back to IrwinID
            complex_id = str(attrs.get("UniqueFireIdentifier") or "").strip()
            if not complex_id:
                complex_id = str(attrs.get("IrwinID") or "").strip()
            if not complex_id:
                continue

            # name: prefer CpxName when non-empty, else IncidentName
            cpx_name = (attrs.get("CpxName") or "").strip() or None
            inc_name = (attrs.get("IncidentName") or "").strip() or None
            name = cpx_name or inc_name or None

            # region: strip "US-" prefix from POOState
            poo_state = str(attrs.get("POOState") or "").strip()
            region = poo_state.removeprefix("US-") if poo_state else "Unknown"

            # hectares: convert acres to hectares
            hectares = _safe_float(attrs.get("IncidentSize")) / _ACRES_PER_HECTARE

            if hectares < HECTARES_FLOOR:
                continue

            start_date = _parse_start_date(attrs.get("FireDiscoveryDateTime"))
            tier = _classify_tier(hectares)
            complexes.append(FireComplex(
                complex_id=complex_id,
                name=name,
                country="US",
                region=region,
                hectares=hectares,
                start_date=start_date,
                tier=tier,
                event_id=f"fire_footprint_{complex_id}_tier{tier}",
            ))
        except Exception:
            continue

    return complexes


def detect_tier_crossings(
    complexes: list[FireComplex],
    state: dict,
) -> list[FireComplex]:
    """Return complexes whose current tier is strictly higher than the
    last tier we've already tweeted about.

    Does not mutate state. The caller writes the updated tier only after
    a draft is successfully saved.
    """
    last_tiers = state.get("fire_complex_tiers", {}) or {}
    crossings: list[FireComplex] = []
    for fc in complexes:
        if fc.tier < 0:
            continue
        previous = last_tiers.get(fc.complex_id, -1)
        if fc.tier > previous:
            crossings.append(fc)
    return crossings
