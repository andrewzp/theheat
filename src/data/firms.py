"""NASA FIRMS fire detection data."""

import csv
import io
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from src.data.error_class import classify_error_class
from src.data.fire_identity import source_event_id
from src.data.fire_source_contract import (
    FIRMS_FIELDS, FIRMS_PRODUCTS, FIRMS_PUBLIC_URL, HMS_FIELDS, HMS_PRODUCT,
    FireSourceRow, freshness, make_receipt, parse_record, reject, validate_days,
)
from src.data._http import fetch_with_retry
from src.data._witness import is_witness_eligible_failure, tag_source_leg, with_witness
from src.data.open_meteo import load_cities
from src.data.source_status import SourceFetchError, SourceSkipped
from src.editorial._regions import _haversine_km

FIRMS_API_KEY = os.environ.get("NASA_FIRMS_API_KEY", "")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Nearest-city fallback bound (row 14, PR-A): a hotspot this far or closer to
# a curated data/cities.csv place gets an honest "near <city>" label instead
# of an unplaceable coordinate string. Beyond this distance (open ocean, deep
# polar) the old coordinate fallback remains. Tightened from 300 to 200 km on
# codex review: 299 km is too far for "near X" in reader-facing prose; 200 is
# still generous for sparse global city coverage.
GEOCODE_NEAR_CITY_MAX_KM = 200.0

# NOAA HMS alternate-host fire witness (R-02). NESDIS can cover a FIRMS host
# outage; per-row satellite/method labels do not establish instrument independence.
# Daily accumulating text file; no auth. N. America coverage only.
HMS_FIRE_URL = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Fire_Points/Text"
# FIRMS same-host product chain (R-06). A given product can be momentarily
# empty/lagged while a sibling has the data. Freshest sensors lead; all share the
# area/csv host + MAP_KEY. Each retains its own product/time/confidence semantics
# with no new evidence_grade. This is product-gap insurance, not a host-outage fix.
_FIRMS_PRODUCT_CHAIN = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
]
# This HMS adapter selects the existing North American box. Outside it the witness
# returns nothing and FIRMS has no fallback (stated honestly in the bundle).
_HMS_NORTH_AMERICA_BBOX = (7.0, 83.0, -170.0, -50.0)  # lat_min, lat_max, lon_min, lon_max


@dataclass
class FireEvent:
    lat: float
    lon: float
    confidence: int
    frp: float  # Fire Radiative Power in MW
    nearest_city: str
    country: str
    event_id: str
    source_leg: str | None = None  # witness leg that served (R-00); None = primary
    source_product: str | None = None
    acquired_at: str | None = None
    acquisition_provenance: dict[str, Any] | None = None


def fetch_fires(
    confidence_min: int = 80,
    frp_min: float = 250.0,
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
    *,
    strict: bool = False,
) -> list[FireEvent]:
    """Fetch active fires from NASA FIRMS, filtered by confidence and FRP.

    ``frp_min`` is Fire Radiative Power floor in megawatts. Raised from
    100 to 250 MW on 2026-04-24 after reviewing production draft quality:
    sub-200 MW fires produced weak copy (e.g., 136 MW framed with an
    awkward "a coal power plant runs at 150 MW, this is one of those"
    comparison). 250 MW roughly matches a "newsworthy" scale floor — a
    fire that reads as a real incident, not noise near a farmer's burn.
    """
    if not FIRMS_API_KEY:
        if strict:
            raise SourceSkipped("NASA_FIRMS_API_KEY is not configured")
        return []

    def primary() -> list[FireEvent]:
        return _fetch_fires_product_chain(confidence_min, frp_min, source, days)

    def witness() -> list[FireEvent]:
        return _fetch_fires_hms(frp_min)

    try:
        _validate_request(source, days)
        return with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")
    except SourceSkipped:
        raise
    except Exception as exc:
        if strict:
            # Classify after the product/witness decision. Never export URL,
            # body, key or chained exception text to the source runner/logs.
            raise SourceFetchError(_public_failure(exc)) from None
        return []


