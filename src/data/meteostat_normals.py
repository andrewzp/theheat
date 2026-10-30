"""Meteostat point normals over the owned bounded transport (product meteostat-normals-point-v1).

This is the agreed provider/data contract, unchanged: meteostat-python 1.x
``Normals(Point(lat, lon), start, end).fetch()`` monthly ``tmax`` (degC) from
the Meteostat bulk v2 interface. The exact semantics are pinned to the
meteostat 1.7.6 sdist (sha256 ``2b83eedb…87bf``, read under the supply lane's
bounded documentation plan) and reproduced here because the SDK hides its
physical requests, transfer bytes, retries and on-disk cache, so it cannot be
bounded (SOURCE-CLOSURE S3). Reproduced:

- station list ``stations/slim.csv.gz`` (16 headerless columns), one GET per run;
- ``Point`` without altitude: ``method='nearest'``, ``radius=35000`` m,
  ``alt_range=350`` m, ``max_count=4``, ``adapt_temp=False``; haversine
  distance (R=6,371,000 m); altitude guessed as the mean elevation of the four
  nearest stations; the ``monthly`` inventory filter for the period (stations
  whose monthly coverage spans it, with the SDK's one-day cache allowance);
  altitude filter; fill-up from the distance-sorted altitude-filtered list;
  score ``(1-d/r)*0.6 + (1-|alt-elev|/350)*0.4``, highest first;
- per selected station ``normals/{id}.csv.gz`` (headerless
  ``start,end,month,tmin,tmax,prcp,wspd,pres,tsun``) filtered to the period end;
- ``nearest`` resolution: per month the first non-missing ``tmax`` in score order.

Differences are all refusals or provenance, never a different baseline:
a station file answering 5xx/transport failure is retried inside the bounds and
then fails the point (the SDK turns any HTTP error into an empty frame and
silently moves to the next station); 404 is the SDK's "no file" and is recorded;
station rows with invalid coordinates and ambiguous duplicate ids are excluded
and counted; distance/score ties break by station-file order; no disk cache is
written; and every value keeps its contributing station, the station list and
station files' digests/Last-Modified/ETag, and the physical retrieval counters.

Data licence as stated by the pinned 1.7.6 sdist: CC BY-NC 4.0 (the 2.x README
states CC BY 4.0 for its data). The attribution travels with the candidate.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import io
import math
import re
import threading
from typing import Any, Callable, Iterator

from src.data import bounded_http

ENDPOINT = "https://bulk.meteostat.net/v2/"
STATIONS_FILE = "stations/slim.csv.gz"
NORMALS_FILE = "normals/{station}.csv.gz"
RADIUS_M = 35_000
ALT_RANGE_M = 350
MAX_COUNT = 4
WEIGHT_DIST = 0.6
WEIGHT_ALT = 0.4
INVENTORY_ALLOWANCE = timedelta(seconds=24 * 60 * 60)  # the SDK's default max_age
EARTH_RADIUS_M = 6_371_000
CONTRACT = {
    "product": "meteostat-normals-point-v1",
    "reference": {"library": "meteostat", "version": "1.7.6",
                  "sdist_sha256": "2b83eedb21a940babe0ffa938be1471b99e55f54f8316ca92330c4eea22487bf",
                  "interface": "Normals(Point(lat, lon), start, end).fetch()"},
    "endpoint": ENDPOINT, "stations_file": STATIONS_FILE, "normals_file": NORMALS_FILE,
    "point": {"method": "nearest", "radius_m": RADIUS_M, "alt_range_m": ALT_RANGE_M, "max_count": MAX_COUNT,
              "adapt_temp": False, "weight_dist": WEIGHT_DIST, "weight_alt": WEIGHT_ALT,
              "inventory": "monthly", "altitude": "mean elevation of the 4 nearest stations"},
    "variable": "tmax", "units": "degC",
    "licence": "CC BY-NC 4.0 (as stated by meteostat 1.7.6); attribute Meteostat",
}
VERSION = "bulk-v2/point-nearest@meteostat-python-1.7.6"
_STATION_ID = re.compile(r"[A-Za-z0-9]{1,16}\Z")
_STATION_COLUMNS = 16
_NORMALS_COLUMNS = 9
MAX_STATION_ROWS = 200_000


class ProductInvalid(ValueError):
    """The provider answered with a product the contract cannot accept (point refused)."""


class ProviderUnavailable(Exception):
    """The run cannot resolve any point (station list missing/refused/malformed)."""

    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    country: str
    lat: float
    lon: float
    elevation: float | None
    monthly_start: date | None
    monthly_end: date | None
    order: int


class NormalsFrame:
    """The attributes of a Meteostat ``Normals.fetch()`` frame the acquisition adapter reads."""

    def __init__(self, tmax: dict[int, float | None], provenance: dict[str, Any]) -> None:
        self.tmax = dict(sorted(tmax.items()))
        self.columns = ["tmax"]
        self.empty = not self.tmax
        self.provenance = provenance

    def iterrows(self) -> Iterator[tuple[int, dict[str, Any]]]:
        for month, value in self.tmax.items():
            yield month, {"tmax": value}


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """meteostat.utilities.helpers.get_distance."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    arch = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(arch))


