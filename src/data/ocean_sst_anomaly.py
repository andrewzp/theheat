"""Per-region SST anomaly detection via NOAA Coral Reef Watch gridded anomaly.

Source: NOAA Coral Reef Watch "Daily Global 5km Satellite SST Anomaly" served
by NOAA CoastWatch ERDDAP griddap (dataset id ``noaacrwsstanomalyDaily``,
variable ``sea_surface_temperature_anomaly``, degree_C, 0.05 degree global,
~2-day lag, no auth). Verified returning live lat/lon/time subsets on
2026-06-08.

The anomaly is published by CRW, referenced to its own daily climatology. This
module does not build or store any climatology. For each region box, it fetches
a strided griddap CSV subset and computes the cos-latitude-weighted mean
anomaly over valid sampled cells. This is not a full-grid basin mean.

This is not a Hobday marine-heatwave implementation. Tiers are provisional
absolute basin-mean anomaly thresholds, not 90th-percentile categories.
"""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import math
import re
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import requests

from src.data._http import fetch_with_retry
from src.data._witness import is_witness_eligible_failure
from src.data.ocean_sst import _REQUEST_HEADERS
from src.data.source_status import SourceFetchError
from src.data import crw_contract as contract

_ERDDAP_BASE = "https://coastwatch.noaa.gov/erddap/griddap/noaacrwsstanomalyDaily.csv"
NOAA_STAR_SSTA_LEG = "noaa_star_nc"
NOAA_STAR_SSTA_BASE_URL = (
    "https://www.star.nesdis.noaa.gov/pub/sod/mecb/crw/data/5km/v3.1_op/nc/v1.0/daily/ssta"
)
_SST_ANOM_VAR = "sea_surface_temperature_anomaly"
_GRID_DEG = 0.05
_TARGET_DEG = 1.0
_GRID_STRIDE = max(1, round(_TARGET_DEG / _GRID_DEG))
_MIN_VALID_CELLS = 10
_FETCH_WORKERS = 4
_FETCH_TIMEOUT_SECONDS = 10
_FETCH_ATTEMPTS = 1

_VALID_RANGE = (-15.0, 15.0)
_SYNTHESIS_ANOMALY_FLOOR_C = 2.0
_NOAA_STAR_FILE_RE = re.compile(r"^ct5km_ssta_v3\.1_(\d{8})\.nc$")

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
    source_leg: str | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class RegionalSSTAnomalyEvent:
    region_slug: str
    region_display_name: str
    date: str
    anomaly_c: float
    tier: int
    cells_used: int
    event_id: str
    source_leg: str | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class RegionalSSTSample:
    """One leg's outcome, including samples below the synthesis floor.

    A candidate can be tier zero (synthesis only), not a publishable event.
    Raw source bytes and exception text never enter the health projection.
    """

    region_slug: str
    outcome: Literal[
        "candidate", "below_floor", "insufficient_sample", "source_rejected", "transport_failure"
    ]
    source_leg: str
    request_attempted: bool = True
    product_date: str | None = None
    total_cells: int | None = None
    valid_cells: int | None = None
    excluded_cells: int | None = None
    diagnostic: str | None = None
    reading: RegionalSSTReading | None = None

    @property
    def qualified(self) -> bool:
        return self.outcome in {"candidate", "below_floor"}

    def summary(self) -> dict:
        return {
            "outcome": self.outcome,
            "source_leg": self.source_leg,
            "request_attempted": self.request_attempted,
            "product_date": self.product_date,
            "total_cells": self.total_cells,
            "valid_cells": self.valid_cells,
            "excluded_cells": self.excluded_cells,
            "diagnostic": self.diagnostic,
        }


class _SampleRejected(SourceFetchError):
    """Retain already decoded counts/date without qualifying a rejected sample."""

    def __init__(self, cause: SourceFetchError, sample: RegionalSSTSample):
        super().__init__(str(cause))
        self.sample = sample


@dataclass(frozen=True)
class RegionalSSTResult:
    primary: RegionalSSTSample
    final: RegionalSSTSample

    @property
    def recovered(self) -> bool:
        return self.final.source_leg == NOAA_STAR_SSTA_LEG and self.final.qualified


