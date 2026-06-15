"""Per-region SST anomaly detection via NOAA Coral Reef Watch gridded anomaly.

Source: NOAA Coral Reef Watch "Daily Global 5km Satellite SST Anomaly" served
by NOAA CoastWatch ERDDAP griddap (dataset id ``noaacrwsstanomalyDaily``,
variable ``sea_surface_temperature_anomaly``, degree_C, 0.05 degree global,
~2-day lag, no auth). Verified returning live lat/lon/time subsets on
2026-06-08.

The anomaly is published by CRW, referenced to its own daily climatology. This
module does not build or store any climatology. For each region box, it fetches
a strided griddap CSV subset and computes the cos-latitude area-weighted mean
anomaly over valid ocean cells.

This is not a Hobday marine-heatwave implementation. Tiers are provisional
absolute basin-mean anomaly thresholds, not 90th-percentile categories.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from io import StringIO

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data.ocean_sst import _REQUEST_HEADERS
from src.data.source_status import SourceFetchError, assert_response_schema

_ERDDAP_BASE = "https://coastwatch.noaa.gov/erddap/griddap/noaacrwsstanomalyDaily.csv"
_SST_ANOM_VAR = "sea_surface_temperature_anomaly"
_GRID_DEG = 0.05
_TARGET_DEG = 1.0
_GRID_STRIDE = max(1, round(_TARGET_DEG / _GRID_DEG))
_MAX_DATA_LAG_DAYS = 5
_MIN_VALID_CELLS = 10
_FETCH_WORKERS = 4
_FETCH_TIMEOUT_SECONDS = 10
_FETCH_ATTEMPTS = 1

_FILL_VALUE = -327.68
_VALID_RANGE = (-15.0, 15.0)
_SYNTHESIS_ANOMALY_FLOOR_C = 2.0

# Provisional absolute area-weighted basin-mean anomaly tiers in degree C.
# These are not Hobday MHW categories; recalibrate after NH late-summer runs.
ANOMALY_TIERS: tuple[tuple[int, float], ...] = (
    (3, 4.5),
    (2, 3.5),
    (1, 2.5),
)


@dataclass(frozen=True)
class RegionDef:
    slug: str
    display_name: str
    lat_s: float
    lat_n: float
    lon_w: float
    lon_e: float


# 13 generous global marquee basin boxes. They deliberately do not cross the
# dateline. Fast follow after NH late-summer calibration: tighten broad boxes
# toward anomaly cores so hot patches are not diluted by basin-wide averaging.
REGION_REGISTRY: tuple[RegionDef, ...] = (
    RegionDef("north_atlantic", "North Atlantic", 0, 60, -80, 0),
    RegionDef("subpolar_n_atlantic", "Subpolar North Atlantic", 45, 60, -45, -20),
    RegionDef("ne_pacific_blob", 'NE Pacific ("the Blob")', 40, 55, -150, -125),
    RegionDef("mediterranean", "Mediterranean Sea", 30, 46, -5, 36),
    RegionDef("tasman_sea", "Tasman Sea", -45, -30, 150, 175),
    RegionDef("gulf_of_mexico", "Gulf of Mexico", 18, 30, -98, -80),
    RegionDef("caribbean", "Caribbean Sea", 9, 22, -88, -60),
    RegionDef("western_indian_ocean", "Western Indian Ocean", -10, 10, 45, 75),
    RegionDef("bay_of_bengal", "Bay of Bengal", 5, 22, 80, 95),
    RegionDef("coral_triangle", "Coral Triangle", -10, 10, 120, 150),
    RegionDef("great_barrier_reef", "Great Barrier Reef", -24, -10, 142, 154),
    RegionDef("california_current", "California Current", 30, 42, -127, -116),
    RegionDef("nino34", "Niño 3.4", -5, 5, -170, -120),
)


@dataclass(frozen=True)
class RegionalSSTReading:
    region_slug: str
    region_display_name: str
    date: str
    anomaly_c: float
    tier: int
    cells_used: int


@dataclass(frozen=True)
class RegionalSSTAnomalyEvent:
    region_slug: str
    region_display_name: str
    date: str
    anomaly_c: float
    tier: int
    cells_used: int
    event_id: str


def _build_url(region: RegionDef, *, time_token: str = "last") -> str:
    """Build a single-box ERDDAP griddap CSV URL for a region."""

    if region.lon_w > region.lon_e:
        raise ValueError(
            f"Region '{region.slug}' has lon_w ({region.lon_w}) > lon_e "
            f"({region.lon_e}): dateline-crossing bboxes are not supported in v1. "
            "Split the region into two sub-boxes and union the area-weighted means."
        )

    stride = _GRID_STRIDE
    return (
        f"{_ERDDAP_BASE}?{_SST_ANOM_VAR}"
        f"[({time_token})]"
        f"[({region.lat_n}):{stride}:({region.lat_s})]"
        f"[({region.lon_w}):{stride}:({region.lon_e})]"
    )


def _parse_griddap_csv(text: str) -> tuple[str | None, list[tuple[float, float]]]:
    """Return ``(YYYY-MM-DD, [(latitude, anomaly_c), ...])`` from CRW CSV."""

    rows = csv.reader(StringIO(text))
    iso_date: str | None = None
    cells: list[tuple[float, float]] = []
    for row_index, row in enumerate(rows):
        if row_index < 2 or not row:
            continue
        if len(row) < 4:
            continue
        if iso_date is None and row[0]:
            iso_date = row[0][:10]
        try:
            lat = float(row[1])
            val = float(row[3])
        except ValueError:
            continue
        if not math.isfinite(val):
            continue
        if val == _FILL_VALUE:
            continue
        if not (_VALID_RANGE[0] <= val <= _VALID_RANGE[1]):
            continue
        cells.append((lat, val))
    return iso_date, cells


def _area_weighted_mean(cells: list[tuple[float, float]]) -> float | None:
    num = 0.0
    den = 0.0
    for lat, val in cells:
        weight = math.cos(math.radians(lat))
        num += val * weight
        den += weight
    if den == 0:
        return None
    return num / den


def _detect_tier(anomaly_c: float) -> int | None:
    for tier, threshold in ANOMALY_TIERS:
        if anomaly_c >= threshold:
            return tier
    return None


def fetch_region_sst(
    region: RegionDef,
    *,
    strict: bool = False,
    min_valid_cells: int = _MIN_VALID_CELLS,
    today: date | None = None,
) -> RegionalSSTReading | None:
    """Fetch and tier a single regional SST anomaly reading."""

    try:
        return _fetch_region_sst_strict(region, min_valid_cells=min_valid_cells, today=today)
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"ocean_sst_anomaly/{region.slug} fetch failed: {exc}") from exc
        print(f"[sst_anom] {region.slug}: fetch skipped ({exc})")
        return None


def _fetch_region_sst_strict(
    region: RegionDef,
    *,
    min_valid_cells: int = _MIN_VALID_CELLS,
    today: date | None = None,
) -> RegionalSSTReading | None:
    """Fetch one region, raising for source errors and returning None below tier."""

    response = fetch_with_retry(
        _build_url(region),
        timeout=_FETCH_TIMEOUT_SECONDS,
        headers=_REQUEST_HEADERS,
        attempts=_FETCH_ATTEMPTS,
    )
    text = response.text
    assert_response_schema({"body": text}, ["body"], "ocean_sst_anomaly")
    if not text.strip():
        raise SourceFetchError(f"ocean_sst_anomaly/{region.slug}: empty response")
    iso_date, cells = _parse_griddap_csv(text)
    if iso_date is None or not cells:
        raise SourceFetchError(f"ocean_sst_anomaly/{region.slug}: empty grid")
    assert_freshness(
        date.fromisoformat(iso_date),
        "ocean_sst_anomaly",
        _MAX_DATA_LAG_DAYS,
        today=today,
    )
    if len(cells) < min_valid_cells:
        print(
            f"[sst_anom] {region.slug}: only {len(cells)} valid cells "
            f"(<{min_valid_cells}), skipping"
        )
        return None
    mean = _area_weighted_mean(cells)
    if mean is None:
        raise SourceFetchError(f"ocean_sst_anomaly/{region.slug}: no valid cells")
    tier = _detect_tier(mean)
    if tier is None:
        if mean < _SYNTHESIS_ANOMALY_FLOOR_C:
            return None
        tier = 0
    return RegionalSSTReading(
        region_slug=region.slug,
        region_display_name=region.display_name,
        date=iso_date,
        anomaly_c=round(mean, 2),
        tier=tier,
        cells_used=len(cells),
    )


def fetch_all_regions(*, strict: bool = False) -> list[RegionalSSTReading]:
    """Fetch all configured regions, degrading per region by default."""

    readings_by_index: dict[int, RegionalSSTReading] = {}
    failures_by_index: dict[int, str] = {}
    failures = 0
    worker_count = min(_FETCH_WORKERS, len(REGION_REGISTRY))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_fetch_region_sst_strict, region): (index, region)
            for index, region in enumerate(REGION_REGISTRY)
        }
        for future in as_completed(futures):
            index, region = futures[future]
            try:
                reading = future.result()
            except (requests.RequestException, SourceFetchError, ValueError) as exc:
                if strict:
                    raise SourceFetchError(
                        f"ocean_sst_anomaly/{region.slug} fetch failed: {exc}"
                    ) from exc
                failures += 1
                failures_by_index[index] = f"{region.slug}: {exc}"
                print(f"[sst_anom] {region.slug}: fetch skipped ({exc})")
                continue
            if reading is not None:
                readings_by_index[index] = reading

    if failures >= len(REGION_REGISTRY):
        samples = "; ".join(
            failures_by_index[index] for index in sorted(failures_by_index)[:3]
        )
        detail = f"; samples: {samples}" if samples else ""
        raise SourceFetchError(f"ocean_sst_anomaly: all regions failed{detail}")
    return [readings_by_index[index] for index in sorted(readings_by_index)]


def detect_regional_sst_anomaly_events(
    readings: list[RegionalSSTReading],
    last_tiers: Mapping[str, int] | None = None,
) -> list[RegionalSSTAnomalyEvent]:
    """Return events where the current tier exceeds the last fired tier."""

    prior_tiers = last_tiers or {}
    events: list[RegionalSSTAnomalyEvent] = []
    for reading in readings:
        try:
            prior_tier = int(prior_tiers.get(reading.region_slug, 0) or 0)
        except (TypeError, ValueError):
            prior_tier = 0
        if reading.tier <= prior_tier:
            continue
        events.append(
            RegionalSSTAnomalyEvent(
                region_slug=reading.region_slug,
                region_display_name=reading.region_display_name,
                date=reading.date,
                anomaly_c=reading.anomaly_c,
                tier=reading.tier,
                cells_used=reading.cells_used,
                event_id=(
                    f"sst_anom_{reading.region_slug}_tier{reading.tier}_{reading.date}"
                ),
            )
        )
    events.sort(key=lambda event: (event.tier, event.anomaly_c), reverse=True)
    return events
