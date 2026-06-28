from __future__ import annotations

"""Reanalysis regional-anomaly detection (Part B / "reganom").

Detects when a coherent region's sampled cities averaged far above their
1991-2020 daily ERA5 climatological normal for >= min_days consecutive
*complete* days. Honestly framed as a POINT INDEX over N sampled cities --
never an area-weighted national mean (see build_regional_anomaly_bundle's
forbidden_claims and the layered honesty defense in the plan).

Rev-3 deltas implemented here:
  §A  Geo model = a hand-curated REGION_WATCHLIST of climatically-coherent
      regions (16 regions / 100 points), NOT auto-derived country buckets.
  §B  Trigger fires only when ALL hold over the window: point-mean anomaly
      >= +6C absolute; mean z-score >= 2.0 (per-MM-DD sigma from the cache);
      and >= 50% of the region's sampled points individually exceed +6C.
  §C  fetch_all_reganom_t2m returns DATED rows {(lat,lon): [(date_iso, t_max)]}
      so detection can skip the ~5-day ERA5 archive lag (null trailing days)
      and align each date -> MM-DD against the daily climatology.

Both the backfill (scripts/build_climatology_cache.py) and the live fetch use
the Open-Meteo ERA5 ARCHIVE endpoint with timezone=UTC, so the live reading and
the 30-year normal share the same day-boundary convention.
"""

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from src.data._http import fetch_with_retry
from src.data.open_meteo import ARCHIVE_URL  # re-exported (used by the backfill + tests)
from src.data.source_status import SourceSkipped

__all__ = [
    "ARCHIVE_URL",
    "RegionDef",
    "RegionalAnomalyEvent",
    "REGION_WATCHLIST",
    "all_watchlist_coords",
    "load_daily_climatology",
    "fetch_all_reganom_t2m",
    "detect_regional_anomaly",
]

# Same coord-list batching cap as the air-quality lane. ~100 watchlist points
# fit in two batched archive requests; this keeps the design "O(1) requests per
# cycle, not per-region fan-out" (Risk 1) while staying under any URL/coord cap.
CHUNK_SIZE = int(os.environ.get("THEHEAT_REGANOM_CHUNK_SIZE", "50"))

# Detection defaults (overridable for tests / future tuning).
MIN_ANOMALY_C = 6.0
MIN_DAYS = 3
MIN_ZSCORE = 2.0
MIN_FRACTION = 0.5
MIN_POINTS = 3
# A sustained spell that ENDED within this many days of the most-recent complete day
# still fires (not only one ongoing on the latest day) — so a major heatwave that just
# eased (e.g. France/UK peaking for a week then dropping yesterday) is still drafted.
# The magnitude bar (+6C / >=2sigma / >=50% support) is unchanged; this only widens recency.
RECENCY_DAYS = 2
DATE_RANGE_DAYS = 12  # covers min_days + ~5-day ERA5 lag + margin
_STD_FLOOR = 0.1  # guards z-score against a zero/near-zero per-day sigma


# --------------------------------------------------------------------------- #
# §A — curated geo model
# --------------------------------------------------------------------------- #

RegionPoints = list[tuple[float, float]]


@dataclass(frozen=True)
class RegionDef:
    """A climatically-coherent watch region and its representative sample points."""

    name: str
    points: RegionPoints

    @property
    def slug(self) -> str:
        return self.name.replace(" ", "_")