@dataclass(frozen=True)
class RegionalSSTCollection:
    regions: tuple[RegionalSSTResult, ...]

    @property
    def readings(self) -> list[RegionalSSTReading]:
        return [row.final.reading for row in self.regions if row.final.reading is not None]

    @property
    def observed(self) -> int:
        return sum(row.final.qualified for row in self.regions)

    @property
    def recovered(self) -> int:
        return sum(row.recovered for row in self.regions)

    @property
    def fallback_attempted(self) -> int:
        # Regions dependent on the shared native download, not HTTP request count.
        return sum(row.final.source_leg == NOAA_STAR_SSTA_LEG for row in self.regions)

    @property
    def status(self) -> str:
        if not self.observed:
            return "failed"
        if self.observed < len(self.regions):
            return "partial_failure"
        return "degraded" if self.recovered else "success"

    @property
    def note(self) -> str:
        return (
            f"Qualified regional samples: {self.observed}/{len(self.regions)}; "
            f"fallback recovered: {self.recovered} (attempted: {self.fallback_attempted}); "
            f"unresolved: {len(self.regions) - self.observed}"
        )

    def details(self) -> dict:
        return {
            "configured_regions": len(self.regions),
            "qualified_regions": self.observed,
            "fallback_regions": self.fallback_attempted,
            "recovered_regions": self.recovered,
            "unresolved_regions": len(self.regions) - self.observed,
            "regions": [
                {
                    "region_slug": row.primary.region_slug,
                    "primary": row.primary.summary(),
                    "final": row.final.summary(),
                    "serving_leg": row.final.source_leg if row.final.qualified else None,
                    "recovered": row.recovered,
                }
                for row in self.regions
            ],
        }


@dataclass(frozen=True)
class NoaaStarSstaFile:
    url: str
    data_date: str
    name: str


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
    """Compatibility projection of the strict decoder; no scientific approval."""
    sample = contract.decode_csv(text)
    return sample.timestamp[:10], sample.cells


def _source_body(
    url: str, *, limit: int, timeout: int, attempts: int, headers=None
) -> tuple[bytes, str]:
    """Bound decoded identity bytes and close responses on every outcome."""
    started = time.monotonic()
    request_headers = dict(headers or {})
    request_headers["Accept-Encoding"] = "identity"
    with closing(
        fetch_with_retry(
            url,
            timeout=timeout,
            attempts=attempts,
            headers=request_headers,
            stream=True,
            allow_redirects=False,
        )
    ) as response:
        if (
            response.status_code != 200
            or response.headers.get("Content-Encoding", "identity").lower() != "identity"
        ):
            contract.reject("unexpected HTTP response")
        data = bytearray()
        for chunk in response.iter_content(65536):
            if len(data) + len(chunk) > limit or time.monotonic() - started > 60:
                contract.reject("response resource limit")
            data.extend(chunk)
    if not data or time.monotonic() - started > 60:
        contract.reject("empty or overdue response")
    return bytes(data), datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _primary_metadata() -> dict:
    body, retrieved = _source_body(
        contract.METADATA_URL, limit=contract.CSV_LIMIT, timeout=10, attempts=1
    )
    return {
        **contract.metadata_contract(body),
        "retrieved_at": retrieved,
        "response_bytes": len(body),
    }


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
    metadata: dict | None = None,
) -> RegionalSSTReading | None:
    """Compatibility projection of the shared collection/classification path."""
    return _fetch_region_sample_strict(
        region, min_valid_cells=min_valid_cells, today=today, metadata=metadata
    ).reading


