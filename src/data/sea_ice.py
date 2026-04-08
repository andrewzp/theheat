"""NSIDC Sea Ice Index — daily Arctic and Antarctic sea ice extent.

Free CSV download, no auth required. Updated daily.
Source: National Snow and Ice Data Center (NSIDC)
Dataset: G02135
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import csv
import io

import requests

ARCTIC_URL = "https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v3.0.csv"
ANTARCTIC_URL = "https://noaadata.apps.nsidc.org/NOAA/G02135/south/daily/data/S_seaice_extent_daily_v3.0.csv"


@dataclass
class SeaIceReading:
    hemisphere: str  # "Arctic" or "Antarctic"
    extent_million_km2: float
    date: str
    event_id: str


@dataclass
class SeaIceRecord:
    hemisphere: str
    extent_million_km2: float
    date: str
    record_type: str  # "lowest" or "highest"
    previous_extent: float
    previous_year: int
    event_id: str


def fetch_sea_ice(hemisphere: str = "Arctic") -> list[SeaIceReading]:
    """Fetch sea ice extent data for a hemisphere."""
    url = ARCTIC_URL if hemisphere == "Arctic" else ANTARCTIC_URL

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        readings = []
        reader = csv.reader(io.StringIO(resp.text))

        # Skip header rows (there are 2)
        next(reader, None)
        next(reader, None)

        for row in reader:
            if len(row) < 4:
                continue
            try:
                year = int(row[0].strip())
                month = int(row[1].strip())
                day = int(row[2].strip())
                extent = float(row[3].strip())
            except (ValueError, IndexError):
                continue

            if extent <= 0:
                continue

            reading_date = f"{year}-{month:02d}-{day:02d}"
            event_id = f"sea_ice_{hemisphere.lower()}_{reading_date}"

            readings.append(SeaIceReading(
                hemisphere=hemisphere,
                extent_million_km2=extent,
                date=reading_date,
                event_id=event_id,
            ))

        return readings

    except (requests.RequestException, csv.Error):
        return []


def detect_record_low(readings: list[SeaIceReading]) -> SeaIceRecord | None:
    """Check if the most recent reading is a record low for that calendar day.

    Compares the latest reading against all readings for the same
    month/day across all years in the dataset.
    """
    if not readings:
        return None

    latest = readings[-1]
    latest_date = datetime.strptime(latest.date, "%Y-%m-%d")
    target_month = latest_date.month
    target_day = latest_date.day

    # Find all readings for the same calendar day
    same_day_readings = []
    for r in readings:
        try:
            d = datetime.strptime(r.date, "%Y-%m-%d")
            if d.month == target_month and d.day == target_day and d.year != latest_date.year:
                same_day_readings.append(r)
        except ValueError:
            continue

    if not same_day_readings:
        return None

    # Find the previous record low
    prev_lowest = min(same_day_readings, key=lambda r: r.extent_million_km2)

    if latest.extent_million_km2 < prev_lowest.extent_million_km2:
        prev_year = int(prev_lowest.date.split("-")[0])
        return SeaIceRecord(
            hemisphere=latest.hemisphere,
            extent_million_km2=latest.extent_million_km2,
            date=latest.date,
            record_type="lowest",
            previous_extent=prev_lowest.extent_million_km2,
            previous_year=prev_year,
            event_id=f"sea_ice_record_{latest.hemisphere.lower()}_{latest.date}",
        )

    return None
