"""Invented CRW-shaped source bytes; no retained weather observations."""

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import Mock

from src.data import crw_contract as contract

DAY = "2026-06-14"
RETRIEVED = "2026-06-16T12:00:00Z"


def metadata_body() -> bytes:
    attrs = {
        ("NC_GLOBAL", "id"): "Satellite_Daily_Global_5km_SST_Anomaly",
        ("NC_GLOBAL", "product_version"): "3.1",
        (
            "NC_GLOBAL",
            "processing_level",
        ): "Derived from L4 satellite sea surface temperaure analysis",
        ("NC_GLOBAL", "time_coverage_start"): "1985-01-01T12:00:00Z",
        ("NC_GLOBAL", "time_coverage_end"): f"{DAY}T12:00:00Z",
        ("latitude", "units"): "degrees_north",
        ("longitude", "units"): "degrees_east",
        ("sea_surface_temperature_anomaly", "units"): "degree_C",
    }
    return json.dumps(
        {
            "table": {
                "columnNames": [
                    "Row Type",
                    "Variable Name",
                    "Attribute Name",
                    "Data Type",
                    "Value",
                ],
                "rows": [
                    ["attribute", name, key, "String", value]
                    for (name, key), value in attrs.items()
                ],
            }
        }
    ).encode()


def metadata_receipt() -> dict:
    body = metadata_body()
    return {
        **contract.metadata_contract(body),
        "response_bytes": len(body),
        "retrieved_at": RETRIEVED,
    }


def response(body: bytes | str, **overrides) -> Mock:
    raw = body.encode() if isinstance(body, str) else body
    result = Mock(status_code=200, headers={}, **overrides)
    result.iter_content.return_value = [raw]
    return result


def csv_body(region, *, day=DAY, value=3.6, selected=None, offset=0.025) -> bytes:
    # Default fills the complete requested strided rectangle with invented values.
    # Explicit selected points leave all other grid cells NaN for coverage tests.
    rows = [
        "time,latitude,longitude,sea_surface_temperature_anomaly",
        "UTC,degrees_north,degrees_east,degree_C",
    ]
    for lat in range(int(region.lat_n), int(region.lat_s) - 1, -1):
        for lon in range(int(region.lon_w), int(region.lon_e) + 1):
            val = selected.get((float(lat), float(lon)), "NaN") if selected is not None else value
            rows.append(f"{day}T12:00:00Z,{lat + offset},{lon + offset},{val}")
    return ("\n".join(rows) + "\n").encode()


def native_file(path, *, day=DAY, region=None, value=3.6):
    """Real compressed NetCDF encoding with global axes and invented local values."""
    import numpy as np
    from netCDF4 import Dataset
    from src.data.ocean_sst_anomaly import REGION_REGISTRY

    region = region or REGION_REGISTRY[-1]
    point = datetime.fromisoformat(day).replace(tzinfo=UTC)
    latitudes = np.linspace(89.975, -89.975, 3600, dtype="f4")
    longitudes = np.linspace(-179.975, 179.975, 7200, dtype="f4")
    with Dataset(path, "w") as ds:
        ds.id = "Satellite_Daily_Global_5km_SST_Anomaly"
        ds.product_version = "3.1"
        ds.processing_level = "Derived from L4 satellite sea surface temperaure analysis"
        ds.time_coverage_start = point.strftime("%Y%m%dT%H%M%SZ")
        ds.time_coverage_end = (point + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
        for name, size in (("time", 1), ("lat", 3600), ("lon", 7200)):
            ds.createDimension(name, size)
        time = ds.createVariable("time", "i4", ("time",))
        time.units = "seconds since 1981-01-01 00:00:00"
        time[:] = [(point + timedelta(hours=12) - datetime(1981, 1, 1, tzinfo=UTC)).total_seconds()]
        for name, values, unit in (
            ("lat", latitudes, "degrees_north"),
            ("lon", longitudes, "degrees_east"),
        ):
            axis = ds.createVariable(name, "f4", (name,))
            axis.units = unit
            axis[:] = values
        anomaly = ds.createVariable(
            "sea_surface_temperature_anomaly",
            "i2",
            ("time", "lat", "lon"),
            fill_value=-32768,
            zlib=True,
            chunksizes=(1, 100, 100),
        )
        anomaly.units = "degrees_Celsius"
        anomaly.scale_factor = 0.01
        anomaly.valid_min = np.int16(-1500)
        anomaly.valid_max = np.int16(1500)
        lat = np.flatnonzero((latitudes >= region.lat_s) & (latitudes <= region.lat_n))
        lon = np.flatnonzero((longitudes >= region.lon_w) & (longitudes <= region.lon_e))
        anomaly[0, lat[0] : lat[-1] + 1, lon[0] : lon[-1] + 1] = value
    return path


def quiet_sample(region):
    """Explicit invented quiet outcome for orchestration-only tests."""
    from src.data.ocean_sst_anomaly import RegionalSSTSample
    total = (int(region.lat_n - region.lat_s) + 1) * (int(region.lon_e - region.lon_w) + 1)
    return RegionalSSTSample(
        region.slug, "below_floor", "coastwatch_erddap", product_date=DAY,
        total_cells=total, valid_cells=total, excluded_cells=0,
    )


def sample_with_reading(reading):
    """Invented report only, not a source receipt or evidence qualification."""
    from src.data.ocean_sst_anomaly import RegionalSSTSample
    return RegionalSSTSample(
        reading.region_slug, "candidate", reading.source_leg or "coastwatch_erddap",
        product_date=reading.date, total_cells=reading.cells_used,
        valid_cells=reading.cells_used, excluded_cells=0, reading=reading,
    )


def quiet_collection(readings=()):
    """Explicitly stipulate valid quiet coverage in mocked runner tests."""
    from src.data.ocean_sst_anomaly import REGION_REGISTRY, RegionalSSTCollection, RegionalSSTResult
    by_slug = {reading.region_slug: sample_with_reading(reading) for reading in readings}
    samples = [by_slug.get(region.slug) or quiet_sample(region) for region in REGION_REGISTRY]
    return RegionalSSTCollection(tuple(RegionalSSTResult(sample, sample) for sample in samples))
