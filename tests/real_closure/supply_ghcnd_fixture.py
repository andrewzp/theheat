"""Invented NOAA GHCN-Daily inputs in the real file formats (test-only; no NOAA bytes).

Fixed-width ``ghcnd-stations.txt`` and ``.dly`` records, whitespace
``ghcnd-inventory.txt``, the ``ghcnd-version.txt`` sentence, a ``ghcnd_all.tar.gz``
with ``ghcnd_all/<ID>.dly`` members and Root's ``theheat.threshold-inputs/v1``
manifest binding them. Station ids, names and values are invented.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile
from typing import Callable

from src.data import ghcnd_monthly_normals as gn
from src.data import places
from tests import live_content_harness as h

VERSION_TEXT = ("The current version of GHCN Daily is 3.35-upd-2026102817 (i.e, an update that started at "
                "2026102817 [yyyymmddhh] UTC; yyyy=year; mm=month; dd=day; hh=hour),\ncreated by appending recently "
                "available data updates to the last fully reprocessed version: 3.35-por-2026102323.\n")
RETRIEVED_AT = "2026-10-30T23:59:36Z"


def dly_line(station_id: str, year: int, month: int, days: dict[int, tuple[int, str]], element: str = "TMAX") -> str:
    """One .dly record; ``days`` maps day -> (tenths of °C, QFLAG); other days are -9999."""
    cells = []
    for day in range(1, 32):
        value, qflag = days.get(day, (-9999, " "))
        cells.append(f"{value:5d} {qflag or ' '} ")
    return f"{station_id:<11}{year:04d}{month:02d}{element:<4}" + "".join(cells)


def station_text(station_id: str, monthly_c: Callable[[int, int], float | None], *,
                 years=range(1985, 2025), missing: Callable[[int, int], set[int]] = lambda y, m: set(),
                 flagged: Callable[[int, int], dict[int, int]] = lambda y, m: {},
                 spread: float = 4.0) -> str:
    """TMAX (+ an ignored TMIN) for every year-month; daily highs vary around ``monthly_c`` by ``spread``."""
    lines = []
    for year in years:
        for month in range(1, 13):
            base = monthly_c(year, month)
            if base is None:
                continue
            last = calendar.monthrange(year, month)[1]
            days: dict[int, tuple[int, str]] = {}
            for day in range(1, last + 1):
                if day in missing(year, month):
                    continue
                offset = spread * ((day % 5) - 2) / 2  # symmetric: mean of a full month == base
                days[day] = (round((base + offset) * 10), " ")
            for day, tenths in flagged(year, month).items():
                days[day] = (tenths, "X")
            lines.append(dly_line(station_id, year, month, days))
            lines.append(dly_line(station_id, year, month, {d: (v - 100, " ") for d, (v, _q) in days.items()},
                                  element="TMIN"))
    return "\n".join(lines) + "\n"


def stations_line(station_id: str, lat: float, lon: float, elevation: float, name: str) -> str:
    return f"{station_id:<11} {lat:8.4f} {lon:9.4f} {elevation:6.1f}    {name:<30}             "


def inventory_lines(station_id: str, lat: float, lon: float, first: int, last: int) -> str:
    return "".join(f"{station_id} {lat:8.4f} {lon:9.4f} {element} {first} {last}\n" for element in ("TMAX", "TMIN"))


class Inputs:
    """A GHCN inputs directory plus the catalogue it serves."""

    def __init__(self, root: Path, names: list[str]):
        self.root, self.names = root, list(names)
        self.dir = root / "inputs"
        self.dir.mkdir(parents=True)
        self.cities = root / "cities.csv"
        h.write_catalogue(self.cities, self.names)
        self.stations: list[tuple[str, float, float, float, str, int, int]] = []
        self.texts: dict[str, str] = {}

    def place(self, name: str) -> dict:
        row = h.catalogue_rows([name])[0]
        return {**places.place_for_row(row), "elevation_m": float(row["elevation_m"])}

    def add(self, station_id: str, near: str, *, north_km: float = 5.0, elevation_delta: float = 10.0,
            text: str | None = None, first: int = 1985, last: int = 2024, base: float = 30.0,
            at: tuple[float, float] | None = None) -> None:
        """A station ``north_km`` north of ``near`` (or exactly ``at`` (lat, lon), 4-decimal like NOAA's)."""
        place = self.place(near)
        lat, lon = at if at is not None else (place["lat"] + north_km / 111.2, place["lon"])
        self.stations.append((station_id, lat, lon, place["elevation_m"] + elevation_delta,
                              f"INVENTED {station_id[-4:]}", first, last))
        self.texts[station_id] = text if text is not None else station_text(
            station_id, lambda y, m: base + m / 10, years=range(first, last + 1))

    def write(self) -> Path:
        files = {
            "version": VERSION_TEXT.encode("ascii"),
            "stations": "".join(stations_line(s, la, lo, el, n) + "\n" for s, la, lo, el, n, _f, _l
                                in self.stations).encode("ascii"),
            "inventory": "".join(inventory_lines(s, la, lo, f, last) for s, la, lo, _e, _n, f, last
                                 in self.stations).encode("ascii"),
        }
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            for station_id, text in sorted(self.texts.items()):
                data = text.encode("ascii")
                info = tarfile.TarInfo(f"ghcnd_all/{station_id}.dly")
                info.size, info.mtime = len(data), 0
                tar.addfile(info, io.BytesIO(data))
        files["archive"] = archive.getvalue()
        inputs = {}
        for role, raw in files.items():
            name = gn.INPUT_FILES[role]
            (self.dir / name).write_bytes(raw)
            inputs[role] = {"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                            "url": "https://www.ncei.noaa.gov/pub/data/ghcn/daily/" + name,
                            "retrieved_at": RETRIEVED_AT, "last_modified": "Fri, 30 Oct 2026 02:15:34 GMT",
                            "etag": '"invented"'}
        manifest = {"schema": gn.INPUTS_SCHEMA, "source_product": gn.INPUT_PRODUCT, "inputs": inputs,
                    "source_version": {"version": "3.35-upd-2026102817", "update_started_at": "2026-10-28T17:00:00Z",
                                       "reprocessed_version": "3.35-por-2026102323",
                                       "text_sha256": inputs["version"]["sha256"]},
                    "suggested_snapshot_date": "2026-10-24"}
        path = self.dir / "inputs-manifest.json"
        path.write_text(json.dumps(manifest, sort_keys=True))
        return path


def installed_rows(month: int, cities=h.CITIES, *, normal_c: float = h.NORMAL_C, **overrides) -> list[dict]:
    """Invented rows of the GHCND product for the real loader (one per registered city with a normal)."""
    out = []
    for index, (name, _zone, kind) in enumerate(cities):
        if kind == "missing":
            continue
        row = h.catalogue_rows([name])[0]
        place = places.place_for_row(row)
        out.append({
            "city": row["city"], "country": row["country"], "place_id": place["place_id"],
            "sampling_point_id": place["sampling_point_id"], "lat": repr(place["lat"]), "lon": repr(place["lon"]),
            "place_elevation_m": repr(float(row["elevation_m"])), "month": str(month), "mean_tmax_c": repr(normal_c),
            "unit": "C", "statistic": gn.STATISTIC, "source_product": gn.PRODUCT, "period_start": "1991",
            "period_end": "2020", "years_used": "30", "first_year": "1991", "last_year": "2020",
            "qualifying_year_mask": "1" * 30, "valid_days": "900", "flagged_values": "0", "station_id": f"XQW000{index:05d}",
            "station_name": f"INVENTED {index}", "station_lat": repr(place["lat"] + 0.05),
            "station_lon": repr(place["lon"]), "station_elevation_m": repr(float(row["elevation_m"]) + 5.0),
            "distance_km": "5.56", "source_version": "3.35-upd-2026102817", "retrieved_at": RETRIEVED_AT,
            **overrides})
    return out


def write_rows(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(gn.FIELDS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path
