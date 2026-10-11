"""Bounded, dated CAMS forecast samples; not observed exposure or source authentication."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import math
import re
from statistics import mean
from typing import Any, NoReturn, TypeGuard
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.data.source_status import SourceFetchError

SOURCE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
PRODUCT = "open-meteo-cams-air-quality-auto"
SOURCE_NAME = "CAMS air-quality forecast via Open-Meteo (automatic domain)"
LIMIT = 32_768
VARIABLES = ("pm2_5", "pm10", "dust", "aerosol_optical_depth", "us_aqi")
UNITS = dict(pm2_5="μg/m³", pm10="μg/m³", dust="μg/m³",
             aerosol_optical_depth="dimensionless", us_aqi="US AQI")
METHOD = "Mean or maximum of 24 instantaneous hourly forecast samples on a local calendar day"
LIMITS = (
    "Model forecast samples, not station measurements or a measured exposure. "
    "Automatic domain selection does not identify the exact model/run or resolution. "
    "Co-reported dust and PM10 do not establish an event-specific causal attribution."
)
_KEYS = {
    "schema_version", "source_product", "source_url", "domain_selection", "evidence_type",
    "requested_location", "grid_location", "date", "timezone", "utc_offset_seconds",
    "requested_at", "retrieved_at", "valid_start", "valid_end", "hours", "series", "method",
}


def reject(code: str) -> NoReturn:
    raise SourceFetchError(f"air_quality window rejected: {code}")


def _number(value: Any) -> TypeGuard[int | float]:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value
    ):
        raise ValueError("invalid UTC timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _encoded(value: Any) -> bytes:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    if len(raw) > LIMIT:
        reject("packet_size")
    return raw


def _bounds(day: str, timezone: str, offset: int) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or len(timezone) > 128:
        raise ValueError("invalid day or timezone")
    parsed = date.fromisoformat(day)
    zone = ZoneInfo(timezone)
    start = datetime.combine(parsed, datetime.min.time(), zone)
    end = datetime.combine(parsed + timedelta(days=1), datetime.min.time(), zone)
    if type(offset) is not int or start.utcoffset() != timedelta(seconds=offset):
        raise ValueError("inconsistent offset")
    a, b = start.astimezone(UTC), end.astimezone(UTC)
    if b - a != timedelta(hours=24):
        raise ValueError("not a 24-hour day")
    return a.isoformat().replace("+00:00", "Z"), b.isoformat().replace("+00:00", "Z")


def _series(values: Any, unit: Any, key: str) -> dict:
    normalized = unit.replace("µ", "μ") if isinstance(unit, str) and len(unit) <= 32 else None
    accepted = {UNITS[key]}
    if key == "aerosol_optical_depth":
        accepted.add("")
    if key == "us_aqi":
        accepted.add("USAQI")
    status = "complete"
    if values is None:
        status = "missing"
    elif (type(values) is not list or len(values) != 24 or normalized not in accepted
          or any(v is not None and (not _number(v) or v < 0) for v in values)):
        status = "invalid"
    elif any(v is None for v in values):
        status = "incomplete"
    return {"status": status, "unit": UNITS[key],
            "values": deepcopy(values) if status in {"complete", "incomplete"} else None}


def build_window(data: dict, *, city: str, country: str, lat: float, lon: float,
                 day: str, requested_at: str, retrieved_at: str) -> dict:
    """Select exactly the requested local day without filling or re-dating gaps."""
    try:
        hourly, units = data["hourly"], data["hourly_units"]
        if hourly["time"] != [f"{day}T{hour:02d}:00" for hour in range(24)]:
            raise ValueError("incomplete requested day")
        start, end = _bounds(day, data["timezone"], data["utc_offset_seconds"])
        core = dict(
            schema_version=1, source_product=PRODUCT, source_url=SOURCE_URL,
            domain_selection="auto", evidence_type="model_forecast", method=METHOD,
            requested_location=dict(city=city, country=country, lat=lat, lon=lon),
            grid_location=[data["latitude"], data["longitude"]], date=day,
            timezone=data["timezone"], utc_offset_seconds=data["utc_offset_seconds"],
            requested_at=requested_at, retrieved_at=retrieved_at, valid_start=start, valid_end=end,
            hours=deepcopy(hourly["time"]),
            series={key: _series(hourly.get(key), units.get(key), key) for key in VARIABLES},
        )
        packet = {**core, "selected_record_sha256": hashlib.sha256(_encoded(core)).hexdigest()}
        validate_window(packet)
        return packet
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError,
            ZoneInfoNotFoundError):
        reject("source_shape_or_time")
    raise AssertionError("unreachable")


def validate_window(packet: Any) -> dict[str, float | int | None]:
    """Recompute available aggregates from an internally consistent selected record."""
    try:
        if type(packet) is not dict or set(packet) != _KEYS | {"selected_record_sha256"}:
            raise ValueError
        _encoded(packet)
        core = {k: packet[k] for k in _KEYS}
        if hashlib.sha256(_encoded(core)).hexdigest() != packet["selected_record_sha256"]:
            raise ValueError
        if (type(core["schema_version"]) is not int or core["schema_version"] != 1
                or core["source_product"] != PRODUCT or core["source_url"] != SOURCE_URL
                or core["domain_selection"] != "auto" or core["evidence_type"] != "model_forecast"
                or core["method"] != METHOD):
            raise ValueError
        requested, retrieved = _utc(core["requested_at"]), _utc(core["retrieved_at"])
        if requested.date().isoformat() != core["date"] or not requested <= retrieved <= requested + timedelta(days=2):
            raise ValueError
        if (core["valid_start"], core["valid_end"]) != _bounds(
            core["date"], core["timezone"], core["utc_offset_seconds"]
        ):
            raise ValueError
        if core["hours"] != [f"{core['date']}T{hour:02d}:00" for hour in range(24)]:
            raise ValueError
        location, grid = core["requested_location"], core["grid_location"]
        if type(location) is not dict or set(location) != {"city", "country", "lat", "lon"}:
            raise ValueError
        if any(type(location[k]) is not str or not 0 < len(location[k].strip()) <= 160 for k in ("city", "country")):
            raise ValueError
        if type(grid) is not list or len(grid) != 2:
            raise ValueError
        for point in ([location["lat"], location["lon"]], grid):
            if not all(_number(v) for v in point) or not -90 <= point[0] <= 90 or not -180 <= point[1] <= 180:
                raise ValueError
        series = core["series"]
        if type(series) is not dict or set(series) != set(VARIABLES):
            raise ValueError
        totals: dict[str, float | int | None] = {}
        for key, entry in series.items():
            if type(entry) is not dict or set(entry) != {"status", "unit", "values"} or entry["unit"] != UNITS[key]:
                raise ValueError
            status, values = entry["status"], entry["values"]
            if status in {"missing", "invalid"}:
                if values is not None:
                    raise ValueError
                totals[key] = None
                continue
            expected = _series(values, entry["unit"], key)
            if status not in {"complete", "incomplete"} or _encoded(entry) != _encoded(expected):
                raise ValueError
            value = (mean(values) if key in {"pm2_5", "pm10"} else max(values)) if status == "complete" else None
            totals[key] = int(round(value)) if key == "us_aqi" and value is not None else value
        return totals
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError,
            ZoneInfoNotFoundError):
        reject("record_binding")
    raise AssertionError("unreachable")
