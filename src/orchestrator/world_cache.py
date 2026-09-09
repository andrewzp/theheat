from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import requests

from copy import deepcopy
from src.data.temperature_evidence import fingerprint
from src.data import places
from src.data.place_migration import migrate_cache
from src.state import GIST_ID, GITHUB_TOKEN, STATE_SIZE_WARNING_BYTES, _headers

WORLD_CACHE_FILENAME = "world_threshold_cache.json"
_META_KEY = "_meta"


def world_key(city, country, lat=None, lon=None) -> str:
    """Product-qualified sampling key; names remain display-only (P04)."""
    return places.cache_key(city, country, lat, lon)


def _as_of(e):
    return str((e or {}).get("as_of") or "")


def _normalized_time(value):
    if not value:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Archive snapshot retrieval time lacks timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _snapshot_time(entry):
    return _normalized_time((entry.get("baseline") or {}).get("retrieved_at", ""))


def _snapshot_fingerprint(entry):
    # A claimed baseline revision ID does not prove that cached comparator
    # fields match it. Include every semantic field, including derived values.
    semantic = {key: value for key, value in entry.items() if key not in ("as_of", "baseline")}
    semantic["baseline"] = {key: value for key, value in entry.get("baseline", {}).items() if key != "retrieved_at"}
    return fingerprint(semantic)


def _version_union(*maps, rows=()):
    """Re-key all variants by their payload, never a caller-supplied revision ID."""
    variants: dict[str, dict] = {}
    for row in [value for versions in maps for value in versions.values()] + list(rows):
        key = _snapshot_fingerprint(row)
        existing = variants.get(key)
        # Equivalent semantics may have a later verification time. An exact-time
        # tie still chooses deterministically between timestamp spellings.
        if existing is None or (_snapshot_time(row), fingerprint(row)) > (_snapshot_time(existing), fingerprint(existing)):
            variants[key] = deepcopy(row)
    return variants


def merge_caches(base: dict, nxt: dict) -> dict:
    """Choose complete source snapshots by retrieval version, never extreme value.

    Same-time conflicting snapshots remain quarantined until a later source read
    resolves them. A later corrected maximum can move downward without a stale
    worker reconstructing the rejected high from individual fields.
    """
    base, nxt = migrate_cache(base or {}), migrate_cache(nxt or {})
    meta = {**base.get("_meta", {}), **nxt.get("_meta", {})}
    for field in ("identity_quarantine", "baseline_conflicts", "baseline_revisions"):
        meta[field] = {
            **base.get("_meta", {}).get(field, {}),
            **nxt.get("_meta", {}).get(field, {}),
        }
    # Preserve all same-time conflict versions across concurrent quarantine merges.
    for key in set(base.get("_meta", {}).get("baseline_conflicts", {})) | set(nxt.get("_meta", {}).get("baseline_conflicts", {})):
        left = base.get("_meta", {}).get("baseline_conflicts", {}).get(key, {})
        right = nxt.get("_meta", {}).get("baseline_conflicts", {}).get(key, {})
        meta["baseline_conflicts"][key] = {
            "retrieved_at": max(_normalized_time(left.get("retrieved_at", "")), _normalized_time(right.get("retrieved_at", ""))),
            "versions": _version_union(left.get("versions", {}), right.get("versions", {})),
        }
    out = {}
    for key in sorted((set(base) | set(nxt)) - {_META_KEY}):
        rows = [row for row in (base.get(key), nxt.get(key)) if row is not None]
        rows.sort(key=lambda row: (_snapshot_time(row), fingerprint(row)))
        newest = rows[-1]
        same_time = [row for row in rows if _snapshot_time(row) == _snapshot_time(newest)]
        conflict = meta["baseline_conflicts"].get(key)
        if len({_snapshot_fingerprint(row) for row in same_time}) > 1 or (
            conflict and _snapshot_time(newest) <= conflict["retrieved_at"]
        ):
            versions = _version_union((conflict or {}).get("versions", {}), rows=same_time)
            meta["baseline_conflicts"][key] = {
                "retrieved_at": max(
                    _snapshot_time(newest), (conflict or {}).get("retrieved_at", "")
                ),
                "versions": versions,
            }
            continue
        out[key] = deepcopy(newest)
        if (
            len(rows) == 2
            and _snapshot_fingerprint(rows[0]) != _snapshot_fingerprint(newest)
        ):
            fields = ("all_time_max", "all_time_min", "monthly_max", "monthly_min", "calendar_max", "calendar_min", "monthly_mean", "wetbulb_max")
            changes = {
                field: {"previous": rows[0].get(field), "current": newest.get(field)}
                for field in fields
                if rows[0].get(field) != newest.get(field)
            }
            if changes:
                review = {
                    "sampling_key": key,
                    "previous_revision": rows[0]["baseline"]["revision_id"],
                    "current_revision": newest["baseline"]["revision_id"],
                    "previous_snapshot_sha256": _snapshot_fingerprint(rows[0]),
                    "current_snapshot_sha256": _snapshot_fingerprint(newest),
                    "retrieved_at": _snapshot_time(newest),
                    "changes": changes,
                }
                meta["baseline_revisions"][fingerprint(review)] = review
    out["_meta"] = meta
    return migrate_cache(out)


def _is_stale(entry, *, ttl_days, today):
    if not entry or not entry.get("as_of"):
        return True
    try:
        return date.fromisoformat(entry["as_of"]) < date.fromisoformat(today) - timedelta(
            days=ttl_days
        )
    except (ValueError, TypeError):
        return True


