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

  --days N   Look back N days (default: 12 — a full week, 4-day lag and buffer).
"""

from __future__ import annotations

import argparse
from contextlib import closing
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
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


def _fetch_diff(start: date, end: date, timeout: int = 120) -> bytes | None:
    """Fetch exactly the source interval requested, without alternate predecessors.

    NOAA diffs describe changes between the two snapshot dates in their names.
    An absent calendar-day endpoint may be covered by a later multi-day interval.
    Only a 404 permits that bounded search; transport errors are not missing dates.
    """
    if not 0 < (end - start).days <= 31:
        raise ArtifactError("invalid_threshold_diff_interval")
    url = f"{BASE_URL}/superghcnd_diff_{start:%Y%m%d}_to_{end:%Y%m%d}.tar.gz"
    resp = requests.get(url, timeout=timeout, allow_redirects=False)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    if resp.status_code != 200:
        raise ArtifactError("unexpected_threshold_diff_response")
    return resp.content


def _fetch_station_thresholds(station_id: str, timeout: int = 120):
    """Recompute one station from its full .dly file after update/delete diffs."""
    url = STATION_DLY_URL.format(station_id=station_id)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return compute_thresholds(parse_dly_bytes(resp.content))


def _resolve_new_watermark(
    *,
    successful_intervals: list[tuple[date, date]],
    current_watermark: date | None,
) -> date | None:
    """Advance only over an exact chain of source snapshot intervals."""
    if current_watermark is None:
        return current_watermark
    latest_contiguous = current_watermark
    for start, end in successful_intervals:
        if end <= current_watermark:
            continue
        if start == latest_contiguous and end > start:
            latest_contiguous = end
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
        "--days", type=int, default=12, help="Number of days to look back (default: 12)"
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
    successful_intervals: list[tuple[date, date]] = []
    cursor = watermark

    for d in dates_to_fetch:
        content = _fetch_diff(cursor, d)
        if content is None:
            # Probe later endpoints from the SAME predecessor, never silently
            # choose a later start that would skip unprocessed changes.
            continue
        if not content:
            print(f"ERROR: Diff interval ending {d} is empty; no update applied.", file=sys.stderr)
            return 1

        records = parse_superghcnd_diff_records_bytes(content)
        relevant_records = [r for r in records if r.station_id in active_ids]
        successful_intervals.append((cursor, d))
        cursor = d

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
        successful_intervals=successful_intervals,
        current_watermark=watermark,
    )
    if new_watermark is None or new_watermark == watermark:
        print("ERROR: No connected diff interval available; no update applied.", file=sys.stderr)
        return 1
    if new_watermark < dates_to_fetch[-1]:
        print(
            f"WARNING: Only a verified prefix through {new_watermark} is available; "
            f"coverage through {dates_to_fetch[-1]} remains incomplete.",
            file=sys.stderr,
        )

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
