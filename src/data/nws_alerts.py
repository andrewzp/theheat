"""NWS (National Weather Service) severe weather alerts.

Free API, no auth required.
Docs: https://www.weather.gov/documentation/services-web-api

Editorial note: We ONLY track the rarest, genuinely-newsworthy tiers.
Tornado warnings in tornado alley in April are routine — we skip them.
The remaining events are either Emergency-tier (catastrophic) or
hurricane-related (rare by definition).
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

NWS_URL = "https://api.weather.gov/alerts/active"

# ONLY truly rare, always-newsworthy events. If it happens every week in
# some part of the US, it's not in this list. Tornado Warnings in tornado
# alley in April are routine — we skip them and only keep Tornado Emergency.
TRACKED_EVENTS = {
    "Hurricane Warning",      # Hurricanes themselves are rare, each one is news
    "Typhoon Warning",        # Same cyclone warning family in the western Pacific
    "Extreme Wind Warning",   # Only issued for major hurricane eyewalls (115+ mph)
    "Storm Surge Warning",    # Hurricane-specific, rare
    # Winter-tier extremes (rare, high-impact, not the routine Winter Storm Warning):
    "Blizzard Warning",       # Sustained 35+ mph winds + <1/4 mi visibility for 3+ hrs
    "Ice Storm Warning",      # 1/4+ inch ice accumulation — regional havoc
    "Extreme Cold Warning",   # NWS' upper-tier dangerous-cold designation
    # Heat-tier extreme. Overlaps Open-Meteo detection somewhat, but NWS
    # issues this only at genuinely dangerous levels (heat index 115F+).
    "Extreme Heat Warning",
}


@dataclass
class SevereWeatherAlert:
    event_type: str
    area: str
    severity: str
    headline: str
    event_id: str
    description: str = ""
    max_wind_gust: str = ""   # e.g. "75 mph"
    max_hail_size: str = ""   # e.g. "2.00 IN"
    tornado_detection: str = ""  # "RADAR INDICATED" or "OBSERVED"
    sender_name: str = ""     # e.g. "NWS Topeka KS"
    source_evidence: dict | None = None


def _typhoon_warning(props: dict) -> bool:
    """Retain the official warning designation; never infer observed winds."""
    if not (props.get("event") == "Typhoon Warning" and props.get("category") == "Met"
            and props.get("status") == "Actual" and props.get("messageType") in ("Alert", "Update")
            and isinstance(props.get("id"), str) and props["id"]
            and isinstance(props.get("areaDesc"), str) and props["areaDesc"].strip()):
        return False
    if props["messageType"] == "Update":
        refs = props.get("references")
        return (isinstance(refs, list) and bool(refs)
                and all(isinstance(r, dict) and isinstance(r.get("identifier"), str)
                        and bool(r["identifier"]) and r["identifier"] != props["id"] for r in refs))
    return True


def fetch_alerts(*, strict: bool = False) -> list[SevereWeatherAlert]:
    """Fetch active severe weather alerts from NWS."""
    try:
        resp = fetch_with_retry(
            NWS_URL,
            params={"status": "actual", "message_type": "alert,update"},
            headers={
                "User-Agent": "(theheat-bot, contact@theheat.app)",
                "Accept": "application/geo+json",
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
        data = resp.json()
        from src.commands.schema import utc_text
        from src.media.published_radar import rare_tornado, source_envelope
        captured_at = utc_text(datetime.now(timezone.utc))

        alerts: list[SevereWeatherAlert] = []
        payload_dates = []
        seen_events = set()
        # CAP references, not feed order, identify replaced typhoon messages.
        typhoon_features: dict[str, dict] = {}
        conflicting_ids = set()
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            if _typhoon_warning(props):
                identity = props["id"]
                if identity in typhoon_features and feature != typhoon_features[identity]:
                    conflicting_ids.add(identity)
                else:
                    typhoon_features[identity] = feature
        typhoons = [f["properties"] for identity, f in typhoon_features.items()
                    if identity not in conflicting_ids]
        superseded = {r["identifier"] for p in typhoons if p["messageType"] == "Update"
                      for r in p["references"]}
        typhoon_areas = Counter(p["areaDesc"]
                               for p in typhoons if p["id"] not in superseded)

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            payload_dates.append(
                props.get("sent") or props.get("effective") or props.get("onset")
            )
            event = props.get("event", "")

            emergency = rare_tornado(props)
            typhoon = _typhoon_warning(props)
            if event == "Typhoon Warning" and (
                not typhoon or props["id"] in superseded or props["id"] in conflicting_ids
                or typhoon_areas[props["areaDesc"]] != 1
            ):
                continue
            if not emergency and not typhoon and (event not in TRACKED_EVENTS or props.get("messageType", "Alert") != "Alert"):
                continue

            severity = props.get("severity", "Unknown")
            area = props.get("areaDesc", "Unknown area")
            headline = props.get("headline", "")
            description = props.get("description", "") or ""
            sender_name = props.get("senderName", "") or ""
            nws_id = props.get("id", "")

            # Rich structured parameters — NWS includes wind gusts, hail size, tornado type
            parameters = props.get("parameters", {}) or {}
            max_wind_gust = _first_param(parameters, "maxWindGust")
            max_hail_size = _first_param(parameters, "maxHailSize")
            tornado_detection = _first_param(parameters, "tornadoDetection")

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
                description=description[:500],  # cap description length
                max_wind_gust=max_wind_gust,
                max_hail_size=max_hail_size,
                tornado_detection=tornado_detection,
                sender_name=sender_name,
                source_evidence=source_envelope(feature, captured_at),
            ))

        if newest_date := newest_freshness_date(payload_dates):
            assert_freshness(newest_date, "nws_alerts", max_age_days=1)
        return alerts

    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"NWS alerts fetch failed: {exc}") from exc
        return []


def _first_param(parameters: dict, key: str) -> str:
    """NWS parameters are dict[str, list]. Return the first value or empty string."""
    val = parameters.get(key)
    if isinstance(val, list) and val:
        return str(val[0])
    if isinstance(val, str):
        return val
    return ""


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
