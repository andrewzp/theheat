"""Hot10: a qualified forecast-anomaly ranking over a disclosed sampled city universe.

Hot10 ranks each sampled city's provider-local forecast daily high by its
departure from an attributable point normal for that month. One normals product
supplies a whole bulletin (``BASELINES``): the default Meteostat point normal, or
the explicit NOAA GHCN-Daily station mean daily maximum (1991-2020), never both
and never relabelled; every row and the bulletin name the product. It is not the
world's ten hottest places, an observed global maximum or a record. A row ranks
only with complete Open-Meteo forecast provenance, the provider's local day at
retrieval, a current interval at qualification, a qualified normal for the same
point and month, a registered unique location and a plausible departure. Fewer
than ten qualified rows hold the bulletin: nothing is padded, replaced or estimated
to fill the slate.

A GHCND baseline is re-checked from what each row retains, never from its declared
result alone: daily coverage possible for the stated qualifying years and month
(leap Februaries and the five-missing-day rule included), non-negative rejection
counts, finite in-range coordinates and elevations, the place elevation of the
registered catalogue point, and the station distance recomputed within the stored
0.01 km rounding. A bulletin re-fingerprinted after any of these was changed fails.
"""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import UTC, date, datetime, timedelta
import math
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.data import places
from src.data.temperature_evidence import FORECAST_PRODUCT, finite
from src.data.json_evidence import fingerprint
from src.two_bot.strict_contract import valid_date as _valid_timestamp

SCHEMA = "theheat.hot10-bulletin/v2"
SIZE = 10
SOURCE_NAME = "Open-Meteo"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
BASELINE_PRODUCT = "meteostat-normals-point-v1"  # the default product; unchanged
GHCND_PRODUCT = "noaa-ghcnd-monthly-mean-tmax-v1"
GHCND_PERIOD = (1991, 2020)
GHCND_MIN_YEARS = 24
GHCND_MAX_DISTANCE_KM = 35.0
# Mirrors of the GHCND builder's rules (src/data/ghcnd_monthly_normals.py; this packaged module must not import it).
GHCND_MAX_ELEVATION_DIFF_M = 350.0
GHCND_MAX_MISSING_DAYS = 5
GHCND_DISTANCE_TOLERANCE_KM = 0.005  # stored distances are rounded to 0.01 km
GHCND_ELEVATION_RANGE_M = (-500.0, 9000.0)  # excludes the -999.9 / -9999 missing-value sentinels
_EARTH_RADIUS_M = 6_371_000
_GHCND_VERSION = re.compile(r"\d+\.\d+-(?:upd|por)-\d{10}\Z")
_GHCND_STATION = re.compile(r"[A-Z0-9]{11}\Z")
MAX_ANOMALY_C = 30.0
MAX_CAPTURE_AGE = timedelta(hours=12)
FUTURE_TOLERANCE = timedelta(minutes=5)
RANKED_BY = "forecast local daily maximum minus the Meteostat point monthly normal"
BASELINE_SCOPE = ("Meteostat point monthly normal for each city's stated period; underlying sample coverage "
                  "unavailable")
UNIVERSE_SCOPE = ("Ranks only the sampled catalogue cities with qualified forecasts and normals; not the world's "
                  "hottest places, an observed global maximum or a record.")
_FORECAST_KEYS = ("source_product", "model", "unit", "aggregation", "provider_grid", "revision_id")
_BASELINE_KEYS = ("source_product", "period_start", "period_end", "retrieved_at", "sampling_point_id", "month",
                  "revision_id")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
GHCND_RANKED_BY = ("forecast local daily maximum minus the NOAA GHCN-Daily station mean daily maximum for that "
                   "month, 1991-2020")
GHCND_BASELINE_SCOPE = ("NOAA GHCN-Daily station climatology: mean daily maximum for the month, 1991-2020, at the "
                        "nearest qualifying station (each row states station, distance and years used); not a "
                        "record maximum")
_GHCND_KEYS = _BASELINE_KEYS + ("statistic", "years_used", "first_year", "last_year", "valid_days", "station_id",
                                "station_name", "station_lat", "station_lon", "station_elevation_m", "distance_km",
                                "source_version", "qualifying_year_mask", "flagged_values", "place_elevation_m")
