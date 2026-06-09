from __future__ import annotations

"""Open-Meteo data fetching for current temps and historical record detection."""

import csv
import os
import random
from dataclasses import dataclass
from datetime import date, timedelta

import requests

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


@dataclass
class RecordEvent:
    city: str
    country: str
    new_temp_c: float
    old_record_c: float
    old_record_year: int
    event_id: str
    signal_date: date | None = None  # date reading was observed; None → use date.today()
    kind: str = "high"  # "high" or "low"; default preserves legacy positional calls
    state: str | None = None  # full state name (e.g. "West Virginia") for US stations; None elsewhere
    lat: float | None = None
    lon: float | None = None


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
      the Open-Meteo path; consumers fall back to date.today().
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
    today_max_c: float | None = None
    today_min_c: float | None = None
    archive_max_c: float | None = None
    archive_max_year: int | None = None
    archive_min_c: float | None = None
    archive_min_year: int | None = None
    signal_date: date | None = None
    station_id: str = ""
    station_name: str = ""


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


def load_cities(cities_path: str = "data/cities.csv") -> list[dict]:
    with open(cities_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_normals(normals_path: str = "data/normals.csv") -> dict[str, dict[int, float]]:
    """Returns {city_name: {month_int: avg_high_c}}."""
    normals = {}
    if not os.path.exists(normals_path):
        return normals
    with open(normals_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            city = row["city"]
            month = int(row["month"])
            normals.setdefault(city, {})[month] = float(row["avg_high_c"])
    return normals


def fetch_city_temp(lat: float, lon: float) -> float | None:
    """Fetch today's high temperature for a single location."""
    try:
        resp = requests.get(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("daily", {}).get("temperature_2m_max", [])
        return temps[0] if temps and temps[0] is not None else None
    except (requests.RequestException, IndexError, KeyError):
        return None


def fetch_all_city_temps(cities: list[dict]) -> list[CityTemp]:
    """Fetch current temps for all cities. Sequential, ~45 seconds for 150 cities."""
    results = []
    for city in cities:
        temp = fetch_city_temp(float(city["lat"]), float(city["lon"]))
        if temp is not None:
            results.append(CityTemp(
                city=city["city"],
                country=city["country"],
                lat=float(city["lat"]),
                lon=float(city["lon"]),
                temp_high_c=temp,
            ))
    return results


def compute_anomalies(
    temps: list[CityTemp],
    normals: dict[str, dict[int, float]],
    max_anomaly_c: float = 30.0,
) -> list[CityTemp]:
    """Compute anomaly for each city. Filter out likely data errors (anomaly > max)."""
    month = date.today().month
    for ct in temps:
        city_normals = normals.get(ct.city)
        if city_normals and month in city_normals:
            ct.normal_high_c = city_normals[month]
            ct.anomaly_c = ct.temp_high_c - ct.normal_high_c
        else:
            ct.anomaly_c = None

    return [
        ct for ct in temps
        if ct.anomaly_c is not None and abs(ct.anomaly_c) <= max_anomaly_c
    ]


def rank_hot10(temps: list[CityTemp]) -> list[CityTemp]:
    """Rank cities by anomaly, return top 10."""
    ranked = sorted(
        [ct for ct in temps if ct.anomaly_c is not None],
        key=lambda ct: ct.anomaly_c,
        reverse=True,
    )
    return ranked[:10]


def detect_records(lat: float, lon: float, city: str, country: str) -> RecordEvent | None:
    """Check whether today's forecast high would break the record for this date."""
    today = date.today()
    try:
        # Use the forecast high as an early warning signal; NOAA confirmations land later.
        resp_today = requests.get(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp_today.raise_for_status()
        today_temp = resp_today.json()["daily"]["temperature_2m_max"][0]
        if today_temp is None:
            return None

        # Fetch historical data for this calendar date going back 30 years
        historical_highs = []
        for years_back in range(1, 31):
            hist_date = today.replace(year=today.year - years_back)
            historical_highs.append((hist_date.year, hist_date))

        # Batch: fetch full range from archive
        try:
            start = today.replace(year=today.year - 30)
        except ValueError:
            # Feb 29 on a non-leap year 30 years ago
            start = today.replace(year=today.year - 30, day=28)
        end = today - timedelta(days=1)
        resp_hist = requests.get(
            f"{ARCHIVE_URL}/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "auto",
            },
            timeout=30,
        )
        resp_hist.raise_for_status()
        hist_data = resp_hist.json()
        dates = hist_data.get("daily", {}).get("time", [])
        temps = hist_data.get("daily", {}).get("temperature_2m_max", [])

        # Find max temp on this calendar date (same month/day) in history
        target_month = today.month
        target_day = today.day
        old_record_c = None
        old_record_year = None

        for d_str, t in zip(dates, temps):
            if t is None:
                continue
            d = date.fromisoformat(d_str)
            if d.month == target_month and d.day == target_day:
                if old_record_c is None or t > old_record_c:
                    old_record_c = t
                    old_record_year = d.year

        if old_record_c is not None and today_temp > old_record_c:
            return RecordEvent(
                city=city,
                country=country,
                new_temp_c=today_temp,
                old_record_c=old_record_c,
                old_record_year=old_record_year,
                event_id=f"record_{city.replace(' ', '_')}_{today.isoformat()}",
                kind="high",
                lat=lat,
                lon=lon,
            )

        return None

    except (requests.RequestException, KeyError, IndexError):
        return None


# Cities most likely to break heat records — check these every run.
# These are the world's hottest cities plus US cities that routinely set records.
PRIORITY_HEAT_CITIES = {
    "Phoenix", "Death Valley", "Las Vegas", "Tucson", "Sacramento",
    "Dubai", "Abu Dhabi", "Doha", "Kuwait City", "Riyadh", "Mecca", "Muscat",
    "Baghdad", "Basra", "Ahvaz",
    "Delhi", "Jacobabad", "Karachi",
    "Djibouti", "Bamako", "Niamey", "N'Djamena", "Khartoum",
    "Miami", "Houston", "San Antonio", "Dallas",
    "Alice Springs", "Seville", "Athens",
}


def prioritize_cities(cities: list[dict]) -> list[dict]:
    """Put known extreme-heat cities first, shuffle the rest.

    Over 6 daily runs with shuffled tails, we cover far more than 50 cities/day.
    """
    priority = [c for c in cities if c["city"] in PRIORITY_HEAT_CITIES]
    rest = [c for c in cities if c["city"] not in PRIORITY_HEAT_CITIES]
    random.shuffle(rest)
    return priority + rest


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
    city_key = city.replace(" ", "_")

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


def detect_extreme_signals(
    lat: float,
    lon: float,
    city: str,
    country: str,
    *,
    archive_years: int = 30,
) -> ExtremeSignalBundle | None:
    """Fetch archive once, compute all extreme signals from it.

    Returns an ExtremeSignalBundle with whichever signals fire (or all None).
    Returns None on API failure. archive_years controls how far back to pull
    historical data; 30 is Open-Meteo's typical reliable window.

    Honest framing: these are "hottest in {archive_years} years of records"
    records, NOT absolute all-time — Open-Meteo's archive doesn't go back
    further reliably. Generators should reflect this.
    """
    today = date.today()
    try:
        resp_today = requests.get(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp_today.raise_for_status()
        today_data = resp_today.json().get("daily", {})
        today_max = (today_data.get("temperature_2m_max") or [None])[0]
        today_min = (today_data.get("temperature_2m_min") or [None])[0]
        if today_max is None and today_min is None:
            return None

        try:
            start = today.replace(year=today.year - archive_years)
        except ValueError:
            start = today.replace(year=today.year - archive_years, day=28)
        end = today - timedelta(days=1)

        resp_hist = requests.get(
            f"{ARCHIVE_URL}/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "auto",
            },
            timeout=30,
        )
        resp_hist.raise_for_status()
        hist_data = resp_hist.json().get("daily", {})
        dates = hist_data.get("time", [])
        highs = hist_data.get("temperature_2m_max", [])
        lows = hist_data.get("temperature_2m_min", [])

        if not dates:
            return None

    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None

    bundle = ExtremeSignalBundle(
        city=city,
        country=country,
        today_max_c=today_max,
        today_min_c=today_min,
    )
    target_month = today.month
    target_day = today.day

    # Build historical statistics in one pass
    hist_max_overall = None
    hist_max_overall_year = None
    hist_min_overall = None
    hist_min_overall_year = None
    hist_max_this_month = None
    hist_max_this_month_year = None
    hist_min_this_month = None
    hist_min_this_month_year = None
    hist_max_calendar = None
    hist_max_calendar_year = None
    hist_min_calendar = None
    hist_min_calendar_year = None
    this_month_highs = []
    this_month_lows = []

    for d_str, hi, lo in zip(dates, highs, lows):
        try:
            d = date.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue

        if hi is not None:
            if hist_max_overall is None or hi > hist_max_overall:
                hist_max_overall = hi
                hist_max_overall_year = d.year
            if d.month == target_month:
                if hist_max_this_month is None or hi > hist_max_this_month:
                    hist_max_this_month = hi
                    hist_max_this_month_year = d.year
                this_month_highs.append(hi)
                if d.day == target_day:
                    if hist_max_calendar is None or hi > hist_max_calendar:
                        hist_max_calendar = hi
                        hist_max_calendar_year = d.year

        if lo is not None:
            if hist_min_overall is None or lo < hist_min_overall:
                hist_min_overall = lo
                hist_min_overall_year = d.year
            if d.month == target_month:
                if hist_min_this_month is None or lo < hist_min_this_month:
                    hist_min_this_month = lo
                    hist_min_this_month_year = d.year
                this_month_lows.append(lo)
                if d.day == target_day:
                    if hist_min_calendar is None or lo < hist_min_calendar:
                        hist_min_calendar = lo
                        hist_min_calendar_year = d.year

    # Expose archive extremes on the bundle so country-level aggregation
    # downstream can compare today's national peak vs the archive's.
    bundle.archive_max_c = hist_max_overall
    bundle.archive_max_year = hist_max_overall_year
    bundle.archive_min_c = hist_min_overall
    bundle.archive_min_year = hist_min_overall_year

    today_iso = today.isoformat()
    city_key = city.replace(" ", "_")

    # Calendar-date records (legacy compatibility)
    if today_max is not None and hist_max_calendar is not None and today_max > hist_max_calendar:
        bundle.calendar_date_high = RecordEvent(
            city=city, country=country,
            new_temp_c=today_max, old_record_c=hist_max_calendar,
            old_record_year=hist_max_calendar_year,
            event_id=f"record_{city_key}_{today_iso}",
            kind="high",
            lat=lat,
            lon=lon,
        )
    if today_min is not None and hist_min_calendar is not None and today_min < hist_min_calendar:
        bundle.calendar_date_low = RecordEvent(
            city=city, country=country,
            new_temp_c=today_min, old_record_c=hist_min_calendar,
            old_record_year=hist_min_calendar_year,
            event_id=f"record_low_{city_key}_{today_iso}",
            kind="low",
            lat=lat,
            lon=lon,
        )

    # All-time records within our archive window
    if today_max is not None and hist_max_overall is not None and today_max > hist_max_overall:
        bundle.all_time_high = AllTimeRecord(
            city=city, country=country, kind="high",
            new_temp_c=today_max, old_record_c=hist_max_overall,
            old_record_year=hist_max_overall_year,
            years_of_data=archive_years,
            event_id=f"alltime_high_{city_key}_{today_iso}",
            lat=lat,
            lon=lon,
        )
    if today_min is not None and hist_min_overall is not None and today_min < hist_min_overall:
        bundle.all_time_low = AllTimeRecord(
            city=city, country=country, kind="low",
            new_temp_c=today_min, old_record_c=hist_min_overall,
            old_record_year=hist_min_overall_year,
            years_of_data=archive_years,
            event_id=f"alltime_low_{city_key}_{today_iso}",
            lat=lat,
            lon=lon,
        )

    # Monthly records (hottest/coldest ever for this month-of-year)
    if today_max is not None and hist_max_this_month is not None and today_max > hist_max_this_month:
        bundle.monthly_high = MonthlyRecord(
            city=city, country=country, kind="high",
            month=target_month,
            new_temp_c=today_max, old_record_c=hist_max_this_month,
            old_record_year=hist_max_this_month_year,
            years_of_data=archive_years,
            event_id=f"monthly_high_{city_key}_{today.year}_{target_month:02d}",
            lat=lat,
            lon=lon,
        )
    if today_min is not None and hist_min_this_month is not None and today_min < hist_min_this_month:
        bundle.monthly_low = MonthlyRecord(
            city=city, country=country, kind="low",
            month=target_month,
            new_temp_c=today_min, old_record_c=hist_min_this_month,
            old_record_year=hist_min_this_month_year,
            years_of_data=archive_years,
            event_id=f"monthly_low_{city_key}_{today.year}_{target_month:02d}",
            lat=lat,
            lon=lon,
        )

    # Anomaly vs historical mean for this month
    if today_max is not None and this_month_highs:
        mean = sum(this_month_highs) / len(this_month_highs)
        anomaly = today_max - mean
        if anomaly >= ANOMALY_HOT_THRESHOLD_C:
            bundle.anomaly_hot = AnomalyEvent(
                city=city, country=country,
                today_temp_c=today_max,
                historical_mean_c=mean,
                anomaly_c=anomaly,
                years_of_data=archive_years,
                event_id=f"anomaly_hot_{city_key}_{today_iso}",
                lat=lat,
                lon=lon,
            )
    if today_min is not None and this_month_lows:
        mean = sum(this_month_lows) / len(this_month_lows)
        anomaly = today_min - mean
        if anomaly <= -ANOMALY_COLD_THRESHOLD_C:
            bundle.anomaly_cold = AnomalyEvent(
                city=city, country=country,
                today_temp_c=today_min,
                historical_mean_c=mean,
                anomaly_c=anomaly,
                years_of_data=archive_years,
                event_id=f"anomaly_cold_{city_key}_{today_iso}",
                lat=lat,
                lon=lon,
            )

    abs_ev = detect_absolute_extreme(lat, lon, today_max, today_min, city, country)
    if abs_ev is not None:
        bundle.absolute_extreme = abs_ev

    return bundle


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
        if any([
            bundle.calendar_date_high, bundle.calendar_date_low,
            bundle.all_time_high, bundle.all_time_low,
            bundle.monthly_high, bundle.monthly_low,
            bundle.anomaly_hot, bundle.anomaly_cold,
            bundle.absolute_extreme,
        ]):
            bundles.append(bundle)

    country_records = detect_country_records(all_readings, archive_years=archive_years)
    if metrics_out is not None:
        metrics_out.update({
            "cities_attempted": len(to_check),
            "city_readings": len(all_readings),
            "city_fetch_failures": failures,
            "signal_bundles": len(bundles),
            "country_records": len(country_records),
        })
    return bundles, country_records


def detect_country_records(
    readings: list[ExtremeSignalBundle],
    *,
    archive_years: int = 30,
    min_cities_per_country: int = 2,
    record_date: date | None = None,
) -> list[CountryRecord]:
    """Aggregate per-city readings into country-level records.

    For each country with at least ``min_cities_per_country`` sampled
    cities, compare today's peak temperature (across all that country's
    cities) against the highest historical reading we've seen (across the
    same set of cities). When today exceeds it, the country has hit a new
    archive-wide high.

    Same logic for lows with the sign flipped.
    """
    today = record_date or date.today()
    today_iso = today.isoformat()

    by_country: dict[str, list[ExtremeSignalBundle]] = {}
    for r in readings:
        if r.country:
            by_country.setdefault(r.country, []).append(r)

    records: list[CountryRecord] = []
    for country, group in by_country.items():
        if len(group) < min_cities_per_country:
            continue

        # Highs
        today_highs = [(r.today_max_c, r.city) for r in group if r.today_max_c is not None]
        hist_highs = [
            (r.archive_max_c, r.city, r.archive_max_year)
            for r in group
            if r.archive_max_c is not None and r.archive_max_year is not None
        ]
        if today_highs and hist_highs:
            peak_today, peak_today_city = max(today_highs, key=lambda x: x[0])
            peak_hist_temp, peak_hist_city, peak_hist_year = max(hist_highs, key=lambda x: x[0])
            if peak_today > peak_hist_temp:
                country_key = country.replace(" ", "_")
                records.append(CountryRecord(
                    country=country,
                    kind="high",
                    new_temp_c=peak_today,
                    peak_city=peak_today_city,
                    old_record_c=peak_hist_temp,
                    old_record_year=peak_hist_year,
                    old_record_city=peak_hist_city,
                    years_of_data=archive_years,
                    cities_sampled=len(group),
                    event_id=f"country_high_{country_key}_{today_iso}",
                    signal_date=record_date,
                ))

        # Lows
        today_lows = [(r.today_min_c, r.city) for r in group if r.today_min_c is not None]
        hist_lows = [
            (r.archive_min_c, r.city, r.archive_min_year)
            for r in group
            if r.archive_min_c is not None and r.archive_min_year is not None
        ]
        if today_lows and hist_lows:
            trough_today, trough_today_city = min(today_lows, key=lambda x: x[0])
            trough_hist_temp, trough_hist_city, trough_hist_year = min(hist_lows, key=lambda x: x[0])
            if trough_today < trough_hist_temp:
                country_key = country.replace(" ", "_")
                records.append(CountryRecord(
                    country=country,
                    kind="low",
                    new_temp_c=trough_today,
                    peak_city=trough_today_city,
                    old_record_c=trough_hist_temp,
                    old_record_year=trough_hist_year,
                    old_record_city=trough_hist_city,
                    years_of_data=archive_years,
                    cities_sampled=len(group),
                    event_id=f"country_low_{country_key}_{today_iso}",
                    signal_date=record_date,
                ))

    return records


def check_records_for_cities(cities: list[dict], max_checks: int | None = None) -> list[RecordEvent]:
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
    """Check whether today's forecast low would break the record low for this date."""
    today = date.today()
    try:
        resp_today = requests.get(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_min",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp_today.raise_for_status()
        today_low = resp_today.json()["daily"]["temperature_2m_min"][0]
        if today_low is None:
            return None

        try:
            start = today.replace(year=today.year - 30)
        except ValueError:
            start = today.replace(year=today.year - 30, day=28)
        end = today - timedelta(days=1)
        resp_hist = requests.get(
            f"{ARCHIVE_URL}/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_min",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "auto",
            },
            timeout=30,
        )
        resp_hist.raise_for_status()
        hist_data = resp_hist.json()
        dates = hist_data.get("daily", {}).get("time", [])
        temps = hist_data.get("daily", {}).get("temperature_2m_min", [])

        target_month = today.month
        target_day = today.day
        old_record_c = None
        old_record_year = None

        for d_str, t in zip(dates, temps):
            if t is None:
                continue
            d = date.fromisoformat(d_str)
            if d.month == target_month and d.day == target_day:
                if old_record_c is None or t < old_record_c:
                    old_record_c = t
                    old_record_year = d.year

        if old_record_c is not None and today_low < old_record_c:
            return RecordEvent(
                city=city,
                country=country,
                new_temp_c=today_low,
                old_record_c=old_record_c,
                old_record_year=old_record_year,
                event_id=f"record_low_{city.replace(' ', '_')}_{today.isoformat()}",
                kind="low",
                lat=lat,
                lon=lon,
            )

        return None

    except (requests.RequestException, KeyError, IndexError):
        return None


# Cities most likely to break cold records — polar + high-altitude + surprise-freeze cities.
PRIORITY_COLD_CITIES = {
    "Anchorage", "Fairbanks", "Yakutsk", "Ulaanbaatar", "Astana",
    "Moscow", "Helsinki", "Reykjavik", "Tromsø",
    "Denver", "Minneapolis", "Chicago", "Montreal", "Winnipeg",
    "La Paz", "Bogota", "Quito", "Lhasa", "Addis Ababa",
    "Dallas", "Atlanta", "Houston",  # surprise freezes are sensational
}


def prioritize_cities_cold(cities: list[dict]) -> list[dict]:
    """Put known cold-record cities first, shuffle the rest."""
    priority = [c for c in cities if c["city"] in PRIORITY_COLD_CITIES]
    rest = [c for c in cities if c["city"] not in PRIORITY_COLD_CITIES]
    random.shuffle(rest)
    return priority + rest


def check_record_lows_for_cities(cities: list[dict], max_checks: int | None = None) -> list[RecordEvent]:
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
