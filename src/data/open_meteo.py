from __future__ import annotations

"""Open-Meteo data fetching for current temps and historical record detection."""

import csv
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import requests

from src.data._http import fetch_with_retry
from src.data import places
from src.data.temperature_evidence import ARCHIVE_MODEL, forecast_day, daily_time, attach_evidence, finite, fingerprint
from src.data.openmeteo_budget import OpenMeteoSaturated

BASE_URL = "https://api.open-meteo.com/v1"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1"


@dataclass
class CityTemp:
    city: str
    country: str
    lat: float
    lon: float
    temp_high_c: float
    normal_high_c: float | None = None
    anomaly_c: float | None = None
    signal_date: date | None = None

    evidence: dict = field(default_factory=dict)


@dataclass
class RecordEvent:
    city: str
    country: str
    new_temp_c: float
    old_record_c: float
    old_record_year: int
    event_id: str
    signal_date: date | None = None  # provider-valid local date; None means unknown, never publication-ready
    kind: str = "high"  # "high" or "low"; default preserves legacy positional calls
    state: str | None = (
        None  # full state name (e.g. "West Virginia") for US stations; None elsewhere
    )
    lat: float | None = None
    lon: float | None = None

    evidence: dict = field(default_factory=dict)


@dataclass
class AllTimeRecord:
    """A city broke its hottest-or-coldest reading in the archive history."""

    city: str
    country: str
    kind: str  # "high" or "low"
    new_temp_c: float
    old_record_c: float
    old_record_year: int
    years_of_data: int  # how many years back the archive goes
    event_id: str
    signal_date: date | None = None
    state: str | None = None
    lat: float | None = None
    lon: float | None = None

    evidence: dict = field(default_factory=dict)


@dataclass
class MonthlyRecord:
    """A city broke its hottest-or-coldest reading for this month of year."""

    city: str
    country: str
    kind: str  # "high" or "low"
    month: int  # 1-12
    new_temp_c: float
    old_record_c: float
    old_record_year: int
    years_of_data: int
    event_id: str
    signal_date: date | None = None
    state: str | None = None
    lat: float | None = None
    lon: float | None = None

    evidence: dict = field(default_factory=dict)


@dataclass
class AnomalyEvent:
    """Today's reading is far above (or below) the historical mean for this month."""

    city: str
    country: str
    today_temp_c: float
    historical_mean_c: float
    anomaly_c: float  # today - mean, positive for hot, negative for cold
    years_of_data: int
    event_id: str
    signal_date: date | None = None
    state: str | None = None
    lat: float | None = None
    lon: float | None = None

    evidence: dict = field(default_factory=dict)


@dataclass
class AbsoluteExtremeEvent:
    """Today's reading exceeds the absolute threshold for its latitude band."""

    city: str
    country: str
    today_temp_c: float
    band_label: str
    threshold_c: float
    kind: str
    lat: float
    lon: float
    event_id: str
    signal_date: date | None = None
    state: str | None = None
    data_source: str = "forecast"

    evidence: dict = field(default_factory=dict)


@dataclass
class RecordStreakEvent:
    """A city has broken its daily record multiple days running."""

    city: str
    country: str
    consecutive_days: int
    start_date: str  # ISO date
    peak_temp_c: float
    event_id: str
    signal_date: date | None = None
    evidence: dict = field(default_factory=dict)


WETBULB_TIERS: list[tuple[int, float, str]] = [
    (3, 35.0, "tier_3"),
    (2, 33.0, "extreme"),
]


@dataclass
class WetBulbEvent:
    """Forecast daily-max wet-bulb temperature crossed an extreme tier."""

    city: str
    country: str
    daily_max_tw_c: float
    tier: int
    tier_label: str
    tier_threshold_c: float
    event_id: str
    signal_date: date | None = None
    lat: float | None = None
    lon: float | None = None
    archive_max_tw_c: float | None = None
    archive_max_year: int | None = None
    archive_years: int | None = None

    evidence: dict = field(default_factory=dict)


