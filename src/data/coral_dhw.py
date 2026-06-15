from __future__ import annotations

"""NOAA Coral Reef Watch regional DHW threshold detection."""

from dataclasses import dataclass
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import html
import io
import math
import re
from collections.abc import Mapping

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data._witness import tag_source_leg, with_witness
from src.data.source_status import SourceFetchError, assert_response_schema

SOURCE_NAME = "NOAA Coral Reef Watch"
STATION_INDEX_URL = "https://coralreefwatch.noaa.gov/product/vs/data.php"
STATION_DATA_BASE_URL = "https://coralreefwatch.noaa.gov/product/vs/data/"
CRW_ERDDAP_LEG = "crw_erddap"
CRW_ERDDAP_DATASET_URL = "https://coastwatch.noaa.gov/erddap/griddap/noaacrwdhwDaily.csv"
# CRW's ERDDAP grid can lag the virtual-station index by several days; the
# 2026-06-14 unblock probe returned a six-day-old latest grid. Keep this
# witness-only budget tight, but wide enough for the documented grid cadence.
CRW_ERDDAP_MAX_AGE_DAYS = 7
_REQUEST_HEADERS = {"User-Agent": "theheat-bot/1.0"}

_LATEST_DATE_RE = re.compile(
    r"Latest Data Date:\s*([A-Za-z]+)\.\s*(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)
_DATA_ROW_RE = re.compile(r"^\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

DHW_THRESHOLDS = (
    (12, "mortality expected"),
    (8, "mass bleaching expected"),
    (4, "bleaching stress"),
)


@dataclass(frozen=True)
class CoralDHWReading:
    region_id: str
    region_full_name: str
    date: str
    dhw_value: float
    stress_level: str
    baa_7day_max: int | None
    lat: float | None = None
    lon: float | None = None
    source_name: str = SOURCE_NAME
    source_leg: str | None = None  # witness leg that served (R-00); None = primary


@dataclass(frozen=True)
class CoralBleachingEvent:
    region_id: str
    region_full_name: str
    date: str
    dhw_value: float
    dhw_tier: int
    bleaching_level: str
    stress_level: str
    event_id: str
    lat: float | None = None
    lon: float | None = None
    source_name: str = SOURCE_NAME
    source_leg: str | None = None  # witness leg that served; None = primary


@dataclass(frozen=True)
class _StationLink:
    region_id: str
    region_full_name: str
    stress_level: str
    data_file: str


@dataclass(frozen=True)
class _ErddapStation:
    region_id: str
    region_full_name: str
    lat: float
    lon: float


CRW_ERDDAP_STATIONS: dict[str, _ErddapStation] = {
    "austral_islands": _ErddapStation("austral_islands", "Austral Islands", -24.825, -149.1),
    "chagos_archipelago": _ErddapStation("chagos_archipelago", "Chagos Archipelago, UK", -6.2, 71.75),
    "clipperton_island": _ErddapStation("clipperton_island", "Clipperton Island, France", 10.3, -109.2),
    "colombia_atlantic": _ErddapStation("colombia_atlantic", "Colombia Atlantic", 9.925, -75.525),
    "costa_rica_pacific": _ErddapStation("costa_rica_pacific", "Costa Rica Pacific", 9.5, -84.425),
    "east_java_bali": _ErddapStation("east_java_bali", "East Java and Bali", -6.95, 114.1),
    "fiji": _ErddapStation("fiji", "Fiji", -16.775, 179.35),
    "florida_keys": _ErddapStation("florida_keys", "Florida Keys", 24.75, -81.625),
    "galapagos": _ErddapStation("galapagos", "Galapagos, Ecuador", 0.15, -90.625),
    "gbr_central": _ErddapStation("gbr_central", "Central GBR", -19.225, 148.275),
    "gbr_northern": _ErddapStation("gbr_northern", "Northern GBR", -16.1, 145.975),
    "gbr_southern": _ErddapStation("gbr_southern", "Southern GBR", -22.625, 151.125),
    "gilbert_islands": _ErddapStation("gilbert_islands", "Gilbert Islands, Kiribati", 0.35, 173.2),
    "great_nicobar": _ErddapStation("great_nicobar", "Great Nicobar, India", 8.025, 93.325),
    "howland_baker": _ErddapStation("howland_baker", "Howland and Baker", 0.5, -176.525),
    "kenya": _ErddapStation("kenya", "Kenya", -3.2, 40.525),
    "malacca_strait": _ErddapStation("malacca_strait", "Malacca Strait, Malaysia", 3.225, 101.35),
    "nauru": _ErddapStation("nauru", "Nauru", -0.525, 166.925),
    "nicaragua": _ErddapStation("nicaragua", "Nicaragua", 14.125, -81.75),
    "northern_line_islands": _ErddapStation("northern_line_islands", "Northern Line Islands", 3.025, -159.8),
    "northern_myanmar": _ErddapStation("northern_myanmar", "Northern Myanmar", 18.15, 93.5),
    "phoenix_islands": _ErddapStation("phoenix_islands", "Phoenix Islands, Kiribati", -3.15, -172.825),
    "samoas": _ErddapStation("samoas", "Samoas", -12.825, -170.475),
    "solomon_islands": _ErddapStation("solomon_islands", "Solomon Islands", -8.7, 162.175),
    "southern_borneo": _ErddapStation("southern_borneo", "Southern Borneo", -3.575, 116.55),
    "west_kalimanta": _ErddapStation("west_kalimanta", "West Kalimantan", -1.05, 109.375),
    "western_madagascar": _ErddapStation("western_madagascar", "Western Madagascar", -17.45, 43.45),
}


def fetch_coral_dhw(
    *,
    strict: bool = False,
    include_inactive: bool = False,
    max_age_days: int = 5,
) -> list[CoralDHWReading]:
    """Fetch latest DHW readings for active CRW regional virtual stations.

    The CRW station text files are full 1985-present histories. To keep the
    scheduled bot polite, the default path fetches the station index once and
    then byte-range tails only for stations whose current stress level is not
    ``No Stress``. Tests and manual audits can set ``include_inactive=True``.
    """
    try:
        return with_witness(
            lambda: _fetch_coral_dhw_primary(
                strict=True,
                include_inactive=include_inactive,
                max_age_days=max_age_days,
            ),
            lambda: _fetch_coral_dhw_erddap(strict=True, max_age_days=max_age_days),
            source_key="coral_dhw",
            leg_label=CRW_ERDDAP_LEG,
        )
    except (requests.RequestException, SourceFetchError) as exc:
        if strict:
            if isinstance(exc, SourceFetchError):
                raise
            raise SourceFetchError(f"coral_dhw fetch failed: {exc}") from exc
        return []


def _fetch_coral_dhw_primary(
    *,
    strict: bool = False,
    include_inactive: bool = False,
    max_age_days: int = 5,
) -> list[CoralDHWReading]:
    """Fetch latest DHW readings from the primary CRW virtual-station text path."""
    try:
        index_text = _fetch_text(STATION_INDEX_URL, source_name="coral_dhw index")
        assert_response_schema({"body": index_text}, ["body"], "coral_dhw")
        latest_index_date = _parse_latest_index_date(index_text)
        assert_freshness(latest_index_date, "coral_dhw", max_age_days)

        stations = _parse_station_index(index_text)
        if not stations:
            raise SourceFetchError("coral_dhw schema drift: no station data links found")

        target_stations = [
            station for station in stations
            if include_inactive or station.stress_level.strip().lower() != "no stress"
        ]
        if not target_stations:
            return []

        readings: list[CoralDHWReading] = []
        errors: list[str] = []
        worker_count = min(8, len(target_stations))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _fetch_station_latest,
                    station,
                    max_age_days=max_age_days,
                ): station
                for station in target_stations
            }
            for future in as_completed(futures):
                station = futures[future]
                try:
                    readings.append(future.result())
                except SourceFetchError as exc:
                    errors.append(f"{station.region_id}: {exc}")

        if not readings and errors:
            raise SourceFetchError(
                "coral_dhw failed to parse active station readings: "
                + "; ".join(errors[:5])
            )
        return readings
    except (requests.RequestException, SourceFetchError, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"coral_dhw fetch failed: {exc}") from exc
        return []


