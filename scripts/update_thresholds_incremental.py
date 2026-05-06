#!/usr/bin/env python3
"""Incrementally update station thresholds from superghcnd_diff.

superghcnd_diff is NOAA's daily update feed — a subset of the full
ghcnd_all.tar.gz that contains only records that changed since the
previous day. It's typically 30-100 MB/day vs 3.44 GB for the full archive.

This script:
  1. Reads the last-synced watermark from the DB (meta table).
  2. Fetches superghcnd_diff files for all dates since the watermark.
  3. Parses new TMAX/TMIN observations.
  4. For each affected active station, calls update_thresholds_with_obs()
     to patch only changed thresholds — no full recompute.
  5. Persists updated thresholds back to the DB.
  6. Updates the watermark.

This runs weekly from .github/workflows/refresh-thresholds.yml
and also from the daily bot.yml (to pull yesterday's new readings
before the per-cycle check).

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
    parse_superghcnd_diff_bytes,
    update_thresholds_with_obs,
)

BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/superghcnd"
META_WATERMARK_KEY = "last_diff_date"


def _diff_url(d: date) -> str:
    """URL for a single superghcnd_diff file (date-based naming)."""
    return f"{BASE_URL}/superghcnd_diff_{d.strftime('%Y%m%d')}.gz"


def _fetch_diff(d: date, timeout: int = 120) -> bytes | None:
    """Fetch one diff file. Returns None if not found (404)."""
    url = _diff_url(d)
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        print(f"  WARNING: Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental GHCN threshold update via superghcnd_diff.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--days", type=int, default=8,
                        help="Number of days to look back (default: 8)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: {args.db} not found. Run build_station_thresholds.py first.", file=sys.stderr)
        return 1

    print("=== GHCN-Daily incremental threshold update ===")
    print(f"DB:    {args.db}")
    print(f"Days:  last {args.days} days")

    today = date.today()
    dates_to_fetch = [today - timedelta(days=i) for i in range(args.days, 0, -1)]

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
    files_fetched = 0

    for d in dates_to_fetch:
        if watermark and d <= watermark:
            continue  # Already processed

        content = _fetch_diff(d)
        if content is None:
            print(f"  {d}: not available (NOAA may not have published yet)", flush=True)
            continue

        obs = parse_superghcnd_diff_bytes(content)
        relevant = [o for o in obs if o.station_id in active_ids]
        files_fetched += 1

        for o in relevant:
            new_obs_by_station.setdefault(o.station_id, []).append(o)

        kb = len(content) / 1024
        print(f"  {d}: {len(obs):,} obs total, {len(relevant):,} for active stations ({kb:.0f} KB)", flush=True)

    if not new_obs_by_station:
        print("No new observations to process.")
        if not args.dry_run and watermark != today - timedelta(days=1):
            with open_db(args.db) as conn:
                set_meta(conn, META_WATERMARK_KEY, (today - timedelta(days=1)).isoformat())
                conn.commit()
        return 0

    print(f"\n{len(new_obs_by_station):,} stations have new obs to integrate")

    if args.dry_run:
        print("[dry-run] Skipping DB writes.")
        return 0

    # 3. Load existing thresholds, update, write back
    t0 = time.monotonic()
    updated_count = 0
    new_station_count = 0

    with open_db(args.db) as conn:
        for i, (station_id, obs_list) in enumerate(new_obs_by_station.items(), 1):
            existing = load_thresholds(conn, station_id)
            if existing is None:
                # Station has no thresholds yet (shouldn't happen after bootstrap,
                # but handle gracefully by building from scratch)
                from src.data.ghcn_format import compute_thresholds
                t = compute_thresholds(obs_list)
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

        # Update watermark to yesterday (NOAA typically 24h lag)
        new_watermark = today - timedelta(days=1)
        set_meta(conn, META_WATERMARK_KEY, new_watermark.isoformat())
        conn.commit()

    elapsed = time.monotonic() - t0
    print(f"\n✓ {updated_count:,} stations updated, {new_station_count} new in {elapsed:.1f}s")
    print(f"  Watermark advanced to {new_watermark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
