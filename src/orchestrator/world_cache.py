from __future__ import annotations

import json
from datetime import date, timedelta

import requests

from src.data.world_thresholds import CityThresholds
from src.state import GIST_ID, GITHUB_TOKEN, STATE_SIZE_WARNING_BYTES, _headers

WORLD_CACHE_FILENAME = "world_threshold_cache.json"
_META_KEY = "_meta"


def world_key(city, country) -> str:
    """Stable per-city identity for the world cache: ``"<city>|<country>"``.

    ``(city, country)`` is unique across the curated city list, so this disambiguates
    genuinely-distinct cities that share a name across countries (e.g. Barcelona
    Spain vs Barcelona Venezuela). The bare ``city`` remains the DISPLAY name; this
    composite is the cache/forecast/dedup IDENTITY. The ``"|"`` separator is also the
    migration marker read_cache uses to drop legacy bare-city keys.
    """
    return f"{city}|{country}"


def _as_of(e):
    return str((e or {}).get("as_of") or "")


def _pick_pair(a, b, *, more_extreme_is_max):
    if a is None:
        return b
    if b is None:
        return a
    return (a if a[0] >= b[0] else b) if more_extreme_is_max else (a if a[0] <= b[0] else b)


def _merge_entry_fields(a: dict, b: dict) -> dict:
    """Equal-as_of field-wise merge: more-extreme per field; richer mean wins."""
    out = dict(a)
    out["all_time_max"] = _pick_pair(a.get("all_time_max"), b.get("all_time_max"), more_extreme_is_max=True)
    out["all_time_min"] = _pick_pair(a.get("all_time_min"), b.get("all_time_min"), more_extreme_is_max=False)
    out["wetbulb_max"] = _pick_pair(a.get("wetbulb_max"), b.get("wetbulb_max"), more_extreme_is_max=True)
    for key, is_max in (("monthly_max", True), ("monthly_min", False)):
        merged = dict(a.get(key) or {})
        for mm, v in (b.get(key) or {}).items():
            merged[mm] = _pick_pair(merged.get(mm), v, more_extreme_is_max=is_max)
        out[key] = merged
    mm_mean = dict(a.get("monthly_mean") or {})
    for mm, v in (b.get("monthly_mean") or {}).items():
        cur = mm_mean.get(mm)
        if cur is None or (v[2] > cur[2]):   # higher sample_count wins
            mm_mean[mm] = v
    out["monthly_mean"] = mm_mean
    return out


def merge_caches(base: dict, nxt: dict) -> dict:
    base = base or {}
    nxt = nxt or {}
    out: dict = {}
    for city in sorted((set(base) | set(nxt)) - {_META_KEY}):
        b = base.get(city)
        n = nxt.get(city)
        if b is None:
            out[city] = n
        elif n is None:
            out[city] = b
        elif _as_of(n) > _as_of(b):
            out[city] = n
        elif _as_of(b) > _as_of(n):
            out[city] = b
        else:
            out[city] = _merge_entry_fields(b, n)
    return out


def _is_stale(entry, *, ttl_days, today):
    if not entry or not entry.get("as_of"):
        return True
    try:
        return date.fromisoformat(entry["as_of"]) < date.fromisoformat(today) - timedelta(days=ttl_days)
    except (ValueError, TypeError):
        return True


