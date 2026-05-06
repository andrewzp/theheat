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

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import requests

from src.data.ghcn_db import (
    DEFAULT_DB_PATH,
    load_active_stations,
    load_thresholds,
    open_db,
)
from src.data.ghcn_format import (
    DailyObs,
    StationThresholds,
    parse_superghcnd_diff_records_bytes,
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

def _diff_urls_for_end_date(d: date, max_start_lag_days: int = 10) -> list[str]:
    """Candidate diff tarballs whose second date is ``d``.

    NOAA usually publishes previous-day-to-current-day diffs, but weekends and
    processing gaps sometimes produce multi-day spans. Try the short span first,
    then wider starts for the same target snapshot date.
    """
    end = d.strftime("%Y%m%d")
    return [
        f"{DIFF_BASE_URL}/superghcnd_diff_{(d - timedelta(days=lag)).strftime('%Y%m%d')}_to_{end}.tar.gz"
        for lag in range(1, max_start_lag_days + 1)
    ]


def _fetch_diff(d: date, timeout: int = 60) -> bytes | None:
    """Fetch one superghcnd_diff tarball ending on ``d``."""
    last_error: Exception | None = None
    for url in _diff_urls_for_end_date(d):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            last_error = e
            log.warning("GHCN diff fetch failed for %s via %s: %s", d, url, e)
    if last_error is None:
        log.info("GHCN diff not available for snapshot date %s", d)
    return None


def _fetch_recent_obs(
    active_ids: frozenset[str],
    lookback_days: int = DIFF_LOOKBACK_DAYS,
) -> dict[tuple[str, date], list[DailyObs]]:
    """Fetch recent TMAX/TMIN observations for active stations.

    Returns a dict mapping (station_id, obs_date) → DailyObs list so same-day
    TMAX and TMIN are preserved instead of one element masking the other.

    Fetches recent superghcnd_diff tarballs in parallel and de-duplicates by
    station/date/element, keeping the latest parsed value.
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
        raise RuntimeError("GHCN: no diff files available from NOAA")

    # Parse all records, keeping only the latest active station/date/element
    # state. Delete records and QC-failed updates must remove any earlier
    # value seen in the same lookback window.
    obs_by_key: dict[tuple[str, date, str], DailyObs] = {}
    for d in sorted(raw_by_date):
        records = parse_superghcnd_diff_records_bytes(raw_by_date[d])
        for rec in records:
            if rec.station_id not in active_ids:
                continue
            key = (rec.station_id, rec.obs_date, rec.element)
            obs = rec.to_daily_obs()
            if obs is None:
                obs_by_key.pop(key, None)
            else:
                obs_by_key[key] = obs

    by_station_date: dict[tuple[str, date], list[DailyObs]] = {}
    for o in obs_by_key.values():
        by_station_date.setdefault((o.station_id, o.obs_date), []).append(o)
    for obs_list in by_station_date.values():
        obs_list.sort(key=lambda o: 0 if o.element == "TMAX" else 1)

    log.info(
        "GHCN: fetched diffs for %d/%d dates; %d active station/date groups have recent readings",
        len(raw_by_date), lookback_days, len(by_station_date),
    )
    if not by_station_date:
        raise RuntimeError("GHCN: diff files parsed but contained no active TMAX/TMIN observations")
    return by_station_date


# ---------------------------------------------------------------------------
# Signal detection for one station
# ---------------------------------------------------------------------------

def _detect_signals_for_station(
    station: dict,
    obs: DailyObs | list[DailyObs],
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

    obs_list = [obs] if isinstance(obs, DailyObs) else list(obs)
    if not obs_list:
        return None

    obs_dates = {o.obs_date for o in obs_list}
    if len(obs_dates) != 1:
        raise ValueError(f"GHCN station bundle received mixed observation dates: {sorted(obs_dates)}")

    obs_date = obs_list[0].obs_date
    obs_date_iso = obs_date.isoformat()

    sid_key = sid.replace(" ", "_")
    month   = obs_date.month
    day     = obs_date.day

    bundle = ExtremeSignalBundle(
        city=city,
        country=country,
        signal_date=obs_date,
        station_id=sid,
        station_name=name,
    )

    md = (month, day)

    usable = False
    for o in obs_list:
        value_c = o.value_c
        if o.element == "TMAX":
            archive_years = (
                thresholds.tmax_archive_years
                or station.get("tmax_archive_years", 0)
                or thresholds.archive_years
                or station.get("archive_years", 0)
            )
            if archive_years < MIN_ARCHIVE_YEARS:
                continue
            usable = True
            bundle.today_max_c = value_c
            bundle.archive_max_c = thresholds.all_time_max_c
            bundle.archive_max_year = thresholds.all_time_max_year

            if thresholds.all_time_max_c is not None and value_c > thresholds.all_time_max_c + RECORD_MARGIN_C:
                bundle.all_time_high = AllTimeRecord(
                    city=city, country=country, kind="high",
                    new_temp_c=value_c,
                    old_record_c=thresholds.all_time_max_c,
                    old_record_year=thresholds.all_time_max_year or 0,
                    years_of_data=archive_years,
                    event_id=f"all_time_high_{sid_key}_{obs_date_iso}",
                    signal_date=obs_date,
                )

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

            cal_max = thresholds.calendar_date_max.get(md)
            if cal_max and value_c > cal_max[0] + RECORD_MARGIN_C:
                bundle.calendar_date_high = RecordEvent(
                    city=city, country=country,
                    new_temp_c=value_c,
                    old_record_c=cal_max[0],
                    old_record_year=cal_max[1],
                    event_id=f"cal_high_{sid_key}_{obs_date_iso}",
                    signal_date=obs_date,
                    kind="high",
                )

            clim_mean = thresholds.climatological_mean.get(month)
            if clim_mean is not None:
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

        elif o.element == "TMIN":
            archive_years = (
                thresholds.tmin_archive_years
                or station.get("tmin_archive_years", 0)
                or thresholds.archive_years
                or station.get("archive_years", 0)
            )
            if archive_years < MIN_ARCHIVE_YEARS:
                continue
            usable = True
            bundle.today_min_c = value_c
            bundle.archive_min_c = thresholds.all_time_min_c
            bundle.archive_min_year = thresholds.all_time_min_year

            if thresholds.all_time_min_c is not None and value_c < thresholds.all_time_min_c - RECORD_MARGIN_C:
                bundle.all_time_low = AllTimeRecord(
                    city=city, country=country, kind="low",
                    new_temp_c=value_c,
                    old_record_c=thresholds.all_time_min_c,
                    old_record_year=thresholds.all_time_min_year or 0,
                    years_of_data=archive_years,
                    event_id=f"all_time_low_{sid_key}_{obs_date_iso}",
                    signal_date=obs_date,
                )

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

            cal_min = thresholds.calendar_date_min.get(md)
            if cal_min and value_c < cal_min[0] - RECORD_MARGIN_C:
                bundle.calendar_date_low = RecordEvent(
                    city=city, country=country,
                    new_temp_c=value_c,
                    old_record_c=cal_min[0],
                    old_record_year=cal_min[1],
                    event_id=f"cal_low_{sid_key}_{obs_date_iso}",
                    signal_date=obs_date,
                    kind="low",
                )

            clim_mean = thresholds.climatological_mean_min.get(month)
            if clim_mean is not None:
                anomaly_c = value_c - clim_mean
                if anomaly_c <= -ANOMALY_COLD_THRESHOLD_C:
                    bundle.anomaly_cold = AnomalyEvent(
                        city=city, country=country,
                        today_temp_c=value_c,
                        historical_mean_c=clim_mean,
                        anomaly_c=anomaly_c,
                        years_of_data=archive_years,
                        event_id=f"anomaly_cold_{sid_key}_{obs_date_iso}",
                        signal_date=obs_date,
                    )

    if not usable:
        return None

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
        raise FileNotFoundError(
            f"GHCN threshold DB not found at {resolved_db}. "
            "Download the thresholds-latest release asset or run scripts/build_station_thresholds.py."
        )

    # 1. Load active stations
    if stations is None:
        with open_db(resolved_db) as conn:
            stations = load_active_stations(conn)

    if max_checks is not None:
        stations = stations[:max_checks]

    if not stations:
        return [], []

    active_ids = frozenset(s["station_id"] for s in stations)
    station_by_id = {s["station_id"]: s for s in stations}

    # 2. Fetch recent observations
    fetch_fn = _fetch_obs_fn or _fetch_recent_obs
    latest_obs = fetch_fn(active_ids)

    if not latest_obs:
        raise RuntimeError("GHCN: no observations returned; check NOAA diff endpoints")

    # 3. Load thresholds for stations that have new observations and compare
    all_bundles: list[ExtremeSignalBundle] = []
    signal_bundles: list[ExtremeSignalBundle] = []

    with open_db(resolved_db) as conn:
        for (station_id, _obs_date), obs_list in latest_obs.items():
            station = station_by_id.get(station_id)
            if station is None:
                continue

            thresholds = load_thresholds(conn, station_id)
            if thresholds is None:
                continue

            bundle = _detect_signals_for_station(station, obs_list, thresholds)
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
    country_records: list[CountryRecord] = []
    by_signal_date: dict[date, list[ExtremeSignalBundle]] = {}
    for bundle in all_bundles:
        if bundle.signal_date is not None:
            by_signal_date.setdefault(bundle.signal_date, []).append(bundle)
    for signal_date, group in by_signal_date.items():
        country_records.extend(
            detect_country_records(group, archive_years=archive_years, record_date=signal_date)
        )

    # 5. Dedup: cap at 2 signal-firing bundles per country
    deduped_signal_bundles = _dedup_by_metro(signal_bundles)

    return deduped_signal_bundles, country_records
