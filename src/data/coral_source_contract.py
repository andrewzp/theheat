"""Bounded CRW DHW point inputs and receipts; hashes bind, not certify, a source."""

from __future__ import annotations

from copy import deepcopy
import csv
from datetime import UTC, datetime
import hashlib
import io
import json
import math
import re
from typing import Any, NoReturn

from src.data.source_status import SourceFetchError

PRODUCT = "noaa-crw-dhw-v3.1"
PRODUCT_NAME = "NOAA Coral Reef Watch daily 5km DHW v3.1"
METADATA_URL = "https://coastwatch.noaa.gov/erddap/info/noaacrwdhwDaily/index.json"
CSV_BASE = "https://coastwatch.noaa.gov/erddap/griddap/noaacrwdhwDaily.csv"
METADATA_LIMIT = 1_048_576
CSV_LIMIT = 8192
MAX_AGE_DAYS = 7
UNIT = "degree_Celsius_weeks"
METHOD = "nearest grid point; accumulated DHW over preceding 12 weeks"
_METADATA_KEYS = {
    "metadata_url",
    "response_sha256",
    "response_bytes",
    "retrieved_at",
    "first_product_time",
    "last_product_time",
}
_RECEIPT_KEYS = {
    "schema_version",
    "source_product",
    "source_name",
    "source_leg",
    "evidence_type",
    "region_id",
    "region_full_name",
    "requested_point",
    "sampled_point",
    "source_url",
    "response_sha256",
    "response_bytes",
    "retrieved_at",
    "product_timestamp",
    "valid_date",
    "dhw_value",
    "unit",
    "native_grid_degrees",
    "method",
    "metadata",
}


def reject(reason: str) -> NoReturn:
    raise SourceFetchError(f"coral_dhw point source contract: {reason}")


