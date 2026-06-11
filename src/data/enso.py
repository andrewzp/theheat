"""NOAA ENSO/ONI (Oceanic Nino Index) — El Nino/La Nina status.

Free plain text download, no auth required. Updated monthly.
Source: NOAA Climate Prediction Center
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import requests

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# ENSO thresholds (standard NOAA definitions)
EL_NINO_THRESHOLD = 0.5
LA_NINA_THRESHOLD = -0.5


@dataclass
class ENSOReading:
    season: str  # e.g., "DJF", "JFM"
    year: int
    oni_value: float
    status: str  # "El Nino", "La Nina", "Neutral"
    event_id: str


def fetch_enso_data(*, strict: bool = False) -> list[ENSOReading]:
    """Fetch ONI time series data."""
    try:
        resp = fetch_with_retry(ONI_URL, timeout=30, attempts=3, backoff_base=1.0)

        readings = []
        for line in resp.text.strip().split("\n"):
            parts = line.split()
            if len(parts) < 4:
                continue

            try:
                season = parts[0]
                year = int(parts[1])
                oni = float(parts[-1])
            except (ValueError, IndexError):
                continue

            if oni >= EL_NINO_THRESHOLD:
                status = "El Nino"
            elif oni <= LA_NINA_THRESHOLD:
                status = "La Nina"
            else:
                status = "Neutral"

            event_id = f"enso_{season}_{year}"

            readings.append(ENSOReading(
                season=season,
                year=year,
                oni_value=oni,
                status=status,
                event_id=event_id,
            ))

        return readings

    except (requests.RequestException, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"ENSO fetch failed: {exc}") from exc
        return []


def detect_transition(readings: list[ENSOReading]) -> dict | None:
    """Detect if a transition between ENSO states has occurred.

    Returns a dict with transition info, or None if no transition.
    """
    if len(readings) < 2:
        return None

    current = readings[-1]
    previous = readings[-2]

    if current.status != previous.status and current.status != "Neutral":
        # Count how many months the last non-Neutral phase lasted
        prev_active = None
        streak = 0
        for r in reversed(readings[:-1]):
            if prev_active is None and r.status != "Neutral":
                prev_active = r.status
            if prev_active and r.status == prev_active:
                streak += 1
            elif prev_active:
                break

        return {
            "from_status": previous.status,
            "to_status": current.status,
            "oni_value": current.oni_value,
            "season": current.season,
            "year": current.year,
            "previous_duration_months": streak,
            "event_id": f"enso_transition_{current.status.replace(' ', '_')}_{current.year}",
        }

    return None
