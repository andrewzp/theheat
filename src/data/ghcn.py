"""NOAA GHCN-Daily extreme-signal detection.

Public surface mirrors check_extreme_signals_for_cities() from open_meteo.py.
Reuses the same dataclasses; GHCN-path bundles populate signal_date,
station_id, and station_name.

Data flow per cycle:
  1. Fetch the latest superghcnd_diff file(s) from NOAA.
  2. Parse TMAX / TMIN observations for active stations.
  3. For each station with a new reading, load its threshold row from the
     SQLite cache built by scripts/build_station_thresholds.py.
  4. Compare reading to all-time / monthly / calendar-date records and the
     climatological mean (anomaly).
  5. Emit ExtremeSignalBundle for every station that tripped at least one
     signal.
  6. Run country-level aggregation across ALL station readings (same logic as
     detect_country_records() in open_meteo.py).

The SQLite file is downloaded from a GitHub Release asset at CI job start
(see .github/workflows/bot.yml); its path defaults to
data/station_thresholds.sqlite and can be overridden via
THEHEAT_GHCN_DB_PATH.

Coverage notes:
  - GHCN-Daily does NOT include Tokashiki/Okinawa (Japan) or Troodos/Cyprus;
    those require hybrid national feeds (P5).
  - Country aggregation here uses the raw station population, not the curated
    638-city set.  This may over-weight dense-coverage countries (e.g. USA has
    ~3,500 active TMAX stations).  A cities.csv station_id mapping (P5) will
    gate country records through the curated set; until then, the per-station
    country records are an approximation.
"""

from __future__ import annotations

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import requests

from src.data.ghcn_db import (
    DEFAULT_DB_PATH,
    get_meta,
    load_active_stations,
    load_thresholds,
    open_db,
)
from src.data.ghcn_format import (
    DailyObs,
    StationThresholds,
    parse_superghcnd_diff_bytes,
)
from src.data.open_meteo import (
    AllTimeRecord,
    AnomalyEvent,
    CountryRecord,
    ExtremeSignalBundle,
    MonthlyRecord,
    RecordEvent,
    detect_country_records,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DIFF_BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/superghcnd"

# How many days of superghcnd_diff to scan for the latest readings.
# NOAA lag is 24-48 hr, so 3 days guarantees we catch yesterday's data even
# on weekends or holidays when processing may be slow.
DIFF_LOOKBACK_DAYS = int(os.environ.get("THEHEAT_GHCN_DIFF_LOOKBACK_DAYS", "3"))

# Minimum margin above the existing record to fire a signal (tenths-of-°C
# converted to °C). Prevents noisy ties from the same day re-firing.
RECORD_MARGIN_C = 0.0

# Anomaly thresholds (°C above/below climatological mean)
ANOMALY_HOT_THRESHOLD_C  = float(os.environ.get("THEHEAT_ANOMALY_HOT_THRESHOLD_C",  "8.0"))
ANOMALY_COLD_THRESHOLD_C = float(os.environ.get("THEHEAT_ANOMALY_COLD_THRESHOLD_C", "8.0"))

# Minimum archive years before we trust thresholds (avoids thin-data false positives)
MIN_ARCHIVE_YEARS = int(os.environ.get("THEHEAT_GHCN_MIN_ARCHIVE_YEARS", "15"))


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    env = os.environ.get("THEHEAT_GHCN_DB_PATH")
    return Path(env) if env else DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Diff fetching
# ---------------------------------------------------------------------------

def _diff_url(d: date) -> str:
    return f"{DIFF_BASE_URL}/superghcnd_diff_{d.strftime('%Y%m%d')}.gz"


def _fetch_diff(d: date, timeout: int = 60) -> bytes | None:
    """Fetch one superghcnd_diff file. Returns None if not yet available."""
    url = _diff_url(d)
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        log.warning("GHCN diff fetch failed for %s: %s", d, e)
        return None


def _fetch_recent_obs(
    active_ids: frozenset[str],
    lookback_days: int = DIFF_LOOKBACK_DAYS,
) -> dict[str, DailyObs]:
    """Fetch the most recent TMAX observation per active station.

    Returns a dict mapping station_id → most-recent DailyObs (TMAX preferred;
    TMIN if no TMAX available on the most-recent date).

    Fetches the last ``lookback_days`` superghcnd_diff files in parallel.
    Takes the observation with the latest date for each station.
    """
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(1, lookback_days + 1)]

    # Fetch diffs in parallel (3 requests, lightweight)
    raw_by_date: dict[date, bytes] = {}
    with ThreadPoolExecutor(max_workers=lookback_days) as pool:
        future_to_date = {pool.submit(_fetch_diff, d): d for d in dates}
        for fut in as_completed(future_to_date):
            d = future_to_date[fut]
            content = fut.result()
            if content is not None:
                raw_by_date[d] = content

    if not raw_by_date:
        log.warning("GHCN: no diff files available (NOAA endpoint may be down)")
        return {}

    # Parse all obs, keep only those for active stations
    all_obs: list[DailyObs] = []
    for d in sorted(raw_by_date):
        obs = parse_superghcnd_diff_bytes(raw_by_date[d])
        all_obs.extend(o for o in obs if o.station_id in active_ids)

    # For each station, take the obs with the latest date
    # Prefer TMAX over TMIN if both exist on the same day.
    latest_by_station: dict[str, DailyObs] = {}
    for o in all_obs:
        existing = latest_by_station.get(o.station_id)
        if existing is None:
            latest_by_station[o.station_id] = o
        elif o.obs_date > existing.obs_date:
            latest_by_station[o.station_id] = o
        elif o.obs_date == existing.obs_date and o.element == "TMAX" and existing.element != "TMAX":
            latest_by_station[o.station_id] = o

    log.info(
        "GHCN: fetched diffs for %d/%d dates; %d active stations have recent readings",
        len(raw_by_date), lookback_days, len(latest_by_station),
    )
    return latest_by_station


