"""GDACS (Global Disaster Alert and Coordination System) events.

Free API, no auth required. Returns global cyclones, floods,
volcanoes, droughts, and wildfires with severity ratings.
Docs: https://www.gdacs.org/Knowledge/models.aspx
"""

from dataclasses import dataclass, field
from datetime import date, datetime
import math
import xml.etree.ElementTree as ET

import requests

from src.data._freshness import assert_freshness, newest_freshness_date, parse_freshness_date
from src.data._http import fetch_with_retry
from src.data._witness import tag_source_leg, with_witness
from src.data import jtwc, nhc, usgs_quakes
from src.data.cyclones import CycloneAdvisory
from src.data.source_status import SourceFetchError
from src.data.usgs_quakes import SignificantEarthquakeEvent

GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"
GDACS_GEORSS_URL = "https://www.gdacs.org/xml/rss.xml"
GDACS_SUBTYPE_LEG = "subtype_witnesses"
GDACS_GEORSS_LEG = "georss"
MAX_GEORSS_BYTES = 2_000_000
MAX_GEORSS_ITEMS = 1_000

# Event types GDACS tracks
EVENT_TYPES = {
    "TC": "Tropical Cyclone",
    "FL": "Flood",
    "EQ": "Earthquake",
    "VO": "Volcano",
    "DR": "Drought",
    "WF": "Wildfire",
}


@dataclass
class GlobalDisasterEvent:
    disaster_type: str
    name: str
    country: str
    severity: str  # Red, Orange, Green
    description: str
    event_id: str
    # Rich fields for sharper tweet generation:
    alert_score: float = 0.0
    severity_value: float = 0.0  # wind speed for TC (km/h), magnitude for EQ, etc.
    severity_unit: str = ""
    population_affected: int = 0
    source_leg: str | None = None  # witness leg that served (R-00); None = primary
    # Set only by the adapter that actually supplied this event. Hand-created
    # legacy events cannot infer provenance from their display name/event ID.
    source_product: str = ""
    source_url: str = ""
    source_event_id: str = ""
    source_provenance: dict = field(default_factory=dict)


class DisasterBatch(list[GlobalDisasterEvent]):
    """Keep feed diagnostics even when no event meets the requested alert tier."""

    def __init__(self, events, *, source_diagnostics):
        super().__init__(events)
        self.source_diagnostics = source_diagnostics


# Saffir-Simpson-ish thresholds in km/h for cyclone intensity tiers.
# When a cyclone crosses a tier, it generates a new event_id so the
# strengthening storm gets a fresh draft instead of being deduplicated.
_CYCLONE_TIERS_KMH = [0, 119, 154, 178, 209, 252]  # TS, Cat1, Cat2, Cat3, Cat4, Cat5


def _intensity_tier(event_type_code: str, severity_value: float) -> str:
    """Return a dedup key segment based on event intensity.

    Tropical cyclones: tier changes when wind speed crosses a Saffir-Simpson
    boundary, so a strengthening storm gets re-drafted.
    Other events: date-based (one draft per calendar day).
    """
    if event_type_code == "TC" and severity_value > 0:
        tier = 0
        for i, threshold in enumerate(_CYCLONE_TIERS_KMH):
            if severity_value >= threshold:
                tier = i
        return f"tier{tier}"
    # Non-evolving events: one per calendar day
    return date.today().isoformat()


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _events_from_features(
    features: list[dict],
    *,
    min_level: int,
    severity_order: dict[str, int],
) -> list[GlobalDisasterEvent]:
    events = []
    for feature in features:
        props = feature.get("properties", {})

        alert_level = props.get("alertlevel", "Green")
        if severity_order.get(alert_level, 0) < min_level:
            continue

        event_type_code = props.get("eventtype", "")
        event_type = EVENT_TYPES.get(event_type_code, event_type_code)
        name = props.get("name", "Unknown")
        country = props.get("country", "Unknown")
        description = props.get("description", "")
        gdacs_id = props.get("eventid", "")

        # Rich data — GDACS severity.value is wind speed (km/h) for cyclones,
        # magnitude for earthquakes, etc.
        severity_obj = props.get("severitydata") or props.get("severity") or {}
        if isinstance(severity_obj, dict):
            severity_value = _safe_float(severity_obj.get("severity"))
            severity_unit = str(severity_obj.get("severityunit", ""))
        else:
            severity_value = 0.0
            severity_unit = ""

        alert_score = _safe_float(props.get("alertscore", 0))
        population_affected = _safe_int(props.get("population", 0))

        # Evolving events (cyclones) get a new event_id when they cross
        # an intensity tier, so strengthening storms get re-drafted.
        # Static events (earthquakes) keep date-based dedup.
        intensity_tier = _intensity_tier(event_type_code, severity_value)
        event_id = f"gdacs_{event_type_code}_{gdacs_id}_{intensity_tier}"

        events.append(GlobalDisasterEvent(
            disaster_type=event_type,
            name=name,
            country=country,
            severity=alert_level,
            description=description,
            event_id=event_id,
            alert_score=alert_score,
            severity_value=severity_value,
            severity_unit=severity_unit,
            population_affected=population_affected,
            source_product="gdacs-events-map",
            source_url=GDACS_URL,
            source_event_id=str(gdacs_id),
            source_provenance={key: props[key] for key in ("eventtype", "fromdate", "todate", "datemodified", "lastupdate", "date") if key in props},
        ))
    return events


