"""Invented complete NOAA-shaped inputs, never recovered observations."""

from datetime import UTC, datetime, timedelta
import json

from src.data import coral_source_contract as contract
from src.data import coral_dhw


def timestamp(days=1):
    day = datetime.now(UTC).date() - timedelta(days=days)
    return f"{day.isoformat()}T12:00:00Z"


def metadata_bytes(stamp=None):
    attrs = {
        ("NC_GLOBAL", "id"): "Satellite_Daily_Global_5km_Degree_Heating_Week",
        ("NC_GLOBAL", "product_version"): "3.1",
        (
            "NC_GLOBAL",
            "processing_level",
        ): "Derived from L4 satellite sea surface temperaure analysis",
        ("NC_GLOBAL", "time_coverage_start"): "1985-03-25T12:00:00Z",
        ("NC_GLOBAL", "time_coverage_end"): stamp or timestamp(),
        ("NC_GLOBAL", "geospatial_lat_resolution"): "0.05",
        ("NC_GLOBAL", "geospatial_lon_resolution"): "0.049999999999999996",
        ("latitude", "units"): "degrees_north",
        ("longitude", "units"): "degrees_east",
        ("latitude", "valid_min"): "-89.975",
        ("latitude", "valid_max"): "89.975",
        ("longitude", "valid_min"): "-179.975",
        ("longitude", "valid_max"): "179.975",
        ("degree_heating_week", "units"): "degree_Celsius_weeks",
        ("degree_heating_week", "valid_min"): "0.0",
        ("degree_heating_week", "valid_max"): "100.0",
        ("degree_heating_week", "_FillValue"): "-327.68",
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
                    ["attribute", variable, name, "String", value]
                    for (variable, name), value in attrs.items()
                ],
            }
        }
    ).encode()


def metadata(stamp=None):
    return contract.decode_metadata(
        metadata_bytes(stamp), retrieved_at=contract.now_utc(), max_age_days=5
    )


def csv_bytes(value=8.3, stamp=None, lat=-16.075, lon=145.975):
    return (
        "time,latitude,longitude,degree_heating_week\n"
        "UTC,degrees_north,degrees_east,degree_Celsius_weeks\n"
        f"{stamp or timestamp()},{lat},{lon},{value}\n"
    ).encode()


def reading(value=8.3):
    meta = metadata()
    return coral_dhw._reading_from_erddap_csv(
        csv_bytes(value, meta["last_product_time"]),
        coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"],
        max_age_days=5,
        metadata=meta,
        retrieved_at=contract.now_utc(),
    )
