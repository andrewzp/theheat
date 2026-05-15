"""USGS gauge heights plus NOAA NWPS flood-stage thresholds.

Both APIs are free and unauthenticated. USGS provides live gauge heights;
NOAA NWPS provides the replacement flood-stage metadata for AHPS/WaterWatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import requests

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError, assert_response_schema

USGS_URL = "https://waterservices.usgs.gov/nwis/iv/"
FLOOD_URL = "https://api.water.noaa.gov/nwps/v1/gauges/{site_id}"
_REQUEST_HEADERS = {"User-Agent": "(theheat-bot, contact@theheat.app)"}

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
    """Fetch minor flood-stage thresholds from NOAA NWPS gauge metadata."""
    stages: dict[str, float] = {}
    for site_id, _river_name, _location in MAJOR_STATIONS:
        try:
            resp = fetch_with_retry(
                FLOOD_URL.format(site_id=site_id),
                headers=_REQUEST_HEADERS,
                timeout=15,
            )
            data = resp.json()
            stage = _parse_nwps_minor_flood_stage(data, site_id)
            if stage is not None:
                stages[site_id] = stage
        except (requests.RequestException, ValueError, SourceFetchError) as exc:
            if strict:
                raise SourceFetchError(
                    f"River gauge flood-stage fetch failed for {site_id}: {exc}"
                ) from exc
            continue
    return stages


def _parse_nwps_minor_flood_stage(payload: object, site_id: str) -> float | None:
    assert_response_schema(payload, ["flood"], "river_gauges")
    if not isinstance(payload, dict):
        raise SourceFetchError("river_gauges schema drift: expected gauge object")
    flood = payload["flood"]
    if not isinstance(flood, dict):
        raise SourceFetchError("river_gauges schema drift: flood was not an object")
    categories = flood.get("categories")
    if not isinstance(categories, dict):
        raise SourceFetchError("river_gauges schema drift: missing flood.categories")
    minor = categories.get("minor")
    if not isinstance(minor, dict):
        return None
    stage = minor.get("stage")
    if stage in (None, "", -9999, "-9999"):
        return None
    try:
        return float(stage)
    except (TypeError, ValueError) as exc:
        raise SourceFetchError(
            f"river_gauges schema drift: invalid minor flood stage for {site_id}"
        ) from exc


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
