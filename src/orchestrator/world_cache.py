from __future__ import annotations

from datetime import date, timedelta

from src.data.world_thresholds import CityThresholds

WORLD_CACHE_FILENAME = "world_threshold_cache.json"
_META_KEY = "_meta"


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
    rank = {name: i for i, name in enumerate(urgent_order)}
    stale = [c for c in world_cities if _is_stale(cache.get(c.get("city")), ttl_days=ttl_days, today=today)]
    stale.sort(key=lambda c: (rank.get(c.get("city"), len(urgent_order)), _as_of(cache.get(c.get("city"))), c.get("city")))
    out, seen = [], set()
    for c in stale:
        name = c.get("city")
        if name in seen:
            continue
        seen.add(name)
        out.append(c)
        if len(out) >= budget:
            break
    return out


def _year(today: str) -> int:
    return date.fromisoformat(today).year


def apply_provisional(cache: dict, bundle, *, today: str) -> None:
    city = bundle.city
    entry = cache.get(city)
    t = CityThresholds.from_dict(entry) if entry else CityThresholds(city=city, as_of=today, years_of_data=0)
    if bundle.all_time_high is not None:
        t.all_time_max = (bundle.all_time_high.new_temp_c, _year(today))
    if bundle.all_time_low is not None:
        t.all_time_min = (bundle.all_time_low.new_temp_c, _year(today))
    if bundle.monthly_high is not None:
        t.monthly_max[f"{bundle.monthly_high.month:02d}"] = (bundle.monthly_high.new_temp_c, _year(today))
    if bundle.monthly_low is not None:
        t.monthly_min[f"{bundle.monthly_low.month:02d}"] = (bundle.monthly_low.new_temp_c, _year(today))
    t.as_of = today
    cache[city] = t.to_dict()
