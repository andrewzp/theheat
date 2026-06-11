"""GDACS (Global Disaster Alert and Coordination System) events.

Free API, no auth required. Returns global cyclones, floods,
volcanoes, droughts, and wildfires with severity ratings.
Docs: https://www.gdacs.org/Knowledge/models.aspx
"""

from dataclasses import dataclass
from datetime import date

import requests

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"

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
    severity_order = {"Green": 0, "Orange": 1, "Red": 2}
    min_level = severity_order.get(min_severity, 1)

    try:
        resp = fetch_with_retry(GDACS_URL, timeout=30, attempts=3, backoff_base=1.0)
        data = resp.json()

        events = []
        for feature in data.get("features", []):
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
            ))

        return events

    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"GDACS fetch failed: {exc}") from exc
        return []
