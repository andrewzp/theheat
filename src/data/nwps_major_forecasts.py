"""Bounded NOAA NWPS discovery and gauge-level verification of major forecasts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
import re
from typing import Any

from requests import RequestException

from src.data._http import fetch_with_retry

INDEX_URL = "https://mapservices.weather.noaa.gov/eventdriven/rest/services/water/riv_gauges/MapServer/3/query"
GAUGES_URL = "https://api.water.noaa.gov/nwps/v1/gauges"
INDEX_FIELDS = "gaugelid,status,state,fcsttime,fcstissunc,forecast,units,major,pedts"
ENABLE_FLAG = "THEHEAT_NWPS_MAJOR_FORECASTS"
MAX_INDEX_ROWS = 50
MAX_DETAIL_GAUGES = 2
MAX_DOCUMENT_BYTES = 200_000
MAX_SOURCE_AGE = timedelta(hours=6)
HORIZON = timedelta(hours=72)


@dataclass(frozen=True)
class MajorRiverForecast:
    lid: str
    gauge_name: str
    state_name: str
    issued_at: datetime
    first_major_at: datetime
    forecast_ft: float
    major_threshold_ft: float
    threshold_impact: str | None
    index_hint: dict[str, Any]


def _utc(value: Any, pattern: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("nwps_time_invalid")
    parsed = datetime.strptime(value, pattern)
    if parsed.strftime(pattern) != value:
        raise ValueError("nwps_time_invalid")
    return parsed.replace(tzinfo=timezone.utc)


def _stage(value: Any) -> float:
    if type(value) not in (int, float, str):
        raise ValueError("nwps_stage_invalid")
    result = float(value)
    if not isfinite(result) or not -100 < result < 500:
        raise ValueError("nwps_stage_invalid")
    return result


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("nwps_gauge_name_invalid")
    return value.strip()


def _read_json(url: str, **kwargs: Any) -> dict:
    response = fetch_with_retry(url, timeout=15, attempts=1, stream=True, allow_redirects=False, **kwargs)
    try:
        if response.status_code != 200:
            raise ValueError("nwps_http_status")
        data = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            data.extend(chunk)
            if len(data) > MAX_DOCUMENT_BYTES:
                raise ValueError("nwps_response_size")
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("nwps_response_shape")
        return parsed
    finally:
        response.close()


def _index(payload: dict, now: datetime) -> list[dict]:
    features = payload.get("features")
    if not isinstance(features, list) or payload.get("error") or payload.get("exceededTransferLimit") \
            or len(features) > MAX_INDEX_ROWS:
        raise ValueError("nwps_index_incomplete")
    candidates = []
    gauge_counts: Counter[str] = Counter()
    for feature in features:
        row = feature.get("attributes") if isinstance(feature, dict) else None
        if not isinstance(row, dict) or not isinstance(row.get("gaugelid"), str):
            raise ValueError("nwps_index_row_invalid")
        gauge_counts[row["gaugelid"]] += 1
        try:
            peak_at = _utc(row["fcsttime"], "%Y-%m-%d %H:%M:%S")
            generated = _utc(row["fcstissunc"], "%Y-%m-%d %H:%M:%S")
            if (re.fullmatch(r"[A-Z0-9]{5}", row["gaugelid"]) is not None
                    and row["status"] == "major" and row["units"] == "ft" and row["pedts"] == "HGIFF"
                    and now < peak_at and timedelta(0) <= now - generated <= MAX_SOURCE_AGE
                    and _stage(row["forecast"]) >= _stage(row["major"])):
                candidates.append((peak_at, row["gaugelid"], row))
        except (KeyError, ValueError, OverflowError):
            continue
    candidates.sort(key=lambda item: item[:2])
    return [row for _, lid, row in candidates if gauge_counts[lid] == 1]


def verify_major_forecast(row: dict, metadata: dict, forecast: dict, now: datetime) -> MajorRiverForecast:
    """Require exact agreement between the GIS hint and the issued point series."""
    lid = row["gaugelid"]
    issued = _utc(forecast["issuedTime"], "%Y-%m-%dT%H:%M:%SZ")
    generated = _utc(row["fcstissunc"], "%Y-%m-%d %H:%M:%S")
    max_time = _utc(row["fcsttime"], "%Y-%m-%d %H:%M:%S")
    threshold = _stage(metadata["flood"]["categories"]["major"]["stage"])
    if (metadata["lid"] != lid or metadata["state"]["abbreviation"] != row["state"]
            or metadata["flood"]["stageUnits"] != "ft" or threshold != _stage(row["major"])
            or metadata["status"]["forecast"]["floodCategory"] != "major"
            or metadata["status"]["forecast"]["primaryUnit"] != "ft"
            or forecast["primaryName"] != "Stage" or forecast["primaryUnits"] != "ft"
            or forecast["pedts"] != row["pedts"] or metadata["pedts"]["forecast"] != row["pedts"]
            or not now - MAX_SOURCE_AGE <= issued <= generated <= now):
        raise ValueError("nwps_forecast_identity_mismatch")
    rows = forecast.get("data")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 400:
        raise ValueError("nwps_forecast_series_invalid")
    points = [(_utc(point["validTime"], "%Y-%m-%dT%H:%M:%SZ"), _stage(point["primary"])) for point in rows]
    if (any(a[0] >= b[0] for a, b in zip(points, points[1:]))
            or any(_utc(point["generatedTime"], "%Y-%m-%dT%H:%M:%SZ") != generated for point in rows)
            or (max_time, _stage(row["forecast"])) not in points):
        raise ValueError("nwps_forecast_index_disagrees")
    first_major = next((point for point in points if point[1] >= threshold), None)
    if first_major is None or not now < first_major[0] <= now + HORIZON:
        raise ValueError("nwps_no_future_major_stage")
    impacts = [impact["statement"] for impact in metadata["flood"].get("impacts", [])
               if isinstance(impact, dict) and impact.get("stage") == threshold
               and isinstance(impact.get("statement"), str) and 0 < len(impact["statement"]) <= 600]
    return MajorRiverForecast(lid, _name(metadata["name"]), _name(metadata["state"]["name"]),
                              issued, first_major[0], first_major[1], threshold,
                              impacts[0] if len(impacts) == 1 else None,
                              {field: row[field] for field in INDEX_FIELDS.split(",")})


def read_gauge_forecast(row: dict, *, read_json: Callable[..., dict] = _read_json) -> tuple[dict, dict]:
    lid = row.get("gaugelid")
    if not isinstance(lid, str) or re.fullmatch(r"[A-Z0-9]{5}", lid) is None:
        raise ValueError("nwps_gauge_id_invalid")
    url = f"{GAUGES_URL}/{lid}"
    return read_json(url), read_json(url + "/stageflow/forecast")


def fetch_major_forecasts(now: datetime, *, read_json: Callable[..., dict] = _read_json,
                          captures: dict[str, dict] | None = None) -> tuple[int, list[MajorRiverForecast]]:
    """One nationwide shortlist and at most two exact gauge/forecast pairs."""
    index = read_json(INDEX_URL, params={
        "where": "status='major'", "outFields": INDEX_FIELDS, "returnGeometry": "false",
        "resultRecordCount": MAX_INDEX_ROWS + 1, "orderByFields": "gaugelid ASC", "f": "json",
    })
    shortlist = _index(index, now)
    qualified = []
    for row in shortlist[:MAX_DETAIL_GAUGES]:
        try:
            metadata, forecast = read_gauge_forecast(row, read_json=read_json)
            event = verify_major_forecast(row, metadata, forecast, now)
            qualified.append(event)
            if captures is not None:
                captures[event.lid] = {"metadata": deepcopy(metadata), "forecast": deepcopy(forecast),
                                       "checked_at": now.isoformat(), "synthetic": False}
        except (RequestException, KeyError, TypeError, ValueError, OverflowError):
            continue
    return len(shortlist), qualified
