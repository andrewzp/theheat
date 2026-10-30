"""Pure NOAA CRW regional definitions shared by the collector and the image path.

No network, model or store access. ``src.data.ocean_sst_anomaly`` re-exports every
name here unchanged; these are the same objects, not copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_ERDDAP_BASE = "https://coastwatch.noaa.gov/erddap/griddap/noaacrwsstanomalyDaily.csv"
_SST_ANOM_VAR = "sea_surface_temperature_anomaly"
_GRID_DEG = 0.05
_TARGET_DEG = 1.0
_GRID_STRIDE = max(1, round(_TARGET_DEG / _GRID_DEG))

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
    # Exact retained source-packet reference (store identities only, never bytes);
    # absent unless explicit collector retention succeeded for this primary event.
    retained_packet: dict[str, Any] | None = None


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


def _detect_tier(anomaly_c: float) -> int | None:
    for tier, threshold in ANOMALY_TIERS:
        if anomaly_c >= threshold:
            return tier
    return None