@dataclass
class ExtremeSignalBundle:
    """All extreme signals detected from a single city's archive fetch.

    Each event field is optional. A city might break ONLY its calendar-date
    record; another might break all-time + monthly + calendar-date
    simultaneously. We emit whichever are true.

    The ``today_*`` and ``archive_*`` fields are populated regardless of
    whether any record broke — downstream country-level aggregation needs
    every city's raw numbers, not just the ones that set records.

    GHCN-path additions (all optional, backward-compatible):
    - ``signal_date``: the date the reading was observed. None means
      unknown evidence and cannot establish a publication date.
    - ``station_id``: GHCN station ID (e.g. "USW00023183"). Empty for
      the Open-Meteo path.
    - ``station_name``: human-readable station name (e.g. "PHOENIX SKY
      HARBOR INTL AP"). Empty for the Open-Meteo path.
    """

    city: str = ""
    country: str = ""
    calendar_date_high: RecordEvent | None = None
    calendar_date_low: RecordEvent | None = None
    all_time_high: AllTimeRecord | None = None
    all_time_low: AllTimeRecord | None = None
    monthly_high: MonthlyRecord | None = None
    monthly_low: MonthlyRecord | None = None
    anomaly_hot: AnomalyEvent | None = None
    anomaly_cold: AnomalyEvent | None = None
    absolute_extreme: AbsoluteExtremeEvent | None = None
    wet_bulb_extreme: WetBulbEvent | None = None
    today_max_c: float | None = None
    today_min_c: float | None = None
    archive_max_c: float | None = None
    archive_max_year: int | None = None
    archive_min_c: float | None = None
    archive_min_year: int | None = None
    signal_date: date | None = None
    station_id: str = ""
    station_name: str = ""
    lat: float | None = None
    lon: float | None = None

    evidence: dict = field(default_factory=dict)


@dataclass
class CountryRecord:
    """A country's peak reading today exceeds its archive-wide peak.

    Unlike per-city records, this aggregates across every city we monitor
    in the country. The ``peak_city`` is the city that posted today's
    country-peak reading; the ``old_record_city`` is the historical holder
    across our archive (may be different city).
    """

    country: str
    kind: str  # "high" or "low"
    new_temp_c: float
    peak_city: str
    old_record_c: float
    old_record_year: int
    old_record_city: str
    years_of_data: int
    cities_sampled: int
    event_id: str
    signal_date: date | None = None
    eligible: int = 0
    cached: int = 0
    forecast_read: int = 0

    evidence: dict = field(default_factory=dict)


def load_cities(cities_path: str = "data/cities.csv") -> list[dict]:
    return places.load_cities(cities_path)


def load_normals(normals_path: str = "data/normals.csv") -> dict[str, dict]:
    """Attributable normals with the actual product and climatology period.

    Bare legacy city/month rows cannot identify a sample point or which fallback
    normal period produced the value. They require a deliberate qualified rebuild.
    """
    normals: dict[str, dict] = {}
    if not os.path.exists(normals_path):
        return normals
    with open(normals_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not all(row.get(k) for k in ("place_id", "sampling_point_id", "country", "lat", "lon", "period_start", "period_end", "retrieved_at")):
                continue
            if row.get("source_product") != "meteostat-normals-point-v1":
                continue
            try:
                identity = places.place_for_row(row)
                if row["sampling_point_id"] != identity["sampling_point_id"]:
                    continue
                start, end = int(row["period_start"]), int(row["period_end"])
                month, value = int(row["month"]), float(row["avg_high_c"])
                if not 1 <= month <= 12 or not 1800 <= start <= end <= 2200 or not finite(value):
                    continue
                key = places.event_location_key(row["city"], row["country"], row["lat"], row["lon"], place_id=row["place_id"])
            except (KeyError, ValueError, TypeError):
                continue
            provenance = {
                "source_product": row["source_product"], "evidence_type": "climatology_point_estimate",
                "period_start": start, "period_end": end, "retrieved_at": row["retrieved_at"],
                "sampling_point_id": identity["sampling_point_id"], "unit": "C", "month": month,
                "sample_count": None, "coverage_fraction": None,
                "comparison_scope": "Meteostat point monthly normal for the stated period; underlying sample coverage unavailable",
            }
            provenance["revision_id"] = fingerprint({"value": value, **provenance})
            entry = normals.setdefault(key, {"_meta": {}})
            # Conflicting rows for one point/month are unavailable, not last-row wins.
            if month in entry and (entry[month] != value or entry["_meta"][month] != provenance):
                entry.pop(month)
                entry["_meta"][month] = {"conflict": True}
            elif not entry["_meta"].get(month, {}).get("conflict"):
                entry[month], entry["_meta"][month] = value, provenance
    return normals


def fetch_city_forecast(lat: float, lon: float) -> dict | None:
    try:
        resp = fetch_with_retry(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max",
                "timezone": "auto",
                "temperature_unit": "celsius",
                "forecast_days": 1,
            },
            timeout=10,
            attempts=3,
            backoff_base=1.0,
        )
        result = forecast_day(resp.json())
        result["evidence"]["requested_sampling_point"] = {"latitude": lat, "longitude": lon}
        return result if result["max_c"] is not None else None
    except (requests.RequestException, IndexError, KeyError, ValueError, TypeError):
        return None