def detect_dhw_thresholds(
    readings: list[CoralDHWReading],
    last_tiers: Mapping[str, int] | None = None,
) -> list[CoralBleachingEvent]:
    """Return one event per region whose DHW crossed a higher alert tier."""
    prior_tiers = last_tiers or {}
    events: list[CoralBleachingEvent] = []
    for reading in readings:
        tier, level = _tier_for_dhw(reading.dhw_value)
        if tier is None:
            continue
        try:
            prior_tier = int(prior_tiers.get(reading.region_id, 0) or 0)
        except (TypeError, ValueError):
            prior_tier = 0
        if tier <= prior_tier:
            continue
        events.append(
            CoralBleachingEvent(
                region_id=reading.region_id,
                region_full_name=reading.region_full_name,
                date=reading.date,
                dhw_value=round(reading.dhw_value, 1),
                dhw_tier=tier,
                bleaching_level=level,
                stress_level=reading.stress_level,
                lat=reading.lat,
                lon=reading.lon,
                event_id=f"coral_dhw_{reading.region_id}_tier{tier}",
                source_leg=reading.source_leg,
            )
        )
    events.sort(key=lambda event: (event.dhw_tier, event.dhw_value), reverse=True)
    return events


def _fetch_coral_dhw_erddap(
    *,
    strict: bool = False,
    max_age_days: int = 5,
) -> list[CoralDHWReading]:
    """Fetch CRW DHW from the NOAA CoastWatch ERDDAP grid backup."""
    readings: list[CoralDHWReading] = []
    errors: list[str] = []
    for station in CRW_ERDDAP_STATIONS.values():
        try:
            csv_text = _fetch_erddap_csv(station)
            readings.append(
                _reading_from_erddap_csv(
                    csv_text,
                    station,
                    max_age_days=max_age_days,
                )
            )
        except (requests.RequestException, SourceFetchError, ValueError) as exc:
            errors.append(f"{station.region_id}: {exc}")
            continue
    if readings:
        return tag_source_leg(readings, CRW_ERDDAP_LEG)
    if strict:
        detail = "; ".join(errors[:5]) if errors else "no stations configured"
        raise SourceFetchError(f"CRW ERDDAP witness failed: {detail}")
    return []


