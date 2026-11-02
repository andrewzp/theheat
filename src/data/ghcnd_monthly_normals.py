"""NOAA GHCN-Daily monthly mean daily maximum per Hot10 place (product noaa-ghcnd-monthly-mean-tmax-v1).

An explicit, versioned alternative to ``meteostat-normals-point-v1`` for the
Hot10 baseline, built offline from the same verified NOAA GHCN-Daily inputs the
threshold build uses (``ghcnd-stations.txt``, ``ghcnd-inventory.txt``,
``ghcnd-version.txt`` and ``ghcnd_all.tar.gz``). It is never labelled Meteostat,
never a record and never mixed with another product:

- statistic: for one station and calendar month, the mean over the qualifying
  years of that year-month's mean daily maximum temperature (``TMAX``), °C. This
  is a climatological average, not the highest value ever observed in the month
  (a monthly record maximum) and not TheHeat's threshold/percentile product;
- fixed period 1991-2020 on every row; values outside the period are ignored;
- QC: a day counts only when ``TMAX`` is present (not -9999), its GHCN quality
  flag (QFLAG) is blank and it is within -90..60 °C; flagged values are rejected
  and counted;
- per station-year-month coverage: at most ``MAX_MISSING_DAYS`` (5) days without a
  valid value and no run of more than ``MAX_CONSECUTIVE_MISSING`` (3) such days;
- per station-calendar-month: at least ``MIN_YEARS`` (24 of 30) qualifying years;
- station for a place-month: the nearest station (haversine, then station id)
  within ``MAX_DISTANCE_M`` (35 km) whose elevation is within
  ``MAX_ELEVATION_DIFF_M`` (350 m) of the place's catalogue elevation and whose
  climatology for that month qualifies. Each row states its station, distance,
  years used and the source version; months of one place may use different
  stations, never different products.

Each row also states its qualifying years (``qualifying_year_mask``: one character per year
1991..2020), so its ``valid_days`` can be bounded exactly: the month's length in each qualifying
year (leap Februaries included) minus at most ``MAX_MISSING_DAYS``. Rejected (flagged) values are
never negative and never exceed the period's free day slots. Coordinates and elevations must be
finite, in range and not the GHCN/Meteostat missing-value sentinels; the place elevation must be
the registered catalogue point's; the station distance is recomputed (haversine) and the stored
0.01 km rounding is the only tolerance.

Install requires at least ``MIN_PLACES_PER_MONTH`` (10) distinct places for every
calendar month, so the Hot10 can hold a full slate whatever the month. The
derived file is for private use: publishing it as a public bulk asset is gated on
Root's terms decision (THRESHOLD-REDISTRIBUTION-SCOPE.md, 2026-10-31).
Loader acceptance and artifact integrity are not scientific qualification.
"""

from __future__ import annotations

import bisect
import calendar
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import tarfile
import tempfile
import time
from typing import Any, BinaryIO, Callable, Iterator

from src.data import acquisition_dependencies as deps
from src.data import places
from src.data.ghcn_format import parse_inventory_file, parse_stations_file
from src.data.temperature_evidence import fingerprint, finite

PRODUCT = "noaa-ghcnd-monthly-mean-tmax-v1"
INPUT_PRODUCT = "noaa-ghcn-daily-v2"
STATISTIC = "mean_daily_maximum"
ELEMENT = "TMAX"
UNIT = "C"
PERIOD = (1991, 2020)
MAX_MISSING_DAYS = 5
MAX_CONSECUTIVE_MISSING = 3
MIN_YEARS = 24
MAX_DISTANCE_M = 35_000
MAX_ELEVATION_DIFF_M = 350.0
VALUE_RANGE_C = (-90.0, 60.0)
MIN_PLACES_PER_MONTH = 10
EARTH_RADIUS_M = 6_371_000
INSTALLED_NAME = "normals_ghcnd_mean_tmax.csv"
DEFAULT_INSTALLED = Path("data") / INSTALLED_NAME
CANDIDATE_SCHEMA = "theheat.ghcnd-normals-candidate/v2"  # v2: rows state their qualifying_year_mask
INSTALL_SCHEMA = "theheat.ghcnd-normals-install-plan/v1"
INPUTS_SCHEMA = "theheat.threshold-inputs/v1"
INPUT_FILES = {"version": "ghcnd-version.txt", "stations": "ghcnd-stations.txt",
               "inventory": "ghcnd-inventory.txt", "archive": "ghcnd_all.tar.gz"}
MAX_TEXT_BYTES = 128 * 1024 * 1024
MAX_CANDIDATE_BYTES = 32 * 1024 * 1024
UNITS = {"mean_tmax_c": "degC", "distance_km": "km", "elevation_m": "m"}
DISTANCE_TOLERANCE_KM = 0.005  # distances are stored rounded to 0.01 km
ELEVATION_RANGE_M = (-500.0, 9000.0)  # excludes the GHCN -999.9 and Meteostat -9999 missing-value sentinels
DATASET = "gov.noaa.ncdc:C00861"
ATTRIBUTION = ("NOAA National Centers for Environmental Information, Global Historical Climatology Network - "
               "Daily (GHCN-Daily), dataset gov.noaa.ncdc:C00861")
