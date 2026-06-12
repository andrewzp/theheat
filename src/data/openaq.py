"""OpenAQ PM2.5 corroboration for CAMS-backed air-quality candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
import os
from typing import Any

import requests

from src.data._http import fetch_with_retry
from src.data.air_quality import PM25HazardEvent
from src.data.source_status import SourceFetchError, SourceSkipped

OPENAQ_LATEST_URL = "https://api.openaq.org/v3/latest"
MAX_DISTANCE_KM = 25.0
MAX_STATION_AGE_HOURS = 6.0
MAX_RELATIVE_DELTA = 0.35


@dataclass(frozen=True)
class OpenAQPM25Reading:
    station_name: str
    pm25_ug_m3: float
    observed_at: datetime
    distance_km: float


def _api_key(explicit: str | None = None) -> str:
    key = explicit if explicit is not None else os.environ.get("OPENAQ_API_KEY", "")
    if not key:
        raise SourceSkipped("OPENAQ_API_KEY is not configured")
    return key


def _parse_datetime(raw: Any) -> datetime | None:
    if isinstance(raw, dict):
        raw = raw.get("utc") or raw.get("local")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * earth_radius_km * asin(sqrt(a))


def _location_name(row: dict[str, Any]) -> str:
    location = row.get("location")
    if isinstance(location, dict):
        name = location.get("name") or location.get("locality")
        if isinstance(name, str) and name.strip():
            return name.strip()
    for key in ("location", "name", "locationName"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "OpenAQ station"


def _coordinates(row: dict[str, Any]) -> tuple[float, float] | None:
    coords = row.get("coordinates")
    if isinstance(coords, dict):
        lat = coords.get("latitude") or coords.get("lat")
        lon = coords.get("longitude") or coords.get("lon")
    else:
        lat = row.get("latitude") or row.get("lat")
        lon = row.get("longitude") or row.get("lon")
    try:
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _distance_km(row: dict[str, Any], lat: float, lon: float) -> float | None:
    raw = row.get("distance")
    if isinstance(raw, int | float):
        return float(raw) / 1000.0 if raw > 250 else float(raw)
    coords = _coordinates(row)
    if coords is None:
        return None
    return _haversine_km(lat, lon, coords[0], coords[1])


def _is_pm25_measurement(measurement: dict[str, Any]) -> bool:
    parameter = measurement.get("parameter")
    candidates = [
        measurement.get("parameter_id"),
        measurement.get("parameterId"),
        measurement.get("parameter"),
    ]
    if isinstance(parameter, dict):
        candidates.extend([
            parameter.get("id"),
            parameter.get("name"),
            parameter.get("displayName"),
        ])
    normalized = {str(value).lower().replace(".", "").replace("_", "") for value in candidates if value is not None}
    return bool({"2", "pm25", "pm2 5", "pm 25"} & normalized)


def _measurement_time(measurement: dict[str, Any]) -> datetime | None:
    period = measurement.get("period")
    if isinstance(period, dict):
        parsed = _parse_datetime(period.get("datetimeFrom") or period.get("datetimeTo"))
        if parsed is not None:
            return parsed
    return _parse_datetime(
        measurement.get("datetime")
        or measurement.get("date")
        or measurement.get("lastUpdated")
    )


def _candidate_readings(payload: dict[str, Any], lat: float, lon: float) -> list[OpenAQPM25Reading]:
    rows = payload.get("results", [])
    if not isinstance(rows, list):
        return []
    readings: list[OpenAQPM25Reading] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        distance = _distance_km(row, lat, lon)
        if distance is None:
            continue
        measurements = row.get("measurements")
        if not isinstance(measurements, list):
            measurements = [row]
        for measurement in measurements:
            if not isinstance(measurement, dict) or not _is_pm25_measurement(measurement):
                continue
            value = measurement.get("value")
            observed_at = _measurement_time(measurement)
            try:
                pm25 = float(value)
            except (TypeError, ValueError):
                continue
            if observed_at is None:
                continue
            readings.append(
                OpenAQPM25Reading(
                    station_name=_location_name(row),
                    pm25_ug_m3=pm25,
                    observed_at=observed_at,
                    distance_km=round(distance, 1),
                )
            )
    readings.sort(key=lambda reading: (reading.distance_km, -reading.observed_at.timestamp()))
    return readings


def fetch_latest_pm25(
    lat: float,
    lon: float,
    *,
    api_key: str | None = None,
) -> OpenAQPM25Reading | None:
    """Fetch the nearest latest OpenAQ PM2.5 reading within 25 km."""

    key = _api_key(api_key)
    response = fetch_with_retry(
        OPENAQ_LATEST_URL,
        timeout=10,
        attempts=1,
        headers={"X-API-Key": key},
        params={
            "coordinates": f"{lat},{lon}",
            "radius": int(MAX_DISTANCE_KM * 1000),
            "parameters_id": 2,
            "limit": 10,
        },
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise SourceFetchError("OpenAQ latest PM2.5 response was not an object")
    readings = _candidate_readings(payload, lat, lon)
    return readings[0] if readings else None


def _corroborates(event: PM25HazardEvent, reading: OpenAQPM25Reading, now: datetime) -> bool:
    if reading.distance_km > MAX_DISTANCE_KM:
        return False
    age_h = (now - reading.observed_at).total_seconds() / 3600
    if age_h < 0 or age_h > MAX_STATION_AGE_HOURS:
        return False
    relative_delta = abs(reading.pm25_ug_m3 - event.pm25_24h_mean) / event.pm25_24h_mean
    return relative_delta <= MAX_RELATIVE_DELTA


def corroborate_pm25_hazard(
    event: PM25HazardEvent,
    *,
    api_key: str | None = None,
    now: datetime | None = None,
) -> PM25HazardEvent:
    """Return an upgraded PM25HazardEvent when a nearby fresh station agrees."""

    now = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        reading = fetch_latest_pm25(event.lat, event.lon, api_key=api_key)
    except SourceSkipped:
        raise
    except (requests.RequestException, SourceFetchError, ValueError, TypeError):
        return event
    if reading is None or not _corroborates(event, reading, now):
        return event
    return replace(
        event,
        evidence_grade="model_corroborated_by_station",
        station_name=reading.station_name,
        station_pm25_ug_m3=round(reading.pm25_ug_m3, 1),
        station_distance_km=round(reading.distance_km, 1),
    )
