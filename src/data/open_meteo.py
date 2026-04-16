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