# Curated regional-anomaly watchlist — 16 climatically-coherent regions, 100
# sample points. Each region is a real synoptic zone anchored to a documented,
# attribution-studied heat event (so the framing survives scientific scrutiny),
# and the set spans both hemispheres for year-round editorial supply. Points
# marked "domain" in the comments are town centers not present in data/cities.csv
# (verified plausible in the backfill spot-check). NEVER reframe a region's mean
# as an area-weighted national average — see the honesty layers.
REGION_WATCHLIST: tuple[RegionDef, ...] = (
    # 2021 Pacific Northwest heat dome (Lytton 49.6C). Portland, Seattle,
    # Vancouver, Spokane, Kamloops, Boise.
    RegionDef("Pacific Northwest", [
        (45.52, -122.68), (47.61, -122.33), (49.25, -123.12),
        (47.66, -117.43), (50.67, -120.33), (43.62, -116.20),
    ]),
    # Phoenix 2023 (31 days >=110F). Phoenix, Las Vegas, Tucson, El Paso,
    # Palm Springs, Yuma.
    RegionDef("Desert Southwest", [
        (33.45, -112.07), (36.17, -115.14), (32.22, -110.93),
        (31.76, -106.49), (33.83, -116.55), (32.69, -114.62),
    ]),
    # 2003/2022/2023 French heatwaves. Paris, Lyon, Marseille, Bordeaux,
    # Toulouse, Nantes.
    RegionDef("France", [
        (48.86, 2.35), (45.75, 4.85), (43.30, 5.37),
        (44.84, -0.58), (43.60, 1.44), (47.22, -1.55),
    ]),
    # 2022/2023 record Iberian heat. Madrid, Lisbon, Seville, Zaragoza,
    # Barcelona, Valencia.
    RegionDef("Iberia", [
        (40.42, -3.70), (38.72, -9.14), (37.39, -5.98),
        (41.66, -0.88), (41.39, 2.16), (39.47, -0.38),
    ]),
    # July 2022 first-ever 40C in Britain. London, Birmingham, Manchester,
    # Leeds, Glasgow, Dublin.
    RegionDef("United Kingdom & Ireland", [
        (51.51, -0.13), (52.48, -1.90), (53.48, -2.24),
        (53.80, -1.55), (55.87, -4.26), (53.35, -6.26),
    ]),
    # 2021/2023 records (Sicily 48.8C). Rome, Naples, Palermo, Athens,
    # Tirana, Valletta.
    RegionDef("Central Mediterranean", [
        (41.90, 12.50), (40.85, 14.27), (38.12, 13.36),
        (37.98, 23.73), (41.33, 19.82), (35.90, 14.51),
    ]),
    # Sahara source-region for European heat domes. Marrakesh, Casablanca,
    # Fes, Algiers, Tunis.
    RegionDef("Maghreb", [
        (31.63, -8.00), (33.57, -7.59), (34.03, -5.00),
        (36.75, 3.04), (36.81, 10.18),
    ]),
    # 2024 Sahel heatwave (impossible-without-climate-change attribution).
    # Niamey, Khartoum, N'Djamena, Timbuktu, Bamako, Kano, Maiduguri.
    RegionDef("Sahel", [
        (13.51, 2.11), (15.50, 32.56), (12.13, 15.05), (16.77, -3.01),
        (12.64, -8.00), (12.00, 8.52), (11.85, 13.16),
    ]),
    # Ahvaz/Basra heat-index records; wet-bulb extremes. Baghdad, Basrah,
    # Mosul, Ahvaz, Kuwait City, Riyadh, Dammam, Doha.
    RegionDef("Mesopotamia & the Gulf", [
        (33.31, 44.37), (30.51, 47.78), (36.34, 43.12), (31.32, 48.67),
        (29.38, 47.99), (24.71, 46.67), (26.43, 50.10), (25.29, 51.53),
    ]),
    # 2022/2024 India-Pakistan spring heat. Delhi, Lahore, Multan, Faisalabad,
    # Jacobabad, Jaipur, Lucknow, Kanpur.
    RegionDef("Indo-Gangetic Plain", [
        (28.61, 77.23), (31.55, 74.35), (30.20, 71.48), (31.42, 73.09),
        (28.28, 68.44), (26.92, 75.79), (26.84, 80.92), (26.47, 80.35),
    ]),
    # 2023 Beijing 41.1C record. Beijing, Tianjin, Shijiazhuang, Jinan,
    # Zhengzhou, Taiyuan.
    RegionDef("North China Plain", [
        (39.90, 116.41), (39.14, 117.18), (38.04, 114.51),
        (36.65, 117.12), (34.75, 113.63), (37.87, 112.56),
    ]),
    # 2020 Siberian heatwave (Verkhoyansk 38C, "Arctic on fire"). Verkhoyansk,
    # Yakutsk, Norilsk, Khatanga, Tiksi, Chersky.
    RegionDef("East Siberia (Sakha)", [
        (67.55, 133.39), (62.04, 129.74), (69.35, 88.20),
        (71.98, 102.47), (71.64, 128.87), (68.75, 161.34),
    ]),
    # Black Summer 2019-20. Sydney, Melbourne, Adelaide, Canberra, Mildura,
    # Wagga Wagga.
    RegionDef("Southeast Australia", [
        (-33.87, 151.21), (-37.81, 144.96), (-34.93, 138.60),
        (-35.28, 149.13), (-34.19, 142.16), (-35.12, 147.37),
    ]),
    # Dec 2022-Jan 2023 record Southern Cone heatwave. Buenos Aires, Cordoba,
    # Rosario, Santiago, Montevideo, Mendoza.
    RegionDef("Southern South America", [
        (-34.60, -58.38), (-31.41, -64.19), (-32.95, -60.64),
        (-33.45, -70.67), (-34.88, -56.17), (-32.89, -68.84),
    ]),
    # Nov 2023 Brazil heatwave (Rio heat index 58.5C). Sao Paulo, Brasilia,
    # Goiania, Belo Horizonte, Cuiaba, Campo Grande.
    RegionDef("Central Brazil", [
        (-23.55, -46.63), (-15.79, -47.88), (-16.68, -49.25),
        (-19.92, -43.94), (-15.60, -56.10), (-20.44, -54.65),
    ]),
    # Austral-summer Highveld/Kalahari heat. Johannesburg, Pretoria, Bulawayo,
    # Gaborone, Windhoek, Polokwane.
    RegionDef("Southern Africa", [
        (-26.20, 28.04), (-25.74, 28.19), (-20.15, 28.58),
        (-24.65, 25.91), (-22.56, 17.08), (-23.90, 29.45),
    ]),
)