def _fetch_fires_product_chain(
    confidence_min: int,
    frp_min: float,
    source: str,
    days: int,
) -> list[FireEvent]:
    """Try FIRMS products in order (R-06): a given product can be momentarily
    empty/lagged while a sibling has the data. A non-first product records
    ``source_leg`` (→ status degraded) but NO new ``evidence_grade``. Product/time
    semantics remain explicit; the historical ordering is unchanged here.

    Returns ``[]`` only when every reachable product is genuinely empty (FIRMS up,
    no big fires — do NOT fall through to the independent HMS witness). Raises
    an outage when EVERY product failed, so ``with_witness`` then tries the
    alternate-host NOAA HMS leg. Schema/access failures still stop immediately.
    This chain is the
    same host and therefore NOT a host-outage fix; HMS (R-02) is."""
    _validate_request(source, days)
    chain = _FIRMS_PRODUCT_CHAIN[_FIRMS_PRODUCT_CHAIN.index(source):]

    last_exc: Exception | None = None
    any_reachable = False
    for index, product in enumerate(chain):
        try:
            fires = _fetch_fires_primary(confidence_min, frp_min, product, days)
        except (SourceFetchError, requests.RequestException) as exc:
            if not is_witness_eligible_failure(exc):
                raise
            last_exc = exc
            continue
        any_reachable = True
        if fires:
            # index 0 is the requested product (primary, no provenance); a later
            # product served the gap -> tag the leg (degraded), no grade.
            return fires if index == 0 else tag_source_leg(fires, product)
    if not any_reachable and last_exc is not None:
        # Retain the typed outage for the host witness decision. Wrapping a
        # Timeout whose text omits "timeout" would erase its eligibility.
        raise last_exc
    return []


def _validate_request(source: str, days: int) -> None:
    if type(source) is not str or source not in FIRMS_PRODUCTS:
        reject("unsupported FIRMS source product")
    validate_days(days)


def _public_failure(exc: Exception) -> str:
    """Fixed outward diagnostics; internal witness decisions retain their inputs."""
    detail = str(exc).lower()
    cause = exc
    seen: set[int] = set()
    while isinstance(cause.__cause__, Exception) and id(cause) not in seen and len(seen) < 16:
        seen.add(id(cause))
        cause = cause.__cause__
    if "schema drift" in detail:
        category = "schema drift (ParseError)"
    elif "freshness check failed" in detail:
        category = "freshness check failed"
    elif isinstance(cause, requests.Timeout):
        category = "timeout"
    elif isinstance(cause, requests.ConnectionError):
        category = "ConnectionError"
    else:
        category = {
            "auth": "auth credential/access failure", "http403": "HTTP 403",
            "http429": "HTTP 429", "http5xx": "HTTP 5xx Server Error",
            "timeout": "timeout", "dns": "NameResolution failure",
            "connection": "ConnectionError", "parse": "ParseError",
        }.get(classify_error_class(str(exc)), "unknown failure")
        if isinstance(cause, requests.HTTPError) and cause.response is not None:
            status = cause.response.status_code
            if type(status) is int and 100 <= status <= 599:
                category = f"HTTP {status}"
    return f"FIRMS/HMS fetch failed: {category}"


def _qualified_rows(text: str, product: str, reference: datetime) -> list[FireSourceRow]:
    """Validate every row before thresholding; never refresh one row with another."""
    reader = csv.reader(io.StringIO(text), strict=True)
    counts = dict(invalid=0, stale=0, future=0)
    valid = 0
    fresh: list[FireSourceRow] = []
    try:
        header = [value.strip() for value in next(reader, [])]
        required = HMS_FIELDS if product == HMS_PRODUCT else FIRMS_FIELDS
        if (not header or len(header) != len(set(header)) or not all(header)
                or not required.issubset(header)):
            reject("missing or duplicated required header")
        for values in reader:
            if not values:  # blank lines are not source records
                continue
            try:
                if len(values) != len(header):
                    reject("source row length disagrees with header")
                row = parse_record(product, dict(zip(header, values, strict=True)))
            except SourceFetchError:
                counts["invalid"] += 1
                continue
            valid += 1
            status = freshness(row, reference)
            if status != "fresh":
                counts[status] += 1
                continue
            fresh.append(row)
    except csv.Error:
        reject("malformed CSV packet")
    if any(counts.values()):
        # Fixed keys and capped integer counts only; never print row contents.
        diagnostic = ", ".join(f"{key}={min(value, 999999)}" for key, value in counts.items())
        print(f"[firms] excluded source rows: {diagnostic}")
    if not valid and counts["invalid"]:
        reject("no structurally valid source rows")
    if valid and not fresh:
        raise SourceFetchError("fire freshness check failed: no current source rows")
    return fresh


