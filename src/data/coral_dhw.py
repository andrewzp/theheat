from __future__ import annotations

"""NOAA Coral Reef Watch regional DHW threshold detection."""

from dataclasses import dataclass
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from collections.abc import Mapping

import requests

from src.data._http import fetch_with_retry
from src.data._witness import tag_source_leg, with_witness
from src.data.source_status import SourceFetchError
from src.data.coral_evidence import DHW_ONLY_STRESS_LEVEL
from src.data import coral_source_contract as point_contract
from src.data import coral_regional_contract as regional_contract

SOURCE_NAME = "NOAA Coral Reef Watch"
STATION_INDEX_URL = "https://coralreefwatch.noaa.gov/product/vs/data.php"
STATION_DATA_BASE_URL = "https://coralreefwatch.noaa.gov/product/vs/data/"
CRW_ERDDAP_LEG = "crw_erddap"
CRW_ERDDAP_DATASET_URL = point_contract.CSV_BASE
# CRW's ERDDAP grid can lag the virtual-station index by several days; the
# 2026-06-14 unblock probe returned a six-day-old latest grid. Keep this
# witness-only budget tight, but wide enough for the documented grid cadence.
CRW_ERDDAP_MAX_AGE_DAYS = point_contract.MAX_AGE_DAYS
_REQUEST_HEADERS = {"User-Agent": "theheat-bot/1.0"}

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
    provenance: dict | None = None


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
    provenance: dict | None = None
    baa_7day_max: int | None = None


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
    then bounded, version-matched header/tail ranges for stations whose current stress level is not
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
        index_body, index_receipt = _fetch_regional_bytes(STATION_INDEX_URL, kind="index")
        stations, index = regional_contract.decode_index(
            index_body, retrieved_at=index_receipt["retrieved_at"], max_age_days=max_age_days,
        )

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
                    index=index,
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
                dhw_value=reading.dhw_value,
                dhw_tier=tier,
                bleaching_level=level,
                stress_level=reading.stress_level,
                lat=reading.lat,
                lon=reading.lon,
                event_id=f"coral_dhw_{reading.region_id}_tier{tier}",
                source_leg=reading.source_leg,
                provenance=deepcopy(reading.provenance),
                baa_7day_max=reading.baa_7day_max,
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
    try:
        metadata_body, metadata_at = _fetch_point_bytes(point_contract.METADATA_URL, point_contract.METADATA_LIMIT)
        metadata = point_contract.decode_metadata(metadata_body, retrieved_at=metadata_at, max_age_days=max_age_days)
    except (requests.RequestException, SourceFetchError) as exc:
        if strict:
            raise SourceFetchError("CRW ERDDAP metadata unavailable or rejected") from exc
        return []
    readings: list[CoralDHWReading] = []
    errors: list[str] = []
    for station in CRW_ERDDAP_STATIONS.values():
        try:
            csv_body, retrieved_at = _fetch_erddap_csv(station, metadata["last_product_time"])
            readings.append(
                _reading_from_erddap_csv(
                    csv_body,
                    station,
                    max_age_days=max_age_days,
                    metadata=metadata, retrieved_at=retrieved_at,
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


def _fetch_point_bytes(url: str, limit: int) -> tuple[bytes, str]:
    response = fetch_with_retry(
        url, headers=_REQUEST_HEADERS, timeout=20, attempts=1,
        stream=True, allow_redirects=False,
    )
    try:
        if response.status_code != 200:
            raise SourceFetchError("CRW ERDDAP unexpected response status")
        chunks = []
        size = 0
        for chunk in response.iter_content(4096):
            size += len(chunk)
            if size > limit:
                raise SourceFetchError("CRW ERDDAP response byte limit")
            chunks.append(chunk)
        return b"".join(chunks), point_contract.now_utc()
    finally:
        response.close()


def _fetch_erddap_csv(station: _ErddapStation, timestamp: str) -> tuple[bytes, str]:
    return _fetch_point_bytes(_erddap_point_url(station.lat, station.lon, timestamp), point_contract.CSV_LIMIT)


def _reading_from_erddap_csv(
    csv_body: bytes,
    station: _ErddapStation,
    *,
    max_age_days: int,
    metadata: dict,
    retrieved_at: str,
) -> CoralDHWReading:
    provenance = point_contract.decode_point(
        csv_body, station, metadata=metadata, retrieved_at=retrieved_at, max_age_days=max_age_days,
    )
    return CoralDHWReading(
        region_id=station.region_id, region_full_name=station.region_full_name,
        date=provenance["valid_date"], dhw_value=provenance["dhw_value"],
        stress_level=DHW_ONLY_STRESS_LEVEL, baa_7day_max=None,
        lat=provenance["sampled_point"][0], lon=provenance["sampled_point"][1],
        source_leg=CRW_ERDDAP_LEG, provenance=provenance,
    )


def _erddap_point_url(lat: float, lon: float, timestamp: str) -> str:
    return point_contract.point_url(lat, lon, timestamp)


def _fetch_regional_bytes(url: str, *, kind: str, prior: dict | None = None) -> tuple[bytes, dict]:
    headers = {**_REQUEST_HEADERS, "Accept-Encoding": "identity"}
    if kind == "tail":
        headers["Range"] = "bytes=-8192"
        limit = regional_contract.TAIL_BYTES
    elif kind == "header" and prior is not None:
        headers.update({"Range": "bytes=0-2048", "If-Match": prior["etag"]})
        limit = regional_contract.HEADER_BYTES
    elif kind == "index":
        limit = regional_contract.INDEX_LIMIT
    else:
        raise SourceFetchError("coral_dhw invalid regional request")
    try:
        response = fetch_with_retry(
            url, headers=headers, timeout=30, attempts=3, stream=True, allow_redirects=False,
        )
        try:
            if kind == "index":
                if response.status_code != 200:
                    raise SourceFetchError("coral_dhw unexpected index status")
                ranges = {}
            else:
                ranges = regional_contract.response_range(response.status_code, response.headers, kind=kind, prior=prior)
            chunks = []
            size = 0
            for chunk in response.iter_content(4096):
                size += len(chunk)
                if size > limit:
                    raise SourceFetchError("coral_dhw regional response byte limit")
                chunks.append(chunk)
            if not size or (kind != "index" and size != limit):
                raise SourceFetchError("coral_dhw regional response length")
            body = b"".join(chunks)
            return body, {
                "source_url": url, "response_sha256": hashlib.sha256(body).hexdigest(),
                "response_bytes": size, "retrieved_at": regional_contract.now_utc(), **ranges,
            }
        finally:
            response.close()
    except requests.RequestException as exc:
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            reason = f"HTTP {exc.response.status_code}"
            if exc.response.status_code == 400:
                reason = "bad request HTTP 400"
        else:
            reason = type(exc).__name__
        raise SourceFetchError(f"coral_dhw regional request failed: {reason}") from exc


def _fetch_station_latest(station: regional_contract.StationLink, *, index: dict, max_age_days: int) -> CoralDHWReading:
    url = f"{STATION_DATA_BASE_URL}{station.data_file}"
    tail_body, tail = _fetch_regional_bytes(url, kind="tail")
    header_body, header = _fetch_regional_bytes(url, kind="header", prior=tail)
    p = regional_contract.decode_station(station, index, header_body, header, tail_body, tail, max_age_days=max_age_days)
    return CoralDHWReading(
        region_id=station.region_id, region_full_name=station.region_full_name,
        date=p["valid_date"], dhw_value=p["dhw_value"], stress_level=p["stress_level"],
        baa_7day_max=p["baa_7day_max"], lat=p["marker_point"][0], lon=p["marker_point"][1],
        provenance=p,
    )


def _tier_for_dhw(dhw_value: float) -> tuple[int | None, str]:
    for tier, level in DHW_THRESHOLDS:
        if dhw_value >= tier:
            return tier, level
    return None, ""