def fetch_city_temp(lat: float, lon: float) -> float | None:
    """Compatibility value-only accessor; publication consumers use full evidence."""
    result = fetch_city_forecast(lat, lon)
    return result["max_c"] if result else None


def fetch_all_city_temps(cities: list[dict]) -> list[CityTemp]:
    """Fetch current temps for all cities. Sequential, ~45 seconds for 150 cities."""
    results = []
    for city in cities:
        forecast = fetch_city_forecast(float(city["lat"]), float(city["lon"]))
        if forecast is not None:
            results.append(
                CityTemp(
                    city=city["city"],
                    country=city["country"],
                    lat=float(city["lat"]),
                    lon=float(city["lon"]),
                    temp_high_c=forecast["max_c"],
                    signal_date=date.fromisoformat(forecast["valid_date"]),
                    evidence=forecast["evidence"],
                )
            )
    return results


def compute_anomalies(
    temps: list[CityTemp],
    normals: dict[str, dict],
    max_anomaly_c: float = 30.0,
) -> list[CityTemp]:
    """Compute anomaly for each city. Filter out likely data errors (anomaly > max)."""
    for ct in temps:
        if ct.signal_date is None:
            ct.anomaly_c = None
            continue
        month = ct.signal_date.month
        city_normals = normals.get(places.event_location_key(ct.city, ct.country, ct.lat, ct.lon))
        if city_normals and month in city_normals:
            ct.normal_high_c = city_normals[month]
            ct.anomaly_c = ct.temp_high_c - ct.normal_high_c
            ct.evidence = {**ct.evidence, "baseline": city_normals.get("_meta", {}).get(month, {
                "evidence_type": "unqualified_normal", "period_start": None, "period_end": None,
                "comparison_scope": "period/source coverage not supplied; not a qualified production normal",
            })}
        else:
            ct.anomaly_c = None

    return [ct for ct in temps if ct.anomaly_c is not None and abs(ct.anomaly_c) <= max_anomaly_c]


def rank_hot10(temps: list[CityTemp]) -> list[CityTemp]:
    """Rank cities by anomaly, return top 10."""
    ranked = sorted(
        [ct for ct in temps if ct.anomaly_c is not None],
        key=lambda ct: ct.anomaly_c,
        reverse=True,
    )
    return ranked[:10]


def detect_records(lat: float, lon: float, city: str, country: str) -> RecordEvent | None:
    """Forecast compared with the calendar day in the declared ERA5 archive."""
    bundle = detect_extreme_signals(lat, lon, city, country)
    return bundle.calendar_date_high if bundle else None


# Cities most likely to break heat records — check these every run.
# These are the world's hottest cities plus US cities that routinely set records.
PRIORITY_HEAT_CITIES = {
    "Phoenix",
    "Death Valley",
    "Las Vegas",
    "Tucson",
    "Sacramento",
    "Dubai",
    "Abu Dhabi",
    "Doha",
    "Kuwait City",
    "Riyadh",
    "Mecca",
    "Muscat",
    "Baghdad",
    "Basra",
    "Ahvaz",
    "Delhi",
    "Jacobabad",
    "Karachi",
    "Djibouti",
    "Bamako",
    "Niamey",
    "N'Djamena",
    "Khartoum",
    "Miami",
    "Houston",
    "San Antonio",
    "Dallas",
    "Alice Springs",
    "Seville",
    "Athens",
}


def prioritize_cities(cities: list[dict]) -> list[dict]:
    """Put known extreme-heat cities first, shuffle the rest.

    Over 6 daily runs with shuffled tails, we cover far more than 50 cities/day.
    """
    priority = [c for c in cities if c["city"] in PRIORITY_HEAT_CITIES]
    rest = [c for c in cities if c["city"] not in PRIORITY_HEAT_CITIES]
    random.shuffle(rest)
    return priority + rest


