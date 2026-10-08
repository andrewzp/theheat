"""Open-Meteo Air Quality API fetch + PM2.5 hazard + dust detection.

Host: air-quality-api.open-meteo.com (CAMS-backed; distinct from the
temperature/archive Open-Meteo hosts in src/data/open_meteo.py).
No API key required for non-commercial use.

Evidence grade: the automatic CAMS domain supplies model forecasts, not station
readings. Exact model/run and resolution are not identified by this response.
"""

from __future__ import annotations

import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from src.data import air_quality_contract as window_contract
from src.data._freshness import assert_freshness, newest_freshness_date
from src.data.source_status import SourceFetchError
from src.data._http import fetch_with_retry
from src.data.places import event_location_key

AQ_URL = window_contract.SOURCE_URL

# WHO 2021 PM2.5 24-hour mean guideline (micrograms per cubic meter).
WHO_24H_GUIDELINE: float = 15.0

# WHO 2021 Air Quality Guideline, PM10 24-hour mean. The dust anchor is
# Co-reported forecast PM10 (Open-Meteo `pm10`), never the `dust` variable itself —
# `dust` is mineral dust only and has no 24h-average standard.
WHO_PM10_24H_GUIDELINE: float = 45.0

# Air Quality API accepts comma-separated lat/lon lists and returns a JSON list
# in request order. 50 keeps 638 cities to about 13 calls.
try:
    CHUNK_SIZE: int = int(os.environ.get("THEHEAT_AQ_CHUNK_SIZE", "50"))
except ValueError:
    CHUNK_SIZE = 50
try:
    CHUNK_PACING_S: int = int(os.environ.get("THEHEAT_AQ_CHUNK_PACING_S", "8"))
except ValueError:
    CHUNK_PACING_S = 8

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
    pm10_24h_mean: float | None
    forecast_window: dict[str, Any] | None = None


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
    forecast_window: dict[str, Any] | None = None


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
    pm10_24h_mean: float | None = None
    who_pm10_multiple: float | None = None
    forecast_window: dict[str, Any] | None = None


def _city_slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace(",", "")


def _tier(value: float, tiers: tuple[int, ...]) -> int | None:
    matched = [index + 1 for index, threshold in enumerate(tiers) if value >= threshold]
    return max(matched) if matched else None


def _parse_single_location(
    data: dict[str, Any], city: str, country: str, lat: float, lon: float,
    today_str: str, *, requested_at: str | None = None, retrieved_at: str | None = None,
) -> CityAirQuality | None:
    now = datetime.now(UTC).isoformat()
    try:
        reference = window_contract._utc(requested_at or now).date()
    except (TypeError, ValueError):
        return None
    hourly = data.get("hourly") if isinstance(data, dict) else None
    times = hourly.get("time") if isinstance(hourly, dict) else None
    if isinstance(times, list) and len(times) <= 72:
        # Preserve the existing explicit stale diagnostic. The batch caller
        # contains it to this location; other cities remain available.
        if newest := newest_freshness_date([t for t in times if isinstance(t, str)]):
            assert_freshness(newest, "air_quality", max_age_days=2, today=reference)
    try:
        packet = window_contract.build_window(
            data, city=city, country=country, lat=lat, lon=lon, day=today_str,
            requested_at=requested_at or now, retrieved_at=retrieved_at or now,
        )
        values = window_contract.validate_window(packet)
    except SourceFetchError:
        print("[air_quality] location withheld: unqualified forecast window")
        return None
    if values["pm2_5"] is None and values["dust"] is None:
        return None
    return CityAirQuality(
        city=city, country=country, lat=lat, lon=lon, date=today_str,
        pm25_24h_mean=values["pm2_5"], dust_daily_max=values["dust"],
        aod_daily_max=values["aerosol_optical_depth"],
        us_aqi_daily_max=int(values["us_aqi"]) if values["us_aqi"] is not None else None,
        pm10_24h_mean=values["pm10"], forecast_window=packet,
    )