def _fetch_region_sample_strict(
    region: RegionDef,
    *,
    min_valid_cells: int = _MIN_VALID_CELLS,
    today: date | None = None,
    metadata: dict | None = None,
) -> RegionalSSTSample:

    metadata = _primary_metadata() if metadata is None else metadata
    url = _build_url(region)
    body, retrieved_at = _source_body(
        url,
        limit=contract.CSV_LIMIT,
        timeout=_FETCH_TIMEOUT_SECONDS,
        headers=_REQUEST_HEADERS,
        attempts=_FETCH_ATTEMPTS,
    )
    sample = contract.decode_csv(body.decode("latin-1"), region)
    iso_date, cells = sample.timestamp[:10], sample.cells
    result = RegionalSSTSample(
        region.slug, "source_rejected", "coastwatch_erddap",
        product_date=iso_date, total_cells=sample.total_cells, valid_cells=len(cells),
        excluded_cells=sample.total_cells - len(cells), diagnostic="regional_source_rejected",
    )
    try:
        if not metadata["first_product_time"] <= sample.timestamp <= metadata["last_product_time"]:
            contract.reject("sample outside metadata time range")
        contract.fresh_day(iso_date, today)
    except SourceFetchError as exc:
        raise _SampleRejected(exc, result) from exc
    if len(cells) < min_valid_cells:
        print(
            f"[sst_anom] {region.slug}: only {len(cells)} valid cells "
            f"(<{min_valid_cells}), skipping"
        )
        return replace(result, outcome="insufficient_sample", diagnostic="insufficient_valid_cells")
    mean = _area_weighted_mean(cells)
    if mean is None:
        raise SourceFetchError(f"ocean_sst_anomaly/{region.slug}: no valid cells")
    tier = _detect_tier(mean)
    if tier is None:
        if mean < _SYNTHESIS_ANOMALY_FLOOR_C:
            return replace(result, outcome="below_floor", diagnostic=None)
        tier = 0
    reading = RegionalSSTReading(
        region_slug=region.slug,
        region_display_name=region.display_name,
        date=iso_date,
        anomaly_c=round(mean, 2),
        tier=tier,
        cells_used=len(cells),
        provenance=contract.provenance(
            body=body,
            url=url,
            retrieved_at=retrieved_at,
            timestamp=sample.timestamp,
            region=region,
            mean=round(mean, 2),
            valid_cells=len(cells),
            total_cells=sample.total_cells,
            sampled_bounds=sample.sampled_bounds,
            leg="coastwatch_erddap",
            metadata=deepcopy(metadata),
        ),
    )
    return replace(result, outcome="candidate", diagnostic=None, reading=reading)


def fetch_all_regions(*, strict: bool = False) -> list[RegionalSSTReading]:
    """List compatibility API; health consumers must use the collection report."""
    report = collect_all_regions(strict=strict)
    if all(row.final.outcome in {"source_rejected", "transport_failure"} for row in report.regions):
        samples = "; ".join(
            f"{row.primary.region_slug}: {row.final.diagnostic}" for row in report.regions[:3]
        )
        raise SourceFetchError(f"ocean_sst_anomaly: all regions failed; samples: {samples}")
    return report.readings


def _failure_sample(
    region: RegionDef, exc: Exception, *, leg: str = "coastwatch_erddap", metadata: bool = False
) -> RegionalSSTSample:
    if isinstance(exc, _SampleRejected):
        return exc.sample
    transport = isinstance(exc, requests.RequestException) or is_witness_eligible_failure(exc)
    outcome: Literal["transport_failure", "source_rejected"] = (
        "transport_failure" if transport else "source_rejected"
    )
    stage = "metadata" if metadata else "native" if leg == NOAA_STAR_SSTA_LEG else "regional"
    return RegionalSSTSample(
        region.slug, outcome, leg, request_attempted=not metadata,
        diagnostic=f"{stage}_{outcome}",
    )


def collect_all_regions(*, strict: bool = False) -> RegionalSSTCollection:
    """Collect once and retain every region's outcome before filtering candidates.

    The native leg still runs only if *all* primary errors are fallback eligible.
    Quiet and insufficient primary samples are never retried or replaced.
    """

    primary: dict[str, RegionalSSTSample] = {}
    failures: dict[str, bool] = {}
    try:
        metadata = _primary_metadata()
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise
        for region in REGION_REGISTRY:
            primary[region.slug] = _failure_sample(region, exc, metadata=True)
            failures[region.slug] = is_witness_eligible_failure(exc)
    else:
        with ThreadPoolExecutor(max_workers=min(_FETCH_WORKERS, len(REGION_REGISTRY))) as executor:
            futures = {
                executor.submit(_fetch_region_sample_strict, region, metadata=metadata): region
                for region in REGION_REGISTRY
            }
            for future in as_completed(futures):
                region = futures[future]
                try:
                    primary[region.slug] = future.result()
                except (requests.RequestException, SourceFetchError, ValueError) as exc:
                    if strict:
                        raise SourceFetchError(
                            f"ocean_sst_anomaly/{region.slug} fetch failed: {exc}"
                        ) from exc
                    primary[region.slug] = _failure_sample(region, exc)
                    # Preserve the existing regional fallback eligibility check,
                    # which classifies the aggregate's source-prefixed error.
                    failures[region.slug] = is_witness_eligible_failure(
                        SourceFetchError(f"{region.slug}: {exc}")
                    )

    final = dict(primary)
    if failures and all(failures.values()):
        failed_regions = tuple(r for r in REGION_REGISTRY if r.slug in failures)
        try:
            fallback = _fetch_noaa_star_ssta_samples_strict(
                regions=failed_regions, min_valid_cells=_MIN_VALID_CELLS, today=None,
            )
            final.update({sample.region_slug: sample for sample in fallback})
        except (requests.RequestException, SourceFetchError, ValueError) as exc:
            for region in failed_regions:
                final[region.slug] = _failure_sample(region, exc, leg=NOAA_STAR_SSTA_LEG)
    return RegionalSSTCollection(tuple(
        RegionalSSTResult(primary[r.slug], final[r.slug]) for r in REGION_REGISTRY
    ))


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
                event_id=(f"sst_anom_{reading.region_slug}_tier{reading.tier}_{reading.date}"),
                source_leg=reading.source_leg,
                provenance=deepcopy(reading.provenance),
            )
        )
    events.sort(key=lambda event: (event.tier, event.anomaly_c), reverse=True)
    return events