_GEORSS_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "gdacs": "http://www.gdacs.org",
    "georss": "http://www.georss.org/georss",
}


def _xml_text(item: ET.Element, path: str) -> str:
    node = item.find(path, _GEORSS_NS)
    return (node.text or "").strip() if node is not None else ""


def _xml_attr_float(item: ET.Element, path: str, attr: str) -> float:
    node = item.find(path, _GEORSS_NS)
    return _safe_float(node.get(attr) if node is not None else None)


def _xml_attr_text(item: ET.Element, path: str, attr: str) -> str:
    node = item.find(path, _GEORSS_NS)
    return str(node.get(attr, "")) if node is not None else ""


def _xml_attr_int(item: ET.Element, path: str, attr: str) -> int:
    node = item.find(path, _GEORSS_NS)
    return _safe_int(node.get(attr) if node is not None else None)


def _has_georss_coordinates(item: ET.Element) -> bool:
    point = _xml_text(item, "georss:point")
    parts = point.split() if point else [
        _xml_text(item, "geo:Point/geo:lat"), _xml_text(item, "geo:Point/geo:long"),
    ]
    try:
        if len(parts) != 2:
            return False
        lat, lon = map(float, parts)
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
    except ValueError:
        return False


def _events_from_georss(
    text: str,
    *,
    min_level: int,
    severity_order: dict[str, int],
    diagnostics: dict | None = None,
) -> tuple[list[GlobalDisasterEvent], date | None]:
    if len(text.encode("utf-8")) > MAX_GEORSS_BYTES:
        raise SourceFetchError("GDACS GeoRSS schema drift: response exceeds parser byte bound")
    root = ET.fromstring(text.lstrip("\ufeff"))
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    if root.tag != "rss" or not items or len(items) > MAX_GEORSS_ITEMS:
        raise SourceFetchError("GDACS GeoRSS schema drift: missing or invalid bounded RSS item collection")
    events: list[GlobalDisasterEvent] = []
    payload_dates: list[date | datetime | int | float | str | None] = []
    alert_counts = {level: 0 for level in severity_order}
    unknown_country_count = 0
    for item in items:
        event_type_code = _xml_text(item, "gdacs:eventtype")
        alert_level = _xml_text(item, "gdacs:alertlevel")
        gdacs_id = _xml_text(item, "gdacs:eventid")
        country = _xml_text(item, "gdacs:country")
        from_date = _xml_text(item, "gdacs:fromdate")
        payload_dates.append(from_date or _xml_text(item, "gdacs:todate"))
        description = _xml_text(item, "description")
        title = _xml_text(item, "title")
        name = _xml_text(item, "gdacs:eventname") or title
        # GDACS explicitly emits an empty country element for some cyclones
        # whose affected countries are unknown. Preserve that absence; it is
        # not a malformed event and cannot imply landfall or a guessed country.
        country_unknown = (
            event_type_code == "TC" and not country
            and item.find("gdacs:country", _GEORSS_NS) is not None
        )
        required = {
            "event_type": event_type_code in EVENT_TYPES,
            "alert_level": alert_level in severity_order,
            "event_id": bool(gdacs_id),
            "country": bool(country) or country_unknown,
            "from_date": parse_freshness_date(from_date) is not None,
            "description": bool(description),
            "name": bool(name),
            "coordinates": _has_georss_coordinates(item),
        }
        missing = [field for field, valid in required.items() if not valid]
        if missing:
            raise SourceFetchError("GDACS GeoRSS insufficient GeoRSS fields: " + ", ".join(missing))
        alert_counts[alert_level] += 1
        unknown_country_count += int(country_unknown)
        if severity_order[alert_level] < min_level:
            continue

        severity_value = _xml_attr_float(item, "gdacs:severity", "value")
        severity_unit = _xml_attr_text(item, "gdacs:severity", "unit")
        alert_score = _safe_float(_xml_text(item, "gdacs:alertscore"))
        population_affected = _xml_attr_int(item, "gdacs:population", "value")
        event_type = EVENT_TYPES.get(event_type_code, event_type_code)
        intensity_tier = _intensity_tier(event_type_code, severity_value)
        event_id = f"gdacs_{event_type_code}_{gdacs_id}_{intensity_tier}"

        events.append(GlobalDisasterEvent(
            disaster_type=event_type,
            name=name,
            country=country,
            severity=alert_level,
            description=description,
            event_id=event_id,
            alert_score=alert_score,
            severity_value=severity_value,
            severity_unit=severity_unit,
            population_affected=population_affected,
            source_leg=GDACS_GEORSS_LEG,
            source_product="gdacs-georss",
            source_url=GDACS_GEORSS_URL,
            source_event_id=gdacs_id,
            source_provenance={
                "eventtype": event_type_code, "fromdate": from_date,
                "todate": _xml_text(item, "gdacs:todate"),
                "datemodified": _xml_text(item, "gdacs:datemodified"),
                "report_link": _xml_text(item, "link"),
                "source_country_known": bool(country),
                "coordinates": _xml_text(item, "georss:point") or {
                    "latitude": _xml_text(item, "geo:Point/geo:lat"),
                    "longitude": _xml_text(item, "geo:Point/geo:long"),
                },
            },
        ))
    if diagnostics is not None:
        diagnostics.update(
            source_leg=GDACS_GEORSS_LEG, feed_items_validated=len(items),
            alert_counts=alert_counts, selected_alerts=len(events),
            unknown_country_items=unknown_country_count,
            status="valid_alerts" if events else "valid_no_qualifying_alerts",
        )
    return events, newest_freshness_date(payload_dates)


