"""NOAA GHCN-Daily extreme-signal detection.

Public surface mirrors check_extreme_signals_for_cities() from open_meteo.py.
Reuses the same dataclasses; GHCN-path bundles populate signal_date,
station_id, and station_name.

Data flow per cycle:
  1. Fetch the latest superghcnd_diff file(s) from NOAA.
  2. Parse TMAX / TMIN observations for active stations.
  3. Use cached SQLite thresholds to discover potential record candidates.
  4. Verify at most 20 candidate/tracked station archives, recomputing accepted
     samples strictly before the actual observation day. Unverified history
     cannot authorize record, anomaly or country comparison claims.
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
import re
import hashlib
from copy import deepcopy
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from itertools import zip_longest
from typing import Callable
from src.state_schema import BotState

import requests


# GHCN station names follow ops conventions ("SISSONVILLE 1SW" = 1 mile
# southwest of Sissonville; "WFO SAN JUAN" = NWS Weather Forecast Office;
# "JFK INTL AP" = airport). These suffixes/prefixes don't belong in
# audience-facing prose and they break the Gemini fact-checker, which
# rejected the SISSONVILLE 1SW draft on 2026-05-08 because the writer
# correctly shortened the name to "Sissonville" and the fact-checker
# treated the dropped "1SW" as an unverifiable named-entity claim.

# CoCoRaHS-style direction-distance suffix: trailing whitespace +
# optional decimal number + optional whitespace + 1-3 cardinal direction
# letters. Examples: "1SW", "0.5N", "2NE", "3WSW", "4 NE", "0.5 N".
# The internal `\s*` between digit and direction handles both adjacent
# ("1SW") and space-separated ("4 NE") GHCN names; the latter caused
# the Paddock Lake fact-check kill regression on 2026-05-12.
_COOP_SUFFIX_RE = re.compile(r"\s+\d+(?:\.\d+)?\s*[NSEW]{1,3}$", re.IGNORECASE)

# Airport suffix: optional "INTL" / "INTERNATIONAL" / "MUNI" / etc.
# Then "AP" at the end. Examples: "INTL AP", "MUNI AP", "AP".
_AIRPORT_SUFFIX_RE = re.compile(
    r"\s+(?:INTL|INTERNATIONAL|MUNI|MUNICIPAL|REGIONAL|REGNL|NATIONAL)?\s*AP$",
    re.IGNORECASE,
)

# Military suffix: GHCN appends "ANG" (Air National Guard) on military
# weather stations ("SIOUX CITY ANG", "LINCOLN ANG"). Match only when
# it's a standalone trailing token — `\s+` before guards against false
# positives on real words ending in "ang" (PENANG, MUSTANG).
_MILITARY_SUFFIX_RE = re.compile(r"\s+ANG$", re.IGNORECASE)

# Weather Forecast Office prefix: "WFO X Y Z" -> "X Y Z".
_WFO_PREFIX_RE = re.compile(r"^WFO\s+", re.IGNORECASE)


# US state code -> full name. GHCN station inventory uses 2-letter codes;
# the writer needs the full name to write naturally ("West Virginia" not
# "WV") and the fact-checker needs the same form to pass entity checks.
# Observed 2026-05-08: writer was guessing state from world knowledge
# ("Dayton, Washington") and fact-checker rejected because state wasn't
# in the bundle.
_US_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "GU": "Guam",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}


def expand_us_state(code: str | None, country_code: str | None) -> str | None:
    """Map a 2-letter state/territory code to its full name.

    Only applied for US stations (country_code starts with "US"). Returns
    None for foreign stations (Canadian provinces, etc.) so the writer
    doesn't get a misleading "WA = Washington" expansion for, say, Canada.
    """
    if not code or not country_code:
        return None
    if not country_code.upper().startswith("US"):
        return None
    return _US_STATE_NAMES.get(code.strip().upper())


def normalize_station_name(raw: str) -> str:
    """Convert a GHCN station name to a human-readable place name.

    Strips the bureaucratic prefix/suffix and title-cases the result.
    Used to populate the ``city`` field on bundles so writer + fact-check
    both see a clean place name. The raw GHCN name is preserved on
    ``bundle.station_name`` for ops traceability.

    When the entire name after prefix/suffix stripping is a single all-caps
    token of length 2-4 (e.g. an IATA airport code: JFK, LAX, DCA), the
    token is returned as-is without title-casing.  This prevents ``JFK INTL AP``
    from becoming ``Jfk``.

    Tokens of length 5+ are real place words (AKRON, MIAMI, LOGAN) and
    title-case normally.  Multi-word post-strip results (e.g. ``SAN JUAN``,
    ``ATKA ISLAND``) are always title-cased; embedded short-token acronyms in
    those names (e.g. ``USC`` in ``L A DOWNTOWN USC``) are not specially
    preserved — doing so would produce false positives on common 3-char
    place-name fragments like SAN, RENO (4 chars), and ATKA (4 chars).

    Examples:
      "SISSONVILLE 1SW"        -> "Sissonville"
      "WFO SAN JUAN"           -> "San Juan"
      "ATKA ISLAND"            -> "Atka Island"
      "MIAMI INTL AP"          -> "Miami"
      "DEATH VALLEY"           -> "Death Valley"
      "JFK INTL AP"            -> "JFK"
      "LAX INTL AP"            -> "LAX"
      "DCA"                    -> "DCA"

    Returns the raw input unchanged if it's empty or stripping leaves
    nothing useful.
    """
    text = (raw or "").strip()
    if not text:
        return text
    text = _WFO_PREFIX_RE.sub("", text)
    text = _COOP_SUFFIX_RE.sub("", text)
    text = _AIRPORT_SUFFIX_RE.sub("", text)
    text = _MILITARY_SUFFIX_RE.sub("", text)
    text = text.strip()
    if not text:
        return raw

    # If the entire remaining text is a single all-caps token of length 2-3
    # (e.g. an IATA code like JFK, LAX, DCA), return it as-is.  Length 4+
    # tokens include real 4-char city names (RENO, ATKA) that should
    # title-case normally, so we only protect 2- and 3-char pure-acronym
    # station names.
    if re.fullmatch(r"[A-Z]{2,3}", text):
        return text

    return text.title()

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
    parse_dly_records_text,
    compute_thresholds,
)
from src.data.temperature_evidence import attach_evidence, fingerprint, finite, utc_now
from src.data.temperature_history import (
    record_claim_finding, record_observation_revision, retained_claims, tracked_points,
)
from src.data.open_meteo import (
    AllTimeRecord,
    AnomalyEvent,
    CountryRecord,
    ExtremeSignalBundle,
    MonthlyRecord,
    RecordEvent,
    detect_country_records,
    detect_absolute_extreme,
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

# Maximum age (in days) of an observation we treat as "current news".
# `superghcnd_diff` files contain late-arriving observations from arbitrary
# earlier dates — a station that uploaded its April 24 reading on May 5 will
# appear in the May 5 diff. We do NOT want to surface week-old readings as
# fresh signals; the editorial bar is "what happened recently," not "what was
# uploaded recently". 4 days = today, 1-, 2-, 3-day lag (covers a 24-72 hr
# publish window plus weekend slack). Tunable for backfill / replay scenarios.
MAX_OBS_AGE_DAYS = int(os.environ.get("THEHEAT_GHCN_MAX_OBS_AGE_DAYS", "4"))

# Minimum margin above the existing record to fire a signal (tenths-of-°C
# converted to °C). Prevents noisy ties from the same day re-firing.
RECORD_MARGIN_C = 0.0

# Anomaly thresholds (°C above/below climatological mean)
ANOMALY_HOT_THRESHOLD_C  = float(os.environ.get("THEHEAT_ANOMALY_HOT_THRESHOLD_C",  "8.0"))
ANOMALY_COLD_THRESHOLD_C = float(os.environ.get("THEHEAT_ANOMALY_COLD_THRESHOLD_C", "8.0"))

# Minimum archive years before we trust thresholds (avoids thin-data false positives)
MIN_ARCHIVE_YEARS = int(os.environ.get("THEHEAT_GHCN_MIN_ARCHIVE_YEARS", "15"))
ARCHIVE_VERIFICATION_LIMIT = 20
GHCN_SOURCE_PRODUCT = "noaa-ghcn-daily-v2"


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
            # bare-get: preserves 404-as-not-yet-published probe before raising.
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
    *,
    max_obs_age_days: int = MAX_OBS_AGE_DAYS,
    today: date | None = None,
    metrics_out: dict | None = None,
    revisions_out: list | None = None,
    tracked_keys: set[tuple[str, date, str]] | None = None,
) -> dict[tuple[str, date], list[DailyObs]]:
    """Fetch recent TMAX/TMIN observations for active stations.

    Returns a dict mapping (station_id, obs_date) → DailyObs list so same-day
    TMAX and TMIN are preserved instead of one element masking the other.

    Fetches recent superghcnd_diff tarballs in parallel and de-duplicates by
    station/date/element, keeping the latest parsed value.

    Late-arriving observations are filtered: any record with obs_date older than
    ``today - max_obs_age_days`` is discarded. ``superghcnd_diff`` regularly
    contains obs from 1-2 weeks ago that just got uploaded; surfacing those as
    fresh signals would be wrong (the bot reports current weather, not data-pipeline
    backfills).
    """
    today = today or date.today()
    dates = [today - timedelta(days=i) for i in range(1, lookback_days + 1)]
    obs_age_cutoff = today - timedelta(days=max_obs_age_days)

    # Fetch diffs in parallel (3 requests, lightweight)
    raw_by_date: dict[date, bytes] = {}
    with ThreadPoolExecutor(max_workers=lookback_days) as pool:
        future_to_date = {pool.submit(_fetch_diff, d): d for d in dates}
        for fut in as_completed(future_to_date):
            d = future_to_date[fut]
            content = fut.result()
            if content is not None:
                raw_by_date[d] = content

    if metrics_out is not None:
        metrics_out.update({
            "diff_dates_attempted": len(dates),
            "diff_dates_fetched": len(raw_by_date),
            "diff_dates_missing": len(dates) - len(raw_by_date),
            "diff_missing_dates": [
                d.isoformat() for d in dates if d not in raw_by_date
            ],
        })

    if not raw_by_date:
        raise RuntimeError("GHCN: no diff files available from NOAA")

    # Parse all records, keeping only the latest active station/date/element
    # state. Delete records and QC-failed updates must remove any earlier
    # value seen in the same lookback window. Records older than the obs-age
    # cutoff are skipped entirely (they're backfill, not news).
    obs_by_key: dict[tuple[str, date, str], DailyObs] = {}
    skipped_stale = 0
    for d in sorted(raw_by_date):
        retrieved_at = utc_now()
        source_revision = hashlib.sha256(raw_by_date[d]).hexdigest()
        records = parse_superghcnd_diff_records_bytes(raw_by_date[d])
        for rec in records:
            key = (rec.station_id, rec.obs_date, rec.element)
            if rec.station_id not in active_ids and key not in (tracked_keys or set()):
                continue
            if revisions_out is not None and key in (tracked_keys or set()):
                revisions_out.append((rec, retrieved_at, source_revision))
            if rec.station_id not in active_ids:
                continue
            if rec.obs_date < obs_age_cutoff or rec.obs_date > today:
                skipped_stale += 1
                continue
            obs = rec.to_daily_obs()
            if obs is None:
                obs_by_key.pop(key, None)
            else:
                obs_by_key[key] = replace(obs, retrieved_at=retrieved_at, source_revision=source_revision)

    by_station_date: dict[tuple[str, date], list[DailyObs]] = {}
    for o in obs_by_key.values():
        by_station_date.setdefault((o.station_id, o.obs_date), []).append(o)
    for obs_list in by_station_date.values():
        obs_list.sort(key=lambda o: 0 if o.element == "TMAX" else 1)

    log.info(
        "GHCN: fetched diffs for %d/%d dates; %d active station/date groups have fresh readings (%d backfill records skipped, cutoff=%s)",
        len(raw_by_date), lookback_days, len(by_station_date), skipped_stale, obs_age_cutoff.isoformat(),
    )
    if not by_station_date and revisions_out is None:
        raise RuntimeError("GHCN: diff files parsed but contained no active TMAX/TMIN observations within obs-age cutoff")
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
    name   = station.get("name", "")  # raw GHCN name, kept for traceability
    # Normalize for human-facing display — strips "1SW"/"INTL AP"/"WFO" etc.
    # so both writer prompt and fact-checker see the same clean place name.
    # Falls back to station_id if normalization yields empty (rare).
    city   = normalize_station_name(name) or sid
    country_name = station.get("country_name", "")
    country_code = station.get("country_code", "")
    # Prefer country_name for display; fall back to code
    country = country_name or country_code
    # Full state name for US stations ("West Virginia", not "WV"). None for
    # foreign stations (Canadian provinces don't get expanded — we don't
    # have that mapping and "WA" being Washington is a US-specific safe bet).
    state = expand_us_state(station.get("state"), country_code)
    try:
        station_lat = float(station["lat"]) if station.get("lat") is not None else None
        station_lon = float(station["lon"]) if station.get("lon") is not None else None
    except (TypeError, ValueError):
        station_lat = None
        station_lon = None

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
        if o.station_id != sid:
            raise ValueError("GHCN observation belongs to another station")
        if not finite(o.value_c) or o.qflag.strip():
            continue
        value_c = o.value_c
        variable = "temperature_2m_max" if o.element == "TMAX" else "temperature_2m_min"
        provenance = thresholds.provenance
        scope = (provenance.get("variables") or {}).get(variable) or {}
        eligible = (
            provenance.get("reconciled") is True
            and provenance.get("station_id") == sid
            and provenance.get("comparison_before") == obs_date_iso
            and provenance.get("source_product") == GHCN_SOURCE_PRODUCT
            and bool(provenance.get("source_payload_sha256"))
            and bool(provenance.get("retrieved_at"))
            and not scope.get("conflicting_dates")
            and scope.get("candidate_accepted") is True
            and scope.get("source_coverage_complete") is True
        )
        archive_years = scope.get("years_with_samples", 0)
        if o.element == "TMAX":
            usable = True
            bundle.today_max_c = value_c
            if not eligible or archive_years < MIN_ARCHIVE_YEARS:
                continue
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
                    state=state,
                    lat=station_lat,
                    lon=station_lon,
                )

            monthly_max = thresholds.monthly_max.get(month)
            if scope.get("monthly_years", {}).get(f"{month:02d}", 0) >= MIN_ARCHIVE_YEARS and monthly_max and value_c > monthly_max[0] + RECORD_MARGIN_C:
                bundle.monthly_high = MonthlyRecord(
                    city=city, country=country, kind="high", month=month,
                    new_temp_c=value_c,
                    old_record_c=monthly_max[0],
                    old_record_year=monthly_max[1],
                    years_of_data=archive_years,
                    event_id=f"monthly_high_{sid_key}_{month:02d}_{obs_date_iso}",
                    signal_date=obs_date,
                    state=state,
                    lat=station_lat,
                    lon=station_lon,
                )

            cal_max = thresholds.calendar_date_max.get(md)
            if scope.get("calendar_years", {}).get(f"{month:02d}-{day:02d}", 0) >= MIN_ARCHIVE_YEARS and cal_max and value_c > cal_max[0] + RECORD_MARGIN_C:
                bundle.calendar_date_high = RecordEvent(
                    city=city, country=country,
                    new_temp_c=value_c,
                    old_record_c=cal_max[0],
                    old_record_year=cal_max[1],
                    event_id=f"cal_high_{sid_key}_{obs_date_iso}",
                    signal_date=obs_date,
                    kind="high",
                    state=state,
                    lat=station_lat,
                    lon=station_lon,
                )

            clim_mean = thresholds.climatological_mean.get(month)
            if clim_mean is not None and scope.get("monthly_years", {}).get(f"{month:02d}", 0) >= MIN_ARCHIVE_YEARS:
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
                        state=state,
                        lat=station_lat,
                        lon=station_lon,
                    )

        elif o.element == "TMIN":
            usable = True
            bundle.today_min_c = value_c
            if not eligible or archive_years < MIN_ARCHIVE_YEARS:
                continue
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
                    state=state,
                    lat=station_lat,
                    lon=station_lon,
                )

            monthly_min = thresholds.monthly_min.get(month)
            if scope.get("monthly_years", {}).get(f"{month:02d}", 0) >= MIN_ARCHIVE_YEARS and monthly_min and value_c < monthly_min[0] - RECORD_MARGIN_C:
                bundle.monthly_low = MonthlyRecord(
                    city=city, country=country, kind="low", month=month,
                    new_temp_c=value_c,
                    old_record_c=monthly_min[0],
                    old_record_year=monthly_min[1],
                    years_of_data=archive_years,
                    event_id=f"monthly_low_{sid_key}_{month:02d}_{obs_date_iso}",
                    signal_date=obs_date,
                    state=state,
                    lat=station_lat,
                    lon=station_lon,
                )

            cal_min = thresholds.calendar_date_min.get(md)
            if scope.get("calendar_years", {}).get(f"{month:02d}-{day:02d}", 0) >= MIN_ARCHIVE_YEARS and cal_min and value_c < cal_min[0] - RECORD_MARGIN_C:
                bundle.calendar_date_low = RecordEvent(
                    city=city, country=country,
                    new_temp_c=value_c,
                    old_record_c=cal_min[0],
                    old_record_year=cal_min[1],
                    event_id=f"cal_low_{sid_key}_{obs_date_iso}",
                    signal_date=obs_date,
                    kind="low",
                    state=state,
                    lat=station_lat,
                    lon=station_lon,
                )

            clim_mean = thresholds.climatological_mean_min.get(month)
            if clim_mean is not None and scope.get("monthly_years", {}).get(f"{month:02d}", 0) >= MIN_ARCHIVE_YEARS:
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
                        state=state,
                        lat=station_lat,
                        lon=station_lon,
                    )

    if not usable:
        return None

    if station_lat is not None and station_lon is not None:
        abs_ev = detect_absolute_extreme(
            station_lat,
            station_lon,
            bundle.today_max_c,
            bundle.today_min_c,
            city,
            country,
            signal_date=obs_date,
            state=state,
            data_source="ghcn",
        )
        if abs_ev is not None:
            abs_ev.event_id = f"absextreme_{abs_ev.kind}_{sid_key}_{obs_date_iso}"
            bundle.absolute_extreme = abs_ev

    evidence = {
        "domain": "temperature", "evidence_type": "observed", "source_product": GHCN_SOURCE_PRODUCT,
        "station_id": sid, "valid_date": obs_date_iso,
        "timezone": None, "valid_start": None, "valid_end": None,
        "issued_at": None, "model_run": None,
        "retrieved_at": max((o.retrieved_at for o in obs_list if o.retrieved_at), default=None),
        "aggregation": "station_reported_daily_extreme", "unit": "C",
        "reporting_interval_known": False,
        "variables": {o.element: {
            "value_c": o.value_c, "mflag": o.mflag, "qflag": o.qflag, "sflag": o.sflag,
            "observation_time": o.observation_time, "source_payload_sha256": o.source_revision,
        } for o in obs_list if finite(o.value_c) and not o.qflag.strip()},
        "baseline": deepcopy(thresholds.provenance),
        "publication_time_qc_known": False,
    }
    evidence["revision_id"] = fingerprint({key: value for key, value in evidence.items() if key != "retrieved_at"})
    attach_evidence(bundle, evidence)
    return bundle


def _has_signal(bundle: ExtremeSignalBundle) -> bool:
    return any([
        bundle.calendar_date_high, bundle.calendar_date_low,
        bundle.all_time_high, bundle.all_time_low,
        bundle.monthly_high, bundle.monthly_low,
        bundle.anomaly_hot, bundle.anomaly_cold,
        bundle.absolute_extreme,
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
        if b.absolute_extreme:
            score += 8
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
    metrics_out: dict | None = None,
    bot_state: BotState | dict | None = None,
    archive_verification_limit: int = ARCHIVE_VERIFICATION_LIMIT,
    _fetch_archive_fn: Callable | None = None,
    _now_fn: Callable | None = None,
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
        bot_state: optional durable material-revision/affected-claim history.
        archive_verification_limit: candidate/tracked station cap; always at most 20.
        _fetch_archive_fn: offline test seam returning original .dly bytes.
        _now_fn: explicit UTC retrieval clock seam, never an observation date.
        metrics_out: if provided, populated in-place with funnel counts
            (stations_active, stations_with_obs, station_obs_pairs,
            stations_checked, raw_signals, bundles_after_dedup,
            country_records). Lets the caller surface pipeline visibility
            in telemetry/dashboards without breaking the return contract.
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
        if metrics_out is not None:
            metrics_out.update(_empty_pipeline_metrics())
        return [], []

    active_ids = frozenset(s["station_id"] for s in stations)
    station_by_id = {s["station_id"]: s for s in stations}

    # Cached thresholds only discover candidates. Every historical comparison
    # is recomputed from a bounded, current station archive before the valid day.
    now = (_now_fn or utc_now)()
    state = bot_state if bot_state is not None else {}
    claims = retained_claims(state)
    points = tracked_points(state)
    revisions: list = []
    fetch_metrics: dict = {}
    if _fetch_obs_fn is None:
        try:
            latest_obs = _fetch_recent_obs(
                active_ids, metrics_out=fetch_metrics, revisions_out=revisions,
                tracked_keys=points, today=date.fromisoformat(now[:10]),
            )
        except RuntimeError:
            if not points:
                raise
            latest_obs = {}
            fetch_metrics["diff_fetch_failed"] = 1
    else:
        latest_obs = _fetch_obs_fn(active_ids)
    metrics = _empty_pipeline_metrics() | fetch_metrics
    with open_db(resolved_db) as conn:
        cached = {sid: load_thresholds(conn, sid) for sid in active_ids}
    candidates = {
        sid for (sid, _), obs in latest_obs.items()
        if sid in active_ids and _could_need_baseline(obs, cached[sid])
    }
    tracked_stations = {sid for sid, _, _ in points}
    # Rotate deterministically by UTC day within each lane, then interleave the
    # two lanes so neither old published evidence nor new candidates starves.
    def rotate(ids):
        ordered = sorted(ids)
        if not ordered:
            return ordered
        offset = date.fromisoformat(now[:10]).toordinal() % len(ordered)
        return ordered[offset:] + ordered[:offset]
    tracked_order = rotate(tracked_stations)
    candidate_order = rotate(candidates)
    priority = list(dict.fromkeys(
        sid for pair in zip_longest(tracked_order, candidate_order)
        for sid in pair if sid is not None
    ))
    if isinstance(archive_verification_limit, bool) or not isinstance(archive_verification_limit, int):
        raise ValueError("GHCN archive verification limit must be an integer")
    limit = max(0, min(archive_verification_limit, ARCHIVE_VERIFICATION_LIMIT))
    selected = priority[:limit]
    metrics["archive_verification_attempted"] = len(selected)
    metrics["archive_verification_exhausted"] = len(priority) - len(selected)
    metrics["tracked_stations_unscanned"] = len(tracked_stations - set(selected))
    snapshots = {}
    fetch_archive = _fetch_archive_fn or _fetch_station_archive
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_archive, sid): sid for sid in selected}
        for future in as_completed(futures):
            sid = futures[future]
            try:
                snapshots[sid] = _archive_snapshot(sid, future.result(), now)
            except (requests.RequestException, OSError, ValueError, TypeError, UnicodeError) as exc:
                metrics["archive_verification_failed"] += 1
                log.warning("GHCN station verification unavailable for %s: %s", sid, exc)
    metrics["archive_verification_verified"] = len(snapshots)
    metrics["tracked_stations_unscanned"] = len(tracked_stations - snapshots.keys())
    # Old-dated QC updates are reviewed even when too old for a news signal.
    latest_revisions = {}
    for record, retrieved, source_revision in revisions:
        _, added = record_observation_revision(state, record, retrieved_at=retrieved, source_revision=source_revision)
        metrics["material_revisions"] += int(added)
        latest_revisions[(record.station_id, record.obs_date, record.element)] = (record, retrieved, source_revision)
    for record, retrieved, source_revision in latest_revisions.values():
        if record.station_id not in snapshots:
            _, findings = _retain_changed_point(state, record, retrieved, source_revision, claims)
            metrics["affected_claims"] += findings
    for sid, snapshot in snapshots.items():
        material, findings = _retain_snapshot_revisions(state, sid, snapshot, claims, points)
        metrics["material_revisions"] += material
        metrics["affected_claims"] += findings
    for claim in claims:
        if claim["station_id"] not in snapshots:
            metrics["affected_claims"] += int(record_claim_finding(
                state, claim, reason="current_archive_unverified", source_revision=None,
                retrieved_at=now, details={"coverage": "station_archive_not_verified_this_run",
                                          "historical_correctness": "not_determined"},
            ))
    if not latest_obs and not tracked_stations:
        if metrics_out is not None:
            metrics_out.update(metrics | {"stations_active": len(stations)})
        raise RuntimeError("GHCN: no observations returned; check NOAA diff endpoints")
    all_bundles: list[ExtremeSignalBundle] = []
    signal_bundles: list[ExtremeSignalBundle] = []
    for (station_id, _obs_date), obs_list in latest_obs.items():
        station = station_by_id.get(station_id)
        if station is None or not obs_list:
            continue
        snapshot = snapshots.get(station_id)
        if snapshot is not None:
            thresholds, checked_obs = _thresholds_from_verified_archive(station_id, obs_list, snapshot)
        else:
            thresholds = deepcopy(cached[station_id]) or StationThresholds(station_id=station_id)
            thresholds.provenance = {"reconciled": False, "comparison_scope": "unverified_cached_baseline",
                                     "limitation": "current_station_archive_not_verified"}
            checked_obs = obs_list
        if not thresholds.provenance.get("reconciled") or any(
            not thresholds.provenance.get("variables", {}).get(
                "temperature_2m_max" if row.element == "TMAX" else "temperature_2m_min", {}
            ).get("source_coverage_complete") for row in obs_list
        ):
            metrics["baseline_cutoff_gaps"] += 1
        bundle = _detect_signals_for_station(station, checked_obs, thresholds)
        if bundle is None:
            continue
        all_bundles.append(bundle)
        if _has_signal(bundle):
            signal_bundles.append(bundle)
        if snapshot is not None:
            metrics["material_revisions"] += _retain_record_points(state, bundle, snapshot)

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

    if metrics_out is not None:
        metrics_out.update({
            **metrics,
            "stations_active": len(stations),
            "stations_with_obs": len({k[0] for k in latest_obs}),
            "station_obs_pairs": len(latest_obs),
            "stations_checked": len(all_bundles),
            "raw_signals": len(signal_bundles),
            "bundles_after_dedup": len(deduped_signal_bundles),
            "country_records": len(country_records),
        })

    return deduped_signal_bundles, country_records


def _empty_pipeline_metrics() -> dict:
    return {
        "stations_active": 0,
        "stations_with_obs": 0,
        "station_obs_pairs": 0,
        "stations_checked": 0,
        "raw_signals": 0,
        "bundles_after_dedup": 0,
        "country_records": 0,
        "archive_verification_attempted": 0, "archive_verification_verified": 0,
        "archive_verification_exhausted": 0, "archive_verification_failed": 0,
        "baseline_cutoff_gaps": 0, "tracked_stations_unscanned": 0,
        "material_revisions": 0, "affected_claims": 0, "diff_fetch_failed": 0,
    }


def _fetch_station_archive(station_id: str) -> bytes:
    """Bounded candidate verification; never a bulk archive/bootstrap download."""
    if not re.fullmatch(r"[A-Z0-9]{11}", station_id):
        raise ValueError("Invalid GHCN station ID")
    with requests.get(
        f"https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{station_id}.dly", timeout=30,
        stream=True,
    ) as response:
        response.raise_for_status()
        chunks = []
        received = 0
        for chunk in response.iter_content(chunk_size=65536):
            received += len(chunk)
            if received > 8_000_000:
                raise ValueError("GHCN station archive exceeds bounded verification size")
            chunks.append(chunk)
        return b"".join(chunks)


def _could_need_baseline(obs, thresholds):
    """Discovery heuristic only; cached thresholds never authorize a record."""
    for row in obs:
        if not finite(row.value_c) or row.qflag.strip():
            continue
        if thresholds is None:
            return True
        high = row.element == "TMAX"
        values = [thresholds.all_time_max_c if high else thresholds.all_time_min_c]
        monthly = thresholds.monthly_max if high else thresholds.monthly_min
        calendar = thresholds.calendar_date_max if high else thresholds.calendar_date_min
        values.extend([monthly.get(row.obs_date.month, (None,))[0], calendar.get((row.obs_date.month, row.obs_date.day), (None,))[0]])
        if any(finite(prior) and (row.value_c > prior if high else row.value_c < prior) for prior in values):
            return True
        mean = (thresholds.climatological_mean if high else thresholds.climatological_mean_min).get(row.obs_date.month)
        if finite(mean) and abs(row.value_c - mean) >= min(ANOMALY_HOT_THRESHOLD_C, ANOMALY_COLD_THRESHOLD_C):
            return True
    return False


def _archive_snapshot(station_id, payload, retrieved_at):
    if not isinstance(payload, bytes):
        raise ValueError("GHCN archive verification requires original source bytes")
    rows = parse_dly_records_text(payload.decode("ascii", errors="strict"))
    if not rows or any(row.station_id != station_id for row in rows):
        raise ValueError("GHCN archive is empty or belongs to another station")
    grouped: dict = {}
    for row in rows:
        key = (row.obs_date, row.element)
        if key in grouped and grouped[key] != row:
            raise ValueError("GHCN archive has contradictory daily observations")
        grouped[key] = row
    return {"records": grouped, "retrieved_at": retrieved_at, "source_revision": hashlib.sha256(payload).hexdigest()}


def _thresholds_from_verified_archive(station_id, obs, snapshot):
    day = obs[0].obs_date
    accepted = [value for row in snapshot["records"].values() if (value := row.to_daily_obs()) is not None]
    thresholds = compute_thresholds(
        accepted, before=day, retrieved_at=snapshot["retrieved_at"], source_revision=snapshot["source_revision"],
    ) or StationThresholds(station_id=station_id)
    _qualify_archive_coverage(thresholds, snapshot, day)
    reconciled = []
    for original in obs:
        row = snapshot["records"].get((original.obs_date, original.element))
        current = row.to_daily_obs() if row else None
        variable = "temperature_2m_max" if original.element == "TMAX" else "temperature_2m_min"
        scope = thresholds.provenance.setdefault("variables", {}).setdefault(variable, {})
        exact = current is not None and current.value_c == original.value_c
        scope["candidate_accepted"] = exact
        if row is not None and (current is None or not exact):
            # A newer QC failure/value discrepancy cannot support the old value,
            # including an otherwise valid absolute-temperature threshold claim.
            continue
        reconciled.append(replace(
            current if current is not None and exact else original,
            retrieved_at=snapshot["retrieved_at"] if exact else original.retrieved_at,
            source_revision=snapshot["source_revision"] if exact else original.source_revision,
        ))
    thresholds.provenance["revision_id"] = fingerprint({key: value for key, value in thresholds.provenance.items() if key != "retrieved_at"})
    return thresholds, reconciled


def _retain_snapshot_revisions(state, station_id, snapshot, claims, points):
    """Review tracked historical points regardless of news freshness cutoff."""
    material = findings = 0
    for (day, element), row in snapshot["records"].items():
        if (station_id, day, element) not in points:
            continue
        added, linked = _retain_changed_point(state, row, snapshot["retrieved_at"], snapshot["source_revision"], claims)
        material += added
        findings += linked
    for claim in claims:
        if (claim["station_id"] == station_id
                and (date.fromisoformat(claim["valid_date"]), claim["element"]) not in snapshot["records"]):
            findings += int(record_claim_finding(
                state, claim, reason="tracked_observation_absent_from_current_archive",
                source_revision=snapshot["source_revision"], retrieved_at=snapshot["retrieved_at"],
                details={"historical_correctness": "not_determined", "current_source_coverage": "missing"},
            ))
    accepted = [value for row in snapshot["records"].values() if (value := row.to_daily_obs()) is not None]
    for claim in claims:
        if claim["station_id"] != station_id or claim.get("reported_previous_c") is None:
            continue
        prior = compute_thresholds(accepted, before=date.fromisoformat(claim["valid_date"]),
                                   retrieved_at=snapshot["retrieved_at"], source_revision=snapshot["source_revision"])
        if prior is None:
            continue
        _qualify_archive_coverage(prior, snapshot, date.fromisoformat(claim["valid_date"]))
        variable = "temperature_2m_max" if claim["element"] == "TMAX" else "temperature_2m_min"
        if not prior.provenance["variables"][variable].get("source_coverage_complete"):
            findings += int(record_claim_finding(
                state, claim, reason="current_archive_comparison_gap", source_revision=snapshot["source_revision"],
                retrieved_at=snapshot["retrieved_at"],
                details={"historical_correctness": "not_determined", "variable": variable,
                         "requested_comparison_cutoff": prior.provenance["requested_comparison_cutoff"]},
            ))
            continue
        high = claim["element"] == "TMAX"
        day = date.fromisoformat(claim["valid_date"])
        event = claim["event_id"]
        if "monthly_" in event:
            found = (prior.monthly_max if high else prior.monthly_min).get(day.month)
            value = found[0] if found else None
        elif "cal_" in event or "record_" in event:
            found = (prior.calendar_date_max if high else prior.calendar_date_min).get((day.month, day.day))
            value = found[0] if found else None
        else:
            value = prior.all_time_max_c if high else prior.all_time_min_c
        if value is not None and value != claim["reported_previous_c"]:
            findings += int(record_claim_finding(
                state, claim, reason="current_archive_comparator_changed", source_revision=prior.provenance["revision_id"],
                retrieved_at=snapshot["retrieved_at"], verified_change=True,
                details={"retained_comparator_c": claim["reported_previous_c"], "current_accepted_comparator_c": value,
                         "comparison_before": claim["valid_date"], "historical_revision_timing": "not_established"},
            ))
    return material, findings


def _retain_changed_point(state, row, retrieved_at, source_revision, claims):
    revision_id, added = record_observation_revision(state, row, retrieved_at=retrieved_at, source_revision=source_revision)
    findings = 0
    for claim in claims:
        if (claim["station_id"], claim["valid_date"], claim["element"]) != (row.station_id, row.obs_date.isoformat(), row.element):
            continue
        changed = claim.get("reported_value_c") is not None and claim["reported_value_c"] != row.value_c
        if row.value_c is None and row.action != "delete" and not row.qflag.strip():
            findings += int(record_claim_finding(
                state, claim, reason="tracked_observation_missing_current_value", source_revision=revision_id,
                retrieved_at=retrieved_at,
                details={"historical_correctness": "not_determined", "current_source_coverage": "missing"},
            ))
        elif row.to_daily_obs() is None or changed:
            findings += int(record_claim_finding(
                state, claim, reason="current_source_qc_or_value_revision", source_revision=revision_id,
                retrieved_at=retrieved_at, verified_change=True,
                details={"current_value_c": row.value_c, "current_qflag": row.qflag.strip(),
                         "source_accepted": row.to_daily_obs() is not None,
                         "publication_time_flag_timing": "unknown" if claim.get("publication_time_qflag") is None else "retained_source_flag"},
            ))
    return int(added), findings


def _retain_record_points(state, bundle, snapshot):
    added = 0
    for field, element, scope_name in (
        ("all_time_high", "TMAX", "all_time"), ("all_time_low", "TMIN", "all_time"),
        ("monthly_high", "TMAX", "monthly"), ("monthly_low", "TMIN", "monthly"),
        ("calendar_date_high", "TMAX", "calendar"), ("calendar_date_low", "TMIN", "calendar"),
    ):
        event = getattr(bundle, field)
        if event is None:
            continue
        variable = "temperature_2m_max" if element == "TMAX" else "temperature_2m_min"
        dates = bundle.evidence["baseline"]["variables"][variable]["record_dates"]
        prior = dates.get(scope_name)
        if isinstance(prior, dict):
            prior = prior.get(bundle.signal_date.strftime("%m" if scope_name == "monthly" else "%m-%d"))
        for day in (bundle.signal_date, date.fromisoformat(prior) if prior else None):
            row = snapshot["records"].get((day, element))
            if row is not None:
                _, created = record_observation_revision(state, row, retrieved_at=snapshot["retrieved_at"], source_revision=snapshot["source_revision"])
                added += int(created)
    return added


def _qualify_archive_coverage(thresholds, snapshot, before):
    """Distinguish omitted source intervals from explicit missing/QC cells.

    A complete source-calendar interval supports only the available accepted
    station samples. It does not certify missing/QC-rejected values or a physical
    all-time extreme outside that scope. Missing source months fail closed.
    """
    provenance = thresholds.provenance
    requested = (before - timedelta(days=1)).isoformat()
    provenance["requested_comparison_cutoff"] = requested
    qualified = []
    for variable, element in (("temperature_2m_max", "TMAX"), ("temperature_2m_min", "TMIN")):
        scope = provenance.setdefault("variables", {}).setdefault(variable, {})
        start = scope.get("start")
        source_rows = [row for (day, kind), row in snapshot["records"].items()
                       if kind == element and start is not None and start <= day.isoformat() < before.isoformat()]
        expected = scope.get("expected_count", 0)
        complete = bool(expected and len(source_rows) == expected)
        scope.update(
            source_calendar_count=len(source_rows), source_coverage_complete=complete,
            source_gap_count=max(0, expected - len(source_rows)),
            source_coverage_fraction=len(source_rows) / expected if expected else 0,
            source_latest_cell=max((row.obs_date.isoformat() for row in source_rows), default=None),
            source_missing_count=sum(row.value_c is None for row in source_rows),
            source_qc_rejected_count=sum(bool(row.qflag.strip()) for row in source_rows),
            requested_comparison_cutoff=requested,
            verified_source_cutoff=requested if complete else None,
        )
        if expected:
            qualified.append(complete)
    provenance["cutoff"] = requested if qualified and all(qualified) else None
    provenance["revision_id"] = fingerprint({key: value for key, value in provenance.items() if key != "retrieved_at"})