COMPARISON_SCOPE = ("NOAA GHCN-Daily station mean daily maximum for the month, 1991-2020 (mean of qualifying "
                    "years' monthly means); not a record maximum")
REDISTRIBUTION = {
    "status": "private_use_release_gated",
    "public_bulk_asset": "refused_until_terms_decision",
    "note": ("Derived from internationally exchanged GHCN-Daily data. NOAA's published conditions describe "
             "country-specific restrictions on some data and on commercial re-export/derived products, and do not "
             "establish a blanket grant for a new public bulk asset (THRESHOLD-REDISTRIBUTION-SCOPE.md, "
             "2026-10-31). Root decides which current terms cover any public asset; private use and ordinary "
             "source-attributed text are not changed by this flag."),
}
RULES = {
    "statistic": STATISTIC, "element": ELEMENT, "unit": UNIT, "period": list(PERIOD),
    "qc": "TMAX present (not -9999), QFLAG blank and -90..60 C; flagged values rejected and counted",
    "year_month": f"at most {MAX_MISSING_DAYS} days without a valid value and no run of more than "
                  f"{MAX_CONSECUTIVE_MISSING} such days",
    "calendar_month": f"at least {MIN_YEARS} qualifying years in {PERIOD[0]}-{PERIOD[1]}; value is the mean of "
                      "those years' monthly means, rounded to 0.1 C",
    "station": f"nearest within {MAX_DISTANCE_M} m and {MAX_ELEVATION_DIFF_M:g} m of the place elevation "
               "(distance, then station id) whose month qualifies",
    "install": f"every calendar month has at least {MIN_PLACES_PER_MONTH} distinct places",
}
FIELDS = ("city", "country", "place_id", "sampling_point_id", "lat", "lon", "place_elevation_m", "month",
          "mean_tmax_c", "unit", "statistic", "source_product", "period_start", "period_end", "years_used",
          "first_year", "last_year", "qualifying_year_mask", "valid_days", "flagged_values", "station_id",
          "station_name", "station_lat", "station_lon", "station_elevation_m", "distance_km", "source_version",
          "retrieved_at")
_STATION_ID = re.compile(r"[A-Z0-9]{11}\Z")



class GhcndNormalsError(deps.AcquisitionError):
    """Fixed labels only."""


# ---------------------------------------------------------------------------
# climatology from one station's .dly text
# ---------------------------------------------------------------------------

@dataclass
class _YearMonth:
    values: dict[int, float]
    flagged: int
    implausible: int


def parse_tmax(text: str, station_id: str, period: tuple[int, int] = PERIOD) -> dict[tuple[int, int], _YearMonth]:
    """``TMAX`` day values inside the period, keyed (year, month); flagged/implausible days are not values.

    Fixed-width .dly layout (NCEI readme IV, as ``ghcn_format``): ID 1-11, YEAR 12-15,
    MONTH 16-17, ELEMENT 18-21, then 31 x (VALUE 5, MFLAG, QFLAG, SFLAG); tenths of °C.
    """
    out: dict[tuple[int, int], _YearMonth] = {}
    for line in text.splitlines():
        if len(line) < 21 or line[17:21] != ELEMENT:
            continue
        if line[0:11].strip() != station_id:
            raise GhcndNormalsError("ghcnd_station_record_mismatch")
        try:
            year, month = int(line[11:15]), int(line[15:17])
        except ValueError:
            raise GhcndNormalsError("ghcnd_record_unreadable") from None
        if not 1 <= month <= 12:
            raise GhcndNormalsError("ghcnd_record_unreadable")
        if not period[0] <= year <= period[1]:
            continue
        if (year, month) in out:
            raise GhcndNormalsError("ghcnd_duplicate_month_record")
        tally = _YearMonth({}, 0, 0)
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            offset = 21 + (day - 1) * 8
            if offset + 7 > len(line):
                break
            try:
                raw = int(line[offset:offset + 5])
            except ValueError:
                raise GhcndNormalsError("ghcnd_record_unreadable") from None
            if raw == -9999:
                continue
            if line[offset + 6:offset + 7].strip():
                tally.flagged += 1
                continue
            value = raw / 10.0
            if not VALUE_RANGE_C[0] <= value <= VALUE_RANGE_C[1]:
                tally.implausible += 1
                continue
            tally.values[day] = value
        out[(year, month)] = tally
    return out