def fetch_disasters(
    min_severity: str = "Red",
    *,
    strict: bool = False,
) -> list[GlobalDisasterEvent]:
    """Fetch active global disaster events from GDACS.

    Only Red alerts by default — Orange is medium severity, not extraordinary.

    Args:
        min_severity: Minimum alert level — "Red", "Orange", or "Green".
    """
    if not strict:
        return _fetch_disasters_primary(min_severity=min_severity, strict=False)
    try:
        return with_witness(
            lambda: _fetch_disasters_primary(min_severity=min_severity, strict=True),
            lambda: _fetch_subtype_witnesses(min_severity=min_severity),
            source_key="gdacs",
            leg_label=GDACS_SUBTYPE_LEG,
        )
    except (requests.RequestException, SourceFetchError) as exc:
        if isinstance(exc, SourceFetchError):
            raise
        raise SourceFetchError(f"GDACS fetch failed: {exc}") from exc


def _fetch_disasters_primary(
    min_severity: str = "Red",
    *,
    strict: bool = False,
) -> list[GlobalDisasterEvent]:
    severity_order = {"Green": 0, "Orange": 1, "Red": 2}
    min_level = severity_order.get(min_severity, 1)

    try:
        resp = fetch_with_retry(GDACS_URL, timeout=30, attempts=3, backoff_base=1.0)
        data = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("features"), list) or not data["features"]:
            raise ValueError("GDACS JSON schema drift: missing or empty feature collection")
        features = data["features"]
        if any(not isinstance(row, dict) or not isinstance(row.get("properties"), dict) for row in features):
            raise ValueError("GDACS JSON schema drift: invalid feature properties")
        if any(not all(row["properties"].get(field) for field in ("eventtype", "eventid", "alertlevel")) for row in features):
            raise ValueError("GDACS JSON schema drift: missing event identity or alert level")
        events = _events_from_features(
            features,
            min_level=min_level,
            severity_order=severity_order,
        )
        if newest_date := newest_freshness_date([
            (feature.get("properties", {}) or {}).get("fromdate")
            or (feature.get("properties", {}) or {}).get("datemodified")
            or (feature.get("properties", {}) or {}).get("lastupdate")
            or (feature.get("properties", {}) or {}).get("date")
            for feature in features
        ]):
            assert_freshness(newest_date, "gdacs", max_age_days=3)
        return events

    except (requests.RequestException, ValueError, KeyError) as exc:
        try:
            diagnostics = {"primary_error_class": type(exc).__name__}
            resp = fetch_with_retry(
                GDACS_GEORSS_URL, timeout=30, attempts=3, backoff_base=1.0
            )
            events, newest_date = _events_from_georss(
                resp.text,
                min_level=min_level,
                severity_order=severity_order,
                diagnostics=diagnostics,
            )
            print("[gdacs] served by georss fallback")
        except (requests.RequestException, ValueError, ET.ParseError, SourceFetchError) as georss_exc:
            if isinstance(georss_exc, (SourceFetchError, ET.ParseError)):
                raise SourceFetchError(f"GDACS GeoRSS schema drift: {georss_exc}") from georss_exc
            if strict:
                raise SourceFetchError(
                    f"GDACS fetch failed: {exc}; GeoRSS fallback failed: {georss_exc}"
                ) from georss_exc
            return []
        if newest_date:
            assert_freshness(newest_date, "gdacs", max_age_days=3)
        return DisasterBatch(events, source_diagnostics=diagnostics)


