"""Pure, idempotent cache migration; no network and no publication mutation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

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
