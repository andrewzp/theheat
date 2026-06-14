"""NASA FIRMS fire detection data."""

import csv
import io
import os
from dataclasses import dataclass
from datetime import date

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry
from src.data._witness import tag_source_leg, with_witness
from src.data.source_status import SourceFetchError, SourceSkipped

FIRMS_API_KEY = os.environ.get("NASA_FIRMS_API_KEY", "")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# NOAA HMS independent fire witness (R-02). Independent HOST
# (satepsanone.nesdis.noaa.gov, NESDIS) AND independent INSTRUMENT (GOES) — so it
# covers a full FIRMS host outage that the same-host R-06 product chain cannot.
# Daily accumulating text file; no auth. N. America coverage only.
HMS_FIRE_URL = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Fire_Points/Text"
# HMS publishes no per-detection confidence percentage — the analyst/NGFS QC IS
# the confidence. We assign the FIRMS "high" floor so HMS events score comparably
# to primary events; the observed_alt_host grade + data_source fact mark provenance.
HMS_NOMINAL_CONFIDENCE = 80
# FIRMS same-host product chain (R-06). A given product can be momentarily
# empty/lagged while a sibling has the data. Freshest sensors lead; all share the
# area/csv host + MAP_KEY, so they are semantically-equivalent observations (no
# evidence_grade). This is product-gap insurance, NOT a host-outage fix (HMS is).
_FIRMS_PRODUCT_CHAIN = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
]
# HMS (GOES-East/West) only resolves the Americas. Outside this box the witness
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


# VIIRS confidence is categorical (l/n/h), MODIS is 0-100 percentage.
# We normalize both to a 0-100 scale so the same filter threshold works.
# VIIRS mapping mirrors NASA's own typical interpretation.
_VIIRS_CONFIDENCE = {
    "l": 30,
    "n": 70,
    "h": 95,
}


def _parse_confidence(raw: str) -> int | None:
    """Return a 0-100 confidence score, or None if unparseable.

    Handles both numeric percentages (MODIS, "90" or "90%") and VIIRS
    categorical letters ("l", "n", "h"). Unknown values return None so the
    caller can skip the row instead of silently scoring it 0 (which was the
    prior bug — VIIRS rows all fell through ``int()`` and were dropped).
    """
    if raw is None:
        return None
    value = str(raw).strip().rstrip("%").strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered in _VIIRS_CONFIDENCE:
        return _VIIRS_CONFIDENCE[lowered]
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


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
        return with_witness(primary, witness, source_key="firms", leg_label="noaa_hms")
    except (SourceFetchError, requests.RequestException) as exc:
        if strict:
            raise SourceFetchError(f"FIRMS fetch failed: {exc}") from exc
        return []


def _fetch_fires_product_chain(
    confidence_min: int,
    frp_min: float,
    source: str,
    days: int,
) -> list[FireEvent]:
    """Try FIRMS products in order (R-06): a given product can be momentarily
    empty/lagged while a sibling has the data. Same host + MAP_KEY, so these are
    semantically-equivalent observations — a non-first product records
    ``source_leg`` (→ status degraded) but NO ``evidence_grade``. Order leads with
    the freshest sensors.

    Returns ``[]`` only when every reachable product is genuinely empty (FIRMS up,
    no big fires — do NOT fall through to the independent HMS witness). Raises
    ``SourceFetchError`` only when EVERY product failed (a real host outage), so
    ``with_witness`` then tries the independent NOAA HMS leg. This chain is the
    same host and therefore NOT a host-outage fix; HMS (R-02) is."""
    if source in _FIRMS_PRODUCT_CHAIN:
        chain = _FIRMS_PRODUCT_CHAIN[_FIRMS_PRODUCT_CHAIN.index(source):]
    else:
        chain = [source, *[p for p in _FIRMS_PRODUCT_CHAIN if p != source]]

    last_exc: Exception | None = None
    any_reachable = False
    for index, product in enumerate(chain):
        try:
            fires = _fetch_fires_primary(confidence_min, frp_min, product, days)
        except (SourceFetchError, requests.RequestException) as exc:
            last_exc = exc
            continue
        any_reachable = True
        if fires:
            # index 0 is the requested product (primary, no provenance); a later
            # product served the gap -> tag the leg (degraded), no grade.
            return fires if index == 0 else tag_source_leg(fires, product)
    if not any_reachable and last_exc is not None:
        raise SourceFetchError(f"FIRMS product chain exhausted: {last_exc}") from last_exc
    return []