# One entry per normals product a bulletin may rank against; the wording is part of the product.
BASELINES = {
    BASELINE_PRODUCT: {"ranked_by": RANKED_BY, "baseline_scope": BASELINE_SCOPE, "keys": _BASELINE_KEYS},
    GHCND_PRODUCT: {"ranked_by": GHCND_RANKED_BY, "baseline_scope": GHCND_BASELINE_SCOPE, "keys": _GHCND_KEYS},
}



def local_weekday(valid_date: str) -> str:
    """English weekday of an already-qualified provider-local ISO date."""
    return _WEEKDAYS[date.fromisoformat(valid_date).weekday()]


def _registered_elevation(place_id: Any, lat: Any, lon: Any) -> float | None:
    """The catalogue elevation of ``place_id``'s registered point when (lat, lon) is that point, else None."""
    try:
        point = places.sampling_point_id(lat, lon)
    except (TypeError, ValueError):
        return None
    for entry in places.registry():
        if entry["place_id"] == place_id:
            same = places.sampling_point_id(entry["lat"], entry["lon"]) == point
            return float(entry["elevation_m"]) if same and finite(entry.get("elevation_m")) else None
    return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine, as the builder selects stations."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    arch = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return _EARTH_RADIUS_M * 2 * math.asin(math.sqrt(min(1.0, arch))) / 1000


def _ghcnd_coverage_ok(meta: dict, month: int) -> bool:
    """valid_days possible for the qualifying years named by the mask; rejection counts in range."""
    mask: Any = meta.get("qualifying_year_mask")
    years: Any = meta.get("years_used")
    valid: Any = meta.get("valid_days")
    flagged: Any = meta.get("flagged_values")
    span = range(GHCND_PERIOD[0], GHCND_PERIOD[1] + 1)
    if type(mask) is not str or len(mask) != len(span) or set(mask) - {"0", "1"} \
            or not all(type(value) is int for value in (years, valid, flagged,
                                                       meta.get("first_year"), meta.get("last_year"))):
        return False
    chosen = [year for year, flag in zip(span, mask) if flag == "1"]
    if len(chosen) != years or not chosen or (chosen[0], chosen[-1]) != (meta.get("first_year"), meta.get("last_year")):
        return False
    days = sum(calendar.monthrange(year, month)[1] for year in chosen)
    slots = sum(calendar.monthrange(year, month)[1] for year in span)
    return days - GHCND_MAX_MISSING_DAYS * len(chosen) <= valid <= days and 0 <= flagged <= slots - valid


def _ghcnd_baseline_ok(meta: dict, *, place_id: Any, lat: Any, lon: Any, month: Any) -> bool:
    """A GHCND baseline row: mean daily maximum, the fixed period, possible coverage, a nearby registered station."""
    years: Any = meta.get("years_used")
    distance: Any = meta.get("distance_km")
    if not (meta.get("statistic") == "mean_daily_maximum"
            and (meta.get("period_start"), meta.get("period_end")) == GHCND_PERIOD
            and type(years) is int and GHCND_MIN_YEARS <= years <= GHCND_PERIOD[1] - GHCND_PERIOD[0] + 1
            and finite(distance) and 0 <= distance <= GHCND_MAX_DISTANCE_KM
            and isinstance(meta.get("station_id"), str) and bool(_GHCND_STATION.fullmatch(meta["station_id"]))
            and isinstance(meta.get("source_version"), str) and bool(_GHCND_VERSION.fullmatch(meta["source_version"]))
            and type(month) is int and meta.get("month") == month and 1 <= month <= 12
            and _ghcnd_coverage_ok(meta, month)):
        return False
    station_lat: Any = meta.get("station_lat")
    station_lon: Any = meta.get("station_lon")
    place_elevation: Any = meta.get("place_elevation_m")
    station_elevation: Any = meta.get("station_elevation_m")
    if not all(finite(value) for value in (lat, lon, station_lat, station_lon, place_elevation, station_elevation)):
        return False
    low, high = GHCND_ELEVATION_RANGE_M
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and -90 <= station_lat <= 90 and -180 <= station_lon <= 180
            and low <= place_elevation <= high and low <= station_elevation <= high
            and abs(station_elevation - place_elevation) <= GHCND_MAX_ELEVATION_DIFF_M
            and place_elevation == _registered_elevation(place_id, lat, lon)):
        return False
    actual = _distance_km(lat, lon, station_lat, station_lon)
    return actual <= GHCND_MAX_DISTANCE_KM and abs(actual - distance) <= GHCND_DISTANCE_TOLERANCE_KM + 1e-9


