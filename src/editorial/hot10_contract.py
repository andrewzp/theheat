"""Hot10: a qualified forecast-anomaly ranking over a disclosed sampled city universe.

Hot10 ranks each sampled city's provider-local forecast daily high by its
departure from an attributable point normal for that month. It is not the
world's ten hottest places, an observed global maximum or a record. A row ranks
only with complete Open-Meteo forecast provenance, the provider's local day at
retrieval, a current interval at qualification, a qualified normal for the same
point and month, a registered unique location and a plausible departure. Fewer
than ten qualified rows hold the bulletin: nothing is padded, replaced or estimated
to fill the slate.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.data import places
from src.data.temperature_evidence import FORECAST_PRODUCT, fingerprint, finite
from src.two_bot.strict_contract import valid_date as _valid_timestamp

SCHEMA = "theheat.hot10-bulletin/v1"
SIZE = 10
SOURCE_NAME = "Open-Meteo"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
BASELINE_PRODUCT = "meteostat-normals-point-v1"
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


def _qualify_one(ct: Any, normals: dict, now: datetime) -> tuple[str | None, dict | None]:
    evidence = getattr(ct, "evidence", None)
    if not isinstance(evidence, dict) or evidence.get("evidence_type") != "forecast" \
            or evidence.get("source_product") != FORECAST_PRODUCT or not evidence.get("revision_id") \
            or not finite(getattr(ct, "temp_high_c", None)) or evidence.get("unit") != "C":
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
    if not isinstance(meta, dict) or meta.get("source_product") != BASELINE_PRODUCT \
            or meta.get("sampling_point_id") != place["sampling_point_id"] or meta.get("month") != month \
            or not _valid_timestamp(meta.get("retrieved_at")) or not finite(entry[month]):
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
        "baseline": {key: meta.get(key) for key in _BASELINE_KEYS},
    }
    return None, row


def row_fingerprint(row: dict) -> str:
    return fingerprint({key: value for key, value in row.items() if key not in ("rank", "row_fingerprint")})


def qualify(temps: list, normals: dict, *, sampled: int, now: datetime) -> dict:
    """Qualified ranked rows (at most ten) plus the disclosed universe and exclusions."""
    now = now.astimezone(UTC)
    excluded: Counter = Counter()
    rows: list[dict] = []
    seen: set[str] = set()
    for ct in temps:
        reason, row = _qualify_one(ct, normals, now)
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
        "excluded": dict(sorted(excluded.items())), "ranked_by": RANKED_BY, "baseline_scope": BASELINE_SCOPE,
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
    if (raw.get("source_product") != FORECAST_PRODUCT or raw.get("source_url") != FORECAST_URL
            or evidence.get("evidence_type") != "forecast" or evidence.get("source_product") != FORECAST_PRODUCT
            or evidence.get("baseline_product") != BASELINE_PRODUCT):
        failures.append("provenance")
    rows = raw.get("cities")
    if not isinstance(rows, list) or len(rows) != SIZE or not all(isinstance(row, dict) for row in rows):
        return failures + ["slate_size"]
    if len({row.get("place_id") for row in rows}) != SIZE:
        failures.append("duplicate_location")
    for rank, row in enumerate(rows, start=1):
        if row.get("rank") != rank or row.get("row_fingerprint") != row_fingerprint(row):
            failures.append("row_fingerprint")
            break
        temp, normal, anomaly = row.get("temp_high_c"), row.get("normal_high_c"), row.get("anomaly_c")
        forecast, baseline = row.get("forecast") or {}, row.get("baseline") or {}
        retrieved = instant(row.get("retrieved_at"))
        if (not all(finite(value) for value in (temp, normal, anomaly)) or abs(temp - normal - anomaly) > 1e-9
                or abs(anomaly) > MAX_ANOMALY_C or forecast.get("source_product") != FORECAST_PRODUCT
                or baseline.get("source_product") != BASELINE_PRODUCT
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
            or universe.get("scope") != UNIVERSE_SCOPE):
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


__all__ = ["BASELINE_PRODUCT", "FORECAST_URL", "SCHEMA", "SIZE", "SOURCE_NAME", "UNIVERSE_SCOPE", "current_hold",
           "qualify", "row_fingerprint", "validate_bundle"]
