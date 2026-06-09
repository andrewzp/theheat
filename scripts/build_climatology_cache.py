#!/usr/bin/env python3
"""One-time ERA5 daily-climatology backfill for the reanalysis-anomaly signal.

Step 0 GATE: build data/climatology_daily_cache.json BEFORE the detection logic
runs in production. One Open-Meteo ARCHIVE request per watchlist point spans
1991-01-01..2020-12-31 (10,958 daily rows), grouped by calendar day (MM-DD) into
a mean + population-std of daily max (plus mean of daily min, for future
cold-anomaly use). ~100 points -> ~100 requests, ~2-3 min total.

Resilience: a 429-aware backoff wrapper (fetch_with_retry does NOT retry 429),
an atomic per-point checkpoint (tmp-write -> os.replace) for crash-safe resume,
and skip-detection so re-runs only fetch missing points.

Usage:
  python -m scripts.build_climatology_cache --all
  python -m scripts.build_climatology_cache --regions Sahel "Indo-Gangetic Plain"
  python -m scripts.build_climatology_cache --all --dry-run        # list, no fetch
  python -m scripts.build_climatology_cache --all --delay-ms 250 --cache-path data/climatology_daily_cache.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path
from statistics import mean, pstdev
from typing import Callable

import requests

from src.data.reanalysis_anomaly import ARCHIVE_URL, REGION_WATCHLIST, RegionDef

CACHE_PATH = "data/climatology_daily_cache.json"
CLIM_START = "1991-01-01"
CLIM_END = "2020-12-31"
_USER_AGENT = "(theheat-bot, contact@theheat.app)"
# A complete 1991-2020 point has 366 MM-DD buckets (365 + the leap-day 02-29).
# A point with fewer is incomplete: Open-Meteo sometimes answers 200 with an
# empty/short `daily` block under load (a soft rate-limit), and writing that to
# the cache would poison the resume guard (the empty point reads as "done").
_MIN_DAY_KEYS = 365
# 30-year x 2-variable archive requests are weighted heavily, so a short burst
# trips Open-Meteo's short-window rate limit (it recovers in ~60s). A rate-limit
# 429 must therefore wait out roughly a full window in ONE go — small exponential
# waits just re-hit the saturated window and burn attempts. The cache checkpoints
# atomically, so even an exhausted run resumes cleanly on re-run.
_MAX_BACKOFF_SECONDS = 90.0
_RATE_LIMIT_WAIT = 60.0


def _wait_seconds(resp: requests.Response | None, attempt: int, backoff_base: float) -> float:
    """How long to sleep before the next attempt.

    A server response (429/5xx) means a rate/availability limit: honor Retry-After
    if present, else wait ~a full rate window (the limit recovers in ~60s). A bare
    transport error (resp is None) uses exponential backoff with a floor.
    """
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        return min(_RATE_LIMIT_WAIT * random.uniform(0.9, 1.1), _MAX_BACKOFF_SECONDS)
    base = min(backoff_base * (2 ** attempt), _MAX_BACKOFF_SECONDS)
    return min(base * random.uniform(0.6, 1.0), _MAX_BACKOFF_SECONDS)


def _fetch_archive_with_backoff(
    url: str,
    params: dict,
    *,
    max_attempts: int = 8,
    backoff_base: float = 2.0,
) -> requests.Response:
    """GET with patient, Retry-After-aware backoff that retries 429 AND 5xx.

    fetch_with_retry (the shared helper) deliberately does NOT retry 429, so the
    backfill needs its own wrapper for the archive endpoint's burst limiting.
    """
    for attempt in range(max_attempts):
        try:
            resp = requests.get(
                url, params=params, timeout=60, headers={"User-Agent": _USER_AGENT}
            )
            if resp.status_code == 429 or (500 <= resp.status_code < 600):
                if attempt < max_attempts - 1:
                    time.sleep(_wait_seconds(resp, attempt, backoff_base))
                    continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout):
            if attempt >= max_attempts - 1:
                raise
            time.sleep(_wait_seconds(None, attempt, backoff_base))
    raise RuntimeError("backoff exhausted")


def _compute_point_climatology(
    dates: list[str],
    tmax: list[float | None],
    tmin: list[float | None],
) -> dict[str, dict]:
    """Group daily rows by MM-DD into {mean_c, std_c, mean_min_c}.

    Highs and lows are grouped in SEPARATE passes: ``tmin`` may be empty (the v1
    backfill requests temperature_2m_max only). A single ``zip(dates, tmax, tmin)``
    would truncate to the shortest list, silently yielding ZERO rows whenever
    tmin is absent — which is exactly how empty day-maps got written.
    """
    highs_by_mmdd: dict[str, list[float]] = {}
    lows_by_mmdd: dict[str, list[float]] = {}
    for d, hi in zip(dates, tmax):
        if hi is not None:
            highs_by_mmdd.setdefault(d[5:], []).append(hi)
    for d, lo in zip(dates, tmin):
        if lo is not None:
            lows_by_mmdd.setdefault(d[5:], []).append(lo)

    days: dict[str, dict] = {}
    for mmdd, highs in highs_by_mmdd.items():
        lows = lows_by_mmdd.get(mmdd, [])
        days[mmdd] = {
            "mean_c": round(mean(highs), 2),
            "std_c": round(pstdev(highs), 2) if len(highs) > 1 else 0.0,
            "mean_min_c": round(mean(lows), 2) if lows else None,
        }
    return days


def _fetch_one_point(lat: float, lon: float, *, max_attempts: int = 4) -> dict:
    """One 1991-2020 archive request for a single point -> its daily climatology.

    Requests only temperature_2m_max: that HALVES Open-Meteo's per-request weight
    versus also pulling _min, and the free archive's weighted rate limit is the
    binding constraint on a 100-point backfill. mean_min_c (reserved for the
    deferred cold-anomaly feature, NOT used in v1) is therefore null for points
    fetched this way; re-backfill with _min if/when cold-anomaly detection lands.

    Retries a soft rate-limit (HTTP 200 with an empty/short `daily` block) by
    waiting out a window, and RAISES if the point is still incomplete — the
    caller must never checkpoint a short point.
    """
    last_n = 0
    for attempt in range(max_attempts):
        resp = _fetch_archive_with_backoff(
            f"{ARCHIVE_URL}/archive",
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": CLIM_START,
                "end_date": CLIM_END,
                "daily": "temperature_2m_max",
                "timezone": "UTC",
            },
        )
        daily = resp.json().get("daily", {})
        days = _compute_point_climatology(
            daily.get("time", []),
            daily.get("temperature_2m_max", []),
            daily.get("temperature_2m_min", []),
        )
        if len(days) >= _MIN_DAY_KEYS:
            return {"lat": lat, "lon": lon, "days": days}
        last_n = len(days)
        if attempt < max_attempts - 1:
            time.sleep(_RATE_LIMIT_WAIT * random.uniform(0.9, 1.1))
    raise RuntimeError(
        f"archive returned only {last_n} day-keys for ({lat},{lon}) after {max_attempts} attempts"
    )


def _load_cache(cache_path: str) -> dict:
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache_atomic(cache: dict, cache_path: str) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    tmp.replace(path)


def _point_is_complete(cache: dict, slug: str, key: str) -> bool:
    return len(cache.get(slug, {}).get(key, {}).get("days", {})) >= _MIN_DAY_KEYS


def incomplete_points(cache: dict, regions: list[RegionDef]) -> list[str]:
    """Every requested point that lacks a full (>= _MIN_DAY_KEYS) climatology."""
    return [
        f"{region.slug}/{lat},{lon}"
        for region in regions
        for (lat, lon) in region.points
        if not _point_is_complete(cache, region.slug, f"{lat},{lon}")
    ]


def build_cache(
    regions: list[RegionDef],
    cache_path: str = CACHE_PATH,
    *,
    delay_ms: int = 250,
    dry_run: bool = False,
    fetch: Callable[[float, float], dict] = _fetch_one_point,
) -> dict:
    """Backfill (or resume) the climatology cache for the given regions.

    Idempotent + self-repairing: a point is skipped ONLY if it is already complete
    (>= _MIN_DAY_KEYS day-keys); a previously-poisoned empty/short point is
    re-fetched. A short or failed fetch is never checkpointed (so it can't poison
    the resume guard) and is reported as incomplete. Writes the cache atomically
    after each completed point, so an interrupted run resumes cleanly.
    """
    cache = _load_cache(cache_path)
    points = [(region, lat, lon) for region in regions for (lat, lon) in region.points]
    total = len(points)
    fetched = 0

    for i, (region, lat, lon) in enumerate(points):
        slug = region.slug
        key = f"{lat},{lon}"
        if _point_is_complete(cache, slug, key):
            continue
        if dry_run:
            print(f"  [{i + 1}/{total}] would fetch {region.name} {key}")
            continue
        try:
            point = fetch(lat, lon)
        except Exception as exc:  # noqa: BLE001 - leave the point unwritten for the next run
            print(f"  [{i + 1}/{total}] {region.name} {key}: FETCH FAILED ({exc}) — left for re-run")
        else:
            if len(point.get("days", {})) >= _MIN_DAY_KEYS:
                cache.setdefault(slug, {})[key] = point
                fetched += 1
                _save_cache_atomic(cache, cache_path)
                print(f"  [{i + 1}/{total}] {region.name} {key}: {len(point['days'])} day-keys")
            else:
                # Never checkpoint a short point — it would read as "done" forever.
                print(f"  [{i + 1}/{total}] {region.name} {key}: INCOMPLETE "
                      f"({len(point.get('days', {}))} day-keys) — not written")
        if i < total - 1:
            time.sleep(delay_ms / 1000)

    if not dry_run:
        missing = incomplete_points(cache, regions)
        print(f"\nBackfill: {fetched} new point(s) written.")
        if missing:
            print(f"INCOMPLETE: {len(missing)} point(s) still short — re-run to repair. "
                  f"e.g. {missing[:5]}")
        else:
            print(f"COMPLETE: every requested point has >= {_MIN_DAY_KEYS} day-keys. "
                  f"Cache at {cache_path}")
    return cache


def _select_regions(names: list[str] | None) -> list[RegionDef]:
    if not names:
        return list(REGION_WATCHLIST)
    by_name = {r.name: r for r in REGION_WATCHLIST}
    selected = []
    for name in names:
        if name not in by_name:
            raise SystemExit(f"unknown region: {name!r} (known: {sorted(by_name)})")
        selected.append(by_name[name])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the ERA5 daily climatology cache.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="backfill every watchlist region")
    group.add_argument("--regions", nargs="+", metavar="NAME", help="specific region display names")
    parser.add_argument("--delay-ms", type=int, default=250, help="polite pacing between points")
    parser.add_argument("--dry-run", action="store_true", help="list points, fetch nothing")
    parser.add_argument("--cache-path", default=CACHE_PATH)
    args = parser.parse_args()

    regions = _select_regions(None if args.all else args.regions)
    cache = build_cache(
        regions,
        args.cache_path,
        delay_ms=args.delay_ms,
        dry_run=args.dry_run,
    )
    # Non-zero exit when any requested point is still incomplete, so a wrapping
    # loop / CI knows to re-run (the Step-0 completeness gate).
    if not args.dry_run and incomplete_points(cache, regions):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