def _event(row: FireSourceRow, source_url: str, *, leg: str | None = None) -> FireEvent:
    if row.frp is None:
        reject("missing fire radiative power cannot become an event")
    city, country = reverse_geocode_simple(row.lat, row.lon)
    return FireEvent(
        lat=row.lat, lon=row.lon, confidence=row.ranking_confidence, frp=row.frp,
        nearest_city=city, country=country,
        event_id=source_event_id(row.lat, row.lon, row.acquired_at), source_leg=leg,
        source_product=row.source_product, acquired_at=row.acquired_at,
        acquisition_provenance=make_receipt(row, source_url),
    )


def _fetch_fires_primary(
    confidence_min: int,
    frp_min: float,
    source: str,
    days: int,
) -> list[FireEvent]:
    _validate_request(source, days)
    resp = fetch_with_retry(
        f"{FIRMS_URL}/{FIRMS_API_KEY}/{source}/world/{days}", timeout=30,
    )
    text = resp.text
    reference = datetime.now(UTC)
    rows = _qualified_rows(text, source, reference)
    return [_event(row, FIRMS_PUBLIC_URL) for row in rows
            if row.frp is not None and row.ranking_confidence >= confidence_min and row.frp >= frp_min]


def _in_north_america(lat: float, lon: float) -> bool:
    lat_min, lat_max, lon_min, lon_max = _HMS_NORTH_AMERICA_BBOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _fetch_fires_hms(frp_min: float) -> list[FireEvent]:
    """Read NOAA's dated file, retaining each row's own UTC acquisition minute."""
    requested_day = datetime.now(UTC).date()
    url = f"{HMS_FIRE_URL}/{requested_day:%Y}/{requested_day:%m}/hms_fire{requested_day:%Y%m%d}.txt"
    resp = fetch_with_retry(url, timeout=30)
    text = resp.text
    reference = datetime.now(UTC)
    rows = _qualified_rows(text, HMS_PRODUCT, reference)
    return [_event(row, url, leg="noaa_hms") for row in rows
            if row.frp is not None and row.frp >= frp_min and _in_north_america(row.lat, row.lon)]


