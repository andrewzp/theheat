"""Open-Meteo Marine API — ocean wave heights and sea surface temps.

Free API, no auth required. Provides global marine forecast data
including significant wave height, wave period, and sea surface temperature.
Docs: https://open-meteo.com/en/docs/marine-weather-api
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import requests

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# Monitoring points: major ocean buoy-equivalent locations
# (lat, lon, name, ocean)
OCEAN_POINTS = [
    (28.5, -88.0, "Gulf of Mexico", "Atlantic"),
    (35.0, -75.0, "Cape Hatteras", "Atlantic"),
    (40.5, -70.0, "Georges Bank", "Atlantic"),
    (25.0, -71.0, "Bermuda Triangle", "Atlantic"),
    (58.0, -5.0, "North Sea", "Atlantic"),
    (47.0, -8.0, "Bay of Biscay", "Atlantic"),
    (12.0, -55.0, "Caribbean Sea", "Atlantic"),
    (35.0, -125.0, "Northern California Coast", "Pacific"),
    (20.0, -157.0, "Hawaii", "Pacific"),
    (45.0, -125.0, "Pacific Northwest", "Pacific"),
    (-40.0, 150.0, "Tasman Sea", "Pacific"),
    (30.0, 130.0, "East China Sea", "Pacific"),
    (-5.0, 80.0, "Indian Ocean", "Indian"),
    (-35.0, 25.0, "South Africa Coast", "Indian"),
    (-60.0, -60.0, "Drake Passage", "Southern"),
    (75.0, 30.0, "Barents Sea", "Arctic"),
]

# Thresholds for extreme events
EXTREME_WAVE_HEIGHT_M = 10.0  # 10+ meters = extreme
EXTREME_SST_HIGH_C = 32.0  # unusually warm sea surface
EXTREME_SST_LOW_C = -1.5  # approaching freeze


@dataclass
class OceanReading:
    location: str
    ocean: str
    lat: float
    lon: float
    wave_height_max_m: float
    sst_c: float | None
    date: str
    event_id: str


@dataclass
class ExtremeWaveEvent:
    location: str
    ocean: str
    wave_height_m: float
    date: str
    event_id: str


def fetch_ocean_conditions() -> list[OceanReading]:
    """Fetch marine conditions for all monitoring points."""
    readings = []
    for lat, lon, name, ocean in OCEAN_POINTS:
        try:
            resp = requests.get(
                MARINE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "wave_height_max,sea_surface_temperature_max",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            daily = data.get("daily", {})

            wave = daily.get("wave_height_max", [None])[0]
            sst = daily.get("sea_surface_temperature_max", [None])[0]

            if wave is None:
                continue

            reading_date = date.today().isoformat()
            event_id = f"ocean_{name.replace(' ', '_').lower()}_{reading_date}"

            readings.append(OceanReading(
                location=name,
                ocean=ocean,
                lat=lat,
                lon=lon,
                wave_height_max_m=wave,
                sst_c=sst,
                date=reading_date,
                event_id=event_id,
            ))
        except (requests.RequestException, KeyError, IndexError):
            continue

    return readings


def detect_extreme_waves(readings: list[OceanReading], threshold_m: float = EXTREME_WAVE_HEIGHT_M) -> list[ExtremeWaveEvent]:
    """Find locations with extreme wave heights."""
    events = []
    for r in readings:
        if r.wave_height_max_m >= threshold_m:
            events.append(ExtremeWaveEvent(
                location=r.location,
                ocean=r.ocean,
                wave_height_m=r.wave_height_max_m,
                date=r.date,
                event_id=f"extreme_wave_{r.location.replace(' ', '_').lower()}_{r.date}",
            ))
    return events
