"""Open-Meteo Air Quality API fetch + PM2.5 hazard + dust detection.

Host: air-quality-api.open-meteo.com (CAMS-backed; distinct from the
temperature/archive Open-Meteo hosts in src/data/open_meteo.py).
No API key required for non-commercial use.

Evidence grade: CAMS global model is gridded at 0.4 degrees, updated every
12 h. City-level values are model estimates, not station readings.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from statistics import mean
from typing import Any

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# WHO 2021 PM2.5 24-hour mean guideline (micrograms per cubic meter).
WHO_24H_GUIDELINE: float = 15.0

# Air Quality API accepts comma-separated lat/lon lists and returns a JSON list
# in request order. 50 keeps 638 cities to about 13 calls.
try:
    CHUNK_SIZE: int = int(os.environ.get("THEHEAT_AQ_CHUNK_SIZE", "50"))
except ValueError:
    CHUNK_SIZE = 50

# Open-Meteo's free tier enforces a per-minute request budget (empirically ~12 of
# our 50-city chunks). A 638-city sweep is ~13 chunks, so the tail chunk(s) get
# HTTP 429 — and the response carries no Retry-After header, so we wait out the
# clock-minute window and retry the rate-limited (or otherwise failed) chunks.
# RECOVERY_PASSES bounds the retries; the source runner treats a small residual
# loss as a successful run rather than a failure.
RECOVERY_PASSES: int = 2
_RATE_LIMIT_DEFAULT_WAIT_S: float = 62.0  # blind wait when no server Date header
_RATE_LIMIT_WAIT_BUFFER_S: float = 2.0
_RATE_LIMIT_WAIT_MIN_S: float = 3.0
_RATE_LIMIT_WAIT_MAX_S: float = 63.0

# PROVISIONAL CAMS-calibrated tiers. Step 0 evidence accepted clean-city floors
# and a real Delhi dust event; keep these constants unless calibration is rerun.
PM25_TIERS: tuple[int, ...] = (150, 250, 350)
DUST_TIERS: tuple[int, ...] = (500, 2000, 5000)


@dataclass(frozen=True)
class CityAirQuality:
    city: str
    country: str
    lat: float
    lon: float
    date: str
    pm25_24h_mean: float | None
    dust_daily_max: float | None
    aod_daily_max: float | None
    us_aqi_daily_max: int | None


@dataclass(frozen=True)
class PM25HazardEvent:
    city: str
    country: str
    lat: float
    lon: float
    date: str
    pm25_24h_mean: float
    tier: int
    who_multiple: float
    us_aqi_daily_max: int | None
    event_id: str
    evidence_grade: str = "model_estimated"
    station_name: str | None = None
    station_pm25_ug_m3: float | None = None
    station_distance_km: float | None = None


@dataclass(frozen=True)
class DustEvent:
    city: str
    country: str
    lat: float
    lon: float
    date: str
    dust_daily_max: float
    tier: int
    aod_daily_max: float | None
    event_id: str


def _city_slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace(",", "")


def _daily_mean(values: list[Any]) -> float | None:
    valid = [float(value) for value in values if isinstance(value, int | float)]
    return mean(valid) if valid else None


def _daily_max(values: list[Any]) -> float | None:
    valid = [float(value) for value in values if isinstance(value, int | float)]
    return max(valid) if valid else None


def _daily_max_int(values: list[Any]) -> int | None:
    value = _daily_max(values)
    return int(round(value)) if value is not None else None


def _tier(value: float, tiers: tuple[int, ...]) -> int | None:
    matched = [index + 1 for index, threshold in enumerate(tiers) if value >= threshold]
    return max(matched) if matched else None


def _parse_single_location(
    data: dict[str, Any],
    city: str,
    country: str,
    lat: float,
    lon: float,
    today_str: str,
) -> CityAirQuality | None:
    hourly = data.get("hourly", {})
    if not isinstance(hourly, dict):
        return None
    times = hourly.get("time", [])
    if not isinstance(times, list) or not times:
        return None
    if newest_time := newest_freshness_date(times):
        assert_freshness(newest_time, "air_quality", max_age_days=2)

    today_indices = [
        index
        for index, timestamp in enumerate(times)
        if isinstance(timestamp, str) and timestamp.startswith(today_str)
    ]
    if not today_indices:
        today_indices = list(range(len(times)))

    def _slice(key: str) -> list[Any]:
        values = hourly.get(key, [])
        if not isinstance(values, list):
            return []
        return [values[index] for index in today_indices if index < len(values)]

    return CityAirQuality(
        city=city,
        country=country,
        lat=lat,
        lon=lon,
        date=today_str,
        pm25_24h_mean=_daily_mean(_slice("pm2_5")),
        dust_daily_max=_daily_max(_slice("dust")),
        aod_daily_max=_daily_max(_slice("aerosol_optical_depth")),
        us_aqi_daily_max=_daily_max_int(_slice("us_aqi")),
    )


def _rate_limit_wait_seconds(date_header: str | None) -> float:
    """Seconds to wait out Open-Meteo's per-minute window before retrying.

    Open-Meteo sends no Retry-After on a 429, so derive the time to the next
    clock-minute boundary from the server Date header (the limit resets per
    calendar minute). Falls back to a safe blind wait when the header is missing
    or unparseable.
    """
    if not date_header:
        return _RATE_LIMIT_DEFAULT_WAIT_S
    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return _RATE_LIMIT_DEFAULT_WAIT_S
    seconds_into_minute = parsed.second + parsed.microsecond / 1_000_000
    wait = (60.0 - seconds_into_minute) + _RATE_LIMIT_WAIT_BUFFER_S
    return max(_RATE_LIMIT_WAIT_MIN_S, min(wait, _RATE_LIMIT_WAIT_MAX_S))


def _fetch_chunk(
    chunk: list[dict],
    today_str: str,
) -> tuple[list[CityAirQuality | None], bool, str | None]:
    """Fetch and parse one batched chunk.

    Returns ``(results, ok, rate_limit_date)``. ``ok`` is False when the HTTP
    fetch failed entirely (every city in the chunk stays None). ``rate_limit_date``
    carries the server Date header when the failure was a 429, so the caller can
    time the wait before retrying.
    """
    out: list[CityAirQuality | None] = [None] * len(chunk)
    lats = ",".join(str(city["lat"]) for city in chunk)
    lons = ",".join(str(city["lon"]) for city in chunk)

    try:
        response = fetch_with_retry(
            AQ_URL,
            timeout=30,
            params={
                "latitude": lats,
                "longitude": lons,
                "hourly": "pm2_5,dust,aerosol_optical_depth,us_aqi",
                "timezone": "auto",
                "forecast_days": 1,
                "past_days": 1,
            },
        )
        payload = response.json()
    except requests.HTTPError as exc:
        resp = exc.response
        if resp is not None and resp.status_code == 429:
            return out, False, resp.headers.get("Date")
        return out, False, None
    except (requests.RequestException, ValueError):
        return out, False, None

    location_list = payload if isinstance(payload, list) else [payload]
    for offset, loc_data in enumerate(location_list):
        if offset >= len(chunk) or not isinstance(loc_data, dict):
            break
        row = chunk[offset]
        try:
            out[offset] = _parse_single_location(
                loc_data,
                city=str(row["city"]),
                country=str(row["country"]),
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                today_str=today_str,
            )
        except (KeyError, TypeError, ValueError):
            out[offset] = None
    return out, True, None


def fetch_batch_air_quality(
    cities: list[dict],
    *,
    chunk_size: int = CHUNK_SIZE,
    recovery_passes: int = RECOVERY_PASSES,
) -> list[CityAirQuality | None]:
    """Fetch air-quality observations for city rows in batched HTTP calls.

    Returns one result per input city. Entries are None when a chunk's fetch
    fails or an individual location response cannot be parsed. Chunks that fail
    the first pass — typically Open-Meteo rate-limiting the tail of the sweep —
    are retried up to ``recovery_passes`` times, waiting out the per-minute
    window between passes.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    today_str = date.today().isoformat()
    results: list[CityAirQuality | None] = [None] * len(cities)

    pending = list(range(0, len(cities), chunk_size))
    rate_limit_date: str | None = None
    for attempt in range(recovery_passes + 1):
        if attempt > 0:
            time.sleep(_rate_limit_wait_seconds(rate_limit_date))
        rate_limit_date = None
        still_failed: list[int] = []
        for chunk_start in pending:
            chunk = cities[chunk_start : chunk_start + chunk_size]
            chunk_results, ok, date_header = _fetch_chunk(chunk, today_str)
            if ok:
                for offset, value in enumerate(chunk_results):
                    results[chunk_start + offset] = value
            else:
                still_failed.append(chunk_start)
                if date_header is not None:
                    rate_limit_date = date_header
        pending = still_failed
        if not pending:
            break

    return results


