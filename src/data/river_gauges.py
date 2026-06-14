"""USGS gauge heights plus NOAA NWPS flood-stage thresholds.

Both APIs are free and unauthenticated. USGS provides live gauge heights;
NOAA NWPS provides the replacement flood-stage metadata for AHPS/WaterWatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry
from src.data._witness import with_witness
from src.data.source_status import SourceFetchError, assert_response_schema

USGS_URL = "https://waterservices.usgs.gov/nwis/iv/"
FLOOD_URL = "https://api.water.noaa.gov/nwps/v1/gauges/{site_id}"
OPEN_METEO_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
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

# Open-Meteo Flood / GloFAS witness (R-05). Coordinates are authoritative USGS
# station coordinates captured in the R-05 groundwork doc. GloFAS samples the
# largest river in a ~5 km cell, so never invent coordinates for unmapped sites.
_OPEN_METEO_FLOOD_COORDS: dict[str, tuple[float, float]] = {
    "01389500": (40.88472222, -74.22611111),
    "02084000": (35.61666667, -77.37277778),
    "02489500": (30.7932614, -89.8209117),
    "03085000": (40.39113189, -79.8580943),
    "05587450": (38.9679722, -90.429),
    "06807000": (40.68180556, -95.8470833),
    "07010000": (38.629, -90.1797778),
    "07374000": (30.44566667, -91.1915556),
    "08066500": (30.4252067, -94.8507622),
    "09380000": (36.86433333, -111.58787222),
    "12113000": (47.3123228, -122.2040082),
    "12340000": (46.8994111, -113.7563194),
}
_OPEN_METEO_FLOOD_LEG = "open_meteo_flood"
_OPEN_METEO_FLOOD_ABSOLUTE_FLOOR_M3S = 500.0


@dataclass
class RiverReading:
    river: str
    location: str
    site_id: str
    gauge_height_ft: float | None
    flood_stage_ft: float | None
    above_flood: bool
    date: str
    event_id: str
    source_leg: str | None = None  # witness leg that served (R-00); None = primary
    discharge_m3s: float | None = None
    discharge_threshold_m3s: float | None = None
    discharge_ratio: float | None = None


@dataclass
class FloodEvent:
    river: str
    location: str
    gauge_height_ft: float | None
    flood_stage_ft: float | None
    above_by_ft: float | None
    date: str
    event_id: str
    source_leg: str | None = None
    discharge_m3s: float | None = None
    discharge_threshold_m3s: float | None = None
    discharge_ratio: float | None = None


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
        return float(str(stage))
    except (TypeError, ValueError) as exc:
        raise SourceFetchError(
            f"river_gauges schema drift: invalid minor flood stage for {site_id}"
        ) from exc


def fetch_river_levels(*, strict: bool = False) -> list[RiverReading]:
    """Fetch current gauge heights for major river stations.

    R-05 wraps the USGS/NWPS primary in the Open-Meteo Flood / GloFAS model
    witness. The public return shape remains ``list[RiverReading]``; model
    readings carry ``source_leg="open_meteo_flood"`` plus discharge fields and
    intentionally leave gauge-height/flood-stage feet as ``None``.
    """

    def primary() -> list[RiverReading]:
        return _fetch_river_levels_primary(strict=strict)

    def witness() -> list[RiverReading]:
        return _fetch_open_meteo_flood()

    try:
        return with_witness(
            primary,
            witness,
            source_key="river_gauges",
            leg_label=_OPEN_METEO_FLOOD_LEG,
        )
    except (SourceFetchError, requests.RequestException) as exc:
        if strict:
            raise SourceFetchError(f"River gauge fetch failed: {exc}") from exc
        return []


def _fetch_river_levels_primary(*, strict: bool = False) -> list[RiverReading]:
    """Fetch current USGS gauge heights plus NOAA NWPS flood stages."""
    site_ids = ",".join(s[0] for s in MAJOR_STATIONS)
    site_map = {s[0]: (s[1], s[2]) for s in MAJOR_STATIONS}

    try:
        # Routed through fetch_with_retry for retry+backoff and a polite UA,
        # matching the NWPS flood-stage leg.
        resp = fetch_with_retry(
            USGS_URL,
            params={
                "format": "json",
                "sites": site_ids,
                "parameterCd": GAUGE_HEIGHT_CODE,
                "siteStatus": "active",
            },
            headers=_REQUEST_HEADERS,
            timeout=30,
        )
        data = resp.json()

        flood_stages = _fetch_flood_stages(strict=strict)
        readings = []
        payload_dates = []
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
            payload_dates.append(latest.get("dateTime"))
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

        if newest_date := newest_freshness_date(payload_dates):
            assert_freshness(newest_date, "river_gauges", max_age_days=2)
        return readings

    except (requests.RequestException, ValueError, KeyError) as exc:
        raise SourceFetchError(f"River gauge fetch failed: {exc}") from exc


def _fetch_open_meteo_flood() -> list[RiverReading]:
    """Fetch modeled GloFAS discharge for stations with known coordinates."""
    readings: list[RiverReading] = []
    for site_id, river, location in MAJOR_STATIONS:
        coords = _OPEN_METEO_FLOOD_COORDS.get(site_id)
        if coords is None:
            continue
        reading = _fetch_open_meteo_flood_station(site_id, river, location, coords)
        if reading is not None:
            readings.append(reading)
    return readings


def _fetch_open_meteo_flood_station(
    site_id: str,
    river: str,
    location: str,
    coords: tuple[float, float],
) -> RiverReading | None:
    """Return one conservative model-flood reading, or None below gate."""
    lat, lon = coords
    resp = fetch_with_retry(
        OPEN_METEO_FLOOD_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge,river_discharge_mean,river_discharge_p75",
            "past_days": 1,
            "forecast_days": 7,
        },
        headers=_REQUEST_HEADERS,
        timeout=30,
    )
    payload = resp.json()
    daily = _parse_open_meteo_flood_daily(payload, site_id)
    candidate = _select_open_meteo_flood_candidate(daily)
    if candidate is None:
        return None
    reading_date, discharge, threshold = candidate
    ratio = discharge / threshold if threshold > 0 else None
    return RiverReading(
        river=river,
        location=location,
        site_id=site_id,
        gauge_height_ft=None,
        flood_stage_ft=None,
        above_flood=True,
        date=reading_date,
        event_id=f"river_model_{site_id}_{reading_date}",
        source_leg=_OPEN_METEO_FLOOD_LEG,
        discharge_m3s=round(discharge, 2),
        discharge_threshold_m3s=round(threshold, 2),
        discharge_ratio=round(ratio, 3) if ratio is not None else None,
    )


def _parse_open_meteo_flood_daily(payload: object, site_id: str) -> dict[str, list]:
    if not isinstance(payload, dict):
        raise SourceFetchError("river_gauges schema drift: expected Open-Meteo object")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise SourceFetchError("river_gauges schema drift: missing Open-Meteo daily")
    required = ("time", "river_discharge", "river_discharge_p75")
    for key in required:
        if not isinstance(daily.get(key), list):
            raise SourceFetchError(
                f"river_gauges schema drift: missing Open-Meteo {key} for {site_id}"
            )
    return daily


def _select_open_meteo_flood_candidate(
    daily: dict[str, list],
) -> tuple[str, float, float] | None:
    times = daily["time"]
    discharges = daily["river_discharge"]
    p75s = daily["river_discharge_p75"]
    best: tuple[str, float, float] | None = None
    for day, raw_discharge, raw_p75 in zip(times, discharges, p75s, strict=False):
        try:
            discharge = float(raw_discharge)
            threshold = float(raw_p75)
        except (TypeError, ValueError):
            continue
        if threshold <= 0:
            continue
        if discharge < _OPEN_METEO_FLOOD_ABSOLUTE_FLOOR_M3S:
            continue
        if discharge < threshold:
            continue
        if best is None or discharge / threshold > best[1] / best[2]:
            best = (str(day), discharge, threshold)
    return best


def detect_floods(readings: list[RiverReading]) -> list[FloodEvent]:
    """Find stations where gauge height exceeds flood stage."""
    events = []
    for r in readings:
        if r.source_leg == _OPEN_METEO_FLOOD_LEG and r.above_flood:
            events.append(FloodEvent(
                river=r.river,
                location=r.location,
                gauge_height_ft=None,
                flood_stage_ft=None,
                above_by_ft=None,
                date=r.date,
                event_id=f"flood_model_{r.site_id}_{r.date}",
                source_leg=r.source_leg,
                discharge_m3s=r.discharge_m3s,
                discharge_threshold_m3s=r.discharge_threshold_m3s,
                discharge_ratio=r.discharge_ratio,
            ))
        elif r.above_flood and r.flood_stage_ft is not None and r.gauge_height_ft is not None:
            events.append(FloodEvent(
                river=r.river,
                location=r.location,
                gauge_height_ft=r.gauge_height_ft,
                flood_stage_ft=r.flood_stage_ft,
                above_by_ft=round(r.gauge_height_ft - r.flood_stage_ft, 2),
                date=r.date,
                event_id=f"flood_{r.site_id}_{r.date}",
                source_leg=r.source_leg,
            ))
    return events