# --- Interim Open-Meteo world-coverage budget (handoff 2026-06-25) -----------
# Open-Meteo's free archive endpoint enforces a per-minute request-weight limit
# that a 30-year daily pull saturates after ~12 cities (observed in prod:
# world[readings:12 failures:584]). `both` mode hands ~595 non-US cities to the
# live archive scan, so all but the first ~12 get 429'd ("Minutely API request
# limit exceeded") and the acute heat event — e.g. the 2026 European heatwave —
# goes unobserved. Until the world threshold cache lands (mirroring the GHCN
# SQLite threshold cache so per-run cost is a cheap forecast call, not a live
# 30-year archive pull), fetch only a budget-sized, deliberately-ordered slice
# so the event is seen instead of starved by the random tail of
# prioritize_cities(). Remove this cap when the cache ships.
WORLD_FETCH_BUDGET = 10

# Ordered, interim curation (most urgent first). Interleaves the 2026 NH-summer
# European heatwave cities (the regression this cap fixes) with the perennial
# global hot-spots so neither is starved by the budget. Spellings must match
# data/cities.csv exactly. Revert/replace when the cache removes the budget.
URGENT_WORLD_HEAT_CITIES = [
    "Madrid",
    "Jacobabad",
    "Sevilla",
    "Kuwait City",
    "Lyon",
    "Mecca",
    "Zaragoza",
    "Delhi",
    "Paris",
    "Ahvaz",
    "Rome",
    "Khartoum",
    "Athens",
    "Naples",
    "Karachi",
    "Lisbon",
]


def select_world_budget_cities(
    world_cities: list[dict],
    *,
    budget: int = WORLD_FETCH_BUDGET,
) -> list[dict]:
    """Return an ordered, deduped slice of ``world_cities`` of length <= budget.

    Urgent heat cities (those present in the input) come first, in
    ``URGENT_WORLD_HEAT_CITIES`` order; any remaining budget is backfilled from
    ``prioritize_cities()`` order. Interim guard for the Open-Meteo archive
    minutely rate limit; superseded by the world threshold cache.
    """
    rank = {name: i for i, name in enumerate(URGENT_WORLD_HEAT_CITIES)}
    ordered = sorted(
        prioritize_cities(world_cities), key=lambda row: rank.get(row["city"], len(rank))
    )
    selected, seen = [], set()
    for row in ordered:
        key = places.place_for_row(row)["place_id"]
        if key not in seen:
            selected.append(row)
            seen.add(key)
        if len(selected) >= budget:
            break
    return selected[:budget]


# Thresholds for elite signal categories
ANOMALY_HOT_THRESHOLD_C = 15.0  # today is 15°C+ above historical mean for this month
ANOMALY_COLD_THRESHOLD_C = 15.0  # today is 15°C+ below historical mean for this month

# Signed-latitude band table. Do not use abs(lat): N and S hemispheres have
# distinct thresholds.
LATITUDE_BANDS: list[tuple[float, float, float, float, str]] = [
    (66.5, 90.0, 30.0, -50.0, "Arctic"),
    (55.0, 66.5, 35.0, -40.0, "Sub-Arctic"),
    (40.0, 55.0, 42.0, -30.0, "N Mid-latitudes"),
    (23.5, 40.0, 47.0, -15.0, "N Sub-tropical"),
    (-23.5, 23.5, 50.0, 5.0, "Tropics"),
    (-40.0, -23.5, 48.0, -20.0, "S Sub-tropical"),
    (-90.0, -40.0, 40.0, -45.0, "S Mid-latitudes"),
]


def detect_absolute_extreme(
    lat: float,
    lon: float,
    today_max_c: float | None,
    today_min_c: float | None,
    city: str,
    country: str,
    *,
    signal_date: date | None = None,
    state: str | None = None,
    data_source: str = "forecast",
) -> AbsoluteExtremeEvent | None:
    """Fire if today's temp crosses the absolute threshold for this latitude band."""
    today = signal_date or date.today()
    today_iso = today.isoformat()
    city_key = places.event_location_key(city, country, lat, lon)

    band = next((b for b in LATITUDE_BANDS if b[0] <= lat < b[1]), None)
    if band is None:
        return None
    _, _, hot_threshold_c, cold_threshold_c, band_label = band

    if today_max_c is not None and today_max_c >= hot_threshold_c:
        return AbsoluteExtremeEvent(
            city=city,
            country=country,
            today_temp_c=today_max_c,
            band_label=band_label,
            threshold_c=hot_threshold_c,
            kind="hot",
            lat=lat,
            lon=lon,
            event_id=f"absextreme_{city_key}_{today_iso}",
            signal_date=signal_date,
            state=state,
            data_source=data_source,
        )

    if today_min_c is not None and today_min_c <= cold_threshold_c:
        return AbsoluteExtremeEvent(
            city=city,
            country=country,
            today_temp_c=today_min_c,
            band_label=band_label,
            threshold_c=cold_threshold_c,
            kind="cold",
            lat=lat,
            lon=lon,
            event_id=f"absextreme_cold_{city_key}_{today_iso}",
            signal_date=signal_date,
            state=state,
            data_source=data_source,
        )

    return None


