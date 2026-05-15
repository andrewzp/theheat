from __future__ import annotations

"""NOAA GML atmospheric methane (CH4) monthly mean milestones."""

from dataclasses import dataclass
from datetime import date

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError, assert_response_schema

CH4_URL = "https://gml.noaa.gov/webdata/ccgg/trends/ch4/ch4_mm_gl.txt"
SOURCE_NAME = "NOAA GML"
MILESTONE_STEP_PPB = 10


@dataclass(frozen=True)
class MethaneReading:
    date: str
    ppb: float
    event_id: str


@dataclass(frozen=True)
class MethaneMilestone:
    ppb_crossed: int
    actual_ppb: float
    date: str
    event_id: str
    source_name: str = SOURCE_NAME


def fetch_ch4_milestones(
    *,
    strict: bool = False,
    max_age_days: int = 180,
) -> list[MethaneReading]:
    """Fetch NOAA GML global monthly CH4 means.

    Kept as ``fetch_ch4_milestones`` to match the Lane 08 brief, but the
    return shape mirrors ``co2.fetch_co2_data``: raw readings in, milestone
    detection as a separate pure function.
    """
    try:
        response = fetch_with_retry(CH4_URL, timeout=30, attempts=3)
        text = response.text
        assert_response_schema({"body": text}, ["body"], "ch4_milestone")
        readings = _parse_ch4_rows(text)
        if not readings:
            raise SourceFetchError("ch4_milestone schema drift: no data rows parsed")
        assert_freshness(readings[-1].date, "ch4_milestone", max_age_days=max_age_days)
        return readings
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"CH4 fetch failed: {exc}") from exc
        return []


def detect_milestone(
    readings: list[MethaneReading],
    *,
    last_milestone: int | None = None,
) -> MethaneMilestone | None:
    """Detect a newly crossed 10-ppb CH4 milestone."""
    if len(readings) < 2:
        return None

    sorted_readings = sorted(readings, key=lambda reading: reading.date, reverse=True)
    latest = sorted_readings[0]
    latest_milestone = _milestone_floor(latest.ppb)
    if latest_milestone <= 0:
        return None

    prior_max = max(_milestone_floor(reading.ppb) for reading in sorted_readings[1:])
    if latest_milestone <= prior_max:
        return None
    if last_milestone is not None and latest_milestone <= int(last_milestone):
        return None

    return MethaneMilestone(
        ppb_crossed=latest_milestone,
        actual_ppb=latest.ppb,
        date=latest.date,
        event_id=f"ch4_milestone_{latest_milestone}ppb",
    )


def _parse_ch4_rows(text: str) -> list[MethaneReading]:
    readings: list[MethaneReading] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 5:
            continue
        try:
            year = int(parts[0])
            month = int(parts[1])
            ppb = float(parts[3])
        except (TypeError, ValueError, IndexError):
            continue
        if ppb < 0:
            continue
        observed = date(year, month, 1)
        readings.append(
            MethaneReading(
                date=observed.isoformat(),
                ppb=ppb,
                event_id=f"ch4_{observed.isoformat()}_{int(ppb)}",
            )
        )
    return readings


def _milestone_floor(ppb: float) -> int:
    return int(ppb) // MILESTONE_STEP_PPB * MILESTONE_STEP_PPB