def _fetch_fires_primary(
    confidence_min: int,
    frp_min: float,
    source: str,
    days: int,
) -> list[FireEvent]:
    """Single-product NASA FIRMS fetch. Raises ``SourceFetchError`` on any failure
    so the product chain / ``with_witness`` can fall through."""
    payload_dates: list[str | None] = []
    try:
        resp = fetch_with_retry(
            f"{FIRMS_URL}/{FIRMS_API_KEY}/{source}/world/{days}",
            timeout=30,
        )

        reader = csv.DictReader(io.StringIO(resp.text))
        fires = []
        for row in reader:
            payload_dates.append(row.get("acq_date") or row.get("acq_datetime"))
            conf = _parse_confidence(row.get("confidence"))
            if conf is None:
                continue
            try:
                frp = float(row.get("frp", "0") or "0")
            except (ValueError, TypeError):
                continue

            if conf >= confidence_min and frp >= frp_min:
                try:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                except (ValueError, KeyError, TypeError):
                    continue
                city, country = reverse_geocode_simple(lat, lon)
                event_id = f"fire_{lat:.2f}_{lon:.2f}_{date.today().isoformat()}"
                fires.append(FireEvent(
                    lat=lat,
                    lon=lon,
                    confidence=conf,
                    frp=frp,
                    nearest_city=city,
                    country=country,
                    event_id=event_id,
                ))

    except (requests.RequestException, csv.Error, KeyError) as exc:
        raise SourceFetchError(f"FIRMS fetch failed: {exc}") from exc
    except SourceFetchError:
        raise
    except Exception as exc:
        raise SourceFetchError(f"FIRMS fetch failed: {exc}") from exc
    if newest_date := newest_freshness_date(payload_dates):
        assert_freshness(newest_date, "firms", max_age_days=2)
    return fires


def _in_north_america(lat: float, lon: float) -> bool:
    lat_min, lat_max, lon_min, lon_max = _HMS_NORTH_AMERICA_BBOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _fetch_fires_hms(frp_min: float) -> list[FireEvent]:
    """NOAA HMS independent fire witness (R-02).

    Fetches the daily HMS fire-points text file (GOES/VIIRS detections from an
    independent NESDIS host) and maps the SAME ``FireEvent`` shape, tagged
    ``source_leg="noaa_hms"``. N. America only — points outside the HMS coverage
    box are dropped (FIRMS has no fallback there). ``-999.0`` FRP is missing, not
    zero. Confidence is the analyst-QC nominal floor (HMS has no per-row %)."""
    today = date.today()
    url = f"{HMS_FIRE_URL}/{today:%Y}/{today:%m}/hms_fire{today:%Y%m%d}.txt"
    resp = fetch_with_retry(url, timeout=30)

    rows = list(csv.reader(io.StringIO(resp.text)))
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    try:
        i_lon, i_lat, i_frp = header.index("Lon"), header.index("Lat"), header.index("FRP")
    except ValueError as exc:
        raise SourceFetchError(f"HMS fire schema drift: header={header}") from exc

    fires: list[FireEvent] = []
    last_col = max(i_lon, i_lat, i_frp)
    for raw in rows[1:]:
        if len(raw) <= last_col:
            continue
        try:
            lon = float(raw[i_lon].strip())
            lat = float(raw[i_lat].strip())
            frp = float(raw[i_frp].strip())
        except (ValueError, IndexError):
            continue
        if frp < 0:  # -999.0 sentinel = FRP not retrieved
            continue
        if frp < frp_min:
            continue
        if not _in_north_america(lat, lon):
            continue
        city, country = reverse_geocode_simple(lat, lon)
        event_id = f"fire_{lat:.2f}_{lon:.2f}_{today.isoformat()}"
        fires.append(FireEvent(
            lat=lat,
            lon=lon,
            confidence=HMS_NOMINAL_CONFIDENCE,
            frp=frp,
            nearest_city=city,
            country=country,
            event_id=event_id,
        ))
    # The file is named for today's UTC date; guard against a stale/misdated file
    # within the same freshness budget the primary uses.
    assert_freshness(today.isoformat(), "firms", max_age_days=2)
    return tag_source_leg(fires, "noaa_hms")


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


def reverse_geocode_simple(lat: float, lon: float) -> tuple[str, str]:
    """Map coordinates to a (region, country) label.

    Bounding-box lookup. Falls back to a coordinate-string region +
    "Unknown" country when no box contains the point — happens mostly
    for open ocean or Arctic / Antarctic waters, where no fire should
    fire anyway.
    """
    match = _lookup_box(lat, lon)
    if match is not None:
        return match
    region = f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}{'E' if lon >= 0 else 'W'}"
    return region, "Unknown"


def _lat_lon_to_region(lat: float, lon: float) -> str:
    """Region name from coordinates. Kept as a thin wrapper for call
    sites and tests that pre-date the unified lookup."""
    return reverse_geocode_simple(lat, lon)[0]


def _lat_lon_to_country(lat: float, lon: float) -> str:
    """Country name from coordinates. Thin wrapper — see ``_lat_lon_to_region``."""
    return reverse_geocode_simple(lat, lon)[1]