def fetch_archive_daily(lat, lon, valid_date: date, *, archive_years=30) -> dict | None:
    """Fetch one consistent reanalysis product; retain the actual archive cutoff.

    ERA5 is delayed. Forecast/past_days values never fill its recent gap.
    The comparison explicitly ends at the returned accepted cutoff.
    """
    try:
        start = valid_date.replace(year=valid_date.year - archive_years)
    except ValueError:
        start = valid_date.replace(year=valid_date.year - archive_years, day=28)
    end = valid_date - timedelta(days=5)
    try:
        response = fetch_with_retry(
            f"{ARCHIVE_URL}/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "auto",
                "temperature_unit": "celsius",
                "models": ARCHIVE_MODEL,
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
        payload = response.json()
        timing = daily_time(payload)
        daily = payload["daily"]
        return {
            **daily,
            "_provenance": {
                **timing,
                "model": ARCHIVE_MODEL,
                "provider_grid": {key: payload.get(key) if finite(payload.get(key)) else None for key in ("latitude", "longitude", "elevation")},
                "provider_units": payload.get("daily_units") or {},
                "requested_sampling_point": {"latitude": lat, "longitude": lon},
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
            },
        }
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 429:
            raise OpenMeteoSaturated("archive 429") from exc
        return None
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def detect_extreme_signals(
    lat: float, lon: float, city: str, country: str, *, archive_years: int = 30
) -> ExtremeSignalBundle | None:
    """Compare a dated forecast with one immutable, scoped ERA5 archive snapshot."""
    from src.data.world_thresholds import compute_city_thresholds, evaluate_city

    try:
        response = fetch_with_retry(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max",
                "timezone": "auto",
                "temperature_unit": "celsius",
                "forecast_days": 1,
            },
            timeout=10,
            attempts=3,
            backoff_base=1.0,
        )
        forecast = forecast_day(response.json())
        if forecast["max_c"] is None and forecast["min_c"] is None:
            return None
        valid = date.fromisoformat(forecast["valid_date"])
        archive = fetch_archive_daily(lat, lon, valid, archive_years=archive_years)
        if not archive:
            return None
        baseline = compute_city_thresholds(
            city,
            archive,
            as_of=forecast["retrieved_at"][:10],
            years_of_data=archive_years,
            country=country,
            lat=lat,
            lon=lon,
        )
        bundle = evaluate_city(
            city, country, forecast, baseline, lat=lat, lon=lon, include_calendar=True
        )
        bundle.absolute_extreme = detect_absolute_extreme(
            lat, lon, forecast["max_c"], forecast["min_c"], city, country, signal_date=valid
        )
        attach_evidence(bundle, bundle.evidence)
        return bundle
    except (requests.RequestException, KeyError, ValueError, TypeError, OpenMeteoSaturated):
        return None


