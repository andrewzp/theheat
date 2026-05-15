"""Monthly NOAA climate-mode indices: NAO, AO, and PDO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError, assert_response_schema

NAO_URL = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.nao.monthly.b5001.current.ascii"
AO_URL = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_ao_index/monthly.ao.index.b50.current.ascii"
PDO_URL = "https://psl.noaa.gov/pdo/data/pdo.timeseries.ersstv5.data"

INDEX_NAMES = {
    "NAO": "North Atlantic Oscillation",
    "AO": "Arctic Oscillation",
    "PDO": "Pacific Decadal Oscillation",
}


@dataclass(frozen=True)
class OscillationReading:
    index_name: str
    full_name: str
    year: int
    month: int
    value: float
    phase: str
    event_id: str

    @property
    def date(self) -> str:
        return date(self.year, self.month, 1).isoformat()


@dataclass(frozen=True)
class OscillationTransition:
    index_name: str
    full_name: str
    year: int
    month: int
    value: float
    from_phase: str
    to_phase: str
    previous_duration_months: int
    event_id: str


@dataclass(frozen=True)
class OscillationExtremeEvent:
    index_name: str
    full_name: str
    year: int
    month: int
    value: float
    mean: float
    stdev: float
    sigma_excursion: float
    comparison_year: int | None
    comparison_month: int | None
    event_id: str


@dataclass(frozen=True)
class OscillationAlignmentEvent:
    year: int
    month: int
    nao_value: float
    ao_value: float
    nao_sigma_excursion: float
    ao_sigma_excursion: float
    event_id: str


def fetch_nao(*, strict: bool = False, max_age_days: int = 120) -> list[OscillationReading]:
    return _fetch_three_column_index(
        index_name="NAO",
        url=NAO_URL,
        strict=strict,
        max_age_days=max_age_days,
    )


def fetch_ao(*, strict: bool = False, max_age_days: int = 120) -> list[OscillationReading]:
    return _fetch_three_column_index(
        index_name="AO",
        url=AO_URL,
        strict=strict,
        max_age_days=max_age_days,
    )


def fetch_pdo(*, strict: bool = False, max_age_days: int = 120) -> list[OscillationReading]:
    try:
        text = _fetch_text(PDO_URL, "pdo")
        readings = _parse_pdo_rows(text)
        _assert_index_readings(readings, "pdo", max_age_days)
        return readings
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"PDO fetch failed: {exc}") from exc
        return []


def detect_phase_transition(
    readings: list[OscillationReading],
    *,
    min_prior_duration_months: int = 3,
) -> OscillationTransition | None:
    ordered = _sort_readings(readings)
    if len(ordered) < min_prior_duration_months + 1:
        return None

    current = ordered[-1]
    if current.phase == "Neutral":
        return None

    previous_phase: str | None = None
    previous_duration = 0
    for reading in reversed(ordered[:-1]):
        if reading.phase == "Neutral":
            if previous_phase is None:
                continue
            break
        if previous_phase is None:
            previous_phase = reading.phase
        if reading.phase == previous_phase:
            previous_duration += 1
            continue
        break

    if previous_phase is None or previous_phase == current.phase:
        return None
    if previous_duration < min_prior_duration_months:
        return None

    return OscillationTransition(
        index_name=current.index_name,
        full_name=current.full_name,
        year=current.year,
        month=current.month,
        value=current.value,
        from_phase=previous_phase,
        to_phase=current.phase,
        previous_duration_months=previous_duration,
        event_id=(
            f"oscillation_transition_{current.index_name.lower()}_"
            f"{current.phase.lower()}_{current.year}_{current.month:02d}"
        ),
    )


def detect_extreme_excursion(
    readings: list[OscillationReading],
    *,
    sigma_threshold: float = 2.0,
) -> OscillationExtremeEvent | None:
    ordered = _sort_readings(readings)
    if len(ordered) < 24:
        return None

    current = ordered[-1]
    baseline = ordered[:-1]
    mean, stdev = _mean_stdev([reading.value for reading in baseline])
    if stdev <= 0:
        return None

    signed_sigma = (current.value - mean) / stdev
    if abs(signed_sigma) < sigma_threshold:
        return None

    comparison = _comparison_reading(current, baseline)
    return OscillationExtremeEvent(
        index_name=current.index_name,
        full_name=current.full_name,
        year=current.year,
        month=current.month,
        value=current.value,
        mean=round(mean, 3),
        stdev=round(stdev, 3),
        sigma_excursion=round(abs(signed_sigma), 2),
        comparison_year=comparison.year if comparison else None,
        comparison_month=comparison.month if comparison else None,
        event_id=(
            f"oscillation_extreme_{current.index_name.lower()}_"
            f"{current.year}_{current.month:02d}"
        ),
    )


def detect_nao_ao_alignment(
    nao_readings: list[OscillationReading],
    ao_readings: list[OscillationReading],
    *,
    sigma_threshold: float = 2.0,
) -> OscillationAlignmentEvent | None:
    nao_ordered = _sort_readings(nao_readings)
    ao_ordered = _sort_readings(ao_readings)
    if len(nao_ordered) < 24 or len(ao_ordered) < 24:
        return None

    nao_latest = nao_ordered[-1]
    ao_latest = ao_ordered[-1]
    if (nao_latest.year, nao_latest.month) != (ao_latest.year, ao_latest.month):
        return None

    nao_sigma = _signed_sigma(nao_latest.value, [reading.value for reading in nao_ordered[:-1]])
    ao_sigma = _signed_sigma(ao_latest.value, [reading.value for reading in ao_ordered[:-1]])
    if nao_sigma is None or ao_sigma is None:
        return None
    if nao_sigma > -sigma_threshold or ao_sigma > -sigma_threshold:
        return None

    return OscillationAlignmentEvent(
        year=nao_latest.year,
        month=nao_latest.month,
        nao_value=nao_latest.value,
        ao_value=ao_latest.value,
        nao_sigma_excursion=round(abs(nao_sigma), 2),
        ao_sigma_excursion=round(abs(ao_sigma), 2),
        event_id=f"oscillation_alignment_nao_ao_{nao_latest.year}_{nao_latest.month:02d}",
    )


def _fetch_three_column_index(
    *,
    index_name: str,
    url: str,
    strict: bool,
    max_age_days: int,
) -> list[OscillationReading]:
    try:
        text = _fetch_text(url, index_name.lower())
        readings = _parse_three_column_rows(text, index_name)
        _assert_index_readings(readings, index_name.lower(), max_age_days)
        return readings
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"{index_name} fetch failed: {exc}") from exc
        return []


def _fetch_text(url: str, source_name: str) -> str:
    response = fetch_with_retry(url, timeout=30, attempts=3)
    text = response.text
    assert_response_schema({"body": text}, ["body"], source_name)
    if not text.strip():
        raise SourceFetchError(f"{source_name} returned empty response")
    return text


def _assert_index_readings(
    readings: list[OscillationReading],
    source_name: str,
    max_age_days: int,
) -> None:
    if not readings:
        raise SourceFetchError(f"{source_name} schema drift: no data rows parsed")
    assert_freshness(readings[-1].date, source_name, max_age_days=max_age_days)


def _parse_three_column_rows(text: str, index_name: str) -> list[OscillationReading]:
    readings: list[OscillationReading] = []
    full_name = INDEX_NAMES[index_name]
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            year = int(parts[0])
            month = int(parts[1])
            value = float(parts[2])
        except (TypeError, ValueError):
            continue
        if not 1 <= month <= 12 or value <= -90:
            continue
        readings.append(_reading(index_name, full_name, year, month, value))
    return _sort_readings(readings)


def _parse_pdo_rows(text: str) -> list[OscillationReading]:
    readings: list[OscillationReading] = []
    full_name = INDEX_NAMES["PDO"]
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            year = int(parts[0])
        except (TypeError, ValueError):
            continue
        for month, raw_value in enumerate(parts[1:13], start=1):
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if value <= -9:
                continue
            readings.append(_reading("PDO", full_name, year, month, value))
    return _sort_readings(readings)


def _reading(
    index_name: str,
    full_name: str,
    year: int,
    month: int,
    value: float,
) -> OscillationReading:
    phase = "Positive" if value > 0 else "Negative" if value < 0 else "Neutral"
    return OscillationReading(
        index_name=index_name,
        full_name=full_name,
        year=year,
        month=month,
        value=value,
        phase=phase,
        event_id=f"climate_index_{index_name.lower()}_{year}_{month:02d}",
    )


def _sort_readings(readings: list[OscillationReading]) -> list[OscillationReading]:
    return sorted(readings, key=lambda reading: (reading.year, reading.month))


def _mean_stdev(values: list[float]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, math.sqrt(variance)


def _signed_sigma(value: float, baseline_values: list[float]) -> float | None:
    if len(baseline_values) < 2:
        return None
    mean, stdev = _mean_stdev(baseline_values)
    if stdev <= 0:
        return None
    return (value - mean) / stdev


def _comparison_reading(
    current: OscillationReading,
    baseline: list[OscillationReading],
) -> OscillationReading | None:
    prior = [reading for reading in baseline if (reading.year, reading.month) < (current.year, current.month)]
    if current.value >= 0:
        matches = [reading for reading in prior if reading.value >= current.value]
    else:
        matches = [reading for reading in prior if reading.value <= current.value]
    if not matches:
        return None
    return max(matches, key=lambda reading: (reading.year, reading.month))