def _float(text: str, *, low: float, high: float, optional: bool) -> float | None:
    text = text.strip()
    if not text:
        if optional:
            return None
        raise ValueError
    value = float(text)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError
    return value


def _date(text: str) -> date | None:
    text = text.strip()
    return date.fromisoformat(text) if text else None


def parse_stations(text: str) -> tuple[list[Station], dict[str, int]]:
    """Headerless slim station list; invalid rows and ambiguous ids are excluded and counted."""
    rows: list[Station] = []
    invalid = 0
    for index, values in enumerate(csv.reader(io.StringIO(text), strict=True)):
        if index >= MAX_STATION_ROWS:
            raise ProviderUnavailable("malformed")
        if not values:
            continue
        try:
            if len(values) != _STATION_COLUMNS or not _STATION_ID.fullmatch(values[0]):
                raise ValueError
            lat = _float(values[6], low=-90, high=90, optional=False)
            lon = _float(values[7], low=-180, high=180, optional=False)
            assert lat is not None and lon is not None
            rows.append(Station(values[0], values[1][:128], values[2][:8], lat, lon,
                                _float(values[8], low=-500, high=9000, optional=True),
                                _date(values[14]), _date(values[15]), index))
        except (ValueError, AssertionError):
            invalid += 1
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.id] = counts.get(row.id, 0) + 1
    ambiguous = {key for key, count in counts.items() if count > 1}
    kept = [row for row in rows if row.id not in ambiguous]
    if not kept:
        raise ProviderUnavailable("malformed")
    return kept, {"rows": len(rows) + invalid, "invalid_rows": invalid, "ambiguous_ids": len(ambiguous),
                  "stations": len(kept)}


def select_stations(stations: list[Station], lat: float, lon: float, start: int, end: int,
                    now: datetime) -> tuple[list[dict[str, Any]], float | None]:
    """``Point(lat, lon).get_stations('monthly', datetime(start,1,1), datetime(end,12,31))``."""
    nearby = sorted(((distance_m(lat, lon, s.lat, s.lon), s) for s in stations), key=lambda x: (x[0], x[1].order))
    nearby = [(d, s) for d, s in nearby if d <= RADIUS_M]
    elevations = [s.elevation for _d, s in nearby[:MAX_COUNT] if s.elevation is not None]
    if not elevations:
        return [], None
    alt = sum(elevations) / len(elevations)

    def in_range(station: Station) -> bool:
        return station.elevation is not None and abs(alt - station.elevation) <= ALT_RANGE_M

    unfiltered = [(d, s) for d, s in nearby if in_range(s)]
    period_start, period_end = date(start, 1, 1), date(end, 12, 31)
    inventory = nearby
    if (now.replace(tzinfo=None) - datetime(end, 12, 31)).days > 180:
        inventory = [(d, s) for d, s in nearby if s.monthly_start is not None and s.monthly_end is not None
                     and s.monthly_start <= period_start and s.monthly_end + INVENTORY_ALLOWANCE >= period_end]
    chosen = [(d, s) for d, s in inventory if in_range(s)]
    if len(chosen) < MAX_COUNT:
        ids = {s.id for _d, s in chosen}
        chosen += [(d, s) for d, s in unfiltered if s.id not in ids][:MAX_COUNT - len(chosen)]
    scored = []
    for position, (d, s) in enumerate(chosen):
        assert s.elevation is not None
        score = (1 - d / RADIUS_M) * WEIGHT_DIST + (1 - abs(alt - s.elevation) / ALT_RANGE_M) * WEIGHT_ALT
        scored.append((-score, position, d, s, score))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [{"station": s, "distance_m": d, "score": score} for _neg, _pos, d, s, score in scored[:MAX_COUNT]], alt


def parse_normals(text: str, station: str) -> list[tuple[int, int, int, float | None]]:
    """Headerless station normals rows -> (start, end, month, tmax). Any invalid row refuses the file."""
    rows = []
    seen: set[tuple[int, int, int]] = set()
    for values in csv.reader(io.StringIO(text), strict=True):
        if not values:
            continue
        try:
            if len(values) != _NORMALS_COLUMNS:
                raise ValueError
            start, end, month = int(values[0]), int(values[1]), int(values[2])
            if not 1 <= month <= 12 or not 1800 <= start <= end <= 2100:
                raise ValueError
            tmax = _float(values[4], low=-90, high=60, optional=True)
        except ValueError:
            raise ProductInvalid("normals_station_file_invalid") from None
        if (start, end, month) in seen:
            raise ProductInvalid("normals_station_file_duplicate_month")
        seen.add((start, end, month))
        rows.append((start, end, month, tmax))
    return rows


