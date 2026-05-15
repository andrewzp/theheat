"""NSIDC Snow Today SWE point observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date
import re
from typing import Any

import requests

from src.data.source_status import SourceFetchError, assert_response_schema

SNOW_TODAY_SWE_URL = "https://nsidc.org/api/snow-today/snow-water-equivalent/points/swe.json"
INCH_TO_MM = 25.4
DAILY_GAIN_MARGIN_MM = 25.4
BLIZZARD_DAY_MIN_MM = 12.7
BLIZZARD_TOTAL_MIN_MM = 50.8
SEASONAL_RECORD_MARGIN_MM = 25.4
SNOW_HISTORY_DAYS = 10


@dataclass(frozen=True)
class SnowReading:
    station: str
    lat: float
    lon: float
    elevation_m: float | None
    date: str
    swe_mm: float | None
    swe_delta_mm: float | None
    swe_normalized_pct: float | None
    event_id: str


@dataclass(frozen=True)
class SnowExtremeEvent:
    kind: str
    station: str
    date: str
    swe_mm: float | None
    mm_swe: float
    deviation_from_record_mm: float | None
    previous_record_mm: float | None
    previous_record_year: int | None
    consecutive_days: int | None
    years_of_archive: int | None
    lat: float
    lon: float
    elevation_m: float | None
    event_id: str


def fetch_snow_today(*, strict: bool = False) -> list[SnowReading]:
    try:
        resp = requests.get(SNOW_TODAY_SWE_URL, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        assert_response_schema(payload, ("metadata", "data"), "NSIDC Snow Today")
        metadata = payload["metadata"]
        rows = payload["data"]
        if not isinstance(metadata, Mapping) or not isinstance(rows, list):
            raise SourceFetchError("NSIDC Snow Today schema drift: bad metadata/data shape")
        reading_date = str(metadata.get("last_date_with_data") or date.today().isoformat())

        readings: list[SnowReading] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            try:
                station = str(row["name"])
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            readings.append(SnowReading(
                station=station,
                lat=lat,
                lon=lon,
                elevation_m=_optional_float(row.get("elevation_meters")),
                date=reading_date,
                swe_mm=_inches_to_mm(row.get("swe_inches")),
                swe_delta_mm=_inches_to_mm(row.get("swe_delta_inches")),
                swe_normalized_pct=_optional_float(row.get("swe_normalized_pct")),
                event_id=f"nsidc_snow_{_safe_key(station)}_{reading_date}",
            ))
        if strict and not readings:
            raise SourceFetchError("NSIDC Snow Today returned no valid point readings")
        return readings
    except (requests.RequestException, ValueError, SourceFetchError) as exc:
        if strict:
            raise SourceFetchError(f"NSIDC Snow Today fetch failed: {exc}") from exc
        return []


def detect_snow_extremes(
    readings: list[SnowReading],
    state: Mapping[str, Any] | None = None,
    *,
    daily_margin_mm: float = DAILY_GAIN_MARGIN_MM,
    seasonal_margin_mm: float = SEASONAL_RECORD_MARGIN_MM,
) -> list[SnowExtremeEvent]:
    tracking = state or {}
    daily_records = tracking.get("snow_daily_swe_gain_records", {})
    seasonal_records = tracking.get("seasonal_snow_records", {})
    if not isinstance(daily_records, Mapping):
        daily_records = {}
    if not isinstance(seasonal_records, Mapping):
        seasonal_records = {}

    events: list[SnowExtremeEvent] = []
    for reading in readings:
        delta = reading.swe_delta_mm
        if delta is None:
            continue
        prior = daily_records.get(_daily_gain_key(reading))
        previous_mm = _record_mm(prior)
        if previous_mm is not None and delta >= previous_mm + daily_margin_mm:
            events.append(_snow_event(
                kind="daily_swe_gain_record",
                reading=reading,
                mm_swe=delta,
                deviation_from_record_mm=delta - previous_mm,
                previous_record_mm=previous_mm,
                previous_record_year=_record_year(prior),
                consecutive_days=None,
                years_of_archive=None,
            ))

    events.extend(_detect_multi_day_snow(readings, tracking))

    for reading in readings:
        swe = reading.swe_mm
        if swe is None:
            continue
        prior = seasonal_records.get(_station_key(reading))
        previous_mm = _record_mm(prior)
        if previous_mm is not None and swe >= previous_mm + seasonal_margin_mm:
            events.append(_snow_event(
                kind="seasonal_snow_record",
                reading=reading,
                mm_swe=swe,
                deviation_from_record_mm=swe - previous_mm,
                previous_record_mm=previous_mm,
                previous_record_year=_record_year(prior),
                consecutive_days=None,
                years_of_archive=_record_years(prior),
            ))

    return events


def update_snow_tracking(
    state: MutableMapping[str, Any],
    readings: Iterable[SnowReading],
    *,
    max_history_days: int = SNOW_HISTORY_DAYS,
) -> None:
    daily = state.setdefault("snow_daily_swe_gain_records", {})
    recent = state.setdefault("snow_recent_by_station", {})
    seasonal = state.setdefault("seasonal_snow_records", {})

    for reading in readings:
        delta = reading.swe_delta_mm
        if delta is not None:
            daily_key = _daily_gain_key(reading)
            current = daily.get(daily_key) if isinstance(daily, MutableMapping) else None
            current_mm = _record_mm(current)
            if current_mm is None or delta > current_mm:
                daily[daily_key] = {
                    "mm": delta,
                    "year": int(reading.date[:4]),
                    "date": reading.date,
                }

            station_key = _station_key(reading)
            rows = recent.setdefault(station_key, [])
            if not isinstance(rows, list):
                rows = []
                recent[station_key] = rows
            rows = [row for row in rows if isinstance(row, Mapping) and row.get("date") != reading.date]
            rows.append({"date": reading.date, "mm": delta})
            rows.sort(key=lambda row: str(row.get("date") or ""))
            recent[station_key] = rows[-max_history_days:]

        swe = reading.swe_mm
        if swe is not None:
            station_key = _station_key(reading)
            current = seasonal.get(station_key) if isinstance(seasonal, MutableMapping) else None
            current_mm = _record_mm(current)
            if current_mm is None or swe > current_mm:
                seasonal[station_key] = {
                    "mm": swe,
                    "year": int(reading.date[:4]),
                    "date": reading.date,
                    "years_of_archive": _record_years(current) or 1,
                }


def _detect_multi_day_snow(
    readings: list[SnowReading],
    state: Mapping[str, Any],
) -> list[SnowExtremeEvent]:
    recent_by_station = state.get("snow_recent_by_station", {})
    if not isinstance(recent_by_station, Mapping):
        recent_by_station = {}

    events: list[SnowExtremeEvent] = []
    for reading in readings:
        if reading.swe_delta_mm is None:
            continue
        prior_rows = recent_by_station.get(_station_key(reading), [])
        rows = [
            {"date": str(row.get("date")), "mm": float(row.get("mm", 0.0))}
            for row in prior_rows
            if isinstance(row, Mapping) and row.get("date")
        ]
        rows = [row for row in rows if row["date"] != reading.date]
        rows.append({"date": reading.date, "mm": reading.swe_delta_mm})
        rows.sort(key=lambda row: row["date"])
        window = rows[-3:]
        if len(window) != 3 or not _dates_are_consecutive([row["date"] for row in window]):
            continue
        total = sum(float(row["mm"]) for row in window)
        if total < BLIZZARD_TOTAL_MIN_MM:
            continue
        if any(float(row["mm"]) < BLIZZARD_DAY_MIN_MM for row in window):
            continue
        events.append(_snow_event(
            kind="multi_day_blizzard",
            reading=reading,
            mm_swe=total,
            deviation_from_record_mm=total - BLIZZARD_TOTAL_MIN_MM,
            previous_record_mm=BLIZZARD_TOTAL_MIN_MM,
            previous_record_year=None,
            consecutive_days=3,
            years_of_archive=None,
        ))
    return events


def _snow_event(
    *,
    kind: str,
    reading: SnowReading,
    mm_swe: float,
    deviation_from_record_mm: float | None,
    previous_record_mm: float | None,
    previous_record_year: int | None,
    consecutive_days: int | None,
    years_of_archive: int | None,
) -> SnowExtremeEvent:
    return SnowExtremeEvent(
        kind=kind,
        station=reading.station,
        date=reading.date,
        swe_mm=reading.swe_mm,
        mm_swe=mm_swe,
        deviation_from_record_mm=deviation_from_record_mm,
        previous_record_mm=previous_record_mm,
        previous_record_year=previous_record_year,
        consecutive_days=consecutive_days,
        years_of_archive=years_of_archive,
        lat=reading.lat,
        lon=reading.lon,
        elevation_m=reading.elevation_m,
        event_id=f"nsidc_snow_{kind}_{_safe_key(reading.station)}_{reading.date}",
    )


def _inches_to_mm(value: object) -> float | None:
    raw = _optional_float(value)
    return None if raw is None else raw * INCH_TO_MM


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _record_years(record: object) -> int | None:
    if not isinstance(record, Mapping):
        return None
    raw = record.get("years_of_archive")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _dates_are_consecutive(raw_dates: list[str]) -> bool:
    try:
        parsed = [date.fromisoformat(raw) for raw in raw_dates]
    except ValueError:
        return False
    return all((b - a).days == 1 for a, b in zip(parsed, parsed[1:]))


def _daily_gain_key(reading: SnowReading) -> str:
    return f"{_station_key(reading)}:{reading.date[5:]}"


def _station_key(reading: SnowReading) -> str:
    return _safe_key(reading.station)


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return key or "unknown"