# Startup invariant: every region must carry at least min-sample points, else the
# region mean is too noisy to claim (matches MIN_POINTS).
for _region in REGION_WATCHLIST:
    assert len(_region.points) >= MIN_POINTS, (
        f"REGION_WATCHLIST entry {_region.name!r} has < {MIN_POINTS} sample points"
    )


def all_watchlist_coords() -> list[tuple[float, float]]:
    """Flat, de-duplicated coord list across every region (backfill + live fetch)."""
    seen: list[tuple[float, float]] = []
    known: set[tuple[float, float]] = set()
    for region in REGION_WATCHLIST:
        for pt in region.points:
            if pt not in known:
                known.add(pt)
                seen.append(pt)
    return seen


# --------------------------------------------------------------------------- #
# event
# --------------------------------------------------------------------------- #


@dataclass
class RegionalAnomalyEvent:
    """A region's sampled cities ran far above daily ERA5 normal for >= min_days."""

    region: str  # display name, e.g. "Sahel"
    region_slug: str  # name.replace(" ", "_")
    cities_sampled: int  # distinct sample points contributing across the window
    mean_anomaly_c: float  # point-mean anomaly over the window (the lead metric)
    mean_zscore: float  # mean per-day z-score over the window (gate + writer context)
    fraction_exceeding: float  # window-wide fraction of point-days exceeding +6C
    sustained_days: int  # length of the qualifying consecutive run
    window_start: str  # ISO date of the run's first day
    window_end: str  # ISO date of the run's last qualifying day (the event date)
    event_id: str  # reganom_<region_slug>_<window_end>
    signal_date: date | None = None
    latest_complete_day: str = ""  # most-recent complete ERA5 day this run; ended_days_ago = it - window_end


# --------------------------------------------------------------------------- #
# climatology cache
# --------------------------------------------------------------------------- #


