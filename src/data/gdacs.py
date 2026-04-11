"""GDACS (Global Disaster Alert and Coordination System) events.

Free API, no auth required. Returns global cyclones, floods,
volcanoes, droughts, and wildfires with severity ratings.
Docs: https://www.gdacs.org/Knowledge/models.aspx
"""

from dataclasses import dataclass
from datetime import date

import requests

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


def fetch_disasters(min_severity: str = "Red") -> list[GlobalDisasterEvent]:
    """Fetch active global disaster events from GDACS.

    Only Red alerts by default — Orange is medium severity, not extraordinary.

    Args:
        min_severity: Minimum alert level — "Red", "Orange", or "Green".
    """
    severity_order = {"Green": 0, "Orange": 1, "Red": 2}
    min_level = severity_order.get(min_severity, 1)

    try:
        resp = requests.get(GDACS_URL, timeout=30)
        resp.raise_for_status()
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

            event_id = f"gdacs_{event_type_code}_{gdacs_id}_{date.today().isoformat()}"

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

    except (requests.RequestException, ValueError, KeyError):
        return []