def _valid_month(value: Any) -> int | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").month if isinstance(value, str) else None
    except ValueError:
        return None


def instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None


def _local_date(moment: datetime, zone_name: str) -> str | None:
    try:
        return moment.astimezone(ZoneInfo(zone_name)).date().isoformat()
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None


def _qualify_one(ct: Any, normals: dict, now: datetime,
                 product: str = BASELINE_PRODUCT) -> tuple[str | None, dict | None]:
    evidence = getattr(ct, "evidence", None)
    if not isinstance(evidence, dict) or evidence.get("evidence_type") != "forecast" \
            or evidence.get("source_product") != FORECAST_PRODUCT or not evidence.get("revision_id") \
            or not finite(getattr(ct, "temp_high_c", None)) or evidence.get("unit") != "C" \
            or type(evidence.get("utc_offset_seconds")) is not int:
        return "forecast_unqualified", None
    valid_date = getattr(ct, "signal_date", None)
    zone = evidence.get("timezone")
    start, end = instant(evidence.get("valid_start")), instant(evidence.get("valid_end"))
    if valid_date is None or evidence.get("valid_date") != valid_date.isoformat() or not isinstance(zone, str) \
            or start is None or end is None or start >= end:
        return "missing_valid_time", None
    retrieved = instant(evidence.get("retrieved_at"))
    if retrieved is None:
        return "forecast_unqualified", None
    if retrieved > now + FUTURE_TOLERANCE:
        return "future_capture", None
    if now - retrieved > MAX_CAPTURE_AGE:
        return "stale_capture", None
    if _local_date(retrieved, zone) != valid_date.isoformat() or not start <= now < end:
        return "wrong_local_day", None
    try:
        place = places.resolve_place(ct.city, ct.country, ct.lat, ct.lon)
        key = places.event_location_key(ct.city, ct.country, ct.lat, ct.lon)
    except (ValueError, TypeError, KeyError):
        return "unregistered_location", None
    if str(place.get("place_id", "")).startswith("ux"):
        return "unregistered_location", None
    entry = normals.get(key) if isinstance(normals, dict) else None
    month = valid_date.month
    meta = ((entry or {}).get("_meta") or {}).get(month) if isinstance(entry, dict) else None
    if not isinstance(entry, dict) or month not in entry:
        return ("ambiguous_normal" if isinstance(meta, dict) and meta.get("conflict") else "missing_normal"), None
    if not isinstance(meta, dict) or meta.get("source_product") != product \
            or meta.get("sampling_point_id") != place["sampling_point_id"] or meta.get("month") != month \
            or any(type(meta.get(key)) is not int for key in ("month", "period_start", "period_end")) \
            or not _valid_timestamp(meta.get("retrieved_at")) or not finite(entry[month]) \
            or (product == GHCND_PRODUCT and not _ghcnd_baseline_ok(meta, place_id=place["place_id"], lat=place["lat"],
                                                                   lon=place["lon"], month=month)):
        return "unqualified_normal", None
    anomaly = float(ct.temp_high_c) - float(entry[month])
    if abs(anomaly) > MAX_ANOMALY_C:
        return "implausible_anomaly", None
    row = {
        "city": ct.city, "country": ct.country, "place_id": place["place_id"],
        "sampling_point_id": place["sampling_point_id"], "lat": float(ct.lat), "lon": float(ct.lon),
        "valid_date": valid_date.isoformat(), "timezone": zone, "utc_offset_seconds": evidence.get("utc_offset_seconds"),
        "valid_start": evidence["valid_start"], "valid_end": evidence["valid_end"],
        "retrieved_at": evidence["retrieved_at"], "temp_high_c": float(ct.temp_high_c),
        "normal_high_c": float(entry[month]), "anomaly_c": anomaly,
        "forecast": {key: evidence.get(key) for key in _FORECAST_KEYS},
        "baseline": {key: meta.get(key) for key in BASELINES[product]["keys"]},
    }
    return None, row


