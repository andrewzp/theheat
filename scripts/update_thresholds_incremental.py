#!/usr/bin/env python3
"""Incrementally update station thresholds from superghcnd_diff.

superghcnd_diff is NOAA's daily update feed: tar.gz snapshots containing
insert/update/delete CSV members for records that changed between two dates.
It is typically much smaller than the 3.44 GB full archive.

This script:
  1. Reads the last-synced watermark from the DB (meta table).
  2. Fetches superghcnd_diff files for all dates since the watermark.
  3. Parses TMAX/TMIN insert/update/delete records.
  4. Recomputes stations touched by update/delete rows and incrementally patches
     insert-only stations.
  5. Persists updated thresholds back to the DB.
  6. Updates the watermark.

This runs weekly from .github/workflows/refresh-thresholds.yml. The bot itself
uses the recent diff window directly so it can detect records before the weekly
cache refresh folds them into the threshold DB.

Usage:
  python -m scripts.update_thresholds_incremental [--db PATH] [--days N] [--dry-run]

  --days N   Look back N days (default: 8 — covers a full week + 1 buffer day).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.ghcn_db import (
    DEFAULT_DB_PATH,
    get_meta,
    load_thresholds,
    open_db,
    set_meta,
    upsert_thresholds,
)
from src.data.ghcn_format import (
    DailyObs,
    compute_thresholds,
    parse_dly_bytes,
    parse_superghcnd_diff_records_bytes,
    update_thresholds_with_obs,
)

BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/superghcnd"
STATION_DLY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{station_id}.dly"
META_WATERMARK_KEY = "last_diff_date"


def _diff_urls_for_end_date(d: date, max_start_lag_days: int = 10) -> list[str]:
    """Candidate URLs for superghcnd_diff tarballs ending on ``d``."""
    end = d.strftime("%Y%m%d")
    return [
        f"{BASE_URL}/superghcnd_diff_{(d - timedelta(days=lag)).strftime('%Y%m%d')}_to_{end}.tar.gz"
        for lag in range(1, max_start_lag_days + 1)
    ]


def _fetch_diff(d: date, timeout: int = 120) -> bytes | None:
    """Fetch one diff tarball ending on ``d``. Returns None if not found."""
    for url in _diff_urls_for_end_date(d):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            print(f"  WARNING: Failed to fetch {url}: {e}", file=sys.stderr)
    return None


def _fetch_station_thresholds(station_id: str, timeout: int = 120):
    """Recompute one station from its full .dly file after update/delete diffs."""
    url = STATION_DLY_URL.format(station_id=station_id)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return compute_thresholds(parse_dly_bytes(resp.content))


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental GHCN threshold update via superghcnd_diff.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--days", type=int, default=8,
                        help="Number of days to look back (default: 8)")
    parser.add_argument("--lag-days", type=int, default=4,
                        help="Leave this many recent diff snapshot days out of the cache so the bot can detect them live")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: {args.db} not found. Run build_station_thresholds.py first.", file=sys.stderr)
        return 1

    print("=== GHCN-Daily incremental threshold update ===")
    print(f"DB:    {args.db}")
    print(f"Days:  last {args.days} days")
    print(f"Lag:   {args.lag_days} days (recent diffs left for hot-path detection)")

    today = date.today()
    cutoff = today - timedelta(days=args.lag_days)
    dates_to_fetch = [
        today - timedelta(days=i)
        for i in range(args.days, 0, -1)
        if today - timedelta(days=i) <= cutoff
    ]

    # 1. Load active station IDs for filtering
    with open_db(args.db) as conn:
        watermark_str = get_meta(conn, META_WATERMARK_KEY)
        rows = conn.execute(
            "SELECT station_id FROM stations WHERE is_active = 1"
        ).fetchall()
    active_ids = frozenset(r[0] for r in rows)

    watermark = date.fromisoformat(watermark_str) if watermark_str else None
    print(f"Active stations: {len(active_ids):,}")
    print(f"Watermark:       {watermark or 'none (first run)'}")

    # 2. Fetch and parse diff files
    # Accumulate obs per station across all diff files
    new_obs_by_station: dict[str, list[DailyObs]] = {}
    recompute_station_ids: set[str] = set()
    successful_dates: list[date] = []

    for d in dates_to_fetch:
        if watermark and d <= watermark:
            continue  # Already processed

        content = _fetch_diff(d)
        if content is None:
            print(f"  {d}: not available (NOAA may not have published yet)", flush=True)
            continue

        records = parse_superghcnd_diff_records_bytes(content)
        relevant_records = [r for r in records if r.station_id in active_ids]
        successful_dates.append(d)

        for r in relevant_records:
            if r.action in {"update", "delete"}:
                recompute_station_ids.add(r.station_id)
                continue
            obs = r.to_daily_obs()
            if obs is not None:
                new_obs_by_station.setdefault(obs.station_id, []).append(obs)

        kb = len(content) / 1024
        print(
            f"  {d}: {len(records):,} diff rows total, "
            f"{len(relevant_records):,} for active stations ({kb:.0f} KB)",
            flush=True,
        )

    if dates_to_fetch and not successful_dates:
        print("ERROR: No diff files were fetched; refusing to advance watermark.", file=sys.stderr)
        return 1

    if not new_obs_by_station and not recompute_station_ids:
        print("No new observations to process.")
        if not args.dry_run and successful_dates:
            with open_db(args.db) as conn:
                set_meta(conn, META_WATERMARK_KEY, max(successful_dates).isoformat())
                conn.commit()
        return 0

    print(f"\n{len(new_obs_by_station):,} stations have insert-only obs to integrate")
    print(f"{len(recompute_station_ids):,} stations need full recompute after update/delete diffs")

    if args.dry_run:
        print("[dry-run] Skipping DB writes.")
        return 0

    # 3. Load existing thresholds, update, write back
    t0 = time.monotonic()
    updated_count = 0
    new_station_count = 0

    with open_db(args.db) as conn:
        for i, station_id in enumerate(sorted(recompute_station_ids), 1):
            try:
                t = _fetch_station_thresholds(station_id)
            except requests.RequestException as e:
                print(f"ERROR: Failed to fetch full .dly for {station_id}: {e}", file=sys.stderr)
                return 1
            if t:
                upsert_thresholds(conn, t)
                updated_count += 1
            if i % 50 == 0:
                conn.commit()
                print(f"  {i:,}/{len(recompute_station_ids):,} full recomputes processed ...", flush=True)

        for i, (station_id, obs_list) in enumerate(new_obs_by_station.items(), 1):
            if station_id in recompute_station_ids:
                continue
            existing = load_thresholds(conn, station_id)
            if existing is None:
                t = _fetch_station_thresholds(station_id)
                if t:
                    upsert_thresholds(conn, t)
                    new_station_count += 1
            else:
                changed = update_thresholds_with_obs(existing, obs_list)
                if changed:
                    upsert_thresholds(conn, existing)
                    updated_count += 1

            if i % 200 == 0:
                conn.commit()
                print(f"  {i:,}/{len(new_obs_by_station):,} processed ...", flush=True)

        new_watermark = max(successful_dates) if successful_dates else watermark
        if new_watermark is None:
            print("ERROR: No successful diff date available for watermark.", file=sys.stderr)
            return 1
        set_meta(conn, META_WATERMARK_KEY, new_watermark.isoformat())
        conn.commit()

    elapsed = time.monotonic() - t0
    print(f"\n✓ {updated_count:,} stations updated, {new_station_count} new in {elapsed:.1f}s")
    print(f"  Watermark advanced to {new_watermark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