def product_time(value: Any) -> datetime:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        reject("invalid UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        reject("invalid UTC timestamp")


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def point_url(lat: float, lon: float, timestamp: str) -> str:
    product_time(timestamp)
    return f"{CSV_BASE}?degree_heating_week%5B({timestamp})%5D%5B({lat})%5D%5B({lon})%5D"


def _digest(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _count(value: Any, limit: int) -> bool:
    return type(value) is int and 0 < value <= limit


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _metadata_valid(meta: Any) -> bool:
    return (
        type(meta) is dict
        and set(meta) == _METADATA_KEYS
        and meta["metadata_url"] == METADATA_URL
        and _digest(meta["response_sha256"])
        and _count(meta["response_bytes"], METADATA_LIMIT)
        and product_time(meta["first_product_time"])
        <= product_time(meta["last_product_time"])
        <= product_time(meta["retrieved_at"])
    )


def _fresh(timestamp: str, retrieved_at: str, max_age_days: int) -> None:
    stamp, retrieved = product_time(timestamp), product_time(retrieved_at)
    if (
        retrieved > datetime.now(UTC)
        or stamp > retrieved
        or not 0 <= (retrieved.date() - stamp.date()).days <= max(max_age_days, MAX_AGE_DAYS)
    ):
        reject("product outside allowed time window")


def _unique_object(pairs: list) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            reject("duplicate JSON key")
        result[key] = value
    return result


def decode_metadata(body: bytes, *, retrieved_at: str, max_age_days: int) -> dict:
    if type(body) is not bytes or not 0 < len(body) <= METADATA_LIMIT:
        reject("metadata byte limit")
    try:
        table = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: reject("non-finite JSON constant"),
        )["table"]
        if table["columnNames"] != [
            "Row Type",
            "Variable Name",
            "Attribute Name",
            "Data Type",
            "Value",
        ]:
            reject("metadata columns")
        if type(table["rows"]) is not list:
            reject("metadata rows")
        attributes = {}
        for row in table["rows"]:
            if type(row) is not list or len(row) != 5 or not all(type(v) is str for v in row):
                reject("metadata row")
            if row[0] == "attribute":
                key = (row[1], row[2])
                if key in attributes:
                    reject("duplicate metadata attribute")
                attributes[key] = row[4]
        expected = {
            ("NC_GLOBAL", "id"): "Satellite_Daily_Global_5km_Degree_Heating_Week",
            ("NC_GLOBAL", "product_version"): "3.1",
            (
                "NC_GLOBAL",
                "processing_level",
            ): "Derived from L4 satellite sea surface temperaure analysis",
            ("latitude", "units"): "degrees_north",
            ("longitude", "units"): "degrees_east",
            ("degree_heating_week", "units"): UNIT,
        }
        if any(attributes.get(k) != v for k, v in expected.items()):
            reject("dataset identity or units")
        numeric = {
            ("degree_heating_week", "valid_min"): 0.0,
            ("degree_heating_week", "valid_max"): 100.0,
            ("degree_heating_week", "_FillValue"): -327.68,
            ("NC_GLOBAL", "geospatial_lat_resolution"): 0.05,
            ("NC_GLOBAL", "geospatial_lon_resolution"): 0.05,
            ("latitude", "valid_min"): -89.975,
            ("latitude", "valid_max"): 89.975,
            ("longitude", "valid_min"): -179.975,
            ("longitude", "valid_max"): 179.975,
        }
        if any(
            not math.isclose(float(attributes[k]), v, rel_tol=0, abs_tol=1e-10)
            for k, v in numeric.items()
        ):
            reject("dataset range or grid")
        meta = {
            "metadata_url": METADATA_URL,
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "response_bytes": len(body),
            "retrieved_at": retrieved_at,
            "first_product_time": attributes[("NC_GLOBAL", "time_coverage_start")],
            "last_product_time": attributes[("NC_GLOBAL", "time_coverage_end")],
        }
        if not _metadata_valid(meta):
            reject("metadata receipt")
        _fresh(meta["last_product_time"], retrieved_at, max_age_days)
        return meta
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        reject("malformed metadata")


def _point_valid(point: Any, requested: list) -> bool:
    if type(point) is not list or len(point) != 2 or not all(_number(v) for v in point):
        return False
    for value, target, origin, upper in zip(
        point, requested, [-89.975, -179.975], [89.975, 179.975]
    ):
        if (
            not origin <= value <= upper
            or abs(value - target) > 0.0251
            or abs(value - (origin + round((value - origin) / 0.05) * 0.05)) > 1e-4
        ):
            return False
    return True


def decode_point(
    body: bytes, station: Any, *, metadata: dict, retrieved_at: str, max_age_days: int
) -> dict:
    """Validate all supplied bytes before creating a compact, detached receipt."""
    if type(body) is not bytes or not 0 < len(body) <= CSV_LIMIT:
        reject("CSV byte limit")
    try:
        if not _metadata_valid(metadata) or product_time(metadata["retrieved_at"]) > product_time(
            retrieved_at
        ):
            reject("metadata receipt chronology")
        rows = list(csv.reader(io.StringIO(body.decode("utf-8")), strict=True))
        if len(rows) < 2 or rows[:2] != [
            ["time", "latitude", "longitude", "degree_heating_week"],
            ["UTC", "degrees_north", "degrees_east", UNIT],
        ]:
            reject("CSV columns or units")
        data = [row for row in rows[2:] if row]
        if len(data) != 1 or len(data[0]) != 4:
            reject("CSV requires exactly one point row")
        stamp, lat, lon, value = data[0]
        if stamp != metadata["last_product_time"]:
            reject("point time differs from pinned metadata time")
        _fresh(stamp, retrieved_at, max_age_days)
        requested = [station.lat, station.lon]
        sampled = [float(lat), float(lon)]
        if not _point_valid(sampled, requested):
            reject("invalid, remote or off-grid point")
        dhw = float(value)
        if not math.isfinite(dhw):
            reject("non-finite DHW")
        if not 0 <= dhw <= 100:
            reject("DHW outside valid range")
        return {
            "schema_version": 1,
            "source_product": PRODUCT,
            "source_name": PRODUCT_NAME,
            "source_leg": "crw_erddap",
            "evidence_type": "satellite_analysis",
            "region_id": station.region_id,
            "region_full_name": station.region_full_name,
            "requested_point": requested,
            "sampled_point": sampled,
            "source_url": point_url(station.lat, station.lon, stamp),
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "response_bytes": len(body),
            "retrieved_at": retrieved_at,
            "product_timestamp": stamp,
            "valid_date": stamp[:10],
            "dhw_value": dhw,
            "unit": UNIT,
            "native_grid_degrees": 0.05,
            "method": METHOD,
            "metadata": deepcopy(metadata),
        }
    except (KeyError, TypeError, ValueError, UnicodeError, csv.Error, OverflowError):
        reject("malformed point response")


def qualified_provenance(event: Any) -> bool:
    """Validate receipt binding, not authenticity of independently supplied input."""
    from src.data.coral_dhw import CRW_ERDDAP_STATIONS, SOURCE_NAME

    p = getattr(event, "provenance", None)
    try:
        station = CRW_ERDDAP_STATIONS.get(event.region_id)
        if station is None or type(p) is not dict or set(p) != _RECEIPT_KEYS:
            return False
        meta = p["metadata"]
        stamp, retrieved = product_time(p["product_timestamp"]), product_time(p["retrieved_at"])
        return bool(
            type(p["schema_version"]) is int
            and p["schema_version"] == 1
            and p["source_product"] == PRODUCT
            and p["source_name"] == PRODUCT_NAME
            and p["source_leg"] == event.source_leg == "crw_erddap"
            and event.source_name == SOURCE_NAME
            and p["evidence_type"] == "satellite_analysis"
            and p["region_id"] == station.region_id
            and p["region_full_name"] == event.region_full_name == station.region_full_name
            and p["requested_point"] == [station.lat, station.lon]
            and type(p["requested_point"]) is list
            and all(_number(v) for v in p["requested_point"])
            and _point_valid(p["sampled_point"], p["requested_point"])
            and p["sampled_point"] == [event.lat, event.lon]
            and _number(event.lat)
            and _number(event.lon)
            and p["source_url"] == point_url(station.lat, station.lon, p["product_timestamp"])
            and _digest(p["response_sha256"])
            and _count(p["response_bytes"], CSV_LIMIT)
            and p["valid_date"] == event.date == stamp.date().isoformat()
            and _number(p["dhw_value"])
            and 0 <= p["dhw_value"] <= 100
            and _number(event.dhw_value)
            and p["dhw_value"] == event.dhw_value
            and p["unit"] == UNIT
            and p["method"] == METHOD
            and type(p["native_grid_degrees"]) is float
            and p["native_grid_degrees"] == 0.05
            and _metadata_valid(meta)
            and meta["last_product_time"] == p["product_timestamp"]
            and stamp <= product_time(meta["retrieved_at"]) <= retrieved <= datetime.now(UTC)
        )
    except (TypeError, KeyError, ValueError, AttributeError, OverflowError, SourceFetchError):
        return False
