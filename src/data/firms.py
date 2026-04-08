"""NASA FIRMS fire detection data."""

import csv
import io
import os
from dataclasses import dataclass
from datetime import date

import requests

FIRMS_API_KEY = os.environ.get("NASA_FIRMS_API_KEY", "")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"


@dataclass
class FireEvent:
    lat: float
    lon: float
    confidence: int
    frp: float  # Fire Radiative Power in MW
    nearest_city: str
    country: str
    event_id: str


def fetch_fires(
    confidence_min: int = 80,
    frp_min: float = 100.0,
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
) -> list[FireEvent]:
    """Fetch active fires from NASA FIRMS, filtered by confidence and FRP."""
    if not FIRMS_API_KEY:
        return []

    try:
        resp = requests.get(
            f"{FIRMS_URL}/{FIRMS_API_KEY}/{source}/world/{days}",
            timeout=30,
        )
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        fires = []
        for row in reader:
            try:
                conf = int(row.get("confidence", "0").rstrip("%").strip() or "0")
                frp = float(row.get("frp", "0") or "0")
            except (ValueError, TypeError):
                continue

            if conf >= confidence_min and frp >= frp_min:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                city, country = reverse_geocode_simple(lat, lon)
                event_id = f"fire_{lat:.2f}_{lon:.2f}_{date.today().isoformat()}"
                fires.append(FireEvent(
                    lat=lat,
                    lon=lon,
                    confidence=conf,
                    frp=frp,
                    nearest_city=city,
                    country=country,
                    event_id=event_id,
                ))

        return fires

    except (requests.RequestException, csv.Error, KeyError):
        return []


def reverse_geocode_simple(lat: float, lon: float) -> tuple[str, str]:
    """Map coordinates to a rough region and country name."""
    return _lat_lon_to_region(lat, lon), _lat_lon_to_country(lat, lon)


def _lat_lon_to_region(lat: float, lon: float) -> str:
    """Rough region name from coordinates."""
    # US regions
    if 24 < lat < 50 and -125 < lon < -66:
        if lon > -100:
            if lat > 40:
                return "Northeastern US"
            else:
                return "Southeastern US"
        else:
            if lat > 40:
                return "Northwestern US"
            else:
                return "Southwestern US"
    if lat > 50 and -170 < lon < -50:
        return "Canada"
    if -35 < lat < 35 and -120 < lon < -30:
        return "Latin America"
    if 35 < lat < 72 and -10 < lon < 40:
        return "Europe"
    if 0 < lat < 40 and 25 < lon < 60:
        return "Middle East"
    if -35 < lat < 40 and -20 < lon < 55:
        return "Africa"
    if 0 < lat < 55 and 60 < lon < 150:
        return "Asia"
    if -50 < lat < -10 and 110 < lon < 180:
        return "Australia"
    return f"{abs(lat):.0f}{'N' if lat >= 0 else 'S'}, {abs(lon):.0f}{'E' if lon >= 0 else 'W'}"


def _lat_lon_to_country(lat: float, lon: float) -> str:
    """Very rough country from coordinates. Good enough for fire alerts."""
    if 24 < lat < 50 and -125 < lon < -66:
        return "US"
    if 50 < lat < 72 and -140 < lon < -50:
        return "Canada"
    if 14 < lat < 33 and -118 < lon < -86:
        return "Mexico"
    if -35 < lat < 6 and -74 < lon < -34:
        return "Brazil"
    if 35 < lat < 60 and -10 < lon < 3:
        return "Western Europe"
    if -45 < lat < -10 and 112 < lon < 155:
        return "Australia"
    return "Unknown"
