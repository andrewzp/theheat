"""Qualified FIRMS/HMS source minutes and compact selected-row receipts.

These hashes bind retained fields, not upstream authenticity or incident identity.
Collection freshness is checked against one explicit UTC response-read reference;
receipt replay itself never substitutes a processing day for the source minute.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import math
import re
from typing import Any, NoReturn

from src.data.source_status import SourceFetchError

FIRMS_PRODUCTS = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
FIRMS_PUBLIC_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/"
HMS_PRODUCT = "noaa-hms-fire-points"
HMS_BASE = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Fire_Points/Text"
FIRMS_FIELDS = frozenset({
    "latitude", "longitude", "frp", "confidence", "acq_date", "acq_time",
    "satellite", "instrument", "version",
})
HMS_FIELDS = frozenset({"Lon", "Lat", "FRP", "YearDay", "Time", "Satellite", "Method"})
RECEIPT_FIELDS = frozenset({
    "schema_version", "source_name", "source_product", "source_url", "acquired_at",
    "precision", "record", "record_sha256",
})
_VIIRS = {"l": (30, "low"), "n": (70, "nominal"), "h": (95, "high")}
_SATELLITE = {"VIIRS_SNPP_NRT": "N", "VIIRS_NOAA20_NRT": "N20", "VIIRS_NOAA21_NRT": "N21"}


def reject(reason: str) -> NoReturn:
    # All callers use bounded constant reasons, never raw field values or URLs.
    raise SourceFetchError(f"fire source schema drift: {reason}")


@dataclass(frozen=True)
class FireSourceRow:
    source_product: str
    acquired_at: str
    lat: float
    lon: float
    frp: float | None
    ranking_confidence: int
    confidence_kind: str
    confidence_value: str | float | None
    record: dict[str, str]


def validate_product(product: Any) -> str:
    if type(product) is not str or product not in (*FIRMS_PRODUCTS, HMS_PRODUCT):
        reject("unsupported source product")
    return product


def validate_days(days: Any) -> int:
    if type(days) is not int or not 1 <= days <= 5:
        reject("requested days must be an integer from one through five")
    return days


def _field(record: Mapping[str, Any], key: str, *, optional: bool = False) -> str:
    value = record.get(key)
    if type(value) is not str:
        reject("missing or non-string required field")
    value = value.strip()
    if (not value and not optional) or len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        reject("empty, oversized or control-bearing source field")
    try:
        value.encode("utf-8")
    except UnicodeError:
        reject("invalid Unicode source field")
    return value


def _number(value: str) -> float:
    # Prevent float() from accepting Unicode digits or special values. Source
    # spelling/precision survives separately in record; numeric projection is finite.
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
        reject("malformed numeric source field")
    number = float(value)
    if not math.isfinite(number):
        reject("nonfinite numeric source field")
    return number


def source_minute(day: str, clock: str, *, hms: bool = False) -> str:
    try:
        if hms:
            if not re.fullmatch(r"[0-9]{7}", day) or not re.fullmatch(r"[0-9]{4}", clock):
                reject("invalid HMS day or minute format")
            year, ordinal = int(day[:4]), int(day[4:])
            first = date(year, 1, 1)
            observed = first + timedelta(days=ordinal - 1)
            if ordinal < 1 or observed.year != year:
                reject("invalid HMS ordinal day")
        else:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) or not re.fullmatch(r"[0-9]{1,4}", clock):
                reject("invalid FIRMS day or minute format")
            observed = date.fromisoformat(day)
        clock = clock.zfill(4)
        stamp = datetime(observed.year, observed.month, observed.day, int(clock[:2]), int(clock[2:]), tzinfo=UTC)
    except (ValueError, OverflowError):
        reject("invalid acquisition calendar or clock")
    return stamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_minute(value: Any) -> datetime:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:00Z", value):
        reject("invalid canonical UTC source minute")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        reject("invalid canonical UTC source minute")


def freshness(row: FireSourceRow, reference: datetime) -> str:
    """Return fresh/stale/future against the collection's explicit UTC minute."""
    if not isinstance(reference, datetime) or reference.tzinfo is None or reference.utcoffset() is None:
        reject("collection reference must be timezone-aware")
    current = reference.astimezone(UTC)
    stamp = parse_minute(row.acquired_at)
    if stamp > current.replace(second=0, microsecond=0):
        return "future"
    return "fresh" if 0 <= (current.date() - stamp.date()).days <= 2 else "stale"