def _fetch_noaa_star_ssta_samples_strict(
    *,
    regions: tuple[RegionDef, ...],
    min_valid_cells: int = _MIN_VALID_CELLS,
    today: date | None = None,
) -> list[RegionalSSTSample]:
    selected = _latest_noaa_star_ssta_file(today=today)
    body, retrieved_at = _source_body(
        selected.url, limit=contract.NETCDF_LIMIT, timeout=30, attempts=2
    )
    return _samples_from_noaa_star_netcdf_bytes(
        body,
        data_date=selected.data_date,
        regions=regions,
        min_valid_cells=min_valid_cells,
        today=today,
        source_url=selected.url,
        retrieved_at=retrieved_at,
    )


def _latest_noaa_star_ssta_file(*, today: date | None = None) -> NoaaStarSstaFile:
    current = today or datetime.now(UTC).date()
    errors: list[str] = []
    for year in (current.year, current.year - 1):
        try:
            body, _ = _source_body(
                _noaa_star_year_index_url(year),
                limit=contract.LISTING_LIMIT,
                timeout=20,
                attempts=2,
            )
            return _latest_noaa_star_file_from_index(body.decode("latin-1"))
        except (requests.RequestException, SourceFetchError) as exc:
            errors.append(f"{year}: {exc}")
            continue
    raise SourceFetchError("NOAA STAR SST anomaly index lookup failed: " + "; ".join(errors))


def _latest_noaa_star_file_from_index(index_html: str) -> NoaaStarSstaFile:
    names = re.findall(r"""href=["']([^"']+)["']""", index_html)
    candidates: list[NoaaStarSstaFile] = []
    for raw_name in names:
        name = raw_name.rsplit("/", 1)[-1]
        match = _NOAA_STAR_FILE_RE.fullmatch(name)
        if match is None:
            continue
        yyyymmdd = match.group(1)
        data_date = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
        candidates.append(
            NoaaStarSstaFile(
                url=f"{NOAA_STAR_SSTA_BASE_URL}/{yyyymmdd[:4]}/{name}",
                data_date=data_date,
                name=name,
            )
        )
    if not candidates:
        raise SourceFetchError("NOAA STAR SST anomaly index had no NetCDF files")
    return max(candidates, key=lambda item: item.data_date)


