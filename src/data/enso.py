"""NOAA ENSO/ONI (Oceanic Nino Index) — El Nino/La Nina status.

Free plain text download, no auth required. Updated monthly.
Source: NOAA Climate Prediction Center
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_cache_revalidation
from src.data.source_status import SourceFetchError

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
_ONI_REVALIDATION_CACHE: dict[str, tuple[str, str]] = {}

# ENSO thresholds (standard NOAA definitions)
EL_NINO_THRESHOLD = 0.5
LA_NINA_THRESHOLD = -0.5
_SEASON_END_MONTH = {
    "DJF": 2,
    "JFM": 3,
    "FMA": 4,
    "MAM": 5,
    "AMJ": 6,
    "MJJ": 7,
    "JJA": 8,
    "JAS": 9,
    "ASO": 10,
    "SON": 11,
    "OND": 12,
    "NDJ": 1,
}


@dataclass
class ENSOReading:
    season: str  # e.g., "DJF", "JFM"
    year: int
    oni_value: float
    status: str  # "El Nino", "La Nina", "Neutral"
    event_id: str


def _oni_month_end(season: str, year: int) -> date | None:
    month = _SEASON_END_MONTH.get(season.upper())
    if month is None:
        return None
    effective_year = year + 1 if season.upper() == "NDJ" else year
    return date(effective_year, month, monthrange(effective_year, month)[1])


def fetch_enso_data(*, strict: bool = False) -> list[ENSOReading]:
    """Fetch ONI time series data."""
    try:
        resp = fetch_with_cache_revalidation(
            ONI_URL,
            cache=_ONI_REVALIDATION_CACHE,
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )

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

        if readings and (latest_date := _oni_month_end(readings[-1].season, readings[-1].year)):
            assert_freshness(latest_date, "enso", max_age_days=45)
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