def parse_record(product: Any, raw: Any) -> FireSourceRow:
    """Normalize only selected documented fields; extra wire columns are allowed.

    Missing/duplicate headers and inconsistent row lengths are rejected by the CSV adapter.
    HMS's missing FRP sentinel is a structurally valid row with no measurement;
    it cannot become a receipt or selected event.
    """
    product = validate_product(product)
    if not isinstance(raw, Mapping):
        reject("source row must be an object")
    hms = product == HMS_PRODUCT
    fields = HMS_FIELDS if hms else FIRMS_FIELDS
    record = {name: _field(raw, name) for name in sorted(fields)}
    if hms and "Ecosystem" in raw:
        record["Ecosystem"] = _field(raw, "Ecosystem", optional=True)
    lat = _number(record["Lat" if hms else "latitude"])
    lon = _number(record["Lon" if hms else "longitude"])
    frp: float | None = _number(record["FRP" if hms else "frp"])
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        reject("coordinates outside their valid ranges")
    if hms and frp == -999:
        frp = None
    elif frp is not None and frp < 0:
        reject("negative fire radiative power")
    confidence: str | float | None
    if hms:
        acquired = source_minute(record["YearDay"], record["Time"], hms=True)
        ranking, kind, confidence = 80, "unavailable", None
    else:
        acquired = source_minute(record["acq_date"], record["acq_time"])
        if product == "MODIS_NRT":
            if record["instrument"] != "MODIS" or record["satellite"] not in {"T", "Terra", "A", "Aqua"}:
                reject("product, instrument and satellite disagree")
            value = _number(record["confidence"])
            if not 0 <= value <= 100:
                reject("MODIS confidence outside its valid range")
            ranking, kind, confidence = int(value), "numeric", value
        else:
            if record["instrument"] != "VIIRS" or record["satellite"] != _SATELLITE[product]:
                reject("product, instrument and satellite disagree")
            if record["confidence"] not in _VIIRS:
                reject("invalid VIIRS confidence category")
            ranking, confidence = _VIIRS[record["confidence"]]
            kind = "categorical"
    return FireSourceRow(product, acquired, lat, lon, frp, ranking, kind, confidence, record)


def source_name(product: str) -> str:
    validate_product(product)
    return "NOAA HMS" if product == HMS_PRODUCT else "NASA FIRMS"


def _source_url(product: str, url: Any) -> str:
    if type(url) is not str:
        reject("invalid public source URL")
    if product != HMS_PRODUCT:
        if url != FIRMS_PUBLIC_URL:
            reject("FIRMS provenance must use the credential-free public URL")
    else:
        match = re.fullmatch(re.escape(HMS_BASE) + r"/([0-9]{4})/([0-9]{2})/hms_fire([0-9]{8})\.txt", url)
        if not match or match[1] + match[2] != match[3][:6]:
            reject("invalid dated HMS source URL")
        try:
            date(int(match[3][:4]), int(match[3][4:6]), int(match[3][6:]))
        except ValueError:
            reject("invalid dated HMS source URL")
    return url


def _digest(record: dict[str, str]) -> str:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_receipt(row: FireSourceRow, source_url: str) -> dict[str, Any]:
    # Re-parse to prevent a mutated row dictionary or fabricated dataclass field
    # from receiving a fresh digest that falsely binds a different projection.
    parsed = parse_record(row.source_product, row.record)
    if parsed != row or row.frp is None or any(
        type(getattr(parsed, name)) is not type(getattr(row, name))
        for name in ("lat", "lon", "frp", "ranking_confidence", "confidence_value")
    ):
        reject("source row projection does not match a usable measurement")
    return {
        "schema_version": 1, "source_name": source_name(row.source_product),
        "source_product": row.source_product, "source_url": _source_url(row.source_product, source_url),
        "acquired_at": row.acquired_at, "precision": "minute",
        "record": deepcopy(row.record), "record_sha256": _digest(row.record),
    }


def validate_receipt(receipt: Any) -> FireSourceRow:
    """Reconstruct the selected source row, including exact product/time binding."""
    if type(receipt) is not dict or set(receipt) != RECEIPT_FIELDS:
        reject("invalid acquisition receipt shape")
    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1 or receipt["precision"] != "minute":
        reject("unsupported acquisition receipt version or precision")
    if any(type(receipt[field]) is not str for field in ("source_name", "source_product", "source_url", "acquired_at", "precision", "record_sha256")):
        reject("invalid acquisition receipt field type")
    product = validate_product(receipt["source_product"])
    if receipt["source_name"] != source_name(product):
        reject("source name and product disagree")
    _source_url(product, receipt["source_url"])
    record = receipt["record"]
    allowed = HMS_FIELDS if product == HMS_PRODUCT else FIRMS_FIELDS
    if type(record) is not dict or set(record) not in (allowed, allowed | {"Ecosystem"} if product == HMS_PRODUCT else allowed):
        reject("invalid retained source fields")
    parsed = parse_record(product, record)
    if parsed.frp is None or parsed.record != record or receipt != make_receipt(parsed, receipt["source_url"]):
        reject("acquisition receipt or source projection changed")
    return parsed


def validate_event(event: Any) -> FireSourceRow:
    """Bind retained source fields to a FireEvent; missing legacy fields reject."""
    parsed = validate_receipt(getattr(event, "acquisition_provenance", None))
    leg = getattr(event, "source_leg", None)
    if (parsed.source_product == HMS_PRODUCT and leg != "noaa_hms") or (
        parsed.source_product != HMS_PRODUCT and leg not in (None, parsed.source_product)
    ):
        reject("event source leg and receipt disagree")
    for field in ("lat", "lon", "frp"):
        value = getattr(event, field, None)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != getattr(parsed, field) or not math.isfinite(value):
            reject("event measurement and source receipt disagree")
    if type(getattr(event, "confidence", None)) is not int or event.confidence != parsed.ranking_confidence:
        reject("event ranking confidence and source receipt disagree")
    if getattr(event, "source_product", None) != parsed.source_product or getattr(event, "acquired_at", None) != parsed.acquired_at:
        reject("event product or minute and source receipt disagree")
    # Imported lazily: identity rules are independent of the network adapter.
    from src.data.fire_identity import source_event_id

    if getattr(event, "event_id", None) != source_event_id(parsed.lat, parsed.lon, parsed.acquired_at):
        reject("event identity and source minute disagree")
    return parsed
