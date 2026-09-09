"""Pure, idempotent cache migration; no network and no publication mutation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from datetime import date, datetime
from src.data.temperature_evidence import finite

from src.data import places


def valid_cache_entry(key: str, row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    identity = row.get("identity") or {}
    if not isinstance(identity, dict):
        return False
    if not all(
        isinstance(identity.get(field), str) and identity[field].strip()
        for field in (
            "source_product",
            "place_id",
            "sampling_point_id",
            "country_code",
            "city",
            "country",
        )
    ):
        return False
    if any(isinstance(identity.get(field), bool) for field in ("lat", "lon")):
        return False
    if identity.get("source_product") != places.CACHE_PRODUCT:
        return False
    baseline = row.get("baseline")
    if (
        not isinstance(baseline, dict)
        or baseline.get("schema_version") != 2
        or baseline.get("model") != "era5"
    ):
        return False
    try:
        if baseline.get("source_product") != places.CACHE_PRODUCT:
            return False
        revision = baseline["revision_id"]
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            return False
        retrieved = datetime.fromisoformat(baseline["retrieved_at"].replace("Z", "+00:00"))
        if retrieved.tzinfo is None:
            return False
        start, end = date.fromisoformat(baseline["requested_start"]), date.fromisoformat(baseline["requested_end"])
        years = baseline["requested_years"]
        if start > end or not isinstance(years, int) or isinstance(years, bool) or years < 1:
            return False
        variables = baseline["variables"]
        for variable in ("temperature_2m_max", "temperature_2m_min", "wet_bulb_temperature_2m_max"):
            value = variables[variable]
            count, expected = value["sample_count"], value["expected_count"]
            sampled_years = value["years_with_samples"]
            if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (count, expected, sampled_years)):
                return False
            if expected != (end - start).days + 1 or count > expected or not isinstance(value["complete"], bool):
                return False
            cutoff = date.fromisoformat(value["cutoff"]) if value.get("cutoff") else None
            if (count > 0) != (cutoff is not None) or (cutoff is not None and not start <= cutoff <= end):
                return False
            if value["complete"] and (count != expected or cutoff != end):
                return False
        for field in ("all_time_max", "all_time_min", "wetbulb_max"):
            value = row.get(field)
            if value is not None and (not isinstance(value, (tuple, list)) or len(value) != 2 or not finite(value[0]) or not isinstance(value[1], int)):
                return False
        for field in ("monthly_max", "monthly_min", "calendar_max", "calendar_min", "monthly_mean"):
            values = row.get(field) or {}
            if not isinstance(values, dict):
                return False
            for value in values.values():
                length = 4 if field == "monthly_mean" else 2
                if not isinstance(value, (tuple, list)) or len(value) != length or any(v is not None and not finite(v) for v in value):
                    return False
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    try:
        resolved = places.resolve_place(
            identity["city"],
            identity["country"],
            identity["lat"],
            identity["lon"],
            place_id=identity["place_id"],
        )
        expected = places.cache_key(
            resolved["city"],
            resolved["country"],
            resolved["lat"],
            resolved["lon"],
            place_id=resolved["place_id"],
        )
        return key == expected and all(
            identity.get(k) == resolved[k]
            for k in ("place_id", "sampling_point_id", "country_code")
        )
    except (KeyError, TypeError, ValueError):
        return False


def migrate_cache(cache: dict) -> dict:
    """Quarantine every non-attributable row rather than guessing a baseline.

    Existing metadata and original rows survive. Quarantine is outside eligible
    entries, and its content-derived key prevents repeated reads adding copies.
    Legacy forecasts may already have altered extrema: migration does not certify
    those values. Fresh archive recomputation is required before comparison.
    """
    out = {}
    raw_meta = cache.get("_meta") or {}
    meta = deepcopy(raw_meta) if isinstance(raw_meta, dict) else {"legacy_meta": deepcopy(raw_meta)}
    quarantine = meta.setdefault("identity_quarantine", {})
    if not isinstance(quarantine, dict):
        meta["legacy_identity_quarantine"] = quarantine
        quarantine = meta["identity_quarantine"] = {}
    for key, value in cache.items():
        if key == "_meta":
            continue
        if valid_cache_entry(key, value):
            out[key] = deepcopy(value)
        else:
            original = {"legacy_key": key, "entry": value}
            digest = hashlib.sha256(
                json.dumps(original, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            quarantine.setdefault(
                digest,
                {**deepcopy(original), "reason": "missing_or_conflicting_sampling_provenance"},
            )
    meta["identity_version"] = 1
    meta["cached_count"] = len(out)
    meta["quarantined_count"] = len(quarantine)
    out["_meta"] = meta
    return out