def load_daily_climatology(cache_path: str = "data/climatology_daily_cache.json") -> dict:
    """Load the checked-in daily ERA5 climatology cache.

    Structure: {region_slug: {"lat,lon": {"lat", "lon", "days": {"MM-DD":
    {"mean_c", "std_c", "mean_min_c"}}}}}. Raises SourceSkipped when the cache is
    absent so a not-yet-backfilled deploy records `skipped`, never `failed`.
    """
    if not os.path.exists(cache_path):
        raise SourceSkipped(f"climatology cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# §C — batched, dated live fetch
# --------------------------------------------------------------------------- #


def fetch_all_reganom_t2m(
    all_coords: list[tuple[float, float]],
    *,
    date_range_days: int = DATE_RANGE_DAYS,
    chunk_size: int = CHUNK_SIZE,
) -> dict[tuple[float, float], list[tuple[str, float | None]] | None]:
    """Batched ERA5-archive fetch returning DATED daily-max rows per coord.

    Returns {(lat, lon): [(date_iso, temp_max | None), ...] | None}. A coord maps
    to None when its location response can't be parsed; the whole dict is empty
    ({}) only on total failure (every chunk errored), which the runner treats as
    `degraded`. Fuses the air-quality comma-join/list-parse skeleton with the
    archive endpoint's daily date+temp shape.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    end = date.today()
    start = end - timedelta(days=date_range_days - 1)
    out: dict[tuple[float, float], list[tuple[str, float | None]] | None] = {}

    for chunk_start in range(0, len(all_coords), chunk_size):
        chunk = all_coords[chunk_start : chunk_start + chunk_size]
        lats = ",".join(str(lat) for (lat, _lon) in chunk)
        lons = ",".join(str(lon) for (_lat, lon) in chunk)
        try:
            resp = fetch_with_retry(
                f"{ARCHIVE_URL}/archive",
                timeout=60,
                params={
                    "latitude": lats,
                    "longitude": lons,
                    "daily": "temperature_2m_max",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "timezone": "UTC",
                },
            )
            payload = resp.json()
        except Exception:  # noqa: BLE001 - any transport/JSON failure drops this chunk
            continue

        location_list = payload if isinstance(payload, list) else [payload]
        for offset, loc in enumerate(location_list):
            if offset >= len(chunk):
                break
            coord = chunk[offset]
            if not isinstance(loc, dict):
                out[coord] = None
                continue
            daily = loc.get("daily", {}) or {}
            dates = daily.get("time", [])
            temps = daily.get("temperature_2m_max", [])
            if not dates:
                out[coord] = None
                continue
            out[coord] = list(zip(dates, temps))

    return out


# --------------------------------------------------------------------------- #
# §B + §C — detection
# --------------------------------------------------------------------------- #


def _mmdd(date_iso: str) -> str:
    """MM-DD key, with leap-day 02-29 folded to 02-28.

    The backfill does write a separate 02-29 bucket (from the ~7 leap years in
    1991-2020), but it is intentionally never read: the 02-28 normal is built from
    ~30 samples vs ~7 for 02-29, so folding to 02-28 uses the more robust normal.
    """
    key = date_iso[5:]
    return "02-28" if key == "02-29" else key


def detect_regional_anomaly(
    region: RegionDef,
    climatology: dict,
    live_temps: dict[tuple[float, float], list[tuple[str, float | None]] | None],
    *,
    min_anomaly_c: float = MIN_ANOMALY_C,
    min_days: int = MIN_DAYS,
    min_zscore: float = MIN_ZSCORE,
    min_fraction: float = MIN_FRACTION,
    min_points: int = MIN_POINTS,
    recency_days: int = RECENCY_DAYS,
) -> RegionalAnomalyEvent | None:
    """Fire when a region's sampled points sustain a +6C / >=2sigma / >=50%-support
    anomaly for >= min_days consecutive complete days, where the spell's last day is
    within ``recency_days`` of the most-recent complete day (so a just-ended heatwave
    still fires, not only one ongoing on the latest day). Returns None otherwise (and on
    any defensive cache miss)."""
    region_clim = climatology.get(region.slug)
    if not region_clim:
        return None

    # Per-date aggregates: date_iso -> list of (anomaly, zscore) across valid points.
    per_date: dict[str, list[tuple[float, float]]] = {}
    for lat, lon in region.points:
        rows = live_temps.get((lat, lon))
        if not rows:
            continue
        point_clim = region_clim.get(f"{lat},{lon}")
        if not point_clim:
            continue
        days = point_clim.get("days", {})
        for date_iso, temp in rows:
            if temp is None:
                continue
            day_norm = days.get(_mmdd(date_iso))
            if not day_norm:
                continue
            anomaly = temp - day_norm["mean_c"]
            std = max(float(day_norm.get("std_c", 0.0)), _STD_FLOOR)
            per_date.setdefault(date_iso, []).append((anomaly, anomaly / std))

    if not per_date:
        return None

    # A day "qualifies" only with >= min_points support AND all three §B gates.
    def _day_stats(cells: list[tuple[float, float]]) -> tuple[bool, float, float, float]:
        n = len(cells)
        mean_anom = mean(a for a, _ in cells)
        mean_z = mean(z for _, z in cells)
        frac = sum(1 for a, _ in cells if a >= min_anomaly_c) / n
        qualifies = (
            n >= min_points
            and mean_anom >= min_anomaly_c
            and mean_z >= min_zscore
            and frac >= min_fraction
        )
        return qualifies, mean_anom, mean_z, frac

    complete_dates = sorted(per_date)  # ascending ISO == chronological
    if not complete_dates:
        return None
    latest = date.fromisoformat(complete_dates[-1])

    # Build every maximal run of calendar-consecutive qualifying days.
    runs: list[list[str]] = []
    cur: list[str] = []
    prev: date | None = None
    for date_iso in complete_dates:
        d = date.fromisoformat(date_iso)
        qualifies = _day_stats(per_date[date_iso])[0]
        if qualifies and cur and prev is not None and (d - prev).days == 1:
            cur.append(date_iso)            # extend the current consecutive run
        elif qualifies:
            if cur:
                runs.append(cur)            # a gap (or first qualifying day) starts a new run
            cur = [date_iso]
        else:
            if cur:
                runs.append(cur)            # a non-qualifying day breaks the run
            cur = []
        prev = d
    if cur:
        runs.append(cur)

    # Eligible spells: sustained (>= min_days) AND ended within ``recency_days`` of the
    # most-recent complete day. Fire on the MOST-RECENT eligible spell (so an isolated
    # recent spike can't mask a genuine sustained spell that just eased).
    eligible = [
        r for r in runs
        if len(r) >= min_days and (latest - date.fromisoformat(r[-1])).days <= recency_days
    ]
    if not eligible:
        return None

    run_dates = max(eligible, key=lambda r: r[-1])  # already chronological (ascending)
    window_cells = [cell for d in run_dates for cell in per_date[d]]
    window_mean_anom = mean(a for a, _ in window_cells)
    window_mean_z = mean(z for _, z in window_cells)
    window_frac = sum(1 for a, _ in window_cells if a >= min_anomaly_c) / len(window_cells)

    # Distinct sample points that contributed at least one day in the window.
    contributing: set[tuple[float, float]] = set()
    run_set = set(run_dates)
    for lat, lon in region.points:
        rows = live_temps.get((lat, lon))
        if not rows or not region_clim.get(f"{lat},{lon}"):
            continue
        if any(date_iso in run_set and temp is not None for date_iso, temp in rows):
            contributing.add((lat, lon))

    window_end = run_dates[-1]
    return RegionalAnomalyEvent(
        region=region.name,
        region_slug=region.slug,
        cities_sampled=len(contributing),
        mean_anomaly_c=round(window_mean_anom, 2),
        mean_zscore=round(window_mean_z, 2),
        fraction_exceeding=round(window_frac, 2),
        sustained_days=len(run_dates),
        window_start=run_dates[0],
        window_end=window_end,
        event_id=f"reganom_{region.slug}_{window_end}",
        signal_date=date.fromisoformat(window_end),
        latest_complete_day=complete_dates[-1],
    )