def check_extreme_signals_for_cities(
    cities: list[dict],
    max_checks: int | None = None,
    *,
    archive_years: int = 30,
    metrics_out: dict | None = None,
) -> tuple[list[ExtremeSignalBundle], list[CountryRecord]]:
    """Check cities for extreme signals. Returns ``(bundles, country_records)``.

    ``bundles`` contains only cities that tripped at least one signal.
    ``country_records`` is aggregated across ALL cities in the sample: when
    a country's peak today exceeds its archive-wide peak across every city
    we've sampled in that country, a CountryRecord fires. Requires at least
    2 cities in a country for the aggregate to be meaningful.
    """
    ordered = prioritize_cities(cities)
    to_check = ordered if max_checks is None else ordered[:max_checks]
    bundles = []
    all_readings: list[ExtremeSignalBundle] = []
    failures = 0
    for city in to_check:
        bundle = detect_extreme_signals(
            lat=float(city["lat"]),
            lon=float(city["lon"]),
            city=city["city"],
            country=city["country"],
            archive_years=archive_years,
        )
        if bundle is None:
            failures += 1
            continue
        all_readings.append(bundle)
        # Only include bundles with at least one per-city signal
        if any(
            [
                bundle.calendar_date_high,
                bundle.calendar_date_low,
                bundle.all_time_high,
                bundle.all_time_low,
                bundle.monthly_high,
                bundle.monthly_low,
                bundle.anomaly_hot,
                bundle.anomaly_cold,
                bundle.absolute_extreme,
                bundle.wet_bulb_extreme,
            ]
        ):
            bundles.append(bundle)

    country_records = detect_country_records(all_readings, archive_years=archive_years)
    withheld = [{"city": bundle.city, "valid_date": bundle.signal_date.isoformat(), "variable": variable, "reason": reason}
        for bundle in all_readings for variable, reason in bundle.evidence.get("comparison", {}).get("withheld_record_variables", {}).items()]
    if metrics_out is not None:
        metrics_out.update(
            {
                "record_comparisons_withheld": len(withheld), "withheld_record_candidates": withheld,
                "cities_attempted": len(to_check),
                "city_readings": len(all_readings),
                "city_fetch_failures": failures,
                "signal_bundles": len(bundles),
                "country_records": len(country_records),
            }
        )
    return bundles, country_records


def detect_country_records(
    readings: list[ExtremeSignalBundle],
    *,
    archive_years: int = 30,
    min_cities_per_country: int = 2,
    record_date: date | None = None,
    country_eligibility: dict[str, int] | None = None,
    country_forecast_read: dict[str, int] | None = None,
) -> list[CountryRecord]:
    """Scoped sampled-network comparisons; never an official national record.

    Separate valid dates and evidence classes cannot become one simultaneous
    observed event. High/low coverage is tested independently for every member.
    """
    groups, seen = {}, set()
    for reading in readings:
        valid = reading.signal_date or record_date
        if not reading.country or valid is None:
            continue
        try:
            identity = (
                reading.station_id
                or places.resolve_place(reading.city, reading.country, reading.lat, reading.lon)[
                    "place_id"
                ]
            )
        except ValueError:
            continue
        kind = reading.evidence.get("evidence_type") or (
            "observed" if reading.station_id else "forecast"
        )
        key = (places.country_key(reading.country), valid.isoformat(), kind)
        member_key = (*key, identity)
        if member_key not in seen:
            groups.setdefault(key, []).append(reading)
            seen.add(member_key)
    records = []
    for (country, valid, evidence_type), group in groups.items():
        eligible = (
            country_eligibility.get(country, len(group)) if country_eligibility else len(group)
        )
        if len(group) < max(min_cities_per_country, eligible):
            continue
        for kind, today_attr, prior_attr, year_attr, variable, choose in (
            ("high", "today_max_c", "archive_max_c", "archive_max_year", "temperature_2m_max", max),
            ("low", "today_min_c", "archive_min_c", "archive_min_year", "temperature_2m_min", min),
        ):
            current = [
                (getattr(row, today_attr), row.city)
                for row in group
                if getattr(row, today_attr) is not None
            ]
            history = [
                (getattr(row, prior_attr), row.city, getattr(row, year_attr))
                for row in group
                if getattr(row, prior_attr) is not None and getattr(row, year_attr) is not None
            ]
            if len(current) != len(group) or len(history) != len(group):
                continue
            peak, city = choose(current, key=lambda row: row[0])
            prior, prior_city, year = choose(history, key=lambda row: row[0])
            if not (peak > prior if kind == "high" else peak < prior):
                continue
            members = [
                {"city": row.city, "station_id": row.station_id or None, "evidence": row.evidence}
                for row in group
            ]
            evidence = {
                "domain": "temperature",
                "evidence_type": evidence_type,
                "source_product": "sampled-temperature-network",
                "valid_date": valid,
                "timezone": None,
                "valid_start": None,
                "valid_end": None,
                "baseline": {
                    "comparison_scope": "sampled_network",
                    "variable": variable,
                    "members": members,
                    "official_national_record": False,
                },
            }
            evidence["revision_id"] = fingerprint(evidence)
            years = [
                (row.evidence.get("baseline") or {})
                .get("variables", {})
                .get(variable, {})
                .get("years_with_samples", archive_years)
                for row in group
            ]
            records.append(
                CountryRecord(
                    country=group[0].country,
                    kind=kind,
                    new_temp_c=peak,
                    peak_city=city,
                    old_record_c=prior,
                    old_record_year=year,
                    old_record_city=prior_city,
                    years_of_data=min(years),
                    cities_sampled=len(group),
                    event_id=f"country_{kind}_{country}_{valid}",
                    signal_date=date.fromisoformat(valid),
                    eligible=eligible,
                    cached=len(group),
                    forecast_read=(
                        country_forecast_read.get(country, len(group))
                        if country_forecast_read
                        else len(group)
                    ),
                    evidence=evidence,
                )
            )
    return records