# ---------------------------------------------------------------------------
# Signal detection for one station
# ---------------------------------------------------------------------------

def _detect_signals_for_station(
    station: dict,
    obs: DailyObs,
    thresholds: StationThresholds,
) -> ExtremeSignalBundle | None:
    """Compare one observation against thresholds and return a bundle.

    Returns None if no signals fired (station has no data worth reporting).
    The bundle is returned even without signals so callers can use
    today_max_c / archive_max_c for country-level aggregation.
    """
    sid    = station["station_id"]
    name   = station.get("name", "")
    city   = station.get("name", sid)   # use station name as display city
    country_name = station.get("country_name", "")
    country_code = station.get("country_code", "")
    # Prefer country_name for display; fall back to code
    country = country_name or country_code

    obs_date = obs.obs_date
    obs_date_iso = obs_date.isoformat()
    archive_years = thresholds.archive_years or station.get("archive_years", 0)

    if archive_years < MIN_ARCHIVE_YEARS:
        return None  # Too little history — skip

    sid_key = sid.replace(" ", "_")
    value_c = obs.value_c
    month   = obs_date.month
    day     = obs_date.day

    bundle = ExtremeSignalBundle(
        city=city,
        country=country,
        signal_date=obs_date,
        station_id=sid,
        station_name=name,
    )

    # ---- Populate raw readings for country aggregation ----
    if obs.element == "TMAX":
        bundle.today_max_c    = value_c
        bundle.archive_max_c  = thresholds.all_time_max_c
        bundle.archive_max_year = thresholds.all_time_max_year
    elif obs.element == "TMIN":
        bundle.today_min_c    = value_c
        bundle.archive_min_c  = thresholds.all_time_min_c
        bundle.archive_min_year = thresholds.all_time_min_year

    # ---- All-time record ----
    if obs.element == "TMAX" and thresholds.all_time_max_c is not None:
        if value_c > thresholds.all_time_max_c + RECORD_MARGIN_C:
            bundle.all_time_high = AllTimeRecord(
                city=city, country=country, kind="high",
                new_temp_c=value_c,
                old_record_c=thresholds.all_time_max_c,
                old_record_year=thresholds.all_time_max_year or 0,
                years_of_data=archive_years,
                event_id=f"all_time_high_{sid_key}_{obs_date_iso}",
                signal_date=obs_date,
            )
    elif obs.element == "TMIN" and thresholds.all_time_min_c is not None:
        if value_c < thresholds.all_time_min_c - RECORD_MARGIN_C:
            bundle.all_time_low = AllTimeRecord(
                city=city, country=country, kind="low",
                new_temp_c=value_c,
                old_record_c=thresholds.all_time_min_c,
                old_record_year=thresholds.all_time_min_year or 0,
                years_of_data=archive_years,
                event_id=f"all_time_low_{sid_key}_{obs_date_iso}",
                signal_date=obs_date,
            )

    # ---- Monthly record ----
    if obs.element == "TMAX":
        monthly_max = thresholds.monthly_max.get(month)
        if monthly_max and value_c > monthly_max[0] + RECORD_MARGIN_C:
            bundle.monthly_high = MonthlyRecord(
                city=city, country=country, kind="high", month=month,
                new_temp_c=value_c,
                old_record_c=monthly_max[0],
                old_record_year=monthly_max[1],
                years_of_data=archive_years,
                event_id=f"monthly_high_{sid_key}_{month:02d}_{obs_date_iso}",
                signal_date=obs_date,
            )
    elif obs.element == "TMIN":
        monthly_min = thresholds.monthly_min.get(month)
        if monthly_min and value_c < monthly_min[0] - RECORD_MARGIN_C:
            bundle.monthly_low = MonthlyRecord(
                city=city, country=country, kind="low", month=month,
                new_temp_c=value_c,
                old_record_c=monthly_min[0],
                old_record_year=monthly_min[1],
                years_of_data=archive_years,
                event_id=f"monthly_low_{sid_key}_{month:02d}_{obs_date_iso}",
                signal_date=obs_date,
            )

    # ---- Calendar-date record ----
    md = (month, day)
    if obs.element == "TMAX":
        cal_max = thresholds.calendar_date_max.get(md)
        if cal_max and value_c > cal_max[0] + RECORD_MARGIN_C:
            bundle.calendar_date_high = RecordEvent(
                city=city, country=country,
                new_temp_c=value_c,
                old_record_c=cal_max[0],
                old_record_year=cal_max[1],
                event_id=f"cal_high_{sid_key}_{obs_date_iso}",
                signal_date=obs_date,
            )
    elif obs.element == "TMIN":
        cal_min = thresholds.calendar_date_min.get(md)
        if cal_min and value_c < cal_min[0] - RECORD_MARGIN_C:
            bundle.calendar_date_low = RecordEvent(
                city=city, country=country,
                new_temp_c=value_c,
                old_record_c=cal_min[0],
                old_record_year=cal_min[1],
                event_id=f"cal_low_{sid_key}_{obs_date_iso}",
                signal_date=obs_date,
            )

    # ---- Anomaly (deviation from climatological mean) ----
    clim_mean = thresholds.climatological_mean.get(month)
    if clim_mean is not None and obs.element == "TMAX":
        anomaly_c = value_c - clim_mean
        if anomaly_c >= ANOMALY_HOT_THRESHOLD_C:
            bundle.anomaly_hot = AnomalyEvent(
                city=city, country=country,
                today_temp_c=value_c,
                historical_mean_c=clim_mean,
                anomaly_c=anomaly_c,
                years_of_data=archive_years,
                event_id=f"anomaly_hot_{sid_key}_{obs_date_iso}",
                signal_date=obs_date,
            )
        elif anomaly_c <= -ANOMALY_COLD_THRESHOLD_C:
            bundle.anomaly_cold = AnomalyEvent(
                city=city, country=country,
                today_temp_c=value_c,
                historical_mean_c=clim_mean,
                anomaly_c=anomaly_c,
                years_of_data=archive_years,
                event_id=f"anomaly_cold_{sid_key}_{obs_date_iso}",
                signal_date=obs_date,
            )

    return bundle


