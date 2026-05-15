#!/usr/bin/env python3
"""Refresh the GHCN-Daily station inventory.

Downloads ghcnd-stations.txt and ghcnd-inventory.txt from NOAA NCEI,
builds/updates the SQLite station table, and writes data/stations.csv.

Run this:
  - Once during initial bootstrap (before build_station_thresholds.py).
  - Weekly from the CI refresh-thresholds workflow to pick up new stations.

Usage:
  python -m scripts.refresh_station_inventory [--db /path/to/db] [--dry-run]

Outputs:
  data/station_thresholds.sqlite  — stations table updated
  data/stations.csv               — human-readable station list for review

No auth, no rate limits. NOAA hosts these as free public files.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import requests

# Add repo root to path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.ghcn_db import DEFAULT_DB_PATH, open_db, upsert_station
from src.data.ghcn_format import (
    ElementInventory,
    parse_countries_file,
    parse_inventory_file,
    parse_stations_file,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATIONS_URL  = f"{BASE_URL}/ghcnd-stations.txt"
INVENTORY_URL = f"{BASE_URL}/ghcnd-inventory.txt"
COUNTRIES_URL = f"{BASE_URL}/ghcnd-countries.txt"

# A station whose TMAX LASTYEAR is within this many years of today is
# considered "active" for our purposes.
ACTIVE_YEAR_LAG = 1  # LASTYEAR >= current_year - ACTIVE_YEAR_LAG

STATIONS_CSV_PATH = Path(__file__).parent.parent / "data" / "stations.csv"


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch_text(url: str, timeout: int = 120) -> str:
    print(f"  Fetching {url} ...", flush=True)
    t0 = time.monotonic()
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    elapsed = time.monotonic() - t0
    kb = len(resp.content) / 1024
    print(f"    → {len(resp.text.splitlines()):,} lines, {kb:.0f} KB in {elapsed:.1f}s", flush=True)
    return resp.text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh GHCN-Daily station inventory.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help="Path to station_thresholds.sqlite")
    parser.add_argument("--dry-run", action="store_true",
                        help="Download and parse but don't write to DB or CSV")
    args = parser.parse_args()

    import datetime
    active_cutoff = datetime.date.today().year - ACTIVE_YEAR_LAG

    print("=== GHCN-Daily station inventory refresh ===")
    print(f"DB:     {args.db}")
    print(f"Active cutoff: TMAX/TMIN LASTYEAR >= {active_cutoff}")

    # 1. Fetch data
    stations_text  = _fetch_text(STATIONS_URL)
    inventory_text = _fetch_text(INVENTORY_URL)
    countries_text = _fetch_text(COUNTRIES_URL)

    # 2. Parse
    print("\nParsing stations ...", flush=True)
    stations = parse_stations_file(stations_text)
    print(f"  {len(stations):,} stations parsed")

    print("Parsing inventory ...", flush=True)
    inv_rows = parse_inventory_file(inventory_text)
    print(f"  {len(inv_rows):,} inventory rows parsed")

    print("Parsing countries ...", flush=True)
    countries = parse_countries_file(countries_text)
    print(f"  {len(countries)} countries parsed")

    # 3. Build per-station inventory index
    print("Building inventory index ...", flush=True)
    inv_by_station: dict[str, list[ElementInventory]] = {}
    for row in inv_rows:
        inv_by_station.setdefault(row.station_id, []).append(row)

    # 4. Count active stations
    active_count = sum(
        1
        for sid, rows in inv_by_station.items()
        if any(r.element in {"TMAX", "TMIN"} and r.last_year >= active_cutoff for r in rows)
    )
    print(f"  {active_count:,} stations have TMAX/TMIN LASTYEAR >= {active_cutoff}")

    if args.dry_run:
        print("\n[dry-run] Skipping DB and CSV writes.")
        return 0

    # 5. Write to SQLite
    args.db.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting to {args.db} ...", flush=True)
    t0 = time.monotonic()
    with open_db(args.db) as conn:
        for i, meta in enumerate(stations, 1):
            inv = inv_by_station.get(meta.station_id, [])
            country_name = countries.get(meta.country_code_inferred(), "")
            upsert_station(conn, meta, country_name, inv, active_cutoff)
            if i % 5000 == 0:
                conn.commit()
                print(f"  {i:,}/{len(stations):,} upserted ...", flush=True)
        conn.commit()
    elapsed = time.monotonic() - t0
    print(f"  Done in {elapsed:.1f}s")

    # 6. Write stations.csv for review
    print(f"\nWriting {STATIONS_CSV_PATH} ...", flush=True)
    # Re-read active stations from DB for the CSV
    with open_db(args.db) as conn:
        rows = conn.execute(
            """
            SELECT station_id, name, country_code, country_name, state,
                   lat, lon, elevation_m, tmax_first_year, tmax_last_year,
                   tmin_first_year, tmin_last_year,
                   tmax_archive_years, tmin_archive_years,
                   archive_years, is_active
            FROM stations
            ORDER BY country_code, station_id
            """
        ).fetchall()

    STATIONS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATIONS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "station_id", "name", "country_code", "country_name", "state",
            "lat", "lon", "elevation_m", "tmax_first_year", "tmax_last_year",
            "tmin_first_year", "tmin_last_year", "tmax_archive_years", "tmin_archive_years",
            "archive_years", "is_active",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(writer.fieldnames, row)))

    total = len(rows)
    active = sum(1 for r in rows if r[-1])
    print(f"  Wrote {total:,} stations ({active:,} active) to {STATIONS_CSV_PATH}")

    print("\n✓ Inventory refresh complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