def month_qualifies(year: int, month: int, valid_days: set[int] | dict[int, float]) -> bool:
    """At most MAX_MISSING_DAYS days without a valid value and no run longer than MAX_CONSECUTIVE_MISSING."""
    days = calendar.monthrange(year, month)[1]
    if days - len([d for d in valid_days if 1 <= d <= days]) > MAX_MISSING_DAYS:
        return False
    run = 0
    for day in range(1, days + 1):
        run = 0 if day in valid_days else run + 1
        if run > MAX_CONSECUTIVE_MISSING:
            return False
    return True


def station_climatology(text: str, station_id: str) -> dict[int, dict[str, Any]]:
    """Calendar month -> the qualified mean daily maximum and its coverage (qualifying months only)."""
    by_month: dict[int, list[tuple[int, float, int]]] = {}
    flagged: dict[int, int] = {}
    for (year, month), tally in parse_tmax(text, station_id).items():
        flagged[month] = flagged.get(month, 0) + tally.flagged
        if month_qualifies(year, month, tally.values):
            mean = sum(tally.values.values()) / len(tally.values)
            by_month.setdefault(month, []).append((year, mean, len(tally.values)))
    out: dict[int, dict[str, Any]] = {}
    for month, years in by_month.items():
        if len(years) < MIN_YEARS:
            continue
        value = round(sum(mean for _y, mean, _n in years) / len(years), 1)
        if not finite(value) or not VALUE_RANGE_C[0] <= value <= VALUE_RANGE_C[1]:
            continue
        out[month] = {"mean_tmax_c": value, "years_used": len(years), "first_year": min(y for y, _m, _n in years),
                      "last_year": max(y for y, _m, _n in years),
                      "qualifying_year_mask": year_mask(y for y, _m, _n in years),
                      "valid_days": sum(n for _y, _m, n in years), "flagged_values": flagged.get(month, 0)}
    return out


def year_mask(years: Any) -> str:
    """One character per period year (1991 first): ``1`` where that year-month qualified."""
    chosen = set(years)
    return "".join("1" if year in chosen else "0" for year in range(PERIOD[0], PERIOD[1] + 1))


def mask_years(mask: Any) -> list[int] | None:
    """The qualifying years a mask names, or None when it is not a period mask."""
    if type(mask) is not str or len(mask) != PERIOD[1] - PERIOD[0] + 1 or set(mask) - {"0", "1"}:
        return None
    return [PERIOD[0] + index for index, flag in enumerate(mask) if flag == "1"]


def coverage_problem(month: int, years_used: int, first: int, last: int, mask: Any, valid_days: int,
                     flagged: int) -> str | None:
    """Exact possible-coverage check for one station-month row; None when the counts can be true.

    Each qualifying year contributes between (days in that year's month - MAX_MISSING_DAYS) and the
    month's days valid values (leap Februaries have 29 days); flagged values are counted over every
    period year and share the period's day slots with the valid values.
    """
    years = mask_years(mask)
    if years is None or len(years) != years_used or not years or (years[0], years[-1]) != (first, last):
        return "coverage_impossible"
    days = sum(calendar.monthrange(year, month)[1] for year in years)
    if not days - MAX_MISSING_DAYS * len(years) <= valid_days <= days:
        return "coverage_impossible"
    slots = sum(calendar.monthrange(year, month)[1] for year in range(PERIOD[0], PERIOD[1] + 1))
    if flagged < 0 or valid_days + flagged > slots:
        return "rejection_count_invalid"
    return None


# ---------------------------------------------------------------------------
# station candidates per place
# ---------------------------------------------------------------------------

def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    arch = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(min(1.0, arch)))


def load_points(cities_path: Path) -> list[dict[str, Any]]:
    """Registered catalogue places (aliases collapsed) with their catalogue elevation."""
    points = []
    for city in places.load_cities(str(cities_path)):
        try:
            elevation: float | None = float(city.get("elevation_m") or "")
        except ValueError:
            elevation = None
        points.append({"city": city["city"], "country": city["country"], "place_id": city["place_id"],
                       "sampling_point_id": city["sampling_point_id"], "lat": float(city["lat"]),
                       "lon": float(city["lon"]), "elevation_m": elevation})
    return sorted(points, key=lambda p: (p["place_id"], p["sampling_point_id"]))


