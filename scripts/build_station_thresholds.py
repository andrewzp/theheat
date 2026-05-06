#!/usr/bin/env python3
"""Bootstrap the GHCN-Daily threshold SQLite from the full archive.

This is a ONE-TIME local run on the developer's machine. The result
(data/station_thresholds.sqlite) is then uploaded as a GitHub Release
asset and downloaded by CI at job start.

What this does:
  1. Downloads ghcnd_all.tar.gz (~3.44 GB compressed) from NOAA NCEI.
  2. Streams through all per-station .dly files.
  3. For each station with TMAX LASTYEAR >= active_cutoff, computes
     all-time / monthly / calendar-date records and climatological means.
  4. Writes everything to station_thresholds.sqlite.

Runtime: ~30-60 minutes on M-series Mac with fast internet.
Disk: ~5 GB temporary (tarball download); SQLite file ends up ~15-30 MB.

Prerequisites:
  - Run refresh_station_inventory.py first (station rows must exist).
  - At least 6 GB free disk space for the tarball download.

Usage:
  python -m scripts.build_station_thresholds [options]

  Options:
    --db PATH       Path to SQLite file (default: data/station_thresholds.sqlite)
    --tarball PATH  Use a pre-downloaded tarball instead of re-downloading
    --no-download   Skip download (assumes tarball already exists at default path)
    --max-stations N  Stop after N stations (for testing; omit for full run)
    --dry-run       Parse but don't write to DB
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.ghcn_db import DEFAULT_DB_PATH, open_db, load_active_stations, upsert_thresholds
from src.data.ghcn_format import (
    compute_thresholds,
    stream_dly_from_tar,
    DailyObs,
)

TARBALL_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd_all.tar.gz"
DEFAULT_TARBALL_PATH = Path(__file__).parent.parent / "data" / "_ghcnd_all.tar.gz"


# ---------------------------------------------------------------------------
# Download with progress
# ---------------------------------------------------------------------------

def _download_tarball(dest: Path, chunk_size: int = 1024 * 1024) -> None:
    """Stream-download the tarball, printing progress every 100 MB."""
    print(f"Downloading {TARBALL_URL}")
    print(f"→ {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.get(TARBALL_URL, stream=True, timeout=300)
    resp.raise_for_status()

    total_bytes = 0
    t0 = time.monotonic()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            total_bytes += len(chunk)
            mb = total_bytes / (1024 ** 2)
            if int(mb) % 100 == 0 and mb > 0:
                elapsed = time.monotonic() - t0
                print(f"  {mb:.0f} MB downloaded in {elapsed:.0f}s ...", flush=True)

    elapsed = time.monotonic() - t0
    gb = total_bytes / (1024 ** 3)
    print(f"  ✓ {gb:.2f} GB downloaded in {elapsed:.0f}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap GHCN threshold SQLite from full archive.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--tarball", type=Path, default=DEFAULT_TARBALL_PATH)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--max-stations", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=== GHCN-Daily threshold bootstrap ===")
    print(f"DB:      {args.db}")
    print(f"Tarball: {args.tarball}")

    # 1. Download tarball if needed
    if args.no_download:
        if not args.tarball.exists():
            print(f"ERROR: --no-download specified but {args.tarball} not found.", file=sys.stderr)
            return 1
        print(f"Using existing tarball: {args.tarball}")
    else:
        _download_tarball(args.tarball)

    # 2. Load active station set from DB (to filter which stations to process)
    print(f"\nLoading active stations from {args.db} ...", flush=True)
    if not args.db.exists():
        print(
            f"ERROR: {args.db} not found. Run scripts/refresh_station_inventory.py first.",
            file=sys.stderr,
        )
        return 1

    with open_db(args.db) as conn:
        active_stations = load_active_stations(conn)

    active_ids = frozenset(s["station_id"] for s in active_stations)
    print(f"  {len(active_ids):,} active stations to process")

    if args.max_stations is not None:
        active_ids = frozenset(list(active_ids)[: args.max_stations])
        print(f"  [--max-stations] Capped at {len(active_ids)} stations")

    # 3. Stream through tarball
    print(f"\nStreaming {args.tarball} ...", flush=True)
    t0 = time.monotonic()

    # Accumulate obs per station
    obs_by_station: dict[str, list[DailyObs]] = collections.defaultdict(list)
    stations_seen = 0

    with open(args.tarball, "rb") as f:
        for obs in stream_dly_from_tar(f, station_ids=active_ids):
            obs_by_station[obs.station_id].append(obs)

    stations_seen = len(obs_by_station)
    total_obs = sum(len(v) for v in obs_by_station.values())
    elapsed = time.monotonic() - t0
    print(f"  {stations_seen:,} stations, {total_obs:,} observations in {elapsed:.0f}s")

    if args.dry_run:
        print("\n[dry-run] Skipping DB writes.")
        return 0

    # 4. Compute thresholds and write to DB
    print("\nComputing thresholds and writing to DB ...", flush=True)
    t0 = time.monotonic()
    written = 0
    skipped = 0

    with open_db(args.db) as conn:
        for i, (station_id, obs_list) in enumerate(obs_by_station.items(), 1):
            t = compute_thresholds(obs_list)
            if t is None:
                skipped += 1
                continue
            upsert_thresholds(conn, t)
            written += 1
            if i % 500 == 0:
                conn.commit()
                elapsed = time.monotonic() - t0
                print(f"  {i:,}/{stations_seen:,} written ({elapsed:.0f}s) ...", flush=True)
        conn.commit()

    elapsed = time.monotonic() - t0
    db_mb = args.db.stat().st_size / (1024 ** 2)
    print(f"  ✓ {written:,} stations written, {skipped} skipped in {elapsed:.0f}s")
    print(f"  DB size: {db_mb:.1f} MB")

    print("\n✓ Bootstrap complete.")
    print("Next: upload data/station_thresholds.sqlite as a GitHub Release asset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