def detect_pm25_hazard(obs: CityAirQuality) -> PM25HazardEvent | None:
    """Return a PM2.5 hazard when 24-hour mean crosses tier 1 or higher."""
    if obs.pm25_24h_mean is None:
        return None
    tier = _tier(obs.pm25_24h_mean, PM25_TIERS)
    if tier is None:
        return None
    slug = _city_slug(obs.city)
    return PM25HazardEvent(
        city=obs.city,
        country=obs.country,
        lat=obs.lat,
        lon=obs.lon,
        date=obs.date,
        pm25_24h_mean=obs.pm25_24h_mean,
        tier=tier,
        who_multiple=round(obs.pm25_24h_mean / WHO_24H_GUIDELINE, 1),
        us_aqi_daily_max=obs.us_aqi_daily_max,
        event_id=f"pm25_{slug}_{obs.date}_tier{tier}",
    )


def detect_dust_event(obs: CityAirQuality) -> DustEvent | None:
    """Return a dust event when daily-max mineral dust crosses tier 1+."""
    if obs.dust_daily_max is None:
        return None
    tier = _tier(obs.dust_daily_max, DUST_TIERS)
    if tier is None:
        return None
    slug = _city_slug(obs.city)
    return DustEvent(
        city=obs.city,
        country=obs.country,
        lat=obs.lat,
        lon=obs.lon,
        date=obs.date,
        dust_daily_max=obs.dust_daily_max,
        tier=tier,
        aod_daily_max=obs.aod_daily_max,
        event_id=f"dust_{slug}_{obs.date}_tier{tier}",
    )