# Ordered list of bounding boxes used to reverse-geocode a FIRMS fire
# coordinate into a (region, country) label.
#
# Ordering is deliberate: the **first** box to contain the point wins.
# So most-specific (smaller) regions must appear before larger
# containers. A "Siberia" box sits above a general "Russia" fallback;
# "California" sits above any generic US box.
#
# Each entry is (lat_min, lat_max, lon_min, lon_max, region, country).
# The ``region`` string is passed to the Gemini generator as the
# human-readable location ("Large wildfire detected in {region},
# {country}..."), so it should read naturally in that slot. Keep it
# specific enough that Gemini doesn't have to guess — "Asia, Unknown"
# is what we're replacing.
_GEO_BOXES: list[tuple[float, float, float, float, str, str]] = [
    # === North America — specific regions ===
    (32.5, 42.0, -124.5, -114.0, "California", "US"),
    (42.0, 49.0, -125.0, -116.5, "the Pacific Northwest", "US"),
    (31.3, 37.0, -114.8, -103.0, "the US Southwest", "US"),
    (37.0, 41.0, -111.0, -102.0, "the Rocky Mountains", "US"),
    (25.0, 37.0, -106.5, -93.5, "Texas", "US"),
    (29.5, 31.0, -93.5, -81.0, "the US Gulf Coast", "US"),
    (24.5, 31.0, -82.5, -80.0, "Florida", "US"),
    (32.0, 37.0, -91.0, -75.0, "the Southeastern US", "US"),
    (37.0, 45.0, -91.0, -67.0, "the Northeastern US", "US"),
    (37.0, 49.0, -104.5, -91.0, "the US Midwest", "US"),
    (54.0, 72.0, -170.0, -130.0, "Alaska", "US"),
    # Canada — broad provinces. Alberta/BC first (fire-prone west).
    (48.5, 60.0, -140.0, -113.0, "British Columbia", "Canada"),
    (48.5, 60.0, -113.0, -90.0, "the Canadian Prairies", "Canada"),
    (42.0, 56.0, -90.0, -74.0, "Ontario", "Canada"),
    (45.0, 62.0, -80.0, -57.0, "Quebec", "Canada"),
    (60.0, 75.0, -140.0, -55.0, "the Canadian Arctic", "Canada"),
    (14.0, 33.0, -118.0, -86.0, "Mexico", "Mexico"),
    (7.0, 18.5, -92.0, -77.0, "Central America", "Guatemala"),
    (17.0, 23.5, -85.0, -65.0, "the Caribbean", "Caribbean"),

    # === South America ===
    (-10.0, 5.0, -74.0, -50.0, "the Amazon Basin", "Brazil"),
    (-22.0, -16.0, -60.0, -54.0, "the Pantanal", "Brazil"),
    (-24.0, -10.0, -52.0, -42.0, "the Cerrado", "Brazil"),
    (-35.0, 5.0, -74.0, -34.0, "Brazil", "Brazil"),
    (-55.0, -40.0, -75.0, -60.0, "Patagonia", "Argentina"),
    (-55.0, -22.0, -74.0, -53.0, "Argentina", "Argentina"),
    (-55.0, -17.0, -76.0, -66.0, "Chile", "Chile"),
    (-23.0, -9.0, -70.0, -57.0, "Bolivia", "Bolivia"),
    (-18.5, 0.0, -82.0, -69.0, "Peru", "Peru"),
    (-4.0, 13.0, -79.0, -66.0, "Colombia", "Colombia"),
    (0.0, 13.0, -73.0, -59.0, "Venezuela", "Venezuela"),

    # === Europe ===
    (54.0, 71.5, 4.0, 32.0, "Scandinavia", "Sweden"),
    (49.5, 60.5, -11.0, 2.0, "the UK", "UK"),
    (36.0, 44.0, -10.0, 3.0, "the Iberian Peninsula", "Spain"),
    (42.0, 51.5, -5.0, 8.5, "France", "France"),
    (36.5, 47.0, 6.5, 18.5, "Italy", "Italy"),
    (34.5, 42.0, 19.0, 30.0, "Greece", "Greece"),
    (47.0, 55.0, 5.0, 17.0, "Central Europe", "Germany"),
    (44.0, 55.0, 17.0, 32.0, "Eastern Europe", "Ukraine"),
    (35.5, 42.5, 26.0, 45.0, "Turkey", "Turkey"),

    # === Africa ===
    (21.0, 37.5, -18.0, 12.0, "North Africa", "Algeria"),
    (22.0, 37.0, 12.0, 36.0, "Libya", "Libya"),
    (10.0, 18.0, -18.0, 15.0, "the Western Sahel", "Mali"),
    (6.0, 16.0, 15.0, 40.0, "the Chad Basin", "Chad"),
    (4.0, 12.0, -18.0, 5.0, "West Africa", "Ghana"),
    (-8.0, 6.0, 10.0, 30.0, "the Congo Basin", "DR Congo"),
    (-5.0, 13.0, 30.0, 52.0, "East Africa", "Kenya"),
    (-35.0, -16.0, 11.0, 35.0, "Southern Africa", "Zambia"),
    (-26.0, -12.0, 43.0, 51.0, "Madagascar", "Madagascar"),

    # === Middle East ===
    (12.0, 32.0, 32.0, 60.0, "the Arabian Peninsula", "Saudi Arabia"),
    (30.0, 40.0, 35.0, 50.0, "the Levant", "Iraq"),
    (25.0, 40.0, 44.0, 65.0, "Iran", "Iran"),

    # === Central Asia ===
    (35.0, 56.0, 45.0, 87.0, "the Kazakhstan steppe", "Kazakhstan"),

    # === Russia (large — split into Siberian regions) ===
    (50.0, 75.0, 100.0, 180.0, "eastern Siberia", "Russia"),
    (50.0, 75.0, 60.0, 100.0, "western Siberia", "Russia"),
    (45.0, 65.0, 20.0, 60.0, "European Russia", "Russia"),

    # === East Asia ===
    (42.0, 54.0, 88.0, 120.0, "Mongolia", "Mongolia"),
    (22.0, 45.0, 85.0, 130.0, "China", "China"),
    (33.0, 43.0, 124.0, 131.0, "Korea", "South Korea"),
    (30.0, 46.0, 129.0, 146.0, "Japan", "Japan"),

    # === South Asia ===
    (5.0, 36.0, 68.0, 97.0, "India", "India"),
    (27.0, 36.0, 61.0, 75.0, "Pakistan", "Pakistan"),

    # === Southeast Asia ===
    (-11.0, 8.0, 95.0, 141.0, "Indonesia", "Indonesia"),
    (5.0, 21.0, 97.0, 106.0, "Thailand", "Thailand"),
    (7.0, 23.5, 104.0, 120.0, "Vietnam", "Vietnam"),
    (5.0, 20.0, 115.0, 127.0, "the Philippines", "Philippines"),
    (-11.0, -3.0, 141.0, 156.0, "Papua New Guinea", "Papua New Guinea"),

    # === Oceania ===
    (-29.0, -10.0, 138.0, 154.0, "Queensland", "Australia"),
    (-38.0, -28.0, 140.0, 154.0, "New South Wales", "Australia"),
    (-39.0, -34.0, 140.0, 150.0, "Victoria", "Australia"),
    (-45.0, -39.0, 143.5, 149.0, "Tasmania", "Australia"),
    (-26.0, -10.0, 129.0, 138.0, "the Northern Territory", "Australia"),
    (-35.0, -12.0, 112.0, 129.0, "Western Australia", "Australia"),
    (-48.0, -34.0, 165.0, 180.0, "New Zealand", "New Zealand"),
]