def _has_signal(bundle: ExtremeSignalBundle) -> bool:
    return any([
        bundle.calendar_date_high, bundle.calendar_date_low,
        bundle.all_time_high, bundle.all_time_low,
        bundle.monthly_high, bundle.monthly_low,
        bundle.anomaly_hot, bundle.anomaly_cold,
    ])


# ---------------------------------------------------------------------------
# Top-level dedup: keep at most 2 firing stations per (country, nearest city)
# ---------------------------------------------------------------------------

def _dedup_by_metro(
    bundles: list[ExtremeSignalBundle],
    max_per_country: int = 2,
) -> list[ExtremeSignalBundle]:
    """Cap at max_per_country signal-firing bundles per country.

    Within a country, ranks by number of signals fired (all-time > monthly >
    calendar-date > anomaly) and keeps the top N.

    This prevents a single country with thousands of stations (e.g. USA)
    from flooding the draft queue on record-breaking days.
    """
    def _signal_rank(b: ExtremeSignalBundle) -> int:
        score = 0
        if b.all_time_high or b.all_time_low:
            score += 100
        if b.monthly_high or b.monthly_low:
            score += 10
        if b.calendar_date_high or b.calendar_date_low:
            score += 5
        if b.anomaly_hot or b.anomaly_cold:
            score += 2
        return score

    by_country: dict[str, list[ExtremeSignalBundle]] = {}
    for b in bundles:
        by_country.setdefault(b.country or "UNKNOWN", []).append(b)

    out: list[ExtremeSignalBundle] = []
    for country, group in by_country.items():
        ranked = sorted(group, key=_signal_rank, reverse=True)
        out.extend(ranked[:max_per_country])
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_extreme_signals_for_stations(
    stations: list[dict] | None = None,
    max_checks: int | None = None,
    *,
    archive_years: int = 30,
    db_path: Path | str | None = None,
    _fetch_obs_fn: Callable | None = None,  # injectable for tests
) -> tuple[list[ExtremeSignalBundle], list[CountryRecord]]:
    """Check active GHCN-Daily stations for extreme signals.

    Mirrors check_extreme_signals_for_cities() from open_meteo.py:
      returns (bundles, country_records)
      bundles — only stations that fired at least one signal
      country_records — aggregated across all stations in the sample

    Args:
        stations: list of station dicts (from load_active_stations()). If None,
                  loads active stations from the SQLite DB automatically.
        max_checks: if set, only check the first N stations in the list.
        archive_years: not used directly (thresholds come from SQLite), but
                       passed through to country aggregation for label text.
        db_path: override the default SQLite path.
        _fetch_obs_fn: injectable for testing; replaces _fetch_recent_obs().
    """
    resolved_db = Path(db_path) if db_path else _db_path()

    if not resolved_db.exists():
        log.error(
            "GHCN threshold DB not found at %s. "
            "Run scripts/build_station_thresholds.py first.",
            resolved_db,
        )
        return [], []

    # 1. Load active stations
    if stations is None:
        with open_db(resolved_db) as conn:
            stations = load_active_stations(conn)

    if max_checks is not None:
        stations = stations[:max_checks]

    active_ids = frozenset(s["station_id"] for s in stations)
    station_by_id = {s["station_id"]: s for s in stations}

    # 2. Fetch recent observations
    fetch_fn = _fetch_obs_fn or _fetch_recent_obs
    latest_obs = fetch_fn(active_ids)

    if not latest_obs:
        log.warning("GHCN: no observations returned; check NOAA diff endpoints")
        return [], []

    # 3. Load thresholds for stations that have new observations and compare
    all_bundles: list[ExtremeSignalBundle] = []
    signal_bundles: list[ExtremeSignalBundle] = []

    with open_db(resolved_db) as conn:
        for station_id, obs in latest_obs.items():
            station = station_by_id.get(station_id)
            if station is None:
                continue

            thresholds = load_thresholds(conn, station_id)
            if thresholds is None:
                continue

            bundle = _detect_signals_for_station(station, obs, thresholds)
            if bundle is None:
                continue

            all_bundles.append(bundle)
            if _has_signal(bundle):
                signal_bundles.append(bundle)

    log.info(
        "GHCN: %d stations checked, %d fired signals",
        len(all_bundles), len(signal_bundles),
    )

    # 4. Country-level aggregation across ALL readings (not just signal ones)
    country_records = detect_country_records(all_bundles, archive_years=archive_years)

    # 5. Dedup: cap at 2 signal-firing bundles per country
    deduped_signal_bundles = _dedup_by_metro(signal_bundles)

    return deduped_signal_bundles, country_records