def candidates(points: list[dict[str, Any]], stations_text: str, inventory_text: str) -> dict[str, list[dict]]:
    """place_id -> stations within distance/elevation whose TMAX inventory could cover MIN_YEARS of the period."""
    span: dict[str, int] = {}
    for row in parse_inventory_file(inventory_text):
        if row.element == ELEMENT:
            overlap = min(row.last_year, PERIOD[1]) - max(row.first_year, PERIOD[0]) + 1
            span[row.station_id] = max(span.get(row.station_id, 0), overlap)
    usable = sorted((meta for meta in parse_stations_file(stations_text)
                     if span.get(meta.station_id, 0) >= MIN_YEARS and meta.elevation_m > -999
                     and _STATION_ID.fullmatch(meta.station_id)), key=lambda m: (m.lat, m.station_id))
    lats = [meta.lat for meta in usable]
    band = MAX_DISTANCE_M / 111_000 + 0.01
    out: dict[str, list[dict]] = {}
    for point in points:
        rows = []
        if point["elevation_m"] is not None:
            low, high = bisect.bisect_left(lats, point["lat"] - band), bisect.bisect_right(lats, point["lat"] + band)
            for meta in usable[low:high]:
                d = distance_m(point["lat"], point["lon"], meta.lat, meta.lon)
                if d <= MAX_DISTANCE_M and abs(meta.elevation_m - point["elevation_m"]) <= MAX_ELEVATION_DIFF_M:
                    rows.append({"station_id": meta.station_id, "name": meta.name, "lat": meta.lat, "lon": meta.lon,
                                 "elevation_m": meta.elevation_m, "distance_m": d})
        out[point["place_id"]] = sorted(rows, key=lambda r: (r["distance_m"], r["station_id"]))
    return out


# ---------------------------------------------------------------------------
# offline build from verified local inputs
# ---------------------------------------------------------------------------

def _sha_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verified_inputs(inputs_manifest: Path, inputs_dir: Path) -> dict[str, Any]:
    """Root's ``theheat.threshold-inputs/v1`` manifest, with every named local file re-verified (sha256, bytes)."""
    manifest = json.loads(inputs_manifest.read_bytes()[:1_048_576])
    if not isinstance(manifest, dict) or manifest.get("schema") != INPUTS_SCHEMA \
            or manifest.get("source_product") != INPUT_PRODUCT:
        raise GhcndNormalsError("ghcnd_inputs_manifest_invalid")
    identities = {}
    for role, name in INPUT_FILES.items():
        expected = (manifest.get("inputs") or {}).get(role) or {}
        path = inputs_dir / name
        if path.is_symlink() or not path.is_file() or expected.get("name") != name:
            raise GhcndNormalsError(f"ghcnd_input_{role}_missing")
        sha, size = _sha_file(path)
        if sha != expected.get("sha256") or size != expected.get("bytes"):
            raise GhcndNormalsError(f"ghcnd_input_{role}_changed")
        identities[role] = {k: expected.get(k) for k in ("name", "sha256", "bytes", "url", "retrieved_at",
                                                          "last_modified", "etag")}
    version = manifest.get("source_version") or {}
    if not version.get("version") or not identities["archive"].get("retrieved_at"):
        raise GhcndNormalsError("ghcnd_inputs_manifest_invalid")
    return {"inputs": identities, "source_version": {k: version.get(k) for k in (
        "version", "update_started_at", "reprocessed_version", "text_sha256")}}


def _station_texts(handle: BinaryIO, wanted: frozenset[str], check: Callable[[], None]) -> Iterator[tuple[str, str]]:
    with tarfile.open(fileobj=handle, mode="r|gz") as archive:
        for member in archive:
            check()
            if not member.isfile() or not member.name.endswith(".dly"):
                continue
            stem = member.name.rsplit("/", 1)[-1][:-4]
            if stem not in wanted:
                continue
            extracted = archive.extractfile(member)
            if extracted is not None:
                yield stem, extracted.read().decode("ascii", errors="replace")


