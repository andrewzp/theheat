from __future__ import annotations

"""Mauna Loa CO2 data from NOAA GML."""

import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta

import requests

# NOAA GML provides daily CO2 readings as a public CSV
CO2_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_daily_mlo.csv"


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


@dataclass
class CO2WeeklyComparison:
    current_avg: float
    last_year_avg: float
    difference: float
    event_id: str


def fetch_co2_data() -> list[CO2Reading]:
    """Fetch recent CO2 readings from NOAA GML."""
    try:
        resp = requests.get(CO2_URL, timeout=15)
        resp.raise_for_status()

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

    except requests.RequestException:
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


# Minimum year-over-year PPM rise we'll tweet about. Below this we're in
# seasonal-noise territory — and a negative weekly diff framed as "the
# direction" is factually misleading against the 67-year monotonic rise.
CO2_WEEKLY_MIN_DIFF_PPM = 1.0


def compute_weekly_comparison(readings: list[CO2Reading]) -> CO2WeeklyComparison | None:
    """Compare this week's average CO2 to same week last year.

    Returns ``None`` when the year-over-year difference is below
    ``CO2_WEEKLY_MIN_DIFF_PPM``, including any negative delta — a single
    week reading lower than same-week-last-year is noise in a signal that
    has risen every year since continuous Mauna Loa measurement began in
    1958. Framing noise as a "dip" or "the direction" would be misleading.
    """
    if not readings:
        return None

    today = date.today()
    week_ago = today - timedelta(days=7)
    last_year_start = week_ago.replace(year=week_ago.year - 1)
    last_year_end = today.replace(year=today.year - 1)

    current_week = [
        r for r in readings
        if week_ago.isoformat() <= r.date <= today.isoformat()
    ]
    last_year_week = [
        r for r in readings
        if last_year_start.isoformat() <= r.date <= last_year_end.isoformat()
    ]

    if not current_week or not last_year_week:
        return None

    current_avg = sum(r.ppm for r in current_week) / len(current_week)
    last_year_avg = sum(r.ppm for r in last_year_week) / len(last_year_week)
    difference = current_avg - last_year_avg

    if difference < CO2_WEEKLY_MIN_DIFF_PPM:
        return None

    return CO2WeeklyComparison(
        current_avg=round(current_avg, 1),
        last_year_avg=round(last_year_avg, 1),
        difference=round(difference, 1),
        event_id=f"co2_weekly_{today.isoformat()}",
    )