def _lookup_box(lat: float, lon: float) -> tuple[str, str] | None:
    """First bounding box containing (lat, lon) wins; None if no match."""
    for lat_min, lat_max, lon_min, lon_max, region, country in _GEO_BOXES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return region, country
    return None


# Lazy module-level cache of data/cities.csv rows, keyed only by the process
# lifetime (the fetch loop calls reverse_geocode_simple once per hotspot, so
# re-reading the CSV per call would be wasteful). None = not yet loaded.
_CITIES_CACHE: list[dict] | None = None


def _nearest_city(lat: float, lon: float) -> tuple[str, str] | None:
    """Nearest ``data/cities.csv`` place within ``GEOCODE_NEAR_CITY_MAX_KM``,
    or None if the CSV is unreadable or every city is farther than that.

    Loads and caches the CSV at module level on first use. Any failure to
    read the CSV degrades to None (the caller falls back to the old
    coordinate-string label) — geocoding must never break the fire fetch.
    """
    global _CITIES_CACHE
    if _CITIES_CACHE is None:
        try:
            _CITIES_CACHE = load_cities()
        except (OSError, csv.Error):
            _CITIES_CACHE = []

    best_city: str | None = None
    best_country: str | None = None
    best_dist = float("inf")
    for row in _CITIES_CACHE:
        try:
            city_lat = float(row["lat"])
            city_lon = float(row["lon"])
        except (KeyError, ValueError, TypeError):
            continue
        dist = _haversine_km(lat, lon, city_lat, city_lon)
        if dist < best_dist:
            best_dist = dist
            best_city = row.get("city")
            best_country = row.get("country")

    if best_city is None or best_dist > GEOCODE_NEAR_CITY_MAX_KM:
        return None
    return f"near {best_city}", best_country or "Unknown"


def reverse_geocode_simple(lat: float, lon: float) -> tuple[str, str]:
    """Map coordinates to a (region, country) label.

    Bounding-box lookup first — curated editorial region names (e.g. "the
    Amazon Basin") always win when they match. On a box miss, fall back to
    the nearest ``data/cities.csv`` place within ``GEOCODE_NEAR_CITY_MAX_KM``:
    ``region="near <city>"``, ``country=<city's country>``. Only beyond that
    distance from every curated city does the old coordinate-string region +
    "Unknown" country fallback remain — happens mostly for open ocean or
    Arctic / Antarctic waters, where no fire should fire anyway.
    """
    match = _lookup_box(lat, lon)
    if match is not None:
        return match
    try:
        near = _nearest_city(lat, lon)
    except Exception:
        # Geocoding must never break the fire fetch — any unexpected failure
        # in the nearest-city lookup degrades to the old fallback.
        near = None
    if near is not None:
        return near
    region = f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}{'E' if lon >= 0 else 'W'}"
    return region, "Unknown"


def _lat_lon_to_region(lat: float, lon: float) -> str:
    """Region name from coordinates. Kept as a thin wrapper for call
    sites and tests that pre-date the unified lookup."""
    return reverse_geocode_simple(lat, lon)[0]


def _lat_lon_to_country(lat: float, lon: float) -> str:
    """Country name from coordinates. Thin wrapper — see ``_lat_lon_to_region``."""
    return reverse_geocode_simple(lat, lon)[1]
