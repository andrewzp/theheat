"""Pure retained-cell contract for bounded inland IMERG discovery.

The map table provides cartographic context. Source agreement, required checks
and publication authority are independent; a matching digest grants none of them.
No HDF5, NumPy, provider client or source fetch is imported here.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import json
import math
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType

from src.data.places import _registry_text
from src.data.json_evidence import fingerprint
from src.data.rainfall_supply import _accumulation_bounds
from src.two_bot.types import StoryBundle

KIND = "satellite_precipitation_report"
SCHEMA = "nasa-imerg-late-daily-grid-cell-v1"
EVENT_PREFIX = "rain_report_imerg_cell_"
SOURCE_URL = "https://gpm.nasa.gov/data/imerg"
TABLE_SHA256 = "b863cd2dabb132da6dbda68d75c3649d68b8f95cf5768da9ea719a9c9f84ea16"
MAP_SHA256 = "6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f"
TABLE_BYTES = 89475
MAX_AGE = timedelta(hours=36)
UNITS = frozenset({"mm/day", "mm/d", "mm day-1", "mm d-1"})
FIELDS = frozenset({"schema", "source_url", "source_product", "product_version", "source_date",
                   "source_time_utc", "source_units", "column", "row", "mm_per_day",
                   "valid_half_hours", "source_file_sha256", "geography_sha256"})
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class GridHeld(ValueError):
    """Fixed diagnostic code; never provider prose, credentials or file contents."""


def require(condition, code):
    if not condition:
        raise GridHeld(code)


def clock(now=None):
    value = now() if callable(now) else now
    value = datetime.now(UTC) if value is None else value
    require(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
            "rainfall_grid_clock_invalid")
    return value.astimezone(UTC)


def _regular_bytes(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as reader:
        metadata = os.fstat(reader.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_size == TABLE_BYTES,
                "rainfall_grid_geography_unavailable")
        return reader.read(TABLE_BYTES + 1)


def _table_bytes() -> bytes:
    registry = files(__package__).joinpath("registry")
    resource = registry.joinpath("geography", "imerg_country_tiles_v1.json")
    try:
        if registry.is_dir():
            # A corrupt embedded asset never falls back to the host checkout.
            require(resource.is_file(), "rainfall_grid_geography_unavailable")
            if isinstance(resource, Path):
                raw = _regular_bytes(resource)
            else:
                with resource.open("rb") as reader:
                    raw = reader.read(TABLE_BYTES + 1)
        else:
            path = Path(__file__).resolve().parents[2] / "data/geography/imerg_country_tiles_v1.json"
            raw = _regular_bytes(path)
    except OSError as exc:
        raise GridHeld("rainfall_grid_geography_unavailable") from exc
    require(len(raw) == TABLE_BYTES and sha256(raw).hexdigest() == TABLE_SHA256,
            "rainfall_grid_geography_identity_changed")
    return raw


@lru_cache(maxsize=1)
def _decode_table(raw: bytes) -> tuple[Mapping[tuple[int, int], str], str]:
    document = json.loads(raw)
    require(document["schema"] == "theheat.imerg-cartographic-tiles/v1"
            and document["source"]["sha256"] == MAP_SHA256
            and document["tile_degrees"] == 1 and document["angular_margin_degrees"] == .5
            and document["latitude_band"] == [-60, 60], "rainfall_grid_geography_invalid")
    rows = document["tiles"]
    require(type(rows) is list and 0 < len(rows) <= 43200, "rainfall_grid_geography_invalid")
    table = {}
    for item in rows:
        require(type(item) is list and len(item) == 3, "rainfall_grid_geography_invalid")
        x, y, code = item
        require(type(x) is int and type(y) is int and 0 <= x < 360 and 30 <= y < 150
                and type(code) is str and re.fullmatch(r"[A-Z]{2}", code) is not None
                and (x, y) not in table, "rainfall_grid_geography_invalid")
        table[x, y] = code
    return MappingProxyType(table), document["country_names_sha256"]


def geography() -> tuple[Mapping[tuple[int, int], str], dict[str, str]]:
    # Reread/pin bytes before any cache hit: a changed source file cannot retain
    # an old eligibility result. The cached value is immutable pure decoding.
    table, expected_names = _decode_table(_table_bytes())
    raw_names = _registry_text("country_names.json").encode()
    require(sha256(raw_names).hexdigest() == expected_names, "rainfall_grid_region_names_changed")
    names = json.loads(raw_names)["names"]
    require(all(code in names for code in table.values()), "rainfall_grid_region_unqualified")
    return table, names


def region(column: int, row: int) -> tuple[str, str]:
    require(type(column) is int and type(row) is int and 0 <= column < 3600 and 0 <= row < 1800,
            "rainfall_grid_cell_invalid")
    table, names = geography()
    code = table.get((column // 10, row // 10))
    require(code is not None, "rainfall_grid_region_unqualified")
    assert code is not None
    return code, names[code]


def coordinates(column: int, row: int) -> tuple[float, float]:
    return round(-89.95 + row * .1, 2), round(-179.95 + column * .1, 2)


def is_family(value) -> bool:
    payload = value if isinstance(value, Mapping) else value.to_dict()
    raw = payload.get("raw_signal_dump")
    evidence = raw.get("evidence") if isinstance(raw, Mapping) else None
    return (str(payload.get("event_id", "")).startswith(EVENT_PREFIX)
            or isinstance(raw, Mapping) and raw.get("report_schema") == SCHEMA
            or isinstance(evidence, Mapping) and evidence.get("schema") == SCHEMA)


def validate_evidence(evidence, *, now=None):
    require(type(evidence) is dict and evidence.keys() == FIELDS, "rainfall_grid_evidence_invalid")
    require(evidence["schema"] == SCHEMA and evidence["source_url"] == SOURCE_URL
            and evidence["source_product"] == "late" and evidence["product_version"] == "V07C",
            "rainfall_grid_source_identity_changed")
    require(evidence["geography_sha256"] == TABLE_SHA256, "rainfall_grid_geography_identity_changed")
    value = evidence["mm_per_day"]
    require(type(value) in (int, float), "rainfall_grid_number_invalid")
    try:
        valid = math.isfinite(value) and 150 <= value <= 1000
    except OverflowError:
        valid = False
    require(valid, "rainfall_grid_outside_automatic_range")
    require(type(evidence["valid_half_hours"]) is int and evidence["valid_half_hours"] == 48
            and type(evidence["source_units"]) is str and evidence["source_units"] in UNITS,
            "rainfall_grid_complete_day_unqualified")
    digest = evidence["source_file_sha256"]
    require(type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest) is not None,
            "rainfall_grid_source_identity_changed")
    try:
        day = date.fromisoformat(evidence["source_date"])
        require(day.isoformat() == evidence["source_date"], "rainfall_grid_day_invalid")
        moment = datetime.fromisoformat(evidence["source_time_utc"].replace("Z", "+00:00"))
        require(moment.utcoffset() == timedelta(0) and moment.date() == day
                and moment.isoformat().replace("+00:00", "Z") == evidence["source_time_utc"],
                "rainfall_grid_day_invalid")
        _start, end = _accumulation_bounds(day, 1)
        age = clock(now) - datetime.fromisoformat(end.replace("Z", "+00:00"))
        require(timedelta(0) <= age <= MAX_AGE, "rainfall_completed_window_expired")
    except (TypeError, ValueError, OverflowError, AttributeError) as exc:
        if isinstance(exc, GridHeld):
            raise
        raise GridHeld("rainfall_grid_day_invalid") from exc
    region(evidence["column"], evidence["row"])
    return deepcopy(evidence)


def _bundle(evidence):
    code, name = region(evidence["column"], evidence["row"])
    latitude, longitude = coordinates(evidence["column"], evidence["row"])
    day = date.fromisoformat(evidence["source_date"])
    start, end = _accumulation_bounds(day, 1)
    value = round(evidence["mm_per_day"], 1)
    event = f"{EVENT_PREFIX}{evidence['column']}_{evidence['row']}_{day.isoformat()}"
    window = {"schema": "theheat.rainfall-window/v1", "domain": "precipitation",
              "evidence_type": "satellite_derived", "source_product": "IMERG Late daily (3IMERGDL)",
              "product_version": "V07", "accumulation_start": start, "accumulation_end": end,
              "integration_interval_hours": 24, "unit": "mm", "retrieved_at": None,
              "retrieved_at_known": False,
              "footprint": {"kind": "grid_cell", "resolution_deg": .1,
                            "center": [latitude, longitude], "members": 1},
              "limit": "One satellite grid cell in an inland cartographic region; no national total or gauge."}
    facts = {"map_region": name, "map_region_code": code, "latitude": latitude, "longitude": longitude,
             "precipitation_mm": value, "source_date_utc": f"{day.day} {MONTHS[day.month - 1]}",
             "accumulation_start": start, "accumulation_end": end, "period_hours": 24,
             "valid_half_hour_slots": 48, "evidence_type": "satellite_derived",
             "source_product": "IMERG Late daily V07C", "quantity_basis": "Liquid-water-equivalent depth",
             "precipitation_phase": "Not established by this estimate",
             "geographic_scope": "One 0.1-degree grid cell; cartographic regional context, not an area total",
             "public_source_url": SOURCE_URL}
    return StoryBundle(KIND, f"{name}: satellite grid cell ({latitude:.2f}, {longitude:.2f})", end, event,
        {"label": "daily_satellite_precipitation_mm", "value": value, "unit": "mm"},
        [{"label": key, "value": value} for key, value in facts.items()],
        historical_context={"scope": "One completed day; no historical or country-wide comparator"},
        raw_signal_dump={"report_schema": SCHEMA, "evidence": deepcopy(evidence), "rainfall_window": window},
        country=code)


def build_bundle(evidence, *, now=None):
    return _bundle(validate_evidence(evidence, now=now))


def validate_bundle(value, *, now=None):
    payload = value if isinstance(value, Mapping) else value.to_dict()
    raw = payload.get("raw_signal_dump")
    evidence = raw.get("evidence") if isinstance(raw, Mapping) else None
    validated = validate_evidence(evidence, now=now)
    try:
        unchanged = (fingerprint(payload, profile="rainfall-grid-bundle-v1")
                     == fingerprint(_bundle(validated).to_dict(), profile="rainfall-grid-bundle-v1"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise GridHeld("rainfall_bundle_changed") from exc
    require(unchanged, "rainfall_bundle_changed")
    return validated


def cell_identity(value) -> tuple[str, int, int]:
    """Identity only, never qualification, review or a source verdict."""
    payload = value if isinstance(value, Mapping) else value.to_dict()
    evidence = payload["raw_signal_dump"]["evidence"]
    return evidence["source_date"], evidence["column"], evidence["row"]
