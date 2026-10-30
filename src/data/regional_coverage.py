"""P17a: qualify current GHCN-Daily coverage for the three observed-temperature pilot regions.

Inputs are the primary NOAA metadata files (``ghcnd-stations.txt``,
``ghcnd-inventory.txt``, ``ghcnd-countries.txt``), normally the byte-pinned set
fetched by ``build_station_thresholds.py fetch-inputs`` and bound by its
inputs manifest, plus the bot's place catalogue. Nothing is fetched here.

For each pilot (Europe/Spain with AEMET, South Asia/India with IMD, Southern
Africa/South Africa with SAWS) it reports what the inventory itself supports:
stations with TMAX, stations whose TMAX inventory reaches the inventory's
latest year ("current"), current stations with at least 30 years of TMAX
history (enough for a threshold comparison), their WMO/GSN subsets, and how
many catalogue places of the incumbent forecast lane have such a station
within 25/50 km. The national service's own access/schema hold and the GHCN
observed lane's threshold-baseline dependency complete the disposition.

Limits kept explicit: an inventory year is not a daily reporting latency, a
station count is not observation availability or QC pass rate, and a
catalogue overlap is not event recall. GHCN uses FIPS country codes; each
pilot's code is checked against the countries file's own name, never guessed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from typing import Any

from src.data import regional_observations
from src.data.ghcn_format import parse_countries_file, parse_inventory_file, parse_stations_file

SCHEMA = "theheat.regional-ghcn-coverage/v1"
LONG_HISTORY_YEARS = 30
NEAR_KM = (25.0, 50.0)
PILOTS: dict[str, dict[str, str]] = {
    "europe": {"adapter": "aemet", "ghcn_code": "SP", "ghcn_name": "Spain", "catalogue_country": "Spain"},
    "south_asia": {"adapter": "imd", "ghcn_code": "IN", "ghcn_name": "India", "catalogue_country": "India"},
    "southern_africa": {"adapter": "saws", "ghcn_code": "SF", "ghcn_name": "South Africa",
                        "catalogue_country": "South Africa"},
}
LIMITS = ("Inventory first/last years are not a daily reporting latency; station counts are not observation "
          "availability or QC pass rates; catalogue overlap is not event recall.")


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(a)))


def qualify(stations_text: str, inventory_text: str, countries_text: str, *,
            catalogue: Iterable[Mapping[str, Any]] = (), source_version: Mapping[str, Any] | None = None,
            input_identities: Mapping[str, Any] | None = None) -> dict[str, Any]:
    countries = parse_countries_file(countries_text)
    stations = {meta.station_id: meta for meta in parse_stations_file(stations_text)}
    tmax: dict[str, tuple[int, int]] = {}
    latest_year = 0
    for row in parse_inventory_file(inventory_text):
        latest_year = max(latest_year, row.last_year)
        if row.element == "TMAX":
            tmax[row.station_id] = (row.first_year, row.last_year)
    places = [row for row in catalogue if isinstance(row, Mapping)]
    pilots: dict[str, Any] = {}
    for region, pilot in PILOTS.items():
        name = countries.get(pilot["ghcn_code"])
        spec = regional_observations.ADAPTERS[pilot["adapter"]]
        national = {"adapter": spec.adapter_id, "source_product": spec.source_product,
                    "schema_status": spec.schema_status, "hold": spec.access_hold, "owner_action": spec.owner_action}
        if name != pilot["ghcn_name"]:
            pilots[region] = {"status": "country_code_unverified", "ghcn_code": pilot["ghcn_code"],
                              "countries_file_name": name, "national_service": national}
            continue
        ids = sorted(sid for sid in stations if sid.startswith(pilot["ghcn_code"]))
        with_tmax = [sid for sid in ids if sid in tmax]
        current = [sid for sid in with_tmax if tmax[sid][1] >= latest_year]
        long_current = [sid for sid in current if tmax[sid][1] - tmax[sid][0] + 1 >= LONG_HISTORY_YEARS]
        places_here = [row for row in places if row.get("country") == pilot["catalogue_country"]]
        near = {limit: 0 for limit in NEAR_KM}
        for place in places_here:
            try:
                lat, lon = float(place["lat"]), float(place["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            nearest = min((_km(lat, lon, stations[sid].lat, stations[sid].lon) for sid in long_current),
                          default=math.inf)
            for limit in NEAR_KM:
                near[limit] += nearest <= limit
        pilots[region] = {
            "status": "ghcn_current_coverage_present" if long_current else "ghcn_current_coverage_absent",
            "ghcn_code": pilot["ghcn_code"], "country": name,
            "stations": len(ids), "tmax_stations": len(with_tmax), "tmax_current": len(current),
            "tmax_current_long_history": len(long_current),
            "tmax_current_long_history_wmo": sum(1 for sid in long_current if stations[sid].wmo_id),
            "tmax_current_long_history_gsn": sum(1 for sid in long_current if stations[sid].gsn_flag),
            "catalogue_places": len(places_here),
            "catalogue_places_with_station_within_km": {str(int(k)): v for k, v in near.items()},
            "national_service": national,
            "end_to_end_observed_pilot": ("blocked: the GHCN observed lane needs the threshold baseline package "
                                          "(threshold_baseline_unavailable); the national service is held"),
        }
    return {"schema": SCHEMA, "inventory_latest_year": latest_year, "long_history_years": LONG_HISTORY_YEARS,
            "source_version": dict(source_version) if source_version else None,
            "inputs": dict(input_identities) if input_identities else None, "pilots": pilots,
            "latency": "GHCN-Daily dataset update cadence is the version pin's update start; per-station reporting "
                       "latency is not in these inputs.",
            "cost": "public HTTPS, no key; one bounded metadata fetch", "rights": "not recorded in these inputs",
            "limits": LIMITS}


__all__ = ["LIMITS", "PILOTS", "SCHEMA", "qualify"]