class MeteostatBulkProvider:
    """The default owner-run normals provider: Meteostat bulk files through ``bounded_http``."""

    name = "meteostat"
    version = VERSION
    bounded_transport = True

    def __init__(self, *, endpoint: str = ENDPOINT, now: Callable[[], datetime] | None = None,
                 transport_options: dict[str, Any] | None = None) -> None:
        if not endpoint.endswith("/"):
            raise ValueError("meteostat_endpoint_invalid")
        self.endpoint = endpoint
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._options = dict(transport_options or {})
        self.transport: bounded_http.BoundedTransport | None = None
        self._stations: list[Station] | None = None
        self._stations_receipt: dict[str, Any] | None = None
        self._files: dict[str, tuple[str, list[tuple[int, int, int, float | None]], dict[str, Any]]] = {}

    def bind(self, limits: bounded_http.Limits, *, deadline_at: float, cancel: threading.Event) -> None:
        """One transport per run: every physical request of the run shares one allowance."""
        self.transport = bounded_http.BoundedTransport(limits, allowed_origins=[self.endpoint], cancel=cancel,
                                                       deadline_at=deadline_at, **self._options)

    def counters(self) -> dict[str, Any]:
        return self.transport.snapshot() if self.transport is not None else {}

    def check(self) -> None:
        if self.transport is None:
            raise RuntimeError("meteostat_provider_unbound")
        self.transport.check()

    def _get(self, path: str) -> tuple[bytes, dict[str, Any]]:
        if self.transport is None:
            raise RuntimeError("meteostat_provider_unbound")
        response = self.transport.get(self.endpoint + path)
        decoded = self.transport.gunzip(response.body)
        return decoded, {**response.receipt(), "decoded_bytes": len(decoded)}

    def _station_list(self) -> list[Station]:
        if self._stations is None:
            try:
                raw, receipt = self._get(STATIONS_FILE)
            except bounded_http.TransportOutcome as outcome:
                raise ProviderUnavailable(outcome.outcome) from None
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ProviderUnavailable("malformed") from None
            self._stations, counts = parse_stations(text)
            self._stations_receipt = {**receipt, **counts, "retrieved_at": _iso(self._now())}
        return self._stations

    def _station_file(self, station: str) -> tuple[str, list[tuple[int, int, int, float | None]], dict[str, Any]]:
        if station not in self._files:
            path = NORMALS_FILE.format(station=station)
            try:
                raw, receipt = self._get(path)
            except bounded_http.TransportOutcome as outcome:
                if outcome.outcome != "endpoint_missing":
                    raise  # retried inside the bounds already; the point stays pending
                self._files[station] = ("missing", [], {"url": self.endpoint + path, "status": outcome.status})
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    raise ProductInvalid("normals_station_file_invalid") from None
                self._files[station] = ("ok", parse_normals(text, station), {**receipt, "retrieved_at": _iso(self._now())})
        return self._files[station]

    def fetch(self, lat: float, lon: float, start: int, end: int) -> NormalsFrame:
        self.check()
        now = self._now()
        if end - start != 29 or end % 10 != 0 or end >= now.year:
            raise ProductInvalid("normals_reference_period_invalid")
        selected, alt = select_stations(self._station_list(), lat, lon, start, end, now)
        months: dict[tuple[int, int, int], tuple[float | None, str | None]] = {}
        stations: list[dict[str, Any]] = []
        for item in selected:
            station: Station = item["station"]
            status, rows, receipt = self._station_file(station.id)
            file_receipt: dict[str, Any] = {"status": status}
            file_receipt.update({k: receipt[k] for k in ("url", "sha256", "bytes", "decoded_bytes", "last_modified",
                                                          "etag", "retrieved_at") if k in receipt})
            stations.append({"station": station.id, "name": station.name, "country": station.country,
                             "lat": station.lat, "lon": station.lon, "elevation_m": station.elevation,
                             "distance_m": round(item["distance_m"], 1), "score": round(item["score"], 6),
                             "normals_file": file_receipt})
            for row_start, row_end, month, tmax in rows:
                if row_end != end:
                    continue
                key = (row_start, row_end, month)
                current = months.get(key)
                if current is None or (current[0] is None and tmax is not None):
                    months[key] = (tmax, station.id if tmax is not None else None)
        starts = {key[0] for key in months}
        if len(starts) > 1 or (starts and starts != {start}):
            raise ProductInvalid("normals_period_start_mismatch")
        tmax_by_month = {key[2]: value for key, (value, _station) in months.items()}
        provenance = {"contract": VERSION, "endpoint": self.endpoint, "period": [start, end],
                      "point": {"lat": lat, "lon": lon},
                      "alt_guess_m": None if alt is None else round(alt, 1),
                      "stations_file": dict(self._stations_receipt or {}), "selected_stations": stations,
                      "month_station": {str(key[2]): station_id for key, (_v, station_id) in sorted(months.items())
                                        if station_id is not None},
                      "units": CONTRACT["units"], "licence": CONTRACT["licence"]}
        self.check()
        return NormalsFrame(tmax_by_month, provenance)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = ["CONTRACT", "ENDPOINT", "MeteostatBulkProvider", "NormalsFrame", "ProductInvalid", "ProviderUnavailable",
           "Station", "VERSION", "distance_m", "parse_normals", "parse_stations", "select_stations"]
