"""Copernicus EMS Rapid Mapping flood activations.

Public, unauthenticated endpoints. The current Rapid Mapping API exposes flood
activations through the dashboard endpoints, with detail calls for impact stats.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import re
from typing import Any

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError, assert_response_schema

SUMMARY_URL = (
    "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/"
    "public-activations-info/"
)
DETAIL_URL = (
    "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/"
    "public-activations/"
)
ACTIVATION_URL = "https://mapping.emergency.copernicus.eu/activations/{code}/"
SOURCE_NAME = "copernicus_ems"
_REQUEST_HEADERS = {"User-Agent": "(theheat-bot, contact@theheat.app)"}

POPULATION_THRESHOLD = 100_000
_FLOOD_CATEGORY = "Flood"
_SUMMARY_MAX_AGE_DAYS = 45
_SEVERITY_ORDER = {
    "Minor": 0,
    "Moderate": 1,
    "Major": 2,
    "Extreme": 3,
}
_POINT_RE = re.compile(
    r"^POINT\s*\(\s*(?P<lon>-?\d+(?:\.\d+)?)\s+(?P<lat>-?\d+(?:\.\d+)?)\s*\)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CopernicusFloodActivation:
    activation_id: str
    country: str
    event_type: str
    severity: str
    populations_affected: int
    affected_area_km2: float
    lat: float
    lon: float
    activation_date: str
    copernicus_url: str
    event_id: str
    name: str = ""
    closed: bool = False
    last_update: str = ""


def _safe_float(value: object) -> float:
    try:
        if value in (None, "", "-", "NA"):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: object) -> int:
    try:
        if value in (None, "", "-", "NA"):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _severity_rank(severity: str) -> int:
    return _SEVERITY_ORDER.get(severity, -1)


def _parse_wkt_point(value: object) -> tuple[float, float]:
    if not isinstance(value, str):
        return 0.0, 0.0
    match = _POINT_RE.match(value.strip())
    if not match:
        return 0.0, 0.0
    lon = _safe_float(match.group("lon"))
    lat = _safe_float(match.group("lat"))
    return lat, lon


def _stats_number(stats: object, names: tuple[str, ...]) -> float:
    if not isinstance(stats, Mapping):
        return 0.0
    wanted = {name.lower() for name in names}
    for key, value in stats.items():
        if str(key).strip().lower() in wanted:
            return _safe_float(value)
    return 0.0


def _countries_from_payload(
    detail: Mapping[str, Any] | None,
    summary: Mapping[str, Any],
) -> str:
    raw_countries = detail.get("countries") if detail is not None else None
    if not raw_countries:
        raw_countries = summary.get("countries")

    names: list[str] = []
    if isinstance(raw_countries, list):
        for country in raw_countries:
            name = ""
            if isinstance(country, Mapping):
                name = str(country.get("name") or country.get("short_name") or "").strip()
            elif isinstance(country, str):
                name = country.strip()
            if name and name not in names:
                names.append(name)
    return ", ".join(names) or "Unknown"


def _category_name(summary: Mapping[str, Any], detail: Mapping[str, Any] | None) -> str:
    raw_category = detail.get("category") if detail is not None else summary.get("category")
    if isinstance(raw_category, Mapping):
        return str(raw_category.get("name") or raw_category.get("slug") or "").strip()
    return str(raw_category or "").strip()


def _event_type(summary: Mapping[str, Any], detail: Mapping[str, Any] | None) -> str:
    subcategory = str((detail or {}).get("subCategory") or "").strip()
    if subcategory:
        return subcategory
    return _category_name(summary, detail) or _FLOOD_CATEGORY


def _classify_severity(
    *,
    populations_affected: int,
    affected_area_km2: float,
    closed: bool,
) -> str:
    """Derive a conservative tier because the public API has no severity field."""
    if populations_affected >= 250_000 or affected_area_km2 >= 500:
        return "Extreme"
    if (
        populations_affected >= POPULATION_THRESHOLD
        or affected_area_km2 >= 100
        or not closed
    ):
        return "Major"
    if populations_affected >= 10_000 or affected_area_km2 >= 10:
        return "Moderate"
    return "Minor"


def _parse_activation(
    summary: Mapping[str, Any],
    detail: Mapping[str, Any] | None = None,
) -> CopernicusFloodActivation | None:
    code = str(summary.get("code") or (detail or {}).get("code") or "").strip()
    if not code:
        return None
    category = _category_name(summary, detail)
    if category.lower() != _FLOOD_CATEGORY.lower():
        return None

    detail_stats = (detail or {}).get("stats")
    population = _safe_int(_stats_number(detail_stats, ("Population [No.]",)))
    area_ha = _stats_number(
        detail_stats,
        ("max_extent", "Event Extent [ha]", "Flooded area [ha]"),
    )
    area_km2 = round(area_ha / 100.0, 2) if area_ha > 0 else 0.0
    closed = bool(summary.get("closed") if "closed" in summary else (detail or {}).get("closed", False))
    severity = _classify_severity(
        populations_affected=population,
        affected_area_km2=area_km2,
        closed=closed,
    )
    lat, lon = _parse_wkt_point(summary.get("centroid") or (detail or {}).get("centroid"))
    activation_date = str(
        summary.get("activationTime") or (detail or {}).get("activationTime") or date.today().isoformat()
    )
    last_update = str(summary.get("lastUpdate") or (detail or {}).get("lastUpdate") or activation_date)
    event_id = f"copernicus_flood_{code}_{severity.lower()}"
    return CopernicusFloodActivation(
        activation_id=code,
        country=_countries_from_payload(detail, summary),
        event_type=_event_type(summary, detail),
        severity=severity,
        populations_affected=population,
        affected_area_km2=area_km2,
        lat=lat,
        lon=lon,
        activation_date=activation_date,
        copernicus_url=ACTIVATION_URL.format(code=code),
        event_id=event_id,
        name=str(summary.get("name") or (detail or {}).get("name") or code),
        closed=closed,
        last_update=last_update,
    )


def _fetch_detail(code: str, *, strict: bool) -> Mapping[str, Any] | None:
    try:
        response = fetch_with_retry(
            DETAIL_URL,
            params={"code": code},
            headers=_REQUEST_HEADERS,
            timeout=30,
        )
        payload = response.json()
        assert_response_schema(payload, ["results"], SOURCE_NAME)
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        if not isinstance(first, Mapping):
            raise SourceFetchError(f"{SOURCE_NAME} schema drift: detail result was not an object")
        return first
    except (requests.RequestException, ValueError, SourceFetchError) as exc:
        if strict:
            raise SourceFetchError(f"Copernicus EMS flood detail fetch failed for {code}: {exc}") from exc
        return None


def fetch_active_flood_activations(
    *,
    strict: bool = False,
    include_closed: bool = False,
    limit: int = 50,
) -> list[CopernicusFloodActivation]:
    """Fetch current public Copernicus Rapid Mapping flood activations.

    By default only open (`closed=false`) activations are fetched so a first
    deploy does not draft historical floods. Tests and archive checks can pass
    ``include_closed=True``.
    """
    params: dict[str, str | int] = {"category": _FLOOD_CATEGORY, "limit": limit}
    if not include_closed:
        params["closed"] = "false"
    try:
        response = fetch_with_retry(
            SUMMARY_URL,
            params=params,
            headers=_REQUEST_HEADERS,
            timeout=30,
        )
        payload = response.json()
        assert_response_schema(payload, ["count", "results"], SOURCE_NAME)
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, list):
            raise SourceFetchError(f"{SOURCE_NAME} schema drift: results was not a list")
        if not results:
            return []

        latest_update = max(
            str(row.get("lastUpdate") or row.get("activationTime") or "")
            for row in results
            if isinstance(row, Mapping)
        )
        if latest_update:
            assert_freshness(latest_update, SOURCE_NAME, _SUMMARY_MAX_AGE_DAYS)

        activations: list[CopernicusFloodActivation] = []
        for row in results:
            if not isinstance(row, Mapping):
                if strict:
                    raise SourceFetchError(f"{SOURCE_NAME} schema drift: result was not an object")
                continue
            code = str(row.get("code") or "").strip()
            detail = _fetch_detail(code, strict=strict) if code else None
            activation = _parse_activation(row, detail)
            if activation is not None:
                activations.append(activation)
        return activations
    except (requests.RequestException, ValueError, SourceFetchError) as exc:
        if strict:
            raise SourceFetchError(f"Copernicus EMS flood fetch failed: {exc}") from exc
        return []


def detect_flood_events(
    activations: list[CopernicusFloodActivation],
    flood_activation_tiers: Mapping[str, str] | None = None,
) -> list[CopernicusFloodActivation]:
    """Return activation tier crossings that should become draft candidates."""
    last_tiers = flood_activation_tiers or {}
    events: list[CopernicusFloodActivation] = []
    for activation in activations:
        current_rank = _severity_rank(activation.severity)
        if current_rank < _SEVERITY_ORDER["Major"] and (
            activation.populations_affected < POPULATION_THRESHOLD
        ):
            continue
        previous_rank = _severity_rank(str(last_tiers.get(activation.activation_id, "")))
        if current_rank <= previous_rank:
            continue
        events.append(activation)
    return events
