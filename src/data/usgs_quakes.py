"""USGS significant earthquake feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError, assert_response_schema

USGS_SIGNIFICANT_DAY_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson"
)


@dataclass
class SignificantEarthquakeEvent:
    event_id: str
    usgs_id: str
    title: str
    place: str
    magnitude: float
    time: str
    updated: str
    url: str
    alert: str | None = None
    significance: int | None = None
    felt_reports: int | None = None
    cdi: float | None = None
    mmi: float | None = None
    tsunami: bool = False
    latitude: float | None = None
    longitude: float | None = None
    depth_km: float | None = None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _iso_from_ms(value: Any) -> str:
    milliseconds = _safe_int(value)
    if milliseconds is None or milliseconds <= 0:
        return ""
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat().replace("+00:00", "Z")


def _parse_feature(feature: object) -> SignificantEarthquakeEvent | None:
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties")
    if not isinstance(props, dict):
        return None

    usgs_id = str(feature.get("id") or props.get("code") or "").strip()
    magnitude = _safe_float(props.get("mag"))
    place = str(props.get("place") or "").strip()
    event_time = _iso_from_ms(props.get("time"))
    if not (usgs_id and magnitude and place and event_time):
        return None

    geometry = feature.get("geometry")
    coordinates = (
        geometry.get("coordinates")
        if isinstance(geometry, dict)
        else None
    )
    longitude = latitude = depth_km = None
    if isinstance(coordinates, list) and len(coordinates) >= 2:
        longitude = _safe_float(coordinates[0])
        latitude = _safe_float(coordinates[1])
        if len(coordinates) >= 3:
            depth_km = _safe_float(coordinates[2])

    alert = props.get("alert")
    alert_text = str(alert).strip().lower() if alert else None
    title = str(props.get("title") or f"M {magnitude:.1f} - {place}").strip()

    return SignificantEarthquakeEvent(
        event_id=f"usgs_eq_{usgs_id}",
        usgs_id=usgs_id,
        title=title,
        place=place,
        magnitude=magnitude,
        time=event_time,
        updated=_iso_from_ms(props.get("updated")),
        url=str(props.get("url") or "").strip(),
        alert=alert_text,
        significance=_safe_int(props.get("sig")),
        felt_reports=_safe_int(props.get("felt")),
        cdi=_safe_float(props.get("cdi")),
        mmi=_safe_float(props.get("mmi")),
        tsunami=(_safe_int(props.get("tsunami")) or 0) == 1,
        latitude=latitude,
        longitude=longitude,
        depth_km=depth_km,
    )


def _events_from_geojson(payload: object) -> list[SignificantEarthquakeEvent]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise SourceFetchError("USGS significant earthquakes schema drift: expected FeatureCollection")
    assert_response_schema(payload, ("type", "features"), "USGS significant earthquakes")
    features = payload.get("features")
    if not isinstance(features, list):
        raise SourceFetchError("USGS significant earthquakes schema drift: features must be a list")
    events = []
    for feature in features:
        event = _parse_feature(feature)
        if event is not None:
            events.append(event)
    return events


def fetch_significant_earthquakes(*, strict: bool = False) -> list[SignificantEarthquakeEvent]:
    """Fetch USGS significant earthquakes from the past day."""

    try:
        response = fetch_with_retry(
            USGS_SIGNIFICANT_DAY_URL,
            headers={
                "User-Agent": "(theheat-bot, contact@theheat.app)",
                "Accept": "application/geo+json, application/json",
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
        payload = response.json()
        events = _events_from_geojson(payload)
        freshness_values: list[str | int | float | None] = [event.time for event in events]
        if isinstance(payload, dict):
            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                freshness_values.append(metadata.get("generated"))
        if newest_date := newest_freshness_date(freshness_values):
            assert_freshness(newest_date, "usgs_quakes", max_age_days=2)
        return events
    except (requests.RequestException, ValueError, KeyError, TypeError, SourceFetchError) as exc:
        if strict:
            raise SourceFetchError(f"USGS earthquake fetch failed: {exc}") from exc
        return []
