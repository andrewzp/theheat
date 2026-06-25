# scripts/build_country_continent.py
"""Derive country -> continent from data/cities.csv lat/lon. Re-run on cities change."""
import csv, json
from collections import Counter


def continent_for(lat: float, lon: float) -> str:
    if lat <= -60: return "Antarctica"
    if lat <= 0 and 110 <= lon <= 180: return "Oceania"
    if -56 <= lat <= 14 and -82 <= lon <= -34: return "South America"
    if lat >= 7 and -170 <= lon <= -50: return "North America"
    if 34 <= lat <= 72 and -25 <= lon <= 60: return "Europe"
    if -37 <= lat <= 37 and -20 <= lon <= 52: return "Africa"
    if -15 <= lat <= 82 and 25 <= lon <= 180: return "Asia"
    return "Unknown"


def build(cities_path: str = "data/cities.csv") -> dict[str, str]:
    votes: dict[str, Counter] = {}
    with open(cities_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            country = (row.get("country") or "").strip()
            if not country: continue
            votes.setdefault(country, Counter())[continent_for(float(row["lat"]), float(row["lon"]))] += 1
    return {c: v.most_common(1)[0][0] for c, v in sorted(votes.items())}


if __name__ == "__main__":
    mapping = build()
    with open("data/country_continent.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False, sort_keys=True); f.write("\n")
    print(f"wrote data/country_continent.json ({len(mapping)} countries)")
