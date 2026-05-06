"""NOAA GHCN-Daily file format parsers.

Handles two NOAA formats:
  .dly  — fixed-width per-station daily archive (all/{ID}.dly)
  diff  — superghcnd_diff incremental delta records (same fixed-width layout)

Spec refs:
  NCEI readme §III (station inventory), §IV (daily format):
  https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt

.dly record layout (one line = one station/year/month/element):
  cols  1-11   station ID
  cols 12-15   year
  cols 16-17   month
  cols 18-21   element (TMAX, TMIN, PRCP, SNOW, SNWD, TAVG, …)
  cols 22-269  31 day-values, each VALUE(5) MFLAG(1) QFLAG(1) SFLAG(1) = 8 chars

Temperature values are in tenths of °C; missing = -9999.
Values with QFLAG != '' (i.e. a quality-failure flag) are excluded.

This module is stdlib-only. Zero external dependencies.
"""

from __future__ import annotations

import gzip
import io
from dataclasses import dataclass
from datetime import date
from typing import Generator, Iterable


# ---------------------------------------------------------------------------
# Station inventory (ghcnd-stations.txt)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class StationMeta:
    """One row from ghcnd-stations.txt."""
    station_id: str       # 11-char GHCN ID, e.g. "USW00023183"
    lat: float
    lon: float
    elevation_m: float    # metres; -999.9 = missing
    state: str            # 2-char US state code or blank
    name: str             # up to 30 chars
    gsn_flag: str         # "GSN" or blank
    hcn_crn_flag: str     # "HCN", "CRN", or blank
    wmo_id: str           # 5-digit WMO ID or blank

    def country_code_inferred(self) -> str:
        """Return the 2-char country prefix from the station ID.

        GHCN IDs are structured as:
          2-char country code + network code + numeric suffix
        e.g. "USW00023183" → country = "US"
             "RSM00024266" → country = "RS"
             "IN019180300" → country = "IN"
        """
        return self.station_id[:2]


def parse_stations_file(text: str) -> list[StationMeta]:
    """Parse ghcnd-stations.txt (fixed-width) into a list of StationMeta.

    Column positions are 1-indexed per the NCEI readme:
      1-11   ID
      13-20  LATITUDE
      22-30  LONGITUDE
      32-37  ELEVATION
      39-40  STATE
      42-71  NAME
      73-75  GSN FLAG
      77-79  HCN/CRN FLAG
      81-85  WMO ID
    """
    stations: list[StationMeta] = []
    for line in text.splitlines():
        if len(line) < 30:
            continue
        station_id = line[0:11].strip()
        if not station_id:
            continue
        try:
            lat = float(line[12:20].strip())
            lon = float(line[21:30].strip())
            elev_str = line[31:37].strip()
            elevation_m = float(elev_str) if elev_str else -999.9
            state = line[38:40].strip() if len(line) > 40 else ""
            name = line[41:71].strip() if len(line) > 41 else ""
            gsn_flag = line[72:75].strip() if len(line) > 75 else ""
            hcn_crn_flag = line[76:79].strip() if len(line) > 79 else ""
            wmo_id = line[80:85].strip() if len(line) > 80 else ""
        except (ValueError, IndexError):
            continue
        stations.append(StationMeta(
            station_id=station_id,
            lat=lat,
            lon=lon,
            elevation_m=elevation_m,
            state=state,
            name=name,
            gsn_flag=gsn_flag,
            hcn_crn_flag=hcn_crn_flag,
            wmo_id=wmo_id,
        ))
    return stations


# ---------------------------------------------------------------------------
# Element inventory (ghcnd-inventory.txt)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ElementInventory:
    """One row from ghcnd-inventory.txt."""
    station_id: str
    element: str     # TMAX, TMIN, PRCP, …
    first_year: int
    last_year: int