def build_candidate(cities_path: Path, inputs_manifest: Path, inputs_dir: Path, out_dir: Path, *,
                    deadline_seconds: float = 1200.0, clock: Callable[[], float] = time.monotonic,
                    now: Callable[[], str] | None = None) -> dict[str, Any]:
    """Verified inputs -> candidate CSV + binding manifest. Writes only under ``out_dir``; no network."""
    if not 1 <= deadline_seconds <= 6 * 3600:
        raise GhcndNormalsError("ghcnd_deadline_invalid")
    started = clock()

    def check() -> None:
        if clock() - started > deadline_seconds:
            raise TimeoutError

    source = verified_inputs(inputs_manifest, inputs_dir)
    points = load_points(cities_path)
    stations_text = (inputs_dir / INPUT_FILES["stations"]).read_bytes()[:MAX_TEXT_BYTES].decode("ascii", "replace")
    inventory_text = (inputs_dir / INPUT_FILES["inventory"]).read_bytes()[:MAX_TEXT_BYTES].decode("ascii", "replace")
    near = candidates(points, stations_text, inventory_text)
    wanted = frozenset(row["station_id"] for rows in near.values() for row in rows)
    climatology: dict[str, dict[int, dict[str, Any]]] = {}
    refused: dict[str, str] = {}
    try:
        with (inputs_dir / INPUT_FILES["archive"]).open("rb") as handle:
            for station_id, text in _station_texts(handle, wanted, check):
                if station_id in climatology or station_id in refused:
                    raise GhcndNormalsError("ghcnd_archive_duplicate_station")
                try:
                    climatology[station_id] = station_climatology(text, station_id)
                except GhcndNormalsError as error:
                    refused[station_id] = str(error)
    except TimeoutError:
        return deps.result("normals", "incomplete", reasons=["deadline"],
                           counters={"stations_read": len(climatology), "stations_wanted": len(wanted)})
    retrieved_at = source["inputs"]["archive"]["retrieved_at"]
    version = source["source_version"]["version"]
    rows = []
    for point in points:
        for month in range(1, 13):
            pick = next((station for station in near[point["place_id"]]
                         if month in climatology.get(station["station_id"], {})), None)
            if pick is None:
                continue
            value = climatology[pick["station_id"]][month]
            rows.append({
                "city": point["city"], "country": point["country"], "place_id": point["place_id"],
                "sampling_point_id": point["sampling_point_id"], "lat": repr(point["lat"]), "lon": repr(point["lon"]),
                "place_elevation_m": repr(point["elevation_m"]), "month": str(month),
                "mean_tmax_c": repr(value["mean_tmax_c"]), "unit": UNIT, "statistic": STATISTIC,
                "source_product": PRODUCT, "period_start": str(PERIOD[0]), "period_end": str(PERIOD[1]),
                **{k: str(value[k]) for k in ("years_used", "first_year", "last_year", "qualifying_year_mask",
                                              "valid_days", "flagged_values")},
                "station_id": pick["station_id"], "station_name": pick["name"], "station_lat": repr(pick["lat"]),
                "station_lon": repr(pick["lon"]), "station_elevation_m": repr(pick["elevation_m"]),
                "distance_km": repr(round(pick["distance_m"] / 1000, 2)), "source_version": version,
                "retrieved_at": retrieved_at})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(FIELDS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    body = buffer.getvalue().encode("utf-8")
    coverage = population(rows)
    manifest = {
        "schema": CANDIDATE_SCHEMA, "product": PRODUCT, "rules": RULES, "csv": "normals.csv",
        "csv_sha256": hashlib.sha256(body).hexdigest(), "csv_bytes": len(body), "rows": len(rows),
        "inputs": source["inputs"], "source_version": source["source_version"], "input_product": INPUT_PRODUCT,
        "cities": {"sha256": _sha_file(cities_path)[0], "points": len(points)},
        "stations": {"candidates": len(wanted), "read": len(climatology), "refused": dict(sorted(refused.items())),
                     "with_any_qualified_month": sum(1 for v in climatology.values() if v)},
        "coverage": coverage, "attribution": ATTRIBUTION, "dataset": DATASET, "redistribution": REDISTRIBUTION,
        "units": dict(UNITS),
        "assembled_at": (now or _utc_now)(),
    }
    _atomic_write(out_dir / "candidate" / "normals.csv", body)
    _atomic_write(out_dir / "candidate" / "manifest.json", _canonical(manifest))
    return deps.result("normals", "ready" if rows else "source_absent",
                       reasons=[] if coverage["hot10_ready"] else ["fewer_than_ten_places_in_some_month"],
                       product={"candidate_sha256": manifest["csv_sha256"], "rows": len(rows),
                                "places": coverage["places"], "min_places_per_month": coverage["min_places_per_month"],
                                "product": PRODUCT},
                       counters={"stations_wanted": len(wanted), "stations_read": len(climatology)},
                       observed=len(points) * 12, promoted=len(rows))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def population(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinct qualified places per calendar month; the install rule needs every month >= 10."""
    by_month: dict[int, set[str]] = {month: set() for month in range(1, 13)}
    for row in rows:
        by_month[int(row["month"])].add(str(row["place_id"]))
    every = set.intersection(*by_month.values()) if rows else set()
    minimum = min(len(ids) for ids in by_month.values())
    return {"places": len({str(row["place_id"]) for row in rows}), "places_all_months": len(every),
            "places_by_month": {str(month): len(ids) for month, ids in by_month.items()},
            "min_places_per_month": minimum, "hot10_ready": minimum >= MIN_PLACES_PER_MONTH,
            "rule": RULES["install"]}


# ---------------------------------------------------------------------------
# loader (the Hot10 consumer reads only this product's own file)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _registered_points() -> dict[str, tuple[str, float | None]]:
    out: dict[str, tuple[str, float | None]] = {}
    for entry in places.registry():
        elevation = entry.get("elevation_m")
        out[entry["place_id"]] = (places.sampling_point_id(entry["lat"], entry["lon"]),
                                  float(elevation) if finite(elevation) else None)
    return out


def registered_elevation(place_id: Any, lat: Any, lon: Any) -> float | None:
    """The catalogue elevation of ``place_id``'s registered point when (lat, lon) is that point, else None."""
    try:
        point = places.sampling_point_id(lat, lon)
    except (TypeError, ValueError):
        return None
    registered = _registered_points().get(place_id) if isinstance(place_id, str) else None
    return registered[1] if registered is not None and registered[0] == point else None


def _in_range(lat: float, lon: float) -> bool:
    return finite(lat) and finite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def _row_problem(row: dict[str, str]) -> str | None:
    """None when one candidate/installed row satisfies the product contract, else a fixed reason."""
    if row.get("source_product") != PRODUCT:
        return "mixed_products"
    if row.get("statistic") != STATISTIC or row.get("unit") != UNIT:
        return "statistic_or_unit_invalid"
    try:
        period = (int(row["period_start"]), int(row["period_end"]))
        month, value = int(row["month"]), float(row["mean_tmax_c"])
        years, first, last = int(row["years_used"]), int(row["first_year"]), int(row["last_year"])
        distance = float(row["distance_km"])
        place_elevation, station_elevation = float(row["place_elevation_m"]), float(row["station_elevation_m"])
        lat, lon = float(row["lat"]), float(row["lon"])
        station_lat, station_lon = float(row["station_lat"]), float(row["station_lon"])
        valid_days, flagged = int(row["valid_days"]), int(row["flagged_values"])
        mask = row["qualifying_year_mask"]
    except (KeyError, TypeError, ValueError):
        return "row_unparseable"
    if period != PERIOD:
        return "wrong_period"
    if not (MIN_YEARS <= years <= PERIOD[1] - PERIOD[0] + 1 and PERIOD[0] <= first <= last <= PERIOD[1]
            and last - first + 1 >= years):
        return "insufficient_coverage"
    if not 1 <= month <= 12 or not finite(value) or not VALUE_RANGE_C[0] <= value <= VALUE_RANGE_C[1]:
        return "value_invalid"
    if not 0 <= distance <= MAX_DISTANCE_M / 1000:
        return "station_out_of_range"
    if not _in_range(lat, lon) or not _in_range(station_lat, station_lon):
        return "coordinates_invalid"
    if not all(finite(v) and ELEVATION_RANGE_M[0] <= v <= ELEVATION_RANGE_M[1]
               for v in (place_elevation, station_elevation)):
        return "elevation_invalid"
    actual_km = distance_m(lat, lon, station_lat, station_lon) / 1000
    if abs(station_elevation - place_elevation) > MAX_ELEVATION_DIFF_M or actual_km > MAX_DISTANCE_M / 1000:
        return "station_out_of_range"
    if abs(actual_km - distance) > DISTANCE_TOLERANCE_KM + 1e-9:
        return "station_distance_misstated"
    problem = coverage_problem(month, years, first, last, mask, valid_days, flagged)
    if problem is not None:
        return problem
    if not _STATION_ID.fullmatch(row.get("station_id") or "") or not row.get("source_version") \
            or not row.get("retrieved_at"):
        return "provenance_missing"
    return None


def _place_problem(row: dict[str, str]) -> tuple[str | None, dict[str, Any], str]:
    """(problem, registry identity, location key) for a row whose own fields already passed ``_row_problem``."""
    try:
        identity = places.place_for_row(row)
        key = places.event_location_key(row["city"], row["country"], row["lat"], row["lon"], place_id=row["place_id"])
    except (KeyError, ValueError, TypeError):
        return "unregistered_place", {}, ""
    if identity["sampling_point_id"] != row["sampling_point_id"]:
        return "point_identity_mismatch", identity, key
    if registered_elevation(identity["place_id"], identity["lat"], identity["lon"]) != float(row["place_elevation_m"]):
        return "place_elevation_unregistered", identity, key
    return None, identity, key


def provenance(row: dict[str, str], identity: dict[str, Any]) -> dict[str, Any]:
    """What a Hot10 row retains about its baseline (the contract's GHCND baseline keys)."""
    meta: dict[str, Any] = {
        "source_product": PRODUCT, "evidence_type": "station_climatology", "statistic": STATISTIC,
        "period_start": PERIOD[0], "period_end": PERIOD[1], "retrieved_at": row["retrieved_at"],
        "sampling_point_id": identity["sampling_point_id"], "unit": UNIT, "month": int(row["month"]),
        "years_used": int(row["years_used"]), "first_year": int(row["first_year"]),
        "last_year": int(row["last_year"]), "qualifying_year_mask": row["qualifying_year_mask"],
        "valid_days": int(row["valid_days"]), "flagged_values": int(row["flagged_values"]),
        "station_id": row["station_id"], "station_name": row["station_name"],
        "station_lat": float(row["station_lat"]), "station_lon": float(row["station_lon"]),
        "station_elevation_m": float(row["station_elevation_m"]),
        "place_elevation_m": float(row["place_elevation_m"]), "distance_km": float(row["distance_km"]),
        "source_version": row["source_version"], "sample_count": int(row["valid_days"]),
        "coverage_fraction": round(int(row["years_used"]) / (PERIOD[1] - PERIOD[0] + 1), 4),
        "comparison_scope": COMPARISON_SCOPE,
    }
    meta["revision_id"] = fingerprint({"value": float(row["mean_tmax_c"]), **meta})
    return meta


def load_normals(path: str | Path = DEFAULT_INSTALLED, report: dict[str, Any] | None = None) -> dict[str, dict]:
    """This product's installed file -> the Hot10 normals mapping; a file holding any other product is refused whole.

    Same shape as ``open_meteo.load_normals``: ``{location_key: {month: value, "_meta": {month: provenance}}}``.
    Never falls back to another product or file.
    """
    report = report if report is not None else {}
    report.update(product=PRODUCT, path=str(path), rows=0, accepted=0, refused={}, status="absent")
    normals: dict[str, dict] = {}
    target = Path(path)
    if not target.exists():
        return normals
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_CANDIDATE_BYTES:
        report["status"] = "refused_file"
        return normals
    reader = csv.DictReader(io.StringIO(target.read_text(encoding="utf-8")))
    if tuple(reader.fieldnames or ()) != FIELDS:
        report["status"] = "refused_schema"
        return normals
    rows = list(reader)
    report["rows"] = len(rows)
    if any(row.get("source_product") != PRODUCT for row in rows):
        report["status"] = "refused_mixed_products"  # never a partial read of a mixed file
        return normals
    refused: dict[str, int] = {}
    for row in rows:
        problem = _row_problem(row)
        identity: dict[str, Any] = {}
        key = ""
        if problem is None:
            problem, identity, key = _place_problem(row)
        if problem is not None:
            refused[problem] = refused.get(problem, 0) + 1
            continue
        month, value = int(row["month"]), float(row["mean_tmax_c"])
        meta = provenance(row, identity)
        entry = normals.setdefault(key, {"_meta": {}})
        if month in entry and (entry[month] != value or entry["_meta"][month] != meta):
            entry.pop(month)
            entry["_meta"][month] = {"conflict": True}
        elif not entry["_meta"].get(month, {}).get("conflict"):
            entry[month], entry["_meta"][month] = value, meta
    report.update(refused=dict(sorted(refused.items())), status="loaded",
                  accepted=sum(1 for entry in normals.values() for month in entry if isinstance(month, int)))
    return normals


# ---------------------------------------------------------------------------
# admission and install plan (Root installs)
# ---------------------------------------------------------------------------

def _read_candidate(candidate_dir: Path) -> tuple[dict[str, Any], bytes]:
    manifest_path, body_path = candidate_dir / "manifest.json", candidate_dir / "normals.csv"
    for path in (manifest_path, body_path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CANDIDATE_BYTES:
            raise GhcndNormalsError("ghcnd_candidate_unreadable")
    return json.loads(manifest_path.read_bytes()), body_path.read_bytes()


def admit(candidate_dir: Path) -> dict[str, Any]:
    """Schema, binding, per-row product contract, mixed-product refusal and actual-loader acceptance."""
    try:
        manifest, body = _read_candidate(candidate_dir)
    except (OSError, ValueError, deps.AcquisitionError):
        return deps.result("normals", "product_invalid", reasons=["candidate_unreadable"])
    if not isinstance(manifest, dict) or manifest.get("schema") != CANDIDATE_SCHEMA or manifest.get("product") != PRODUCT:
        return deps.result("normals", "product_invalid", reasons=["candidate_manifest_schema"])
    reasons: list[str] = []
    if manifest.get("csv_sha256") != hashlib.sha256(body).hexdigest() or manifest.get("csv_bytes") != len(body):
        reasons.append("candidate_csv_not_bound_by_manifest")
    if manifest.get("rules") != RULES or manifest.get("redistribution") != REDISTRIBUTION:
        reasons.append("candidate_rules_altered")
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if tuple(reader.fieldnames or ()) != FIELDS:
        return deps.result("normals", "product_invalid", reasons=sorted(set(reasons + ["candidate_schema_incompatible"])))
    rows = list(reader)
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        problem = _row_problem(row)
        if problem is None:
            problem = _place_problem(row)[0]
        if problem is not None:
            reasons.append(problem)
        key = (row.get("place_id", ""), row.get("sampling_point_id", ""), row.get("month", ""))
        if key in seen:
            reasons.append("duplicate_point_month")
        seen.add(key)
    coverage = population(rows) if not reasons else None
    accepted = 0
    if not reasons:
        with tempfile.TemporaryDirectory(prefix="theheat-ghcnd-admission-") as scratch:
            copy = Path(scratch) / INSTALLED_NAME
            copy.write_bytes(body)
            report: dict[str, Any] = {}
            loaded = load_normals(copy, report)
        accepted = sum(1 for entry in loaded.values() for month in entry if isinstance(month, int))
        if accepted != len(rows):
            reasons.append("loader_refused_rows")
    status = "product_invalid" if reasons else ("ready" if rows else "source_absent")
    return deps.result("normals", status, reasons=reasons,
                       product={"product": PRODUCT, "candidate_sha256": manifest.get("csv_sha256"), "rows": len(rows),
                                "loader_accepted_point_months": accepted,
                                "coverage": coverage, "redistribution": REDISTRIBUTION["status"]},
                       observed=len(rows), promoted=accepted)


def _installed_rows(path: Path) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise GhcndNormalsError("ghcnd_install_target_holds_another_product")
    rows = list(reader)
    if any(row.get("source_product") != PRODUCT for row in rows):
        raise GhcndNormalsError("ghcnd_install_target_holds_another_product")
    return rows


def install_plan(candidate_dir: Path, installed_path: Path) -> dict[str, Any]:
    """Admitted candidate vs this product's own installed file; a retained rollback copy. Root installs."""
    if installed_path.name != INSTALLED_NAME:
        raise GhcndNormalsError("ghcnd_install_target_not_product_path")  # never data/normals.csv
    admission = admit(candidate_dir)
    if admission["status"] != "ready":
        raise GhcndNormalsError("ghcnd_candidate_not_admitted")
    coverage = admission["product"]["coverage"]
    if coverage["min_places_per_month"] < MIN_PLACES_PER_MONTH:
        raise GhcndNormalsError("ghcnd_candidate_fewer_than_ten_places")
    manifest, body = _read_candidate(candidate_dir)
    previous = None
    old: dict[tuple[str, str, int], float] = {}
    if installed_path.exists():
        rows = _installed_rows(installed_path)
        raw = installed_path.read_bytes()
        previous = {"name": installed_path.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                    "git_blob_sha1": hashlib.sha1(b"blob %d\0" % len(raw) + raw, usedforsecurity=False).hexdigest()}
        old = {(r["place_id"], r["sampling_point_id"], int(r["month"])): float(r["mean_tmax_c"]) for r in rows}
    new = {(r["place_id"], r["sampling_point_id"], int(r["month"])): float(r["mean_tmax_c"])
           for r in csv.DictReader(io.StringIO(body.decode("utf-8")))}
    rollback = None
    if previous is not None:
        rollback = candidate_dir / "rollback" / f"{installed_path.stem}-{previous['sha256'][:16]}.csv"
        _atomic_write(rollback, installed_path.read_bytes())
    candidate_sha = hashlib.sha256(body).hexdigest()
    plan = {
        "schema": INSTALL_SCHEMA, "product": PRODUCT, "admission": admission["status"],
        "candidate": {"path": str(candidate_dir / "normals.csv"), "sha256": candidate_sha, "bytes": len(body),
                      "source_version": manifest.get("source_version"), "inputs": manifest.get("inputs")},
        "previous": previous, "coverage": coverage,
        "comparison": {"added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
                       "changed": sum(1 for k in old.keys() & new.keys() if old[k] != new[k])},
        "install": {"performed_by": "root", "target": str(installed_path),
                    "requires": ["terms decision: committing this file to a public repository or any public "
                                 "asset publishes derived GHCN-Daily values (redistribution.status "
                                 "private_use_release_gated); decide the covering terms or use a private "
                                 "delivery path first"],
                    "steps": [f"verify sha256 {candidate_sha} of {candidate_dir / 'normals.csv'}",
                              f"copy {candidate_dir / 'normals.csv'} -> {installed_path}",
                              "commit the installed file with the candidate manifest and this plan only "
                              "after the terms decision above",
                              "only then set THEHEAT_HOT10_NORMALS_PRODUCT=" + PRODUCT + " (default stays "
                              "meteostat-normals-point-v1; unset or that value restores it)"]},
        "rollback": None if previous is None else {"retained_copy": str(rollback), "sha256": previous["sha256"],
                                                   "steps": [f"copy {rollback} -> {installed_path}",
                                                             "or unset THEHEAT_HOT10_NORMALS_PRODUCT"]},
        "redistribution": REDISTRIBUTION, "attribution": ATTRIBUTION,
        "scientific_qualification": "not_established_by_loader_acceptance",
    }
    _atomic_write(candidate_dir / "install-plan.json", _canonical(plan))
    return plan


__all__ = ["ATTRIBUTION", "CANDIDATE_SCHEMA", "COMPARISON_SCOPE", "DEFAULT_INSTALLED", "DISTANCE_TOLERANCE_KM",
           "ELEVATION_RANGE_M", "FIELDS", "GhcndNormalsError", "INSTALLED_NAME", "MAX_CONSECUTIVE_MISSING",
           "MAX_DISTANCE_M", "MAX_ELEVATION_DIFF_M", "MAX_MISSING_DAYS", "MIN_PLACES_PER_MONTH", "MIN_YEARS", "PERIOD",
           "PRODUCT", "REDISTRIBUTION", "RULES", "STATISTIC", "admit", "build_candidate", "candidates",
           "coverage_problem", "install_plan", "load_normals", "load_points", "mask_years", "month_qualifies",
           "parse_tmax", "population", "provenance", "registered_elevation", "station_climatology", "year_mask"]
