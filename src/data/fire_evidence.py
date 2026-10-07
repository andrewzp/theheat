"""Bind thermal story/related projections to their compact source-row receipts.

This establishes internal consistency, never authenticity or physical simultaneity.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
import re
from typing import Any

from src.data.fire_identity import source_event_id
from src.data.fire_source_contract import (
    FIRMS_PRODUCTS, HMS_PRODUCT, FireSourceRow, reject, source_name, validate_receipt,
)
from src.data.source_status import SourceFetchError


def confidence_fact(row: FireSourceRow) -> dict[str, Any]:
    fact = {"label": "satellite_confidence", "value": row.confidence_value}
    if row.confidence_kind == "numeric":
        fact["unit"] = "%"
    return fact


def source_facts(row: FireSourceRow) -> list[dict[str, Any]]:
    return [
        confidence_fact(row),
        {"label": "satellite_confidence_kind", "value": row.confidence_kind},
        {"label": "source_product", "value": row.source_product},
        {"label": "acquired_at", "value": row.acquired_at},
        {"label": "source_date", "value": row.acquired_at[:10]},
        {"label": "acquisition_precision", "value": "minute"},
        {"label": "lat", "value": row.lat},
        {"label": "lon", "value": row.lon},
    ]


def is_thermal(value: Any) -> bool:
    raw = getattr(value, "raw_signal_dump", None)
    raw = raw if isinstance(raw, Mapping) else {}
    metric = getattr(value, "headline_metric", None)
    metric = metric if isinstance(metric, Mapping) else {}
    identity = getattr(value, "event_id", "")
    return (getattr(value, "signal_kind", None) == "fire"
            or getattr(value, "acquisition_evidence", None) is not None
            or "acquisition_provenance" in raw
            or raw.get("source_product") in (*FIRMS_PRODUCTS, HMS_PRODUCT)
            or raw.get("source_name") in ("NASA FIRMS", "NOAA HMS")
            or raw.get("source_leg") in (*FIRMS_PRODUCTS, "noaa_hms")
            or metric.get("label") == "FRP"
            or (isinstance(identity, str) and re.match(r"^fire_-?[0-9]", identity) is not None))


def _same_number(actual: Any, expected: Any) -> bool:
    try:
        return type(actual) in (float, int) and math.isfinite(actual) and actual == expected
    except OverflowError:
        return False


def _bind_summary(value: Any, row: FireSourceRow) -> None:
    if getattr(value, "signal_kind", None) != "fire":
        reject("thermal packet routed as a different signal")
    if getattr(value, "event_id", None) != source_event_id(row.lat, row.lon, row.acquired_at):
        reject("thermal summary identity and source row disagree")
    if getattr(value, "when", None) != row.acquired_at:
        reject("thermal summary minute and source row disagree")
    metric = getattr(value, "headline_metric", None)
    if (type(metric) is not dict or set(metric) != {"label", "value", "unit"}
            or metric["label"] != "FRP" or metric["unit"] != "MW"
            or row.frp is None or not _same_number(metric["value"], round(row.frp, 1))):
        reject("thermal headline and source measurement disagree")


def validate_bundle(bundle: Any) -> FireSourceRow:
    raw = getattr(bundle, "raw_signal_dump", None)
    if type(raw) is not dict:
        reject("missing thermal source packet")
    row = validate_receipt(raw.get("acquisition_provenance"))
    _bind_summary(bundle, row)
    expected = dict(
        source_name=source_name(row.source_product), source_product=row.source_product,
        acquired_at=row.acquired_at, source_date=row.acquired_at[:10],
        acquisition_precision="minute", confidence_kind=row.confidence_kind,
        confidence=row.confidence_value, event_id=bundle.event_id,
    )
    for key, value in expected.items():
        if key not in raw or type(raw[key]) is not type(value) or raw[key] != value:
            reject("thermal source facts and receipt disagree")
    leg = raw.get("source_leg")
    if "source_leg" not in raw or (row.source_product == HMS_PRODUCT and leg != "noaa_hms") or (
        row.source_product != HMS_PRODUCT and leg not in (None, row.source_product)
    ):
        reject("thermal source leg and receipt disagree")
    for key, expected_number in (("lat", row.lat), ("lon", row.lon), ("frp_source", row.frp),
                                 ("frp", round(row.frp, 1) if row.frp is not None else None)):
        if not _same_number(raw.get(key), expected_number):
            reject("thermal source measurement and receipt disagree")
    facts = getattr(bundle, "current_facts", None)
    if type(facts) is not list:
        reject("missing thermal facts")
    for fact in source_facts(row):
        matches = [f for f in facts if type(f) is dict and f.get("label") == fact["label"]]
        # JSON equality alone would accept bool as a numeric measurement.
        if (len(matches) != 1 or matches[0] != fact
                or type(matches[0].get("value")) is not type(fact["value"])):
            reject("thermal current fact and receipt disagree")
    return row


def fire_bundle_failures(bundle: Any) -> list[str]:
    failures = []
    if is_thermal(bundle):
        try:
            validate_bundle(bundle)
        except (SourceFetchError, ValueError, TypeError, OverflowError):
            failures.append("primary thermal evidence lacks a consistent source minute and measurement receipt")
    related = getattr(bundle, "related_signals", None)
    if isinstance(related, list):
        for signal in related:
            if is_thermal(signal):
                try:
                    row = validate_receipt(getattr(signal, "acquisition_evidence", None))
                    _bind_summary(signal, row)
                except (SourceFetchError, ValueError, TypeError, OverflowError):
                    failures.append("related thermal evidence lacks a consistent source minute and measurement receipt")
                    break
    return failures


def temporal_claim_failures(tweet: str, bundle: Any) -> list[str]:
    if not (is_thermal(bundle) or any(is_thermal(r) for r in (getattr(bundle, "related_signals", None) or []))):
        return []
    normalized = re.sub(r"[\s\-\u2010-\u2015\u2212]+", " ", tweet.lower())
    if re.search(r"\b(?:simultaneous(?:ly)?|concurrent(?:ly)?|at the same (?:time|moment|instant)|"
                 r"same (?:satellite )?(?:overpass|scan))\b", normalized):
        return ["unwarranted_thermal_simultaneity: source minutes do not establish physical simultaneity or a shared satellite overpass"]
    return []