def parse_inventory_file(text: str) -> list[ElementInventory]:
    """Parse ghcnd-inventory.txt into a list of ElementInventory.

    Format: space-delimited:
      ID LAT LON ELEMENT FIRSTYEAR LASTYEAR
    """
    rows: list[ElementInventory] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            rows.append(ElementInventory(
                station_id=parts[0],
                element=parts[3],
                first_year=int(parts[4]),
                last_year=int(parts[5]),
            ))
        except (ValueError, IndexError):
            continue
    return rows


# ---------------------------------------------------------------------------
# Country / state lookups
# ---------------------------------------------------------------------------

def parse_countries_file(text: str) -> dict[str, str]:
    """Parse ghcnd-countries.txt → {code: name}.

    Format: CODE<space>NAME  (code is first 2 chars)
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        if len(line) < 3:
            continue
        code = line[0:2].strip()
        name = line[3:].strip()
        if code:
            out[code] = name
    return out


# ---------------------------------------------------------------------------
# Daily observation
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DailyObs:
    """One valid temperature observation parsed from a .dly record."""
    station_id: str
    obs_date: date
    element: str     # "TMAX" or "TMIN"
    value_c: float   # converted from tenths-of-°C


# ---------------------------------------------------------------------------
# .dly fixed-width parser
# ---------------------------------------------------------------------------

_MISSING = -9999


def _parse_dly_line(
    line: str,
    elements: frozenset[str] | None = None,
) -> Generator[DailyObs, None, None]:
    """Yield DailyObs from one .dly line.

    Args:
        line: one raw text line from a .dly file (≥269 chars expected).
        elements: if provided, only yield obs for elements in this set.
                  None means yield all elements.
    """
    if len(line) < 21:
        return

    station_id = line[0:11].strip()
    try:
        year = int(line[11:15])
        month = int(line[15:17])
        element = line[17:21].strip()
    except (ValueError, IndexError):
        return

    if elements is not None and element not in elements:
        return

    # 31 day-values starting at col 22 (0-indexed: 21), each 8 chars wide
    for day in range(1, 32):
        offset = 21 + (day - 1) * 8
        if offset + 8 > len(line):
            break
        value_str = line[offset:offset + 5]
        qflag = line[offset + 6:offset + 7]  # quality flag (col 7 of the 8)

        try:
            raw = int(value_str)
        except ValueError:
            continue

        # Skip missing and quality-failed values
        if raw == _MISSING or qflag.strip():
            continue

        # Validate month/day combination
        try:
            obs_date = date(year, month, day)
        except ValueError:
            continue  # e.g. Feb 30

        yield DailyObs(
            station_id=station_id,
            obs_date=obs_date,
            element=element,
            value_c=raw / 10.0,
        )


def parse_dly_text(
    text: str,
    elements: frozenset[str] | None = frozenset({"TMAX", "TMIN"}),
) -> list[DailyObs]:
    """Parse all observations from a complete .dly file text."""
    obs: list[DailyObs] = []
    for line in text.splitlines():
        obs.extend(_parse_dly_line(line, elements))
    return obs


def parse_dly_bytes(
    data: bytes,
    elements: frozenset[str] | None = frozenset({"TMAX", "TMIN"}),
) -> list[DailyObs]:
    """Parse all observations from raw .dly bytes (uncompressed)."""
    return parse_dly_text(data.decode("ascii", errors="replace"), elements)


def parse_dly_gz_bytes(
    gz_data: bytes,
    elements: frozenset[str] | None = frozenset({"TMAX", "TMIN"}),
) -> list[DailyObs]:
    """Parse a gzip-compressed .dly file from raw bytes."""
    return parse_dly_bytes(gzip.decompress(gz_data), elements)


def stream_dly_from_tar(
    tar_fileobj: io.IOBase,
    elements: frozenset[str] | None = frozenset({"TMAX", "TMIN"}),
    station_ids: frozenset[str] | None = None,
) -> Generator[DailyObs, None, None]:
    """Stream DailyObs from a ghcnd_all.tar.gz file object.

    Args:
        tar_fileobj: open binary file object positioned at start of tarball.
        elements: filter by element; None means all.
        station_ids: if provided, only yield obs for stations in this set.
                     None means all stations.

    Memory-efficient: reads one .dly member at a time. Suitable for the
    3.44 GB ghcnd_all.tar.gz bootstrap without loading everything into RAM.
    """
    import tarfile

    with tarfile.open(fileobj=tar_fileobj, mode="r:gz") as tf:
        for member in tf:
            if not member.name.endswith(".dly"):
                continue
            # Member name is like "ghcnd_all/USW00023183.dly"
            stem = member.name.rsplit("/", 1)[-1].replace(".dly", "")
            if station_ids is not None and stem not in station_ids:
                continue

            f = tf.extractfile(member)
            if f is None:
                continue
            text = f.read().decode("ascii", errors="replace")
            yield from (
                obs
                for line in text.splitlines()
                for obs in _parse_dly_line(line, elements)
            )


# ---------------------------------------------------------------------------
# superghcnd_diff parser
# ---------------------------------------------------------------------------

def parse_superghcnd_diff_text(
    text: str,
    elements: frozenset[str] | None = frozenset({"TMAX", "TMIN"}),
) -> list[DailyObs]:
    """Parse a superghcnd_diff file.

    superghcnd_diff files use the same fixed-width .dly record format.
    Each line represents updated/inserted records for a station/month.
    Parsing is identical to a regular .dly file.
    """
    return parse_dly_text(text, elements)


def parse_superghcnd_diff_bytes(
    data: bytes,
    elements: frozenset[str] | None = frozenset({"TMAX", "TMIN"}),
) -> list[DailyObs]:
    """Parse raw bytes from a superghcnd_diff file (may be plain or gzip)."""
    if data[:2] == b"\x1f\x8b":  # gzip magic bytes
        data = gzip.decompress(data)
    return parse_dly_bytes(data, elements)


# ---------------------------------------------------------------------------
# Threshold computation
# ---------------------------------------------------------------------------

@dataclass
class StationThresholds:
    """Computed record thresholds for one station, derived from its full archive."""
    station_id: str
    all_time_max_c: float | None = None
    all_time_max_year: int | None = None
    all_time_min_c: float | None = None
    all_time_min_year: int | None = None
    # {month: (max_c, max_year)}
    monthly_max: dict[int, tuple[float, int]] = None  # type: ignore[assignment]
    # {month: (min_c, min_year)}
    monthly_min: dict[int, tuple[float, int]] = None  # type: ignore[assignment]
    # {(month, day): (max_c, max_year)}
    calendar_date_max: dict[tuple[int, int], tuple[float, int]] = None  # type: ignore[assignment]
    # {(month, day): (min_c, min_year)}
    calendar_date_min: dict[tuple[int, int], tuple[float, int]] = None  # type: ignore[assignment]
    # {month: mean_max_c}  (climatological mean of TMAX by month)
    climatological_mean: dict[int, float] = None  # type: ignore[assignment]
    archive_years: int = 0

    def __post_init__(self) -> None:
        if self.monthly_max is None:
            self.monthly_max = {}
        if self.monthly_min is None:
            self.monthly_min = {}
        if self.calendar_date_max is None:
            self.calendar_date_max = {}
        if self.calendar_date_min is None:
            self.calendar_date_min = {}
        if self.climatological_mean is None:
            self.climatological_mean = {}


def compute_thresholds(obs: Iterable[DailyObs]) -> StationThresholds | None:
    """Compute record thresholds from an iterable of DailyObs for one station.

    Returns None if no valid observations are provided.
    The caller is responsible for passing obs from a single station only.
    """
    tmax_obs: list[DailyObs] = []
    tmin_obs: list[DailyObs] = []

    station_id: str | None = None

    for o in obs:
        if station_id is None:
            station_id = o.station_id
        if o.element == "TMAX":
            tmax_obs.append(o)
        elif o.element == "TMIN":
            tmin_obs.append(o)

    if station_id is None:
        return None

    thresholds = StationThresholds(station_id=station_id)

    # ---- TMAX thresholds ----
    if tmax_obs:
        # All-time max
        best = max(tmax_obs, key=lambda o: o.value_c)
        thresholds.all_time_max_c = best.value_c
        thresholds.all_time_max_year = best.obs_date.year

        # Monthly max: best TMAX per month across all years
        by_month: dict[int, list[DailyObs]] = {}
        by_month_day: dict[tuple[int, int], list[DailyObs]] = {}
        monthly_sums: dict[int, list[float]] = {}

        for o in tmax_obs:
            m = o.obs_date.month
            md = (o.obs_date.month, o.obs_date.day)
            by_month.setdefault(m, []).append(o)
            by_month_day.setdefault(md, []).append(o)
            monthly_sums.setdefault(m, []).append(o.value_c)

        for m, obs_list in by_month.items():
            best_m = max(obs_list, key=lambda o: o.value_c)
            thresholds.monthly_max[m] = (best_m.value_c, best_m.obs_date.year)

        for md, obs_list in by_month_day.items():
            best_md = max(obs_list, key=lambda o: o.value_c)
            thresholds.calendar_date_max[md] = (best_md.value_c, best_md.obs_date.year)

        # Climatological mean TMAX by month (mean of all observed TMAX values)
        for m, values in monthly_sums.items():
            thresholds.climatological_mean[m] = sum(values) / len(values)

        # Archive years = span from first to last obs
        first_year = min(o.obs_date.year for o in tmax_obs)
        last_year = max(o.obs_date.year for o in tmax_obs)
        thresholds.archive_years = last_year - first_year + 1

    # ---- TMIN thresholds ----
    if tmin_obs:
        worst = min(tmin_obs, key=lambda o: o.value_c)
        thresholds.all_time_min_c = worst.value_c
        thresholds.all_time_min_year = worst.obs_date.year

        by_month_min: dict[int, list[DailyObs]] = {}
        by_month_day_min: dict[tuple[int, int], list[DailyObs]] = {}

        for o in tmin_obs:
            m = o.obs_date.month
            md = (o.obs_date.month, o.obs_date.day)
            by_month_min.setdefault(m, []).append(o)
            by_month_day_min.setdefault(md, []).append(o)

        for m, obs_list in by_month_min.items():
            worst_m = min(obs_list, key=lambda o: o.value_c)
            thresholds.monthly_min[m] = (worst_m.value_c, worst_m.obs_date.year)

        for md, obs_list in by_month_day_min.items():
            worst_md = min(obs_list, key=lambda o: o.value_c)
            thresholds.calendar_date_min[md] = (worst_md.value_c, worst_md.obs_date.year)

    return thresholds


def update_thresholds_with_obs(
    existing: StationThresholds,
    new_obs: Iterable[DailyObs],
) -> bool:
    """Mutate `existing` to incorporate any new records from `new_obs`.

    Returns True if any threshold was updated.
    """
    updated = False

    for o in new_obs:
        v = o.value_c
        y = o.obs_date.year
        m = o.obs_date.month
        md = (o.obs_date.month, o.obs_date.day)

        if o.element == "TMAX":
            if existing.all_time_max_c is None or v > existing.all_time_max_c:
                existing.all_time_max_c = v
                existing.all_time_max_year = y
                updated = True

            cur_m = existing.monthly_max.get(m)
            if cur_m is None or v > cur_m[0]:
                existing.monthly_max[m] = (v, y)
                updated = True

            cur_md = existing.calendar_date_max.get(md)
            if cur_md is None or v > cur_md[0]:
                existing.calendar_date_max[md] = (v, y)
                updated = True

        elif o.element == "TMIN":
            if existing.all_time_min_c is None or v < existing.all_time_min_c:
                existing.all_time_min_c = v
                existing.all_time_min_year = y
                updated = True

            cur_m = existing.monthly_min.get(m)
            if cur_m is None or v < cur_m[0]:
                existing.monthly_min[m] = (v, y)
                updated = True

            cur_md = existing.calendar_date_min.get(md)
            if cur_md is None or v < cur_md[0]:
                existing.calendar_date_min[md] = (v, y)
                updated = True

    return updated