def _rate_limit_wait_seconds(date_header: str | None) -> float:
    """Seconds to wait out Open-Meteo's per-minute window before retrying.

    Open-Meteo sends no Retry-After on a 429, so derive the time to the next
    clock-minute boundary from the server Date header (the limit resets per
    calendar minute). Falls back to a safe blind wait when the header is missing
    or unparseable.
    """
    parsed = _http_date(date_header)
    if parsed is None:
        return _RATE_LIMIT_DEFAULT_WAIT_S
    seconds_into_minute = parsed.second + parsed.microsecond / 1_000_000
    wait = (60.0 - seconds_into_minute) + _RATE_LIMIT_WAIT_BUFFER_S
    return max(_RATE_LIMIT_WAIT_MIN_S, min(wait, _RATE_LIMIT_WAIT_MAX_S))


def _http_date(value: str | None) -> datetime | None:
    """Only bounded, timezone-aware response dates can establish a wait."""
    if not isinstance(value, str) or not 0 < len(value) <= 256:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _retry_after_wait_seconds(
    retry_after_header: str | None, date_header: str | None = None,
) -> float | None:
    """RFC9110 seconds/date, or None for a malformed/missing header.

    Oversized values return a bounded sentinel above the wait limit. The caller
    defers the sweep; it must not shorten a long server delay and retry early.
    """
    if not isinstance(retry_after_header, str) or not retry_after_header:
        return None
    if len(retry_after_header) > 256:
        return _RATE_LIMIT_WAIT_MAX_S + 1
    text = retry_after_header.strip()
    if re.fullmatch(r"[0-9]+", text):
        return float(min(int(text), int(_RATE_LIMIT_WAIT_MAX_S) + 1))
    retry_at = _http_date(text)
    if retry_at is None:
        return None
    reference = _http_date(date_header) or datetime.now(UTC)
    return max(0.0, (retry_at - reference).total_seconds())


def _rate_limit_wait_seconds_for_headers(
    date_header: str | None,
    retry_after_header: str | None,
) -> float | None:
    """Finite wait up to the existing limit; None means defer this sweep."""
    retry_after_wait = _retry_after_wait_seconds(retry_after_header, date_header)
    if retry_after_wait is not None:
        return retry_after_wait if retry_after_wait <= _RATE_LIMIT_WAIT_MAX_S else None
    return _rate_limit_wait_seconds(date_header)


def _pacing_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _chunk_pacing_sleep() -> None:
    _pacing_sleep(float(CHUNK_PACING_S))