def select_stale_cities(cache, world_cities, *, ttl_days, budget, today, urgent_order):
    # Identity (cache lookup + dedup) is keyed by world_key so two genuinely-distinct
    # same-name cities are both eligible; urgent-order RANKING stays keyed on the bare
    # display city (URGENT_WORLD_HEAT_CITIES is bare names; it only orders warming).
    rank = {name: i for i, name in enumerate(urgent_order)}
    stale = [
        c
        for c in world_cities
        if _is_stale(
            cache.get(world_key(c.get("city"), c.get("country"), c.get("lat"), c.get("lon"))),
            ttl_days=ttl_days,
            today=today,
        )
    ]
    stale.sort(
        key=lambda c: (
            rank.get(c.get("city"), len(urgent_order)),
            _as_of(
                cache.get(world_key(c.get("city"), c.get("country"), c.get("lat"), c.get("lon")))
            ),
            c.get("city"),
        )
    )
    out, seen = [], set()
    for c in stale:
        key = world_key(c.get("city"), c.get("country"), c.get("lat"), c.get("lon"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= budget:
            break
    return out


def apply_provisional(cache: dict, bundle, *, today: str) -> None:
    """Compatibility no-op: a forecast cannot modify historical evidence.

    Event IDs and retained draft revisions provide suppression. Forecasts remain
    inside candidate evidence; only a new archive snapshot can replace a baseline.
    """


def apply_provisional_preserving_as_of(cache, bundle, *, today, advance_as_of, ttl_days) -> None:
    """Compatibility no-op; forecast activity is not archive freshness."""


WORLD_COVERAGE_FLOOR = 0.85
WORLD_FORECAST_FAIL_FLOOR = 0.25
WORLD_WARM_FAILURE_FLOOR = 0.5


def classify_world_status(metrics: dict, *, prev_cached_count: int) -> str:
    total = int(metrics.get("world_total", 0) or 0)
    cached = int(metrics.get("cached_count", 0) or 0)
    fa = int(metrics.get("forecast_attempted", 0) or 0)
    ff = int(metrics.get("forecast_failures", 0) or 0)
    wa = int(metrics.get("warm_attempted", 0) or 0)
    wf = int(metrics.get("warm_failures", 0) or 0)

    # Split saturation flags. Legacy single-flag callers/tests (only ``saturated``) map
    # to ``eval_sat`` so the existing "saturated -> degraded" contract is preserved.
    eval_sat = bool(metrics.get("eval_saturated", metrics.get("saturated", False)))
    warm_sat = bool(metrics.get("warm_saturated", False))

    if eval_sat:
        return "degraded"  # records could not be evaluated -> hard fail
    if wa > 0 and wf / wa > WORLD_WARM_FAILURE_FLOOR:
        return "degraded"  # archive systematically failing (unconditional)

    # Steady-state is keyed to PRE-RUN fullness, not post-run ``cached``: under eval-first
    # the cache that eval saw is the pre-warm one, so a cold 0->total first-fill (post-run
    # cached==total but coverage_ratio==0.0) is bootstrap, not a steady-state coverage miss.
    bootstrap = not (total > 0 and prev_cached_count >= total)
    growing = cached > prev_cached_count

    # Archive (warm) saturation is tolerated ONLY during healthy bootstrap growth; in
    # steady state OR a stalled bootstrap it means climatology is going stale -> degraded.
    if warm_sat and not (bootstrap and growing):
        return "degraded"

    # Forecast-failure floor is unconditional (both phases): a real non-429 forecast-payload
    # failure rate degrades even while warm is still growing the cache.
    if fa > 0 and ff / fa > WORLD_FORECAST_FAIL_FLOOR:
        return "degraded"

    if not bootstrap:  # steady state (cache full at run start)
        if float(metrics.get("coverage_ratio", 1.0)) < WORLD_COVERAGE_FLOOR:
            return "degraded"
        return "success"

    # bootstrap: degraded only if warming was attempted but the cache STALLED.
    if wa > 0 and not growing:
        return "degraded"
    return "success"


def read_cache() -> dict:
    if not GIST_ID or not GITHUB_TOKEN:
        return {}
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{GIST_ID}", headers=_headers(), timeout=15
        )
        resp.raise_for_status()
        meta = resp.json().get("files", {}).get(WORLD_CACHE_FILENAME)
        if not meta:
            return {}
        if meta.get("truncated"):
            raw = requests.get(meta["raw_url"], headers=_headers(), timeout=30)
            raw.raise_for_status()
            content = raw.text
        else:
            content = meta["content"]
        data = json.loads(content)
        if not isinstance(data, dict):
            return {}
        # Preserve original unattributed rows in idempotent quarantine; never guess geography.
        return migrate_cache(data)
    except (requests.RequestException, ValueError, KeyError):
        return {}


def write_cache(cache: dict) -> bool:
    if not GIST_ID or not GITHUB_TOKEN:
        return False
    try:
        merged = merge_caches(read_cache(), cache)
        payload = json.dumps(merged, separators=(",", ":"))
        if len(payload) > STATE_SIZE_WARNING_BYTES:
            print(f"[world_cache] WARNING size {len(payload)}B approaching gist inline cliff")
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            json={"files": {WORLD_CACHE_FILENAME: {"content": payload}}},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except (requests.RequestException, TypeError, ValueError):
        return False