def row_fingerprint(row: dict) -> str:
    return fingerprint({key: value for key, value in row.items() if key not in ("rank", "row_fingerprint")}, profile=SCHEMA)


def qualify(temps: list, normals: dict, *, sampled: int, now: datetime, product: str = BASELINE_PRODUCT) -> dict:
    """Qualified ranked rows (at most ten) plus the disclosed universe and exclusions.

    ``normals`` must come from ``product`` alone; a normal of any other product is
    ``unqualified_normal``, never ranked.
    """
    if product not in BASELINES:
        raise ValueError("hot10_baseline_product_unknown")
    now = now.astimezone(UTC)
    excluded: Counter = Counter()
    rows: list[dict] = []
    seen: set[str] = set()
    for ct in temps:
        reason, row = _qualify_one(ct, normals, now, product)
        if row is not None and row["place_id"] in seen:
            reason, row = "duplicate_location", None
        if row is None:
            excluded[reason or "forecast_unqualified"] += 1
            continue
        seen.add(row["place_id"])
        rows.append(row)
    rows.sort(key=lambda row: (-row["anomaly_c"], row["place_id"]))
    ranked = []
    for rank, row in enumerate(rows[:SIZE], start=1):
        ranked.append({**row, "rank": rank, "row_fingerprint": row_fingerprint(row)})
    universe = {
        "sampled_cities": int(sampled), "returned_forecasts": len(temps), "qualified_cities": len(rows),
        "excluded": dict(sorted(excluded.items())), "ranked_by": BASELINES[product]["ranked_by"],
        "baseline_scope": BASELINES[product]["baseline_scope"],
        "scope": UNIVERSE_SCOPE, "local_days": sorted({row["valid_date"] for row in ranked}),
    }
    return {"rows": ranked, "universe": universe, "complete": len(rows) >= SIZE}


def _field(bundle: Any, name: str) -> Any:
    # A live StoryBundle and its retained review_context dict share one contract.
    return bundle.get(name) if isinstance(bundle, dict) else getattr(bundle, name, None)