def _fetch_subtype_witnesses(min_severity: str) -> list[GlobalDisasterEvent]:
    """Independent subtype witnesses for GDACS outage coverage.

    ReliefWeb remains blocked on appname approval, so this witness covers only
    the GDACS subtypes that already have verified official feeds in the repo:
    USGS significant earthquakes and NHC/JTWC active cyclones.
    """
    errors: list[str] = []
    events: list[GlobalDisasterEvent] = []

    try:
        events.extend(
            _quake_to_gdacs_event(quake)
            for quake in usgs_quakes.fetch_significant_earthquakes(strict=True)
        )
    except (requests.RequestException, SourceFetchError) as exc:
        errors.append(f"usgs_quakes: {exc}")

    for source_name, fetch_fn in (
        ("nhc", nhc.fetch_active_cyclones),
        ("jtwc", jtwc.fetch_active_cyclones),
    ):
        try:
            events.extend(_cyclone_to_gdacs_event(advisory) for advisory in fetch_fn(strict=True))
        except (requests.RequestException, SourceFetchError) as exc:
            errors.append(f"{source_name}: {exc}")

    severity_order = {"Green": 0, "Orange": 1, "Red": 2}
    min_level = severity_order.get(min_severity, 1)
    filtered = [
        event for event in events
        if event is not None and severity_order.get(event.severity, 0) >= min_level
    ]
    if filtered:
        return tag_source_leg(filtered, GDACS_SUBTYPE_LEG)
    if errors and len(errors) >= 3:
        raise SourceFetchError(
            "GDACS subtype witnesses failed: " + "; ".join(errors)
        )
    return []


def _quake_to_gdacs_event(quake: SignificantEarthquakeEvent) -> GlobalDisasterEvent:
    severity = _quake_severity(quake)
    return GlobalDisasterEvent(
        disaster_type="Earthquake",
        name=quake.title or f"M {quake.magnitude:.1f} earthquake",
        country=quake.place or "Unknown",
        severity=severity,
        description=(
            "USGS significant earthquake feed"
            + (f"; PAGER alert {quake.alert}" if quake.alert else "")
        ),
        event_id=f"gdacs_EQ_usgs_{quake.usgs_id}_{date.today().isoformat()}",
        alert_score=float(quake.significance or 0),
        severity_value=quake.magnitude,
        severity_unit="M",
        population_affected=0,
        source_product="usgs-significant-earthquake",
        source_url=quake.url or usgs_quakes.USGS_SIGNIFICANT_DAY_URL,
        source_event_id=quake.usgs_id,
        source_provenance={"event_time": quake.time, "event_updated": quake.updated},
    )


def _quake_severity(quake: SignificantEarthquakeEvent) -> str:
    alert = (quake.alert or "").lower()
    if alert == "red":
        return "Red"
    if alert == "orange":
        return "Orange"
    if quake.magnitude >= 7.5 and (quake.tsunami or (quake.significance or 0) >= 1000):
        return "Red"
    if quake.magnitude >= 7.0:
        return "Orange"
    return "Green"


def _cyclone_to_gdacs_event(advisory: CycloneAdvisory) -> GlobalDisasterEvent:
    severity_value_kmh = round(float(advisory.wind_kt) * 1.852, 2)
    category = advisory.category
    severity = "Red" if category >= 4 else "Orange" if category >= 3 else "Green"
    intensity_tier = _intensity_tier("TC", severity_value_kmh)
    source = advisory.source or "cyclone"
    return GlobalDisasterEvent(
        disaster_type="Tropical Cyclone",
        name=advisory.storm_name or advisory.storm_id,
        country=advisory.basin or "Unknown",
        severity=severity,
        description=(
            f"{source.upper()} active cyclone advisory"
            + (f" {advisory.advisory_number}" if advisory.advisory_number else "")
        ),
        event_id=f"gdacs_TC_{source}_{advisory.storm_id}_{intensity_tier}",
        alert_score=float(category),
        severity_value=severity_value_kmh,
        severity_unit="km/h",
        population_affected=0,
        source_product=f"{advisory.source}-cyclone-advisory" if advisory.source else "",
        source_url=advisory.public_advisory_url,
        source_event_id=advisory.storm_id,
        source_provenance={"issued_at": advisory.issued_at, "advisory_number": advisory.advisory_number,
                           "original_source_leg": advisory.source_leg},
    )
