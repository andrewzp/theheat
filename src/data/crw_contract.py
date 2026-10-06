"""Coherent NOAA CRW samples and their bounded provenance, not record claims."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
from io import StringIO
import json
import math
import re
from typing import Any, NoReturn

from src.data.source_status import SourceFetchError

PRODUCT = "noaa-crw-ssta-v3.1"
PRODUCT_NAME = "NOAA Coral Reef Watch daily 5km SST anomaly v3.1"
METADATA_URL = "https://coastwatch.noaa.gov/erddap/info/noaacrwsstanomalyDaily/index.json"
CSV_BASE = "https://coastwatch.noaa.gov/erddap/griddap/noaacrwsstanomalyDaily.csv"
METHOD = "cos-latitude-weighted mean of valid strided sample cells"
CSV_LIMIT = 1_048_576
NETCDF_LIMIT = 67_108_864
LISTING_LIMIT = 2_097_152
CELL_TOLERANCE = 0.0251


def reject(reason: str) -> NoReturn:
    raise SourceFetchError(f"ocean_sst_anomaly schema drift: {reason}")


def product_time(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        reject("invalid product time")


def fresh_day(value: str, today: date | None) -> None:
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        reject("invalid product date")
    age = ((today or datetime.now(UTC).date()) - parsed).days
    if age < 0 or age > 5:
        raise SourceFetchError(
            "ocean_sst_anomaly freshness check failed: product outside allowed date window"
        )


def metadata_contract(body: bytes) -> dict:
    """Validate the current primary dataset once per collection, before CSVs."""
    try:
        table = json.loads(body)["table"]
        if table["columnNames"] != [
            "Row Type",
            "Variable Name",
            "Attribute Name",
            "Data Type",
            "Value",
        ]:
            reject("metadata columns")
        attributes = {}
        for row in table["rows"]:
            if (
                not isinstance(row, list)
                or len(row) != 5
                or not all(isinstance(v, str) for v in row)
            ):
                reject("metadata row")
            if row[0] == "attribute":
                key = (row[1], row[2])
                if key in attributes:
                    reject("duplicate metadata attribute")
                attributes[key] = row[4]
        expected = {
            ("NC_GLOBAL", "id"): "Satellite_Daily_Global_5km_SST_Anomaly",
            ("NC_GLOBAL", "product_version"): "3.1",
            (
                "NC_GLOBAL",
                "processing_level",
            ): "Derived from L4 satellite sea surface temperaure analysis",
            ("latitude", "units"): "degrees_north",
            ("longitude", "units"): "degrees_east",
            ("sea_surface_temperature_anomaly", "units"): "degree_C",
        }
        if any(attributes.get(k) != v for k, v in expected.items()):
            reject("unrecognized dataset identity or units")
        start = attributes[("NC_GLOBAL", "time_coverage_start")]
        end = attributes[("NC_GLOBAL", "time_coverage_end")]
        if product_time(start) > product_time(end):
            reject("metadata time range")
        return dict(
            metadata_url=METADATA_URL,
            metadata_sha256=hashlib.sha256(body).hexdigest(),
            first_product_time=start,
            last_product_time=end,
        )
    except (ValueError, TypeError, KeyError, UnicodeError):
        reject("malformed dataset metadata")


@dataclass(frozen=True)
class CSVSample:
    timestamp: str
    cells: list[tuple[float, float]]
    total_cells: int
    sampled_bounds: list[float]


def decode_csv(text: str, region: Any | None = None) -> CSVSample:
    """Validate every row, including coordinates/time on excluded cells."""
    reader = csv.reader(StringIO(text), strict=True)
    try:
        if next(reader) != ["time", "latitude", "longitude", "sea_surface_temperature_anomaly"]:
            reject("CSV columns")
        if next(reader) != ["UTC", "degrees_north", "degrees_east", "degree_C"]:
            reject("CSV units")
        timestamp = None
        cells: list[tuple[float, float]] = []
        points: set[tuple[float, float]] = set()
        for row in reader:
            if not row:
                continue
            if len(row) != 4:
                reject("CSV row width")
            parsed_time = product_time(row[0])
            if timestamp is None:
                timestamp = parsed_time
            if timestamp != parsed_time:
                reject("mixed product times")
            lat, lon = float(row[1]), float(row[2])
            if (
                not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
            ):
                reject("invalid cell coordinate")
            if (lat, lon) in points:
                reject("duplicate sample cell")
            points.add((lat, lon))
            if len(points) > 20_000:
                reject("sample cell limit")
            if region is not None and not (
                region.lat_s - CELL_TOLERANCE <= lat <= region.lat_n + CELL_TOLERANCE
                and region.lon_w - CELL_TOLERANCE <= lon <= region.lon_e + CELL_TOLERANCE
            ):
                reject("cell outside requested region")
            value = float(row[3])
            if math.isinf(value):
                reject("infinite anomaly")
            if math.isnan(value) or value == -327.68 or not -15 <= value <= 15:
                continue
            cells.append((lat, value))
        if timestamp is None or not points:
            reject("empty sample")
        lats, lons = sorted({p[0] for p in points}), sorted({p[1] for p in points})
        if region is not None:
            for axis, low, high in (
                (lats, region.lat_s, region.lat_n),
                (lons, region.lon_w, region.lon_e),
            ):
                expected_count = math.floor((high - low) + 1e-6) + 1
                if (
                    len(axis) != expected_count
                    or abs(axis[0] - low) > CELL_TOLERANCE
                    or abs(axis[-1] - high) > CELL_TOLERANCE
                ):
                    reject("incomplete sample axis")
                if any(abs(b - a - 1.0) > 1e-4 for a, b in zip(axis, axis[1:])):
                    reject("sample stride mismatch")
            if len(points) != len(lats) * len(lons):
                reject("incomplete rectangular sample")
        return CSVSample(
            timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            cells,
            len(points),
            [lats[0], lats[-1], lons[0], lons[-1]],
        )
    except (ValueError, TypeError, StopIteration, csv.Error):
        reject("malformed CSV sample")


def provenance(
    *,
    body: bytes,
    url: str,
    retrieved_at: str,
    timestamp: str,
    region: Any,
    mean: float,
    valid_cells: int,
    total_cells: int,
    sampled_bounds: list[float],
    leg: str,
    metadata: dict | None = None,
) -> dict:
    return dict(
        schema_version=1,
        source_product=PRODUCT,
        source_name=PRODUCT_NAME,
        source_url=url,
        response_sha256=hashlib.sha256(body).hexdigest(),
        response_bytes=len(body),
        retrieved_at=retrieved_at,
        valid_date=timestamp[:10],
        product_timestamp=timestamp,
        evidence_type="satellite_analysis",
        source_leg=leg,
        region_slug=region.slug,
        region_display_name=region.display_name,
        requested_bounds=[region.lat_s, region.lat_n, region.lon_w, region.lon_e],
        sampled_bounds=sampled_bounds,
        native_grid_degrees=0.05,
        grid_stride=20,
        method=METHOD,
        unit="degree_C",
        mean_anomaly_c=mean,
        valid_cells=valid_cells,
        total_cells=total_cells,
        excluded_cells=total_cells - valid_cells,
        primary_metadata=metadata,
    )


def qualified_provenance(event: Any) -> bool:
    """Check binding only; a hash is not an independently certified source."""
    p = getattr(event, "provenance", None)
    if not isinstance(p, dict):
        return False
    try:
        from urllib.parse import urlsplit
        from src.data.ocean_sst_anomaly import REGION_REGISTRY, _build_url

        region = next((r for r in REGION_REGISTRY if r.slug == event.region_slug), None)
        if region is None or event.region_display_name != region.display_name:
            return False
        if p["requested_bounds"] != [region.lat_s, region.lat_n, region.lon_w, region.lon_e]:
            return False
        if not _sample_bounds_match(p, region, event.source_leg):
            return False
        stamp = product_time(p["product_timestamp"])
        retrieved = product_time(p["retrieved_at"])
        url = urlsplit(p["source_url"])
        leg = "noaa_star_nc" if event.source_leg == "noaa_star_nc" else "coastwatch_erddap"
        source_ok = (
            leg == "coastwatch_erddap"
            and event.source_leg is None
            and p["source_url"] == _build_url(region)
            and isinstance(p["primary_metadata"], dict)
            and p["primary_metadata"].get("metadata_url") == METADATA_URL
            and re.fullmatch(r"[0-9a-f]{64}", p["primary_metadata"].get("metadata_sha256", ""))
            and product_time(p["primary_metadata"]["first_product_time"])
            <= stamp
            <= product_time(p["primary_metadata"]["last_product_time"])
            and stamp <= product_time(p["primary_metadata"]["retrieved_at"]) <= retrieved
            and type(p["primary_metadata"]["response_bytes"]) is int
            and 0 < p["primary_metadata"]["response_bytes"] <= CSV_LIMIT
        ) or (
            leg == "noaa_star_nc"
            and p["source_url"]
            == (
                "https://www.star.nesdis.noaa.gov/pub/sod/mecb/crw/data/5km/v3.1_op/nc/v1.0/daily/ssta/"
                f"{event.date[:4]}/ct5km_ssta_v3.1_{event.date.replace('-', '')}.nc"
            )
        )
        return bool(
            source_ok
            and not url.username
            and not url.password
            and not url.fragment
            and type(p["schema_version"]) is int
            and p["schema_version"] == 1
            and p["source_product"] == PRODUCT
            and p["source_name"] == PRODUCT_NAME
            and p["source_leg"] == leg
            and p["evidence_type"] == "satellite_analysis"
            and p["region_slug"] == event.region_slug
            and p["region_display_name"] == event.region_display_name
            and p["valid_date"]
            == event.date
            == product_time(p["product_timestamp"]).date().isoformat()
            and retrieved >= stamp
            and p["unit"] == "degree_C"
            and p["method"] == METHOD
            and p["native_grid_degrees"] == 0.05
            and type(p["grid_stride"]) is int
            and p["grid_stride"] == 20
            and type(p["mean_anomaly_c"]) in (int, float)
            and math.isfinite(p["mean_anomaly_c"])
            and -15 <= p["mean_anomaly_c"] <= 15
            and p["mean_anomaly_c"] == event.anomaly_c
            and type(event.cells_used) is int
            and type(p["valid_cells"]) is int
            and p["valid_cells"] == event.cells_used
            and type(p["total_cells"]) is int
            and 10 <= p["valid_cells"] <= p["total_cells"] <= 20_000
            and type(p["excluded_cells"]) is int
            and p["excluded_cells"] == p["total_cells"] - p["valid_cells"]
            and type(p["response_bytes"]) is int
            and 0 < p["response_bytes"] <= (NETCDF_LIMIT if leg == "noaa_star_nc" else CSV_LIMIT)
            and re.fullmatch(r"[0-9a-f]{64}", p["response_sha256"])
            and all(
                isinstance(p[k], list)
                and len(p[k]) == 4
                and all(type(x) in (int, float) and math.isfinite(x) for x in p[k])
                for k in ("requested_bounds", "sampled_bounds")
            )
        )
    except (TypeError, KeyError, ValueError, SourceFetchError):
        return False


def _sample_bounds_match(p: dict, region: Any, source_leg: str | None) -> bool:
    """Recheck the registered integer-degree boxes and their sample size."""
    bounds = p["sampled_bounds"]
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
    ):
        return False
    if source_leg == "noaa_star_nc":
        # The descending latitude axis starts just inside the north edge;
        # longitude starts just inside the west edge. A stride of 20 ends
        # 0.975 degrees short of the opposite integer-degree edge.
        expected = [
            region.lat_s + 0.975,
            region.lat_n - 0.025,
            region.lon_w + 0.025,
            region.lon_e - 0.975,
        ]
        count = int(region.lat_n - region.lat_s) * int(region.lon_e - region.lon_w)
        return p["total_cells"] == count and all(
            abs(a - b) < 0.0001 for a, b in zip(bounds, expected)
        )
    expected = [region.lat_s, region.lat_n, region.lon_w, region.lon_e]
    count = (int(region.lat_n - region.lat_s) + 1) * (int(region.lon_e - region.lon_w) + 1)
    return p["total_cells"] == count and all(
        abs(a - b) <= CELL_TOLERANCE for a, b in zip(bounds, expected)
    )
