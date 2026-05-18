"""NASA GPM IMERG daily precipitation point checks.

Operational daily reads use the IMERG Late daily product so the bot can smoke
recent data. The Final product remains the archive reference, but it lags by
months and is not suitable for "today" checks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date, timedelta
import csv
import os
import re
from pathlib import Path
from typing import Any

import requests

from src.data.source_status import SourceFetchError, SourceSkipped

LATE_OPENDAP_BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDL.07"
FINAL_OPENDAP_BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07"

GRID_STEP_DEGREES = 0.1
LON_CELLS = 3600
LAT_CELLS = 1800
FILL_VALUE = -9999.0
DEFAULT_RECORD_MARGIN_MM = 20.0
DEFAULT_CITY_LIMIT = 75
PRECIP_HISTORY_DAYS = 10


@dataclass(frozen=True)
class CityPrecipReading:
    city: str
    country: str
    lat: float
    lon: float
    date: str
    mm_total: float
    source_product: str
    event_id: str


@dataclass(frozen=True)
class PrecipExtremeEvent:
    kind: str
    location: str
    country: str
    date: str
    mm_total: float
    period_days: int
    deviation_from_record_mm: float | None
    previous_record_mm: float | None
    previous_record_year: int | None
    lat: float
    lon: float
    city_count: int | None
    sample_cities: list[str]
    event_id: str


def load_cities(cities_path: str = "data/cities.csv") -> list[dict[str, str]]:
    with Path(cities_path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_daily_precip(
    cities: list[Mapping[str, Any]] | None = None,
    *,
    target_date: date | None = None,
    product: str = "late",
    max_cities: int | None = DEFAULT_CITY_LIMIT,
    strict: bool = False,
) -> list[CityPrecipReading]:
    """Fetch point daily precipitation for monitored cities.

    Returns city readings sorted in input order. Missing credentials skip the
    source in non-strict mode; strict mode raises so smoke tests can fail loud.
    """

    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        print("[gpm_imerg] EARTHDATA_TOKEN not configured — skipping")
        if strict:
            raise SourceSkipped("EARTHDATA_TOKEN is not configured")
        return []

    requested_date = target_date or date.today() - timedelta(days=1)
    rows = cities if cities is not None else load_cities()
    selected = list(rows if max_cities is None else rows[:max_cities])
    headers = {"Authorization": f"Bearer {token}"}
    readings: list[CityPrecipReading] = []
    failures = 0

    for city in selected:
        try:
            city_name = str(city["city"])
            country = str(city["country"])
            lat = float(city["lat"])
            lon = float(city["lon"])
            mm_total = _fetch_city_precip(
                lat=lat,
                lon=lon,
                target_date=requested_date,
                product=product,
                headers=headers,
            )
        except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
            failures += 1
            if strict and cities is not None and len(selected) == 1:
                raise SourceFetchError(f"GPM IMERG city fetch failed: {exc}") from exc
            continue

        if mm_total is None:
            continue

        city_key = _safe_key(city_name)
        country_key = _safe_key(country)
        date_key = requested_date.isoformat()
        readings.append(CityPrecipReading(
            city=city_name,
            country=country,
            lat=lat,
            lon=lon,
            date=date_key,
            mm_total=mm_total,
            source_product=product,
            event_id=f"gpm_imerg_{country_key}_{city_key}_{date_key}",
        ))

    if strict and not readings:
        raise SourceFetchError(
            f"GPM IMERG fetch returned no city readings for {requested_date.isoformat()} "
            f"({failures} failed)"
        )
    return readings


def detect_precip_records(
    readings: list[CityPrecipReading],
    state: Mapping[str, Any] | None = None,
    *,
    record_margin_mm: float = DEFAULT_RECORD_MARGIN_MM,
    min_country_records: int = 10,
) -> list[PrecipExtremeEvent]:
    tracking = state or {}
    events: list[PrecipExtremeEvent] = []
    daily_records = tracking.get("precip_daily_records", {})
    if not isinstance(daily_records, Mapping):
        daily_records = {}

    for reading in readings:
        key = _daily_record_key(reading)
        previous = daily_records.get(key)
        previous_mm = _record_mm(previous)
        if previous_mm is not None and reading.mm_total >= previous_mm + record_margin_mm:
            events.append(PrecipExtremeEvent(
                kind="daily_record",
                location=reading.city,
                country=reading.country,
                date=reading.date,
                mm_total=reading.mm_total,
                period_days=1,
                deviation_from_record_mm=reading.mm_total - previous_mm,
                previous_record_mm=previous_mm,
                previous_record_year=_record_year(previous),
                lat=reading.lat,
                lon=reading.lon,
                city_count=None,
                sample_cities=[],
                event_id=f"gpm_precip_record_{_safe_key(reading.country)}_"
                f"{_safe_key(reading.city)}_{reading.date}",
            ))

    events.extend(_detect_rolling_accumulations(readings, tracking))
    events.extend(_detect_country_events(events, min_country_records=min_country_records))
    return events


def update_precip_tracking(
    state: MutableMapping[str, Any],
    readings: Iterable[CityPrecipReading],
    *,
    max_history_days: int = PRECIP_HISTORY_DAYS,
) -> None:
    daily = state.setdefault("precip_daily_records", {})
    recent = state.setdefault("precip_recent_by_city", {})
    for reading in readings:
        daily_key = _daily_record_key(reading)
        current = daily.get(daily_key) if isinstance(daily, MutableMapping) else None
        current_mm = _record_mm(current)
        if current_mm is None or reading.mm_total > current_mm:
            daily[daily_key] = {
                "mm": reading.mm_total,
                "year": int(reading.date[:4]),
                "date": reading.date,
            }

        city_key = _city_key(reading)
        rows = recent.setdefault(city_key, [])
        if not isinstance(rows, list):
            rows = []
            recent[city_key] = rows
        rows = [row for row in rows if isinstance(row, Mapping) and row.get("date") != reading.date]
        rows.append({"date": reading.date, "mm": reading.mm_total})
        rows.sort(key=lambda row: str(row.get("date") or ""))
        recent[city_key] = rows[-max_history_days:]


def _fetch_city_precip(
    *,
    lat: float,
    lon: float,
    target_date: date,
    product: str,
    headers: Mapping[str, str],
) -> float | None:
    variable = "precipitation"
    url = _ascii_subset_url(
        lat=lat,
        lon=lon,
        target_date=target_date,
        product=product,
        variable=variable,
    )
    resp = requests.get(url, headers=dict(headers), timeout=30)
    resp.raise_for_status()
    value = _parse_ascii_value(resp.text, variable)
    if value is None or value <= FILL_VALUE:
        return None
    return max(value, 0.0)


def _ascii_subset_url(
    *,
    lat: float,
    lon: float,
    target_date: date,
    product: str,
    variable: str,
) -> str:
    product_key = product.lower()
    if product_key == "final":
        base = FINAL_OPENDAP_BASE
        filename = (
            f"3B-DAY.MS.MRG.3IMERG.{target_date:%Y%m%d}-S000000-E235959.V07B.nc4"
        )
    elif product_key == "late":
        base = LATE_OPENDAP_BASE
        filename = (
            f"3B-DAY-L.MS.MRG.3IMERG.{target_date:%Y%m%d}-S000000-E235959.V07C.nc4"
        )
    else:
        raise ValueError(f"unknown GPM IMERG product: {product}")

    lon_index = _lon_index(lon)
    lat_index = _lat_index(lat)
    subset = (
        f"{variable}[0:1:0][{lon_index}:1:{lon_index}][{lat_index}:1:{lat_index}],"
        f"lat[{lat_index}:1:{lat_index}],lon[{lon_index}:1:{lon_index}]"
    )
    return f"{base}/{target_date:%Y}/{target_date:%m}/{filename}.ascii?{subset}"


def _parse_ascii_value(text: str, variable: str = "precipitation") -> float | None:
    for line in text.splitlines():
        stripped = line.strip()
        if variable not in stripped or "," not in stripped:
            continue
        raw = stripped.rsplit(",", 1)[1].strip().rstrip(";")
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def _lon_index(lon: float) -> int:
    normalized = ((lon + 180.0) % 360.0) - 180.0
    index = int(round((normalized + 179.95) / GRID_STEP_DEGREES))
    return min(max(index, 0), LON_CELLS - 1)


def _lat_index(lat: float) -> int:
    index = int(round((lat + 89.95) / GRID_STEP_DEGREES))
    return min(max(index, 0), LAT_CELLS - 1)


def _detect_rolling_accumulations(
    readings: list[CityPrecipReading],
    state: Mapping[str, Any],
) -> list[PrecipExtremeEvent]:
    recent_by_city = state.get("precip_recent_by_city", {})
    if not isinstance(recent_by_city, Mapping):
        recent_by_city = {}

    events: list[PrecipExtremeEvent] = []
    thresholds = {3: 150.0, 7: 300.0}
    for reading in readings:
        prior_rows = recent_by_city.get(_city_key(reading), [])
        rows = [
            {"date": str(row.get("date")), "mm": float(row.get("mm", 0.0))}
            for row in prior_rows
            if isinstance(row, Mapping) and row.get("date")
        ]
        rows = [row for row in rows if row["date"] != reading.date]
        rows.append({"date": reading.date, "mm": reading.mm_total})
        rows.sort(key=lambda row: row["date"])
        for period_days, threshold_mm in thresholds.items():
            window = rows[-period_days:]
            if len(window) != period_days or not _dates_are_consecutive([row["date"] for row in window]):
                continue
            total = sum(float(row["mm"]) for row in window)
            if total < threshold_mm:
                continue
            events.append(PrecipExtremeEvent(
                kind="multi_day_accumulation",
                location=reading.city,
                country=reading.country,
                date=reading.date,
                mm_total=total,
                period_days=period_days,
                deviation_from_record_mm=total - threshold_mm,
                previous_record_mm=threshold_mm,
                previous_record_year=None,
                lat=reading.lat,
                lon=reading.lon,
                city_count=None,
                sample_cities=[],
                event_id=f"gpm_precip_{period_days}d_{_safe_key(reading.country)}_"
                f"{_safe_key(reading.city)}_{reading.date}",
            ))
    return events


def _detect_country_events(
    events: list[PrecipExtremeEvent],
    *,
    min_country_records: int,
) -> list[PrecipExtremeEvent]:
    by_country: dict[str, list[PrecipExtremeEvent]] = {}
    for event in events:
        if event.kind == "daily_record" and event.country:
            by_country.setdefault(event.country, []).append(event)

    country_events: list[PrecipExtremeEvent] = []
    for country, group in by_country.items():
        if len(group) < min_country_records:
            continue
        leader = max(group, key=lambda event: event.mm_total)
        sample_cities = [event.location for event in group[:12]]
        country_events.append(PrecipExtremeEvent(
            kind="country_precip_event",
            location=country,
            country=country,
            date=leader.date,
            mm_total=max(event.mm_total for event in group),
            period_days=1,
            deviation_from_record_mm=None,
            previous_record_mm=None,
            previous_record_year=None,
            lat=leader.lat,
            lon=leader.lon,
            city_count=len(group),
            sample_cities=sample_cities,
            event_id=f"gpm_precip_country_{_safe_key(country)}_{leader.date}",
        ))
    return country_events


def _dates_are_consecutive(raw_dates: list[str]) -> bool:
    try:
        parsed = [date.fromisoformat(raw) for raw in raw_dates]
    except ValueError:
        return False
    return all((b - a).days == 1 for a, b in zip(parsed, parsed[1:]))


def _record_mm(record: object) -> float | None:
    if not isinstance(record, Mapping):
        return None
    raw = record.get("mm")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _record_year(record: object) -> int | None:
    if not isinstance(record, Mapping):
        return None
    raw = record.get("year")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _city_key(reading: CityPrecipReading) -> str:
    return f"{_safe_key(reading.country)}:{_safe_key(reading.city)}"


def _daily_record_key(reading: CityPrecipReading) -> str:
    month_day = reading.date[5:]
    return f"{_city_key(reading)}:{month_day}"


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return key or "unknown"
