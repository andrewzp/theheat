#!/usr/bin/env python3
"""Build normals.csv from Meteostat 1991-2020 climate normals.

Reads cities.csv, fetches 30-year monthly avg high temps via Meteostat,
writes normals.csv. Takes ~1 minute for 257 cities.
"""

import csv
import sys
from pathlib import Path

from meteostat import Normals, Point

CITIES_PATH = Path(__file__).parent.parent / "data" / "cities.csv"
NORMALS_PATH = Path(__file__).parent.parent / "data" / "normals.csv"


def main():
    # Load cities
    with open(CITIES_PATH, newline="", encoding="utf-8") as f:
        cities = list(csv.DictReader(f))

    print(f"Fetching normals for {len(cities)} cities...")

    rows = []
    missing = []

    for i, city in enumerate(cities, 1):
        name = city["city"]
        lat = float(city["lat"])
        lon = float(city["lon"])

        try:
            point = Point(lat, lon)
            data = Normals(point, 1991, 2020).fetch()

            if data.empty or "tmax" not in data.columns:
                # Try wider period as fallback
                data = Normals(point, 1961, 1990).fetch()

            if data.empty or "tmax" not in data.columns:
                missing.append(name)
                print(f"  [{i}/{len(cities)}] {name}: NO DATA")
                continue

            for month_idx, row in data.iterrows():
                tmax = row.get("tmax")
                if tmax is not None and not (tmax != tmax):  # not NaN
                    rows.append({
                        "city": name,
                        "month": int(month_idx),
                        "avg_high_c": round(float(tmax), 1),
                    })

            print(f"  [{i}/{len(cities)}] {name}: OK ({len(data)} months)")

        except Exception as e:
            missing.append(name)
            print(f"  [{i}/{len(cities)}] {name}: ERROR ({e})")

    # Write normals.csv
    with open(NORMALS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "month", "avg_high_c"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {NORMALS_PATH}")
    print(f"Cities with data: {len(cities) - len(missing)}/{len(cities)}")
    if missing:
        print(f"Missing ({len(missing)}): {', '.join(missing)}")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