def _fetch_erddap_csv(station: _ErddapStation) -> str:
    response = fetch_with_retry(
        _erddap_point_url(station.lat, station.lon),
        headers=_REQUEST_HEADERS,
        timeout=20,
        attempts=1,
    )
    return response.text


def _reading_from_erddap_csv(
    csv_text: str,
    station: _ErddapStation,
    *,
    max_age_days: int,
) -> CoralDHWReading:
    rows = csv.DictReader(io.StringIO(csv_text))
    for row in rows:
        if row.get("time") == "UTC":
            continue
        observed_at = str(row.get("time") or "")
        observed_date = observed_at.split("T", 1)[0]
        try:
            dhw = float(str(row.get("degree_heating_week") or ""))
            lat = float(str(row.get("latitude") or station.lat))
            lon = float(str(row.get("longitude") or station.lon))
        except ValueError as exc:
            raise SourceFetchError(
                f"CRW ERDDAP schema drift for {station.region_id}: malformed row"
            ) from exc
        if not math.isfinite(dhw):
            raise SourceFetchError(f"CRW ERDDAP returned non-finite DHW for {station.region_id}")
        if dhw <= -300:
            raise SourceFetchError(f"CRW ERDDAP returned fill value for {station.region_id}")
        assert_freshness(
            observed_date,
            "coral_dhw",
            max(max_age_days, CRW_ERDDAP_MAX_AGE_DAYS),
        )
        return CoralDHWReading(
            region_id=station.region_id,
            region_full_name=station.region_full_name,
            date=observed_date,
            dhw_value=round(dhw, 1),
            stress_level=_stress_level_for_dhw(dhw),
            baa_7day_max=None,
            lat=lat,
            lon=lon,
        )
    raise SourceFetchError(f"CRW ERDDAP schema drift for {station.region_id}: no data rows")


def _erddap_point_url(lat: float, lon: float) -> str:
    return (
        f"{CRW_ERDDAP_DATASET_URL}?"
        f"degree_heating_week%5B(last)%5D%5B({lat})%5D%5B({lon})%5D"
    )


def _stress_level_for_dhw(dhw: float) -> str:
    if dhw >= 8:
        return "Bleaching Alert Level 2"
    if dhw >= 4:
        return "Bleaching Alert Level 1"
    return "No Stress"


def _fetch_text(
    url: str,
    *,
    source_name: str,
    byte_range: str | None = None,
) -> str:
    headers = dict(_REQUEST_HEADERS)
    if byte_range:
        headers["Range"] = byte_range
    response = fetch_with_retry(url, headers=headers, timeout=30, attempts=3)
    text = response.text
    assert_response_schema({"body": text}, ["body"], source_name)
    if not text.strip():
        raise SourceFetchError(f"{source_name} returned empty response")
    return text