def _readings_from_noaa_star_netcdf_bytes(
    content: bytes,
    *,
    data_date: str,
    regions: tuple[RegionDef, ...] = REGION_REGISTRY,
    min_valid_cells: int = _MIN_VALID_CELLS,
    today: date | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> list[RegionalSSTReading]:
    """Compatibility projection; decoding and sampling happen only once."""
    return [
        sample.reading for sample in _samples_from_noaa_star_netcdf_bytes(
            content, data_date=data_date, regions=regions, min_valid_cells=min_valid_cells,
            today=today, source_url=source_url, retrieved_at=retrieved_at,
        ) if sample.reading is not None
    ]


def _samples_from_noaa_star_netcdf_bytes(
    content: bytes,
    *,
    data_date: str,
    regions: tuple[RegionDef, ...] = REGION_REGISTRY,
    min_valid_cells: int = _MIN_VALID_CELLS,
    today: date | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> list[RegionalSSTSample]:
    try:
        from netCDF4 import Dataset
        import numpy as np
    except ImportError as exc:
        raise SourceFetchError("NOAA STAR SST anomaly fallback requires netCDF4/numpy") from exc

    contract.fresh_day(data_date, today)
    if not isinstance(content, bytes) or not 0 < len(content) <= contract.NETCDF_LIMIT:
        contract.reject("native file size")
    try:
        with Dataset("noaa_star_ssta.nc", memory=content) as dataset:
            timestamp = _native_metadata(dataset, data_date, np=np)
            latitudes = np.asarray(dataset.variables["lat"][:], dtype=float)
            longitudes = np.asarray(dataset.variables["lon"][:], dtype=float)
            ssta = dataset.variables[_SST_ANOM_VAR]
            if ssta.ndim != 3:
                raise SourceFetchError("NOAA STAR SST anomaly schema drift: SSTA grid was not 3D")
            samples = []
            for region in regions:
                sample = _sample_from_noaa_star_grid(
                    ssta,
                    latitudes,
                    longitudes,
                    region,
                    data_date=data_date,
                    min_valid_cells=min_valid_cells,
                    np=np,
                )
                reading = sample.reading
                if reading is not None:
                    lat_slice = _axis_window_slice(latitudes, region.lat_s, region.lat_n, np=np)
                    lon_slice = _axis_window_slice(longitudes, region.lon_w, region.lon_e, np=np)
                    lat, lon = latitudes[lat_slice], longitudes[lon_slice]
                    # Direct offline decoding without a transfer receipt stays unqualified.
                    if source_url is not None and retrieved_at is not None:
                        reading = replace(
                            reading,
                            provenance=contract.provenance(
                                body=content,
                                url=source_url,
                                retrieved_at=retrieved_at,
                                timestamp=timestamp,
                                region=region,
                                mean=reading.anomaly_c,
                                valid_cells=reading.cells_used,
                                total_cells=len(lat) * len(lon),
                                sampled_bounds=[
                                    float(min(lat)),
                                    float(max(lat)),
                                    float(min(lon)),
                                    float(max(lon)),
                                ],
                                leg=NOAA_STAR_SSTA_LEG,
                            ),
                        )
                    sample = replace(sample, reading=reading)
                samples.append(sample)
            return samples
    except KeyError as exc:
        raise SourceFetchError(f"NOAA STAR SST anomaly schema drift: missing {exc}") from exc
    except (OSError, RuntimeError) as exc:
        raise SourceFetchError(f"NOAA STAR SST anomaly NetCDF read failed: {exc}") from exc
    except (ValueError, TypeError, AttributeError, OverflowError):
        contract.reject("invalid native metadata")


def _native_metadata(dataset, data_date: str, *, np) -> str:
    """Check native file semantics before reading any measurement slices."""
    if (
        getattr(dataset, "id", None) != "Satellite_Daily_Global_5km_SST_Anomaly"
        or getattr(dataset, "product_version", None) != "3.1"
        or getattr(dataset, "processing_level", None)
        != "Derived from L4 satellite sea surface temperaure analysis"
        or {k: len(dataset.dimensions[k]) for k in ("time", "lat", "lon")}
        != {"time": 1, "lat": 3600, "lon": 7200}
    ):
        contract.reject("native product identity or dimensions")
    for name, length, start, stop, unit in (
        ("lat", 3600, 89.975, -89.975, "degrees_north"),
        ("lon", 7200, -179.975, 179.975, "degrees_east"),
    ):
        axis = dataset.variables[name]
        values = np.ma.asarray(axis[:], dtype=float)
        if (
            axis.dimensions != (name,)
            or getattr(axis, "units", None) != unit
            or values.shape != (length,)
            or np.ma.getmaskarray(values).any()
            or not np.isfinite(values).all()
            or not np.allclose(values, np.linspace(start, stop, length), rtol=0, atol=0.0001)
        ):
            contract.reject("native coordinate axis")
    variable = dataset.variables[_SST_ANOM_VAR]
    if (
        variable.dimensions != ("time", "lat", "lon")
        or variable.dtype != np.dtype("int16")
        or getattr(variable, "units", None) != "degrees_Celsius"
        or not math.isclose(
            float(getattr(variable, "scale_factor", float("nan"))), 0.01, rel_tol=0, abs_tol=1e-8
        )
        or getattr(variable, "add_offset", 0) != 0
        or getattr(variable, "_FillValue", None) != -32768
        or getattr(variable, "missing_value", -32768) != -32768
        or getattr(variable, "_Unsigned", "false") != "false"
        or not np.array_equal(getattr(variable, "valid_range", [-1500, 1500]), [-1500, 1500])
        or getattr(variable, "valid_min", None) != -1500
        or getattr(variable, "valid_max", None) != 1500
    ):
        contract.reject("native anomaly units or encoding")
    reference = dataset.variables["time"]
    if (
        reference.dimensions != ("time",)
        or reference.dtype != np.dtype("int32")
        or getattr(reference, "units", None) != "seconds since 1981-01-01 00:00:00"
        or getattr(reference, "calendar", "standard")
        not in ("standard", "gregorian", "proleptic_gregorian")
    ):
        contract.reject("native time encoding")
    seconds = np.ma.asarray(reference[:], dtype=float)
    if seconds.shape != (1,) or np.ma.getmaskarray(seconds).any() or not np.isfinite(seconds).all():
        contract.reject("native reference time")
    try:
        point = datetime(1981, 1, 1, tzinfo=UTC) + timedelta(seconds=float(seconds[0]))
        coverage_start = datetime.strptime(dataset.time_coverage_start, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        )
        coverage_end = datetime.strptime(dataset.time_coverage_end, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        )
        if (
            point.date().isoformat() != data_date
            or coverage_start != point.replace(hour=0, minute=0, second=0, microsecond=0)
            or not coverage_start <= point < coverage_end
            or coverage_end - coverage_start != timedelta(days=1)
        ):
            contract.reject("native date does not match selected file")
        return point.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, AttributeError, OverflowError):
        contract.reject("invalid native coverage time")


def _sample_from_noaa_star_grid(
    ssta,
    latitudes,
    longitudes,
    region: RegionDef,
    *,
    data_date: str,
    min_valid_cells: int,
    np,
) -> RegionalSSTSample:
    lat_slice = _axis_window_slice(latitudes, region.lat_s, region.lat_n, np=np)
    lon_slice = _axis_window_slice(longitudes, region.lon_w, region.lon_e, np=np)
    grid = np.ma.array(ssta[0, lat_slice, lon_slice], dtype=float)
    grid = np.ma.masked_invalid(grid)
    grid = np.ma.masked_outside(grid, _VALID_RANGE[0], _VALID_RANGE[1])
    cells_used = int(np.ma.count(grid))
    sample = RegionalSSTSample(
        region.slug, "insufficient_sample", NOAA_STAR_SSTA_LEG,
        product_date=data_date, total_cells=int(grid.size), valid_cells=cells_used,
        excluded_cells=int(grid.size) - cells_used, diagnostic="insufficient_valid_cells",
    )
    if cells_used < min_valid_cells:
        return sample
    mean = _weighted_grid_mean(grid, latitudes[lat_slice], np=np)
    if mean is None:
        raise SourceFetchError(f"NOAA STAR SST anomaly/{region.slug}: no valid cells")
    tier = _detect_tier(mean)
    if tier is None:
        if mean < _SYNTHESIS_ANOMALY_FLOOR_C:
            return replace(sample, outcome="below_floor", diagnostic=None)
        tier = 0
    reading = RegionalSSTReading(
        region_slug=region.slug,
        region_display_name=region.display_name,
        date=data_date,
        anomaly_c=round(float(mean), 2),
        tier=tier,
        cells_used=cells_used,
        source_leg=NOAA_STAR_SSTA_LEG,
    )
    return replace(sample, outcome="candidate", diagnostic=None, reading=reading)


def _axis_window_slice(values, lower: float, upper: float, *, np) -> slice:
    indices = np.flatnonzero((values >= lower) & (values <= upper))
    if len(indices) == 0:
        raise SourceFetchError("NOAA STAR SST anomaly schema drift: region outside grid")
    start = int(indices[0])
    stop = int(indices[-1]) + 1
    return slice(start, stop, _GRID_STRIDE)


def _weighted_grid_mean(grid, latitudes, *, np) -> float | None:
    weights = np.cos(np.deg2rad(latitudes))[:, None]
    weights = np.broadcast_to(weights, grid.shape)
    mask = np.ma.getmaskarray(grid)
    weighted = np.ma.array(grid * weights, mask=mask)
    denom = np.ma.array(weights, mask=mask).sum()
    if not denom:
        return None
    return float(weighted.sum() / denom)


def _noaa_star_year_index_url(year: int) -> str:
    return f"{NOAA_STAR_SSTA_BASE_URL}/{year}/"