def check_records_for_cities(
    cities: list[dict], max_checks: int | None = None
) -> list[RecordEvent]:
    """Check cities for broken heat records.

    All 257 cities by default. Priority cities checked first so if the run
    is interrupted, the most likely record-breakers were already checked.
    """
    ordered = prioritize_cities(cities)
    to_check = ordered if max_checks is None else ordered[:max_checks]
    records = []
    for city in to_check:
        record = detect_records(
            lat=float(city["lat"]),
            lon=float(city["lon"]),
            city=city["city"],
            country=city["country"],
        )
        if record:
            records.append(record)
    return records


def detect_record_lows(lat: float, lon: float, city: str, country: str) -> RecordEvent | None:
    bundle = detect_extreme_signals(lat, lon, city, country)
    return bundle.calendar_date_low if bundle else None


PRIORITY_COLD_CITIES = {
    "Anchorage",
    "Fairbanks",
    "Yakutsk",
    "Ulaanbaatar",
    "Astana",
    "Moscow",
    "Helsinki",
    "Reykjavik",
    "Tromsø",
    "Denver",
    "Minneapolis",
    "Chicago",
    "Montreal",
    "Winnipeg",
    "La Paz",
    "Bogota",
    "Quito",
    "Lhasa",
    "Addis Ababa",
    "Dallas",
    "Atlanta",
    "Houston",  # surprise freezes are sensational
}


def prioritize_cities_cold(cities: list[dict]) -> list[dict]:
    """Put known cold-record cities first, shuffle the rest."""
    priority = [c for c in cities if c["city"] in PRIORITY_COLD_CITIES]
    rest = [c for c in cities if c["city"] not in PRIORITY_COLD_CITIES]
    random.shuffle(rest)
    return priority + rest


def check_record_lows_for_cities(
    cities: list[dict], max_checks: int | None = None
) -> list[RecordEvent]:
    """Check cities for broken cold records.

    All 257 cities by default. Priority cold cities checked first.
    """
    ordered = prioritize_cities_cold(cities)
    to_check = ordered if max_checks is None else ordered[:max_checks]
    records = []
    for city in to_check:
        record = detect_record_lows(
            lat=float(city["lat"]),
            lon=float(city["lon"]),
            city=city["city"],
            country=city["country"],
        )
        if record:
            records.append(record)
    return records


def fetch_forecasts_batch(cities: list[dict]) -> dict[str, dict]:
    """Fetch forecast data for multiple cities in one Open-Meteo request.

    Returns a mapping of product-qualified sampling key to {max_c, min_c, tw_max_c}. Raises
    OpenMeteoSaturated on HTTP 429; returns {} on any other failure.
    """
    if not cities:
        return {}
    lats = ",".join(str(c["lat"]) for c in cities)
    lons = ",".join(str(c["lon"]) for c in cities)
    try:
        resp = fetch_with_retry(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lats,
                "longitude": lons,
                "daily": "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max",
                "timezone": "auto",
                "temperature_unit": "celsius",
                "forecast_days": 1,
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 429:
            raise OpenMeteoSaturated("forecast 429") from exc
        return {}
    except requests.RequestException:
        return {}
    try:
        payload = resp.json()
    except ValueError:
        return {}
    blocks = payload if isinstance(payload, list) else [payload]
    if len(blocks) != len(cities) or any(not isinstance(block, dict) for block in blocks):
        return {}  # A partial/malformed batch cannot safely align readings to requested places.
    out: dict[str, dict] = {}
    for city, block in zip(cities, blocks):
        try:
            forecast = forecast_day(block)
        except (ValueError, TypeError, AttributeError):
            continue
        out[places.cache_key(city["city"], city["country"], city["lat"], city["lon"])] = forecast
    return out