def select_stale_cities(cache, world_cities, *, ttl_days, budget, today, urgent_order):
    # Identity (cache lookup + dedup) is keyed by world_key so two genuinely-distinct
    # same-name cities are both eligible; urgent-order RANKING stays keyed on the bare
    # display city (URGENT_WORLD_HEAT_CITIES is bare names; it only orders warming).
    rank = {name: i for i, name in enumerate(urgent_order)}
    stale = [
        c for c in world_cities
        if _is_stale(cache.get(world_key(c.get("city"), c.get("country"))), ttl_days=ttl_days, today=today)
    ]
    stale.sort(key=lambda c: (
        rank.get(c.get("city"), len(urgent_order)),
        _as_of(cache.get(world_key(c.get("city"), c.get("country")))),
        c.get("city"),
    ))
    out, seen = [], set()
    for c in stale:
        key = world_key(c.get("city"), c.get("country"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= budget:
            break
    return out


def _year(today: str) -> int:
    return date.fromisoformat(today).year


def apply_provisional(cache: dict, bundle, *, today: str) -> None:
    key = world_key(bundle.city, bundle.country)   # composite identity; bundle.city stays display
    entry = cache.get(key)
    t = CityThresholds.from_dict(entry) if entry else CityThresholds(city=bundle.city, as_of=today, years_of_data=0)
    if bundle.all_time_high is not None:
        t.all_time_max = (bundle.all_time_high.new_temp_c, _year(today))
    if bundle.all_time_low is not None:
        t.all_time_min = (bundle.all_time_low.new_temp_c, _year(today))
    if bundle.monthly_high is not None:
        t.monthly_max[f"{bundle.monthly_high.month:02d}"] = (bundle.monthly_high.new_temp_c, _year(today))
    if bundle.monthly_low is not None:
        t.monthly_min[f"{bundle.monthly_low.month:02d}"] = (bundle.monthly_low.new_temp_c, _year(today))
    t.as_of = today
    cache[key] = t.to_dict()


def apply_provisional_preserving_as_of(cache, bundle, *, today, advance_as_of, ttl_days) -> None:
    """Stamp today's provisional record fields, with freshness honesty on ``as_of``.

    Advance ``as_of`` to today when the city was warmed this run (``advance_as_of``) OR
    its prior entry is non-stale; otherwise (stale AND not warmed) keep the prior
    ``as_of`` so a record fired against still-stale climatology stays eligible for
    re-warming next run. ``advance_as_of`` is the caller's "warmed this run" signal;
    staleness is recomputed here so a fresh-cached, non-warmed record keeps
    ``as_of=today`` (the dominant production path). A stale, not-warmed entry whose
    prior ``as_of`` is falsy (missing/empty) is kept stale (``as_of=""``), NOT advanced
    to today — advancing would mark unconfirmed climatology fresh (false freshness).
    """
    key = world_key(bundle.city, bundle.country)
    prior = cache.get(key)
    prior_as_of = (prior or {}).get("as_of")
    prior_stale = _is_stale(prior, ttl_days=ttl_days, today=today)
    apply_provisional(cache, bundle, today=today)        # writes record fields + as_of=today
    if not advance_as_of and prior_stale:
        cache[key]["as_of"] = prior_as_of or ""          # keep stale + not-warmed warm-eligible


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
        return "degraded"                          # records could not be evaluated -> hard fail
    if wa > 0 and wf / wa > WORLD_WARM_FAILURE_FLOOR:
        return "degraded"                          # archive systematically failing (unconditional)

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

    if not bootstrap:                              # steady state (cache full at run start)
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
        resp = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=_headers(), timeout=15)
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
        # One-time migration: drop legacy bare-city keys (pre city|country re-key). They
        # are unreachable under composite keys and, left in place, would be merged back by
        # write_cache and inflate cached_count (breaking steady-state detection). Keeping
        # only composite ("|") keys + _meta means the next write rewrites the gist
        # composite-only; the few legacy entries simply re-warm.
        return {k: v for k, v in data.items() if k == _META_KEY or "|" in str(k)}
    except (requests.RequestException, ValueError, KeyError):
        return {}


def write_cache(cache: dict) -> bool:
    if not GIST_ID or not GITHUB_TOKEN:
        return False
    try:
        merged = merge_caches(read_cache(), cache)
        if _META_KEY in cache:
            merged[_META_KEY] = cache[_META_KEY]
        payload = json.dumps(merged, separators=(",", ":"))
        if len(payload) > STATE_SIZE_WARNING_BYTES:
            print(f"[world_cache] WARNING size {len(payload)}B approaching gist inline cliff")
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}", headers=_headers(),
            json={"files": {WORLD_CACHE_FILENAME: {"content": payload}}}, timeout=15,
        )
        resp.raise_for_status()
        return True
    except (requests.RequestException, TypeError, ValueError):
        return False