def validate_bundle(bundle: Any) -> list[str]:
    """Retained-bulletin contract; codes only. Never repairs or re-ranks a bundle."""
    raw = _field(bundle, "raw_signal_dump")
    if _field(bundle, "signal_kind") != "hot10":
        return ["bulletin_schema"] if isinstance(bundle, dict) or bundle is None else []
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return ["bulletin_schema"]
    failures = []
    value = raw.get("evidence")
    evidence: dict = value if isinstance(value, dict) else {}
    product = evidence.get("baseline_product") if isinstance(evidence.get("baseline_product"), str) else None
    if (raw.get("source_product") != FORECAST_PRODUCT or raw.get("source_url") != FORECAST_URL
            or evidence.get("evidence_type") != "forecast" or evidence.get("source_product") != FORECAST_PRODUCT
            or product not in BASELINES):
        failures.append("provenance")
    rows = raw.get("cities")
    if not isinstance(rows, list) or len(rows) != SIZE or not all(isinstance(row, dict) for row in rows):
        return failures + ["slate_size"]
    if len({row.get("place_id") for row in rows}) != SIZE:
        failures.append("duplicate_location")
    known = {row["baseline"].get("source_product") for row in rows if isinstance(row.get("baseline"), dict)
             and isinstance(row["baseline"].get("source_product"), str)} & set(BASELINES)
    if len(known) > 1 or (product in BASELINES and known and known != {product}):
        failures.append("baseline_mixed")  # one product per bulletin; never mixed or relabelled
    expected = product if product in BASELINES else BASELINE_PRODUCT
    for rank, row in enumerate(rows, start=1):
        try:
            row_identity = row_fingerprint(row)
        except (ValueError, TypeError, OverflowError, RecursionError):
            failures.append("row_fingerprint")
            break
        if type(row.get("rank")) is not int or row["rank"] != rank or row.get("row_fingerprint") != row_identity:
            failures.append("row_fingerprint")
            break
        temp, normal, anomaly = row.get("temp_high_c"), row.get("normal_high_c"), row.get("anomaly_c")
        forecast, baseline = row.get("forecast") or {}, row.get("baseline") or {}
        if (type(row.get("utc_offset_seconds")) is not int
                or not isinstance(baseline, dict)
                or any(type(baseline.get(key)) is not int for key in ("month", "period_start", "period_end"))):
            failures.append("integer_metadata")
            break
        retrieved = instant(row.get("retrieved_at"))
        if (not all(finite(value) for value in (temp, normal, anomaly)) or abs(temp - normal - anomaly) > 1e-9
                or abs(anomaly) > MAX_ANOMALY_C or forecast.get("source_product") != FORECAST_PRODUCT
                or baseline.get("source_product") != expected
                or (expected == GHCND_PRODUCT and not _ghcnd_baseline_ok(
                    baseline, place_id=row.get("place_id"), lat=row.get("lat"), lon=row.get("lon"),
                    month=_valid_month(row.get("valid_date"))))
                or baseline.get("sampling_point_id") != row.get("sampling_point_id")
                or retrieved is None or _local_date(retrieved, str(row.get("timezone"))) != row.get("valid_date")):
            failures.append("row_unqualified")
            break
    ordered = sorted(rows, key=lambda row: (-(row.get("anomaly_c") or 0.0), str(row.get("place_id"))))
    if [row.get("place_id") for row in ordered] != [row.get("place_id") for row in rows]:
        failures.append("ranking_order")
    value = raw.get("universe")
    universe: dict = value if isinstance(value, dict) else {}
    qualified, sampled = universe.get("qualified_cities"), universe.get("sampled_cities")
    if (not isinstance(qualified, int) or not isinstance(sampled, int) or qualified < SIZE or sampled < qualified
            or universe.get("scope") != UNIVERSE_SCOPE
            or (product == GHCND_PRODUCT and (universe.get("ranked_by"), universe.get("baseline_scope"))
                != (GHCND_RANKED_BY, GHCND_BASELINE_SCOPE))):
        failures.append("universe")
    leader = rows[0]
    metric = _field(bundle, "headline_metric") or {}
    if metric.get("value") != leader.get("anomaly_c") or _field(bundle, "where") != \
            f"{leader.get('city')}, {leader.get('country')}" or _field(bundle, "when") != leader.get("valid_date"):
        failures.append("leader")
    return failures


def current_hold(bundle: Any, now: datetime | None = None) -> str | None:
    """Final-boundary contract: every ranked row is intact, recent and its local day current.

    This re-derives every hold from the retained rows; it never re-fetches,
    re-ranks or substitutes a city, and a hold is never repaired here.
    """
    failures = validate_bundle(bundle)
    if failures:
        return "hot10_contract_invalid:" + failures[0]
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    for row in _field(bundle, "raw_signal_dump")["cities"]:
        start, end = instant(row.get("valid_start")), instant(row.get("valid_end"))
        retrieved = instant(row.get("retrieved_at"))
        if start is None or end is None or start >= end or retrieved is None:
            return "hot10_contract_invalid:row_unqualified"
        if moment >= end:
            return "hot10_local_day_over"
        if moment < start or retrieved > moment + FUTURE_TOLERANCE:
            return "hot10_not_yet_valid"
        if moment - retrieved > MAX_CAPTURE_AGE:
            return "hot10_capture_stale"
    return None


__all__ = ["BASELINES", "BASELINE_PRODUCT", "FORECAST_URL", "GHCND_BASELINE_SCOPE", "GHCND_PRODUCT", "GHCND_RANKED_BY",
           "SCHEMA", "SIZE", "SOURCE_NAME", "UNIVERSE_SCOPE", "current_hold", "qualify", "row_fingerprint",
           "validate_bundle"]
