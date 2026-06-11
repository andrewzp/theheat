from __future__ import annotations

"""Mauna Loa CO2 data from NOAA GML."""

from dataclasses import dataclass
from datetime import date

import requests

from src.data._http import fetch_with_cache_revalidation
from src.data.source_status import SourceFetchError

# NOAA GML provides daily CO2 readings as a public CSV
CO2_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_daily_mlo.csv"
_CO2_REVALIDATION_CACHE: dict[str, tuple[str, str]] = {}


@dataclass
class CO2Reading:
    date: str
    ppm: float
    event_id: str


@dataclass
class CO2Milestone:
    ppm_crossed: int
    actual_ppm: float
    date: str
    event_id: str


def fetch_co2_data(*, strict: bool = False) -> list[CO2Reading]:
    """Fetch recent CO2 readings from NOAA GML."""
    try:
        resp = fetch_with_cache_revalidation(
            CO2_URL,
            cache=_CO2_REVALIDATION_CACHE,
            timeout=15,
            attempts=3,
            backoff_base=1.0,
        )

        readings = []
        for line in resp.text.splitlines():
            # Skip comments and header
            if line.startswith("#") or line.startswith('"') or not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                year = int(parts[0].strip())
                month = int(parts[1].strip())
                day = int(parts[2].strip())
                ppm = float(parts[4].strip())
                if ppm < 0:
                    continue
                d = date(year, month, day)
                readings.append(CO2Reading(
                    date=d.isoformat(),
                    ppm=ppm,
                    event_id=f"co2_{d.isoformat()}_{int(ppm)}",
                ))
            except (ValueError, IndexError):
                continue

        return readings

    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"CO2 fetch failed: {exc}") from exc
        return []


def detect_milestone(readings: list[CO2Reading]) -> CO2Milestone | None:
    """Detect if a new integer PPM was crossed for the first time."""
    if len(readings) < 2:
        return None

    # Sort by date, most recent first
    sorted_readings = sorted(readings, key=lambda r: r.date, reverse=True)
    latest = sorted_readings[0]
    latest_int = int(latest.ppm)

    # Check if any previous reading already crossed this integer
    for reading in sorted_readings[1:]:
        if int(reading.ppm) >= latest_int:
            return None

    return CO2Milestone(
        ppm_crossed=latest_int,
        actual_ppm=latest.ppm,
        date=latest.date,
        event_id=f"co2_milestone_{latest_int}ppm",
    )
