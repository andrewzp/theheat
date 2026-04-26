#!/usr/bin/env python3
"""Fill missing elevation_m values in data/cities.csv.

Idempotent: skips rows that already have an elevation. Hits Open-Meteo's
elevation API one row at a time with a sleep between requests so the
rate-limited tail-batch problem (2026-04-24 session) doesn't recur.

Usage:
    python scripts/fill_missing_elevations.py
    python scripts/fill_missing_elevations.py --sleep 1.0  # tighten if safe
    python scripts/fill_missing_elevations.py --dry-run    # preview only
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import requests

CITIES_PATH = Path(__file__).parent.parent / "data" / "cities.csv"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"


def fetch_elevation(lat: float, lon: float, timeout: float = 10.0) -> int | None:
    """Return elevation in meters, rounded to int. None on any failure."""
    try:
        resp = requests.get(
            ELEVATION_URL,
            params={"latitude": lat, "longitude": lon},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        elevations = data.get("elevation", [])
        if not elevations:
            return None
        return int(round(float(elevations[0])))
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sleep", type=float, default=2.0,
        help="seconds between API requests (default 2.0)",
    )
    parser.add_argument(
        "--retries", type=int, default=2,
        help="retries per failed request (default 2)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print what would be fetched but don't make API calls or write",
    )
    args = parser.parse_args(argv)

    with open(CITIES_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if "elevation_m" not in fieldnames:
        print("ERROR: cities.csv has no elevation_m column", file=sys.stderr)
        return 2

    missing = [r for r in rows if not (r.get("elevation_m") or "").strip()]
    print(f"Total rows: {len(rows)} | Missing elevation: {len(missing)}")

    if not missing:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        for r in missing:
            print(f"  would fetch: {r['city']:<35} {r['country']:<25} ({r['lat']}, {r['lon']})")
        return 0

    filled = 0
    failed: list[dict] = []

    for i, row in enumerate(missing, 1):
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (ValueError, KeyError):
            print(f"  [{i}/{len(missing)}] {row.get('city', '?')}: bad lat/lon, skipping")
            failed.append(row)
            continue

        elevation: int | None = None
        for attempt in range(args.retries + 1):
            elevation = fetch_elevation(lat, lon)
            if elevation is not None:
                break
            if attempt < args.retries:
                # Back off a touch on retry — most failures are transient.
                time.sleep(args.sleep * 2)

        if elevation is None:
            print(f"  [{i}/{len(missing)}] {row['city']}, {row['country']}: FAILED after retries")
            failed.append(row)
        else:
            row["elevation_m"] = str(elevation)
            filled += 1
            print(f"  [{i}/{len(missing)}] {row['city']}, {row['country']}: {elevation}m")

        # Polite pacing — Open-Meteo has no published rate limit but the
        # tail-batch 429 we saw 2026-04-24 came from sustained burst.
        if i < len(missing):
            time.sleep(args.sleep)

    # Write atomically: tmp file in same dir, then rename. Avoids
    # partial-write corruption if the script is interrupted.
    tmp_path = CITIES_PATH.with_suffix(".csv.tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(CITIES_PATH)

    print(f"\nFilled {filled}/{len(missing)} rows. Failed: {len(failed)}.")
    if failed:
        print("Re-run the script — Open-Meteo flakes occasionally and "
              "another pass usually sweeps up the stragglers.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
