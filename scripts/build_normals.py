#!/usr/bin/env python3
"""Build normals.csv from Meteostat 1991-2020 climate normals.

Reads cities.csv, fetches 30-year monthly avg high temps via Meteostat,
writes normals.csv. Takes ~1 minute for 257 cities.
"""

import csv
import sys
from pathlib import Path

from meteostat import Normals, Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data import places
from src.data.temperature_evidence import utc_now

CITIES_PATH = Path(__file__).parent.parent / "data" / "cities.csv"
NORMALS_PATH = Path(__file__).parent.parent / "data" / "normals.csv"


def main():
    # Load cities
    cities = places.load_cities(str(CITIES_PATH))

    print(f"Fetching normals for {len(cities)} cities...")

    rows = []
    missing = []

    for i, city in enumerate(cities, 1):
        name = city["city"]
        lat = float(city["lat"])
        lon = float(city["lon"])

        try:
            point = Point(lat, lon)
            period_start, period_end = 1991, 2020
            data = Normals(point, period_start, period_end).fetch()

            if data.empty or "tmax" not in data.columns:
                # A different earlier period is explicit in each output row.
                period_start, period_end = 1961, 1990
                data = Normals(point, period_start, period_end).fetch()

            if data.empty or "tmax" not in data.columns:
                missing.append(name)
                print(f"  [{i}/{len(cities)}] {name}: NO DATA")
                continue

            retrieved_at = utc_now()
            for month_idx, row in data.iterrows():
                tmax = row.get("tmax")
                if tmax is not None and not (tmax != tmax):  # not NaN
                    rows.append({
                        "city": name,
                        "country": city["country"], "place_id": city["place_id"],
                        "sampling_point_id": city["sampling_point_id"], "lat": lat, "lon": lon,
                        "month": int(month_idx),
                        "avg_high_c": round(float(tmax), 1),
                        "source_product": "meteostat-normals-point-v1",
                        "period_start": period_start, "period_end": period_end,
                        "retrieved_at": retrieved_at,
                    })

            print(f"  [{i}/{len(cities)}] {name}: OK ({len(data)} months)")

        except Exception as e:
            missing.append(name)
            print(f"  [{i}/{len(cities)}] {name}: ERROR ({e})")

    # Write normals.csv
    with open(NORMALS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "country", "place_id", "sampling_point_id", "lat", "lon", "month", "avg_high_c", "source_product", "period_start", "period_end", "retrieved_at"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {NORMALS_PATH}")
    print(f"Cities with data: {len(cities) - len(missing)}/{len(cities)}")
    if missing:
        print(f"Missing ({len(missing)}): {', '.join(missing)}")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