def _fetch_chunk(
    chunk: list[dict],
    today_str: str,
    requested_at: str | None = None,
) -> tuple[list[CityAirQuality | None], bool, str | None, str | None]:
    """Fetch and parse one batched chunk.

    Returns ``(results, ok, rate_limit_date, retry_after)``. ``ok`` is False when the HTTP
    fetch failed entirely (every city in the chunk stays None). ``rate_limit_date``
    and ``retry_after`` carry the server headers when the failure was a 429, so
    the caller can time the wait before retrying.
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
                "hourly": "pm2_5,pm10,dust,aerosol_optical_depth,us_aqi",
                "timezone": "auto",
                "domains": "auto",
                "start_date": today_str,
                "end_date": today_str,
            },
        )
        payload = response.json()
        retrieved_at = datetime.now(UTC).isoformat()
    except requests.HTTPError as exc:
        resp = exc.response
        if resp is not None and resp.status_code == 429:
            return out, False, resp.headers.get("Date"), resp.headers.get("Retry-After")
        return out, False, None, None
    except (requests.RequestException, ValueError):
        return out, False, None, None

    location_list = payload if isinstance(payload, list) else [payload]
    if len(location_list) != len(chunk):
        return out, False, None, None  # Cannot assign an incomplete positional batch safely.
    stale_count = 0
    for offset, loc_data in enumerate(location_list):
        if not isinstance(loc_data, dict):
            continue
        row = chunk[offset]
        try:
            out[offset] = _parse_single_location(
                loc_data,
                city=str(row["city"]),
                country=str(row["country"]),
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                today_str=today_str,
                requested_at=requested_at,
                retrieved_at=retrieved_at,
            )
        except SourceFetchError:
            stale_count += 1
        except (KeyError, TypeError, ValueError):
            out[offset] = None
    if stale_count and not any(item is not None for item in out):
        raise SourceFetchError("air_quality stale data: no usable current location in chunk")
    return out, True, None, None


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
    window between passes. A server delay beyond the bounded recovery window
    defers the remaining sweep, preserving already-qualified city results.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    requested_at = datetime.now(UTC).isoformat()
    today_str = requested_at[:10]
    results: list[CityAirQuality | None] = [None] * len(cities)

    pending = list(range(0, len(cities), chunk_size))
    stale_error: SourceFetchError | None = None
    recovery_wait = 0.0
    for attempt in range(recovery_passes + 1):
        if attempt > 0:
            time.sleep(recovery_wait)
        recovery_wait = 0.0
        recovery_deferred = False
        still_failed: list[int] = []
        for chunk_index, chunk_start in enumerate(pending):
            chunk = cities[chunk_start : chunk_start + chunk_size]
            try:
                chunk_results, ok, date_header, retry_after_header = _fetch_chunk(chunk, today_str, requested_at)
            except SourceFetchError as exc:
                # Stale source evidence is unavailable, not a transient HTTP
                # outage worth retrying; continue other chunks before reporting.
                stale_error = exc
                if chunk_index < len(pending) - 1:
                    _chunk_pacing_sleep()
                continue
            if ok:
                for offset, value in enumerate(chunk_results):
                    results[chunk_start + offset] = value
            else:
                still_failed.append(chunk_start)
                wait = _rate_limit_wait_seconds_for_headers(date_header, retry_after_header)
                if wait is None:
                    # Preserve qualified results and leave all unresolved city
                    # positions unavailable. No retry before the server's delay.
                    print("[air_quality] recovery deferred: server wait exceeds sweep limit")
                    recovery_deferred = True
                    break
                # Keep each response's headers paired, and never let a later
                # shorter delay overwrite an earlier server requirement.
                recovery_wait = max(recovery_wait, wait)
            if chunk_index < len(pending) - 1:
                _chunk_pacing_sleep()
        pending = still_failed
        if recovery_deferred or not pending:
            break

    if stale_error is not None and not any(item is not None for item in results):
        raise stale_error
    return results


def detect_pm25_hazard(obs: CityAirQuality) -> PM25HazardEvent | None:
    """Return a PM2.5 hazard when 24-hour mean crosses tier 1 or higher."""
    if obs.pm25_24h_mean is None:
        return None
    tier = _tier(obs.pm25_24h_mean, PM25_TIERS)
    if tier is None:
        return None
    slug = event_location_key(obs.city, obs.country, obs.lat, obs.lon)
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
        forecast_window=deepcopy(obs.forecast_window),
        event_id=f"pm25_{slug}_{obs.date}_tier{tier}",
    )


def detect_dust_event(obs: CityAirQuality) -> DustEvent | None:
    """Return a dust event when daily-max mineral dust crosses tier 1+."""
    if obs.dust_daily_max is None:
        return None
    tier = _tier(obs.dust_daily_max, DUST_TIERS)
    if tier is None:
        return None
    slug = event_location_key(obs.city, obs.country, obs.lat, obs.lon)
    # Co-reported forecast PM10 anchor, pre-rounded here so the writer never divides
    # (the value_rounded_c pattern). None-safe: a cycle with no pm10 series
    # still mints the event, just without the WHO anchor.
    who_pm10_multiple = (
        round(obs.pm10_24h_mean / WHO_PM10_24H_GUIDELINE, 1)
        if obs.pm10_24h_mean is not None
        else None
    )
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
        pm10_24h_mean=obs.pm10_24h_mean,
        who_pm10_multiple=who_pm10_multiple,
        forecast_window=deepcopy(obs.forecast_window),
    )
