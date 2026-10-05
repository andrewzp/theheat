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
from contextlib import closing
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
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
from scripts.threshold_artifacts import ArtifactError, pending_diff_dates

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


def _resolve_new_watermark(
    *,
    dates_to_fetch: list[date],
    successful_dates: list[date],
    current_watermark: date | None,
) -> date | None:
    """Advance only across contiguous successful diff dates.

    If a middle date is missing but a later date succeeded, do not skip the
    gap forever by jumping the watermark over it.
    """

    if current_watermark is None or not successful_dates:
        return current_watermark
    successful = set(successful_dates)
    latest_contiguous = current_watermark
    for d in sorted(set(dates_to_fetch)):
        if d <= current_watermark:
            continue
        if d == latest_contiguous + timedelta(days=1) and d in successful:
            latest_contiguous = d
            continue
        break
    return latest_contiguous


def _read_baseline(path: Path) -> tuple[str | None, frozenset[str]]:
    """Read without the schema creation/migration side effects of open_db."""
    if not path.is_file() or path.is_symlink():
        raise ArtifactError("threshold_database_unavailable")
    for suffix in ("-wal", "-journal"):
        journal = Path(str(path) + suffix)
        if journal.exists() and journal.stat().st_size:
            raise ArtifactError("threshold_database_uncheckpointed")
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    ) as conn:
        conn.execute("PRAGMA query_only=ON")
        watermark = get_meta(conn, META_WATERMARK_KEY)
        rows = conn.execute("SELECT station_id FROM stations WHERE is_active = 1").fetchall()
    return watermark, frozenset(r[0] for r in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Incremental GHCN threshold update via superghcnd_diff."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--days", type=int, default=8, help="Number of days to look back (default: 8)"
    )
    parser.add_argument(
        "--lag-days",
        type=int,
        default=4,
        help="Leave this many recent diff snapshot days out of the cache so the bot can detect them live",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(
            f"ERROR: {args.db} not found. Run build_station_thresholds.py first.", file=sys.stderr
        )
        return 1

    print("=== GHCN-Daily incremental threshold update ===")
    print(f"DB:    {args.db}")
    print(f"Days:  last {args.days} days")
    print(f"Lag:   {args.lag_days} days (recent diffs left for hot-path detection)")

    # 1. Validate lineage before any schema or threshold writes.
    try:
        watermark_str, active_ids = _read_baseline(args.db)
        dates_to_fetch = pending_diff_dates(
            watermark_str,
            days=args.days,
            lag_days=args.lag_days,
            today=datetime.now(timezone.utc).date(),
        )
    except (ArtifactError, sqlite3.Error, OSError) as error:
        label = str(error) if isinstance(error, ArtifactError) else "threshold_database_unavailable"
        print(f"ERROR: {label}", file=sys.stderr)
        return 1
    # A successful plan requires an exact nonempty checkpoint.
    assert watermark_str is not None
    watermark = date.fromisoformat(watermark_str)
    print(f"Active stations: {len(active_ids):,}")
    print(f"Watermark:       {watermark}")
    if not dates_to_fetch:
        print("No pending diff dates; baseline is already at the lag cutoff.")
        return 0

    # 2. Fetch and parse diff files
    # Accumulate obs per station across all diff files
    new_obs_by_station: dict[str, list[DailyObs]] = {}
    recompute_station_ids: set[str] = set()
    successful_dates: list[date] = []

    for d in dates_to_fetch:
        content = _fetch_diff(d)
        if not content:
            print(
                f"ERROR: Required diff date {d} is unavailable; no update applied.", file=sys.stderr
            )
            return 1

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

    new_watermark = _resolve_new_watermark(
        dates_to_fetch=dates_to_fetch,
        successful_dates=successful_dates,
        current_watermark=watermark,
    )
    if new_watermark != dates_to_fetch[-1]:
        print("ERROR: Diff coverage is incomplete; no update applied.", file=sys.stderr)
        return 1

    if not new_obs_by_station and not recompute_station_ids:
        print("No new observations to process.")
        if not args.dry_run:
            with open_db(args.db) as conn:
                set_meta(conn, META_WATERMARK_KEY, new_watermark.isoformat())
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
            if t is None:
                print("ERROR: Station recompute returned no usable thresholds.", file=sys.stderr)
                return 1
            upsert_thresholds(conn, t)
            updated_count += 1
            if i % 50 == 0:
                conn.commit()
                print(
                    f"  {i:,}/{len(recompute_station_ids):,} full recomputes processed ...",
                    flush=True,
                )

        for i, (station_id, obs_list) in enumerate(new_obs_by_station.items(), 1):
            if station_id in recompute_station_ids:
                continue
            existing = load_thresholds(conn, station_id)
            if existing is None:
                t = _fetch_station_thresholds(station_id)
                if t is None:
                    print("ERROR: New station returned no usable thresholds.", file=sys.stderr)
                    return 1
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

        set_meta(conn, META_WATERMARK_KEY, new_watermark.isoformat())
        conn.commit()

    elapsed = time.monotonic() - t0
    print(f"\n✓ {updated_count:,} stations updated, {new_station_count} new in {elapsed:.1f}s")
    print(f"  Watermark advanced to {new_watermark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
