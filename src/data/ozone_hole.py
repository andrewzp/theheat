"""NASA Ozone Watch Antarctic ozone hole seasonal peak data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError, assert_response_schema

OZONE_AREA_URL_TEMPLATE = (
    "https://ozonewatch.gsfc.nasa.gov/meteorology/figures/ozone/"
    "to3areas_{year}_toms+omi+omps.txt"
)
OZONE_ANNUAL_PEAKS_URL = "https://ozonewatch.gsfc.nasa.gov/statistics/ytd_data.txt"
SOURCE_NAME = "NASA Ozone Watch"


@dataclass(frozen=True)
class OzoneHoleReading:
    date: str
    area_million_km2: float
    climatology_mean: float | None
    climatology_max: float | None
    event_id: str
    source_name: str = SOURCE_NAME


@dataclass(frozen=True)
class OzoneHoleAnnualPeak:
    year: int
    peak_date: str
    area_million_km2: float
    min_ozone_date: str
    min_ozone_du: float
    source_name: str = SOURCE_NAME


@dataclass(frozen=True)
class OzoneHoleSeasonalEvent:
    year: int
    peak_date: str
    area_million_km2: float
    previous_year: int | None
    previous_area_million_km2: float | None
    record_year: int | None
    record_area_million_km2: float | None
    trailing_10yr_mean_area_million_km2: float | None
    larger_than_previous_year: bool
    event_id: str
    source_name: str = SOURCE_NAME


def fetch_ozone_hole_data(
    *,
    year: int | None = None,
    strict: bool = False,
    max_age_days: int = 30,
) -> list[OzoneHoleReading]:
    target_year = year or date.today().year
    url = OZONE_AREA_URL_TEMPLATE.format(year=target_year)
    try:
        text = _fetch_text(url, "ozone_hole")
        readings = _parse_daily_area_rows(text)
        if not readings:
            raise SourceFetchError("ozone_hole schema drift: no daily area rows parsed")
        assert_freshness(readings[-1].date, "ozone_hole", max_age_days=max_age_days)
        return readings
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"ozone_hole fetch failed: {exc}") from exc
        return []


def fetch_ozone_hole_annual_peaks(
    *,
    strict: bool = False,
) -> list[OzoneHoleAnnualPeak]:
    try:
        text = _fetch_text(OZONE_ANNUAL_PEAKS_URL, "ozone_hole annual peaks")
        peaks = _parse_annual_peak_rows(text)
        if not peaks:
            raise SourceFetchError("ozone_hole schema drift: no annual peak rows parsed")
        return peaks
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"ozone_hole annual peak fetch failed: {exc}") from exc
        return []


def detect_seasonal_peak(
    readings: list[OzoneHoleReading],
    annual_peaks: list[OzoneHoleAnnualPeak] | None = None,
    *,
    last_peaks: dict[str, dict] | None = None,
    today: date | None = None,
    confirmation_days: int = 7,
) -> OzoneHoleSeasonalEvent | None:
    ordered = sorted(readings, key=lambda reading: reading.date)
    if not ordered:
        return None

    latest_date = date.fromisoformat(ordered[-1].date)
    current_year = latest_date.year
    seasonal_readings = [
        reading for reading in ordered
        if date.fromisoformat(reading.date).month in {8, 9, 10, 11}
        and reading.area_million_km2 > 0
    ]
    if not seasonal_readings:
        return None

    peaks_by_year = {peak.year: peak for peak in annual_peaks or []}
    current_peak = peaks_by_year.get(current_year)
    if current_peak is None:
        max_reading = max(seasonal_readings, key=lambda reading: reading.area_million_km2)
        current_peak = OzoneHoleAnnualPeak(
            year=current_year,
            peak_date=max_reading.date,
            area_million_km2=max_reading.area_million_km2,
            min_ozone_date=max_reading.date,
            min_ozone_du=0.0,
        )

    peak_date = date.fromisoformat(current_peak.peak_date)
    effective_today = today or latest_date
    if effective_today < peak_date + timedelta(days=confirmation_days):
        return None
    if effective_today.month < 11 and latest_date.month < 11:
        return None

    prior_payload = (last_peaks or {}).get(str(current_year))
    if isinstance(prior_payload, dict):
        prior_area = _float_or_none(prior_payload.get("area_million_km2"))
        prior_date = str(prior_payload.get("peak_date") or "")
        if prior_date == current_peak.peak_date and prior_area is not None and prior_area >= current_peak.area_million_km2:
            return None

    prior_peaks = sorted(
        [peak for peak in peaks_by_year.values() if peak.year < current_year],
        key=lambda peak: peak.year,
    )
    previous_peak = prior_peaks[-1] if prior_peaks else None
    record_peak = max(prior_peaks, key=lambda peak: peak.area_million_km2) if prior_peaks else None
    trailing = prior_peaks[-10:]
    trailing_mean = (
        round(sum(peak.area_million_km2 for peak in trailing) / len(trailing), 1)
        if trailing else None
    )

    return OzoneHoleSeasonalEvent(
        year=current_year,
        peak_date=current_peak.peak_date,
        area_million_km2=current_peak.area_million_km2,
        previous_year=previous_peak.year if previous_peak else None,
        previous_area_million_km2=previous_peak.area_million_km2 if previous_peak else None,
        record_year=record_peak.year if record_peak else None,
        record_area_million_km2=record_peak.area_million_km2 if record_peak else None,
        trailing_10yr_mean_area_million_km2=trailing_mean,
        larger_than_previous_year=(
            bool(previous_peak)
            and current_peak.area_million_km2 > previous_peak.area_million_km2
        ),
        event_id=f"ozone_hole_peak_{current_year}",
    )


def _fetch_text(url: str, source_name: str) -> str:
    response = fetch_with_retry(url, timeout=30, attempts=3)
    text = response.text
    assert_response_schema({"body": text}, ["body"], source_name)
    if not text.strip():
        raise SourceFetchError(f"{source_name} returned empty response")
    return text


def _parse_daily_area_rows(text: str) -> list[OzoneHoleReading]:
    readings: list[OzoneHoleReading] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            observed = date.fromisoformat(parts[0])
            area = float(parts[1])
            climatology_mean = float(parts[5])
            climatology_max = float(parts[8]) if len(parts) > 8 else None
        except (TypeError, ValueError):
            continue
        if area <= -999:
            continue
        readings.append(
            OzoneHoleReading(
                date=observed.isoformat(),
                area_million_km2=area,
                climatology_mean=climatology_mean,
                climatology_max=climatology_max,
                event_id=f"ozone_hole_area_{observed.isoformat()}",
            )
        )
    return readings


def _parse_annual_peak_rows(text: str) -> list[OzoneHoleAnnualPeak]:
    peaks: list[OzoneHoleAnnualPeak] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            year = int(parts[0])
            area_date = _mmdd_to_date(year, parts[1])
            area = float(parts[2])
            min_ozone_date = _mmdd_to_date(year, parts[3])
            min_ozone_du = float(parts[4])
        except (TypeError, ValueError):
            continue
        if area < 0:
            continue
        peaks.append(
            OzoneHoleAnnualPeak(
                year=year,
                peak_date=area_date.isoformat(),
                area_million_km2=area,
                min_ozone_date=min_ozone_date.isoformat(),
                min_ozone_du=min_ozone_du,
            )
        )
    return sorted(peaks, key=lambda peak: peak.year)


def _mmdd_to_date(year: int, value: str) -> date:
    if len(value) != 4:
        raise ValueError(f"invalid MMDD value: {value}")
    return date(year, int(value[:2]), int(value[2:]))


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