def _parse_latest_index_date(index_text: str) -> date:
    match = _LATEST_DATE_RE.search(index_text)
    if not match:
        raise SourceFetchError("coral_dhw schema drift: missing latest data date")
    month_raw, day_raw, year_raw = match.groups()
    month = _MONTHS.get(month_raw.lower())
    if month is None:
        raise SourceFetchError(f"coral_dhw schema drift: unknown month {month_raw!r}")
    return date(int(year_raw), month, int(day_raw))


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _parse_station_index(index_text: str) -> list[_StationLink]:
    stations: list[_StationLink] = []
    seen: set[str] = set()
    for row_match in re.finditer(r"<tr>(.*?)</tr>", index_text, re.IGNORECASE | re.DOTALL):
        row = row_match.group(1)
        data_match = re.search(r'href="data/(?P<file>[^"]+\.txt)"', row, re.IGNORECASE)
        name_match = re.search(
            r'href="timeseries/[^"]+#(?P<id>[^"]+)">(?P<name>.*?)</a>',
            row,
            re.IGNORECASE | re.DOTALL,
        )
        stress_match = re.search(
            r'href="gauges/[^"]+">(?P<stress>.*?)</a>',
            row,
            re.IGNORECASE | re.DOTALL,
        )
        if not data_match or not name_match or not stress_match:
            continue
        region_id = html.unescape(name_match.group("id")).strip()
        if not region_id or region_id in seen:
            continue
        seen.add(region_id)
        stations.append(
            _StationLink(
                region_id=region_id,
                region_full_name=_strip_html(name_match.group("name")),
                stress_level=_strip_html(stress_match.group("stress")),
                data_file=data_match.group("file"),
            )
        )
    return stations


def _fetch_station_latest(station: _StationLink, *, max_age_days: int) -> CoralDHWReading:
    url = f"{STATION_DATA_BASE_URL}{station.data_file}"
    tail_text = _fetch_text(
        url,
        source_name=f"coral_dhw station {station.region_id}",
        byte_range="bytes=-8192",
    )
    latest = _parse_latest_station_row(tail_text, station.region_id)
    assert_freshness(latest["date"], "coral_dhw", max_age_days)

    lat: float | None = None
    lon: float | None = None
    if float(latest["dhw"]) >= 4.0:
        head_text = _fetch_text(
            url,
            source_name=f"coral_dhw station metadata {station.region_id}",
            byte_range="bytes=0-2048",
        )
        metadata = _parse_station_metadata(head_text)
        lat = metadata.get("lat")
        lon = metadata.get("lon")

    return CoralDHWReading(
        region_id=station.region_id,
        region_full_name=station.region_full_name,
        date=str(latest["date"]),
        dhw_value=round(float(latest["dhw"]), 1),
        stress_level=station.stress_level,
        baa_7day_max=int(latest["baa"]) if latest["baa"] is not None else None,
        lat=lat,
        lon=lon,
    )


def _parse_latest_station_row(text: str, region_id: str) -> dict[str, object]:
    latest: dict[str, object] | None = None
    for line in text.splitlines():
        if not _DATA_ROW_RE.match(line):
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            observed = date(int(parts[0]), int(parts[1]), int(parts[2]))
            dhw = float(parts[8])
            baa = int(float(parts[9]))
        except (TypeError, ValueError) as exc:
            raise SourceFetchError(
                f"coral_dhw schema drift for {region_id}: malformed data row"
            ) from exc
        latest = {"date": observed.isoformat(), "dhw": dhw, "baa": baa}
    if latest is None:
        raise SourceFetchError(f"coral_dhw schema drift for {region_id}: no data rows")
    return latest


def _parse_station_metadata(text: str) -> dict[str, float]:
    metadata: dict[str, float] = {}
    lat_match = re.search(r"Polygon Middle Latitude:\s*([-+]?\d+(?:\.\d+)?)", text)
    lon_match = re.search(r"Polygon Middle Longitude:\s*([-+]?\d+(?:\.\d+)?)", text)
    if lat_match:
        metadata["lat"] = float(lat_match.group(1))
    if lon_match:
        metadata["lon"] = float(lon_match.group(1))
    return metadata


def _tier_for_dhw(dhw_value: float) -> tuple[int | None, str]:
    for tier, level in DHW_THRESHOLDS:
        if dhw_value >= tier:
            return tier, level
    return None, ""
