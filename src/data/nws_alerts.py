"""NWS (National Weather Service) severe weather alerts.

Free API, no auth required. Returns active tornado, hurricane,
flood, and severe storm warnings across the US.
Docs: https://www.weather.gov/documentation/services-web-api
"""

from dataclasses import dataclass
from datetime import date

import requests

NWS_URL = "https://api.weather.gov/alerts/active"

# High-severity event types we care about
TRACKED_EVENTS = {
    "Tornado Warning",
    "Tornado Watch",
    "Hurricane Warning",
    "Hurricane Watch",
    "Tropical Storm Warning",
    "Flash Flood Emergency",
    "Flash Flood Warning",
    "Severe Thunderstorm Warning",
    "Extreme Wind Warning",
    "Storm Surge Warning",
    "Blizzard Warning",
    "Ice Storm Warning",
}


@dataclass
class SevereWeatherAlert:
    event_type: str
    area: str
    severity: str
    headline: str
    event_id: str


def fetch_alerts() -> list[SevereWeatherAlert]:
    """Fetch active severe weather alerts from NWS."""
    try:
        resp = requests.get(
            NWS_URL,
            params={"status": "actual", "message_type": "alert"},
            headers={
                "User-Agent": "(theheat-bot, contact@theheat.app)",
                "Accept": "application/geo+json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        alerts = []
        seen_events = set()

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            event = props.get("event", "")

            if event not in TRACKED_EVENTS:
                continue

            severity = props.get("severity", "Unknown")
            area = props.get("areaDesc", "Unknown area")
            headline = props.get("headline", "")
            nws_id = props.get("id", "")

            # Deduplicate by event type + area (NWS sends many alerts per storm)
            dedup_key = f"{event}_{_simplify_area(area)}"
            if dedup_key in seen_events:
                continue
            seen_events.add(dedup_key)

            # Use NWS-provided ID for stable dedup; fall back to position-based
            if nws_id:
                event_id = f"nws_{nws_id}"
            else:
                event_id = f"nws_{event.replace(' ', '_').lower()}_{date.today().isoformat()}_{len(alerts)}"

            alerts.append(SevereWeatherAlert(
                event_type=event,
                area=_simplify_area(area),
                severity=severity,
                headline=headline,
                event_id=event_id,
            ))

        return alerts

    except (requests.RequestException, ValueError, KeyError):
        return []


def _simplify_area(area: str) -> str:
    """Simplify NWS area descriptions (they can be very long lists of counties)."""
    # NWS areas look like "Tulsa, OK; Rogers, OK; Creek, OK; ..."
    # Take first area and state
    parts = area.split(";")
    if len(parts) <= 2:
        return area.strip()
    # Return first county + state with count
    first = parts[0].strip()
    return f"{first} and {len(parts) - 1} other areas"
