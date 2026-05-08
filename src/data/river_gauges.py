"""USGS Water Services — river flood stages.

Free API, no auth required. Real-time streamflow and gauge height
data from thousands of stations across the US.
Docs: https://waterservices.usgs.gov/rest/IV-Service.html
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import requests

from src.data.source_status import SourceFetchError

USGS_URL = "https://waterservices.usgs.gov/nwis/iv/"
FLOOD_URL = "https://waterwatch.usgs.gov/webservices/floodstage"

# Major river stations: (site_id, river_name, location)
# Chosen for flood significance and population exposure
MAJOR_STATIONS = [
    ("07010000", "Mississippi River", "St. Louis, MO"),
    ("07374000", "Mississippi River", "Baton Rouge, LA"),
    ("03085000", "Monongahela River", "Pittsburgh, PA"),
    ("01389500", "Passaic River", "Little Falls, NJ"),
    ("08066500", "Trinity River", "Romayor, TX"),
    ("02489500", "Pearl River", "Bogalusa, LA"),
    ("12113000", "Green River", "Auburn, WA"),
    ("05587450", "Mississippi River", "Grafton, IL"),
    ("02084000", "Tar River", "Greenville, NC"),
    ("06807000", "Missouri River", "Nebraska City, NE"),
    ("09380000", "Colorado River", "Lees Ferry, AZ"),
    ("12340000", "Clark Fork", "St. Regis, MT"),
]

# USGS parameter codes
GAUGE_HEIGHT_CODE = "00065"  # Gage height, ft


@dataclass
class RiverReading:
    river: str
    location: str
    site_id: str
    gauge_height_ft: float
    flood_stage_ft: float | None
    above_flood: bool
    date: str
    event_id: str


@dataclass
class FloodEvent:
    river: str
    location: str
    gauge_height_ft: float
    flood_stage_ft: float
    above_by_ft: float
    date: str
    event_id: str


def _fetch_flood_stages(*, strict: bool = False) -> dict[str, float]:
    """Fetch flood stage thresholds for USGS stations."""
    try:
        resp = requests.get(
            FLOOD_URL,
            params={"format": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        stages = {}
        for site in data.get("sites", []):
            site_id = site.get("site_no", "")
            flood = site.get("flood_stage", "")
            if site_id and flood:
                try:
                    stages[site_id] = float(flood)
                except ValueError:
                    continue
        return stages

    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"Flood stage fetch failed: {exc}") from exc
        return {}


def fetch_river_levels(*, strict: bool = False) -> list[RiverReading]:
    """Fetch current gauge heights for major river stations."""
    site_ids = ",".join(s[0] for s in MAJOR_STATIONS)
    site_map = {s[0]: (s[1], s[2]) for s in MAJOR_STATIONS}

    try:
        resp = requests.get(
            USGS_URL,
            params={
                "format": "json",
                "sites": site_ids,
                "parameterCd": GAUGE_HEIGHT_CODE,
                "siteStatus": "active",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        flood_stages = _fetch_flood_stages(strict=strict)
        readings = []
        today = date.today().isoformat()

        time_series = data.get("value", {}).get("timeSeries", [])
        for series in time_series:
            site_info = series.get("sourceInfo", {})
            site_id = site_info.get("siteCode", [{}])[0].get("value", "")

            if site_id not in site_map:
                continue

            values = series.get("values", [{}])[0].get("value", [])
            if not values:
                continue

            # Get most recent reading
            latest = values[-1]
            try:
                gauge_ft = float(latest.get("value", 0))
            except (ValueError, TypeError):
                continue

            if gauge_ft <= 0:
                continue

            river, location = site_map[site_id]
            flood_stage = flood_stages.get(site_id)
            above = flood_stage is not None and gauge_ft >= flood_stage

            readings.append(RiverReading(
                river=river,
                location=location,
                site_id=site_id,
                gauge_height_ft=round(gauge_ft, 2),
                flood_stage_ft=flood_stage,
                above_flood=above,
                date=today,
                event_id=f"river_{site_id}_{today}",
            ))

        return readings

    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"River gauge fetch failed: {exc}") from exc
        return []


def detect_floods(readings: list[RiverReading]) -> list[FloodEvent]:
    """Find stations where gauge height exceeds flood stage."""
    events = []
    for r in readings:
        if r.above_flood and r.flood_stage_ft is not None:
            events.append(FloodEvent(
                river=r.river,
                location=r.location,
                gauge_height_ft=r.gauge_height_ft,
                flood_stage_ft=r.flood_stage_ft,
                above_by_ft=round(r.gauge_height_ft - r.flood_stage_ft, 2),
                date=r.date,
                event_id=f"flood_{r.site_id}_{r.date}",
            ))
    return events
