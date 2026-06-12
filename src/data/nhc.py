"""National Hurricane Center active tropical-cyclone advisories."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry
from src.data.cyclones import (
    BasinRecordEvent,
    CycloneAdvisory,
    LandfallEvent,
    RapidIntensificationEvent,
    TierCrossingEvent,
    detect_basin_records,
    detect_landfalls,
    detect_rapid_intensification,
    detect_tier_crossings,
    parse_coordinate,
    parse_int,
)
from src.data.source_status import SourceFetchError, assert_response_schema

NHC_CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
NHC_BASE_URL = "https://www.nhc.noaa.gov/"


def fetch_active_cyclones(*, strict: bool = False) -> list[CycloneAdvisory]:
    """Fetch active NHC Atlantic and East Pacific storm advisories."""

    fetched_advisories: list[CycloneAdvisory] = []
    try:
        response = fetch_with_retry(
            NHC_CURRENT_STORMS_URL,
            headers={
                "User-Agent": "(theheat-bot, contact@theheat.app)",
                "Accept": "application/json",
            },
            timeout=30,
        )
        payload = response.json()
        assert_response_schema(payload, ("activeStorms",), "NHC CurrentStorms")

        advisories = []
        for raw in payload.get("activeStorms") or []:
            if not isinstance(raw, dict):
                continue
            advisory = _parse_active_storm(raw)
            if advisory is not None:
                advisories.append(advisory)
        fetched_advisories = advisories
    except (requests.RequestException, ValueError, KeyError, TypeError, SourceFetchError) as exc:
        if strict:
            raise SourceFetchError(f"NHC fetch failed: {exc}") from exc
        return []
    if fetched_advisories and (
        newest_date := newest_freshness_date([advisory.issued_at for advisory in fetched_advisories])
    ):
        assert_freshness(newest_date, "nhc", max_age_days=2)
    return fetched_advisories


def _parse_active_storm(raw: dict[str, Any]) -> CycloneAdvisory | None:
    storm_id = str(_first_present(
        raw,
        "id",
        "stormId",
        "storm_id",
        "stormKey",
        "binNumber",
        default="",
    ) or "").strip()
    name = str(_first_present(raw, "name", "stormName", "storm_name", default="") or "").strip()
    if not storm_id and not name:
        return None

    wind = parse_int(_first_present(
        raw,
        "intensity",
        "wind",
        "wind_kt",
        "maxWind",
        "max_wind_kt",
        "maxSustainedWind",
        "max_sustained_wind_kt",
    ))
    if wind is None:
        return None

    pressure = parse_int(_first_present(
        raw,
        "pressure",
        "pressure_mb",
        "minPressure",
        "centralPressure",
        "central_pressure_mb",
    ))
    lat = parse_coordinate(_first_present(raw, "latitudeNumeric", "lat", "latitude"))
    lon = parse_coordinate(_first_present(raw, "longitudeNumeric", "lon", "longitude"))
    basin = str(_first_present(raw, "basin", "region", default=_basin_from_storm_id(storm_id)) or "")
    advisory_number = str(_first_present(
        raw,
        "advisoryNumber",
        "advisory_number",
        "advNum",
        "number",
        default="",
    ) or "").strip()
    issued_at = str(_first_present(
        raw,
        "lastUpdate",
        "last_update",
        "advisoryTime",
        "issued_at",
        "pubDate",
        default="",
    ) or "").strip()
    public_advisory_url = _normalize_url(str(_first_present(
        raw,
        "publicAdvisory",
        "publicAdvisoryUrl",
        "public_advisory",
        "public_advisory_url",
        "advisoryUrl",
        default="",
    ) or "").strip())
    advisory_text = _fetch_advisory_text(public_advisory_url)

    return CycloneAdvisory(
        source="nhc",
        storm_id=storm_id or name,
        storm_name=name or storm_id,
        basin=basin or _basin_from_storm_id(storm_id),
        advisory_number=advisory_number,
        issued_at=issued_at,
        wind_kt=wind,
        pressure_mb=pressure,
        lat=lat,
        lon=lon,
        classification=str(_first_present(raw, "classification", "status", default="") or ""),
        public_advisory_url=public_advisory_url,
        advisory_text=advisory_text,
    )


def _first_present(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return default


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    return urljoin(NHC_BASE_URL, url)


def _fetch_advisory_text(url: str) -> str:
    if not url:
        return ""
    try:
        response = fetch_with_retry(
            url,
            headers={"User-Agent": "(theheat-bot, contact@theheat.app)"},
            timeout=15,
            attempts=2,
        )
        return response.text[:8000]
    except requests.RequestException:
        return ""


def _basin_from_storm_id(storm_id: str) -> str:
    upper = storm_id.upper()
    if upper.startswith("AL"):
        return "Atlantic"
    if upper.startswith("EP"):
        return "East Pacific"
    if upper.startswith("CP"):
        return "Central Pacific"
    return "NHC basin"


__all__ = [
    "BasinRecordEvent",
    "CycloneAdvisory",
    "LandfallEvent",
    "RapidIntensificationEvent",
    "TierCrossingEvent",
    "detect_basin_records",
    "detect_landfalls",
    "detect_rapid_intensification",
    "detect_tier_crossings",
    "fetch_active_cyclones",
]
