"""Nearest-named-landmass resolution for the cyclone land-threat signal.

v1 approximates "named landmass" as the nearest populated place in the
curated data/cities.csv (638 cities) — the landmass NAME is that city's
country, and the tweet may say "near <city>". This is deliberately coarse
and conservative: a forecast point within LAND_THREAT_MAX_NM of a curated
city is unambiguously approaching land a reader can name. A true
coastline-geometry check is a noted fast-follow; no coastline dataset
exists in this repo today.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.editorial._regions import _haversine_km

NM_PER_KM = 1 / 1.852


@dataclass(frozen=True)
class NearestLandmass:
    country: str
    city: str
    distance_nm: float


def nearest_landmass(lat: float, lon: float, cities: list[dict]) -> NearestLandmass | None:
    best: NearestLandmass | None = None
    for row in cities:
        try:
            c_lat = float(row["lat"])
            c_lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        distance_nm = _haversine_km(lat, lon, c_lat, c_lon) * NM_PER_KM
        if best is None or distance_nm < best.distance_nm:
            best = NearestLandmass(
                country=str(row.get("country") or "").strip(),
                city=str(row.get("city") or "").strip(),
                distance_nm=round(distance_nm, 1),
            )
    return best
