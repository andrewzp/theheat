"""A4/P17a: current-GHCN pilot qualification from primary-format metadata (invented stations).

Exercises the real NOAA fixed-width parsers, the place catalogue join and the CLI,
including the byte-pinned inputs-manifest path. Counts describe the inventory only.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from scripts import regional_coverage as cli
from src.data import regional_coverage as rc, threshold_rebuild as rebuild


def _station(sid, lat, lon, name, wmo=""):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {100.0:6.1f}    {name:<30} {'':3} {'':3} {wmo:>5}\n"


COUNTRIES = "SP Spain\nIN India\nSF South Africa\n"
STATIONS = (_station("SPE00000001", 40.42, -3.70, "INVENTED MADRID", "08221")      # current, long, WMO
            + _station("SPE00000002", 41.40, 2.17, "INVENTED BARCELONA")            # current, short history
            + _station("SPE00000003", 37.39, -5.98, "INVENTED SEVILLA")             # ended 1999
            + _station("INM00000001", 28.58, 77.20, "INVENTED DELHI", "42182")       # current, long, WMO
            + _station("IN000000002", 19.07, 72.88, "INVENTED MUMBAI PRCP ONLY")     # no TMAX
            + _station("SFM00000001", -33.97, 18.60, "INVENTED CAPE TOWN", "68816"))
INVENTORY = ("SPE00000001 40.42 -3.70 TMAX 1920 2026\nSPE00000002 41.40 2.17 TMAX 2010 2026\n"
             "SPE00000003 37.39 -5.98 TMAX 1950 1999\nINM00000001 28.58 77.20 TMAX 1940 2026\n"
             "IN000000002 19.07 72.88 PRCP 1940 2026\nSFM00000001 -33.97 18.60 TMAX 1960 2026\n")
CATALOGUE = [{"city": "Madrid", "country": "Spain", "lat": "40.4168", "lon": "-3.7038"},
             {"city": "Barcelona", "country": "Spain", "lat": "41.3874", "lon": "2.1686"},
             {"city": "Delhi", "country": "India", "lat": "28.7041", "lon": "77.1025"},
             {"city": "Mumbai", "country": "India", "lat": "19.0760", "lon": "72.8777"},
             {"city": "Durban", "country": "South Africa", "lat": "-29.8587", "lon": "31.0218"}]


def test_inventory_counts_place_overlap_and_holds_per_pilot():
    out = rc.qualify(STATIONS, INVENTORY, COUNTRIES, catalogue=CATALOGUE)
    spain, india, africa = (out["pilots"][k] for k in ("europe", "south_asia", "southern_africa"))
    assert out["inventory_latest_year"] == 2026
    assert (spain["stations"], spain["tmax_stations"], spain["tmax_current"], spain["tmax_current_long_history"]) == (3, 3, 2, 1)
    assert spain["tmax_current_long_history_wmo"] == 1
    assert spain["catalogue_places_with_station_within_km"] == {"25": 1, "50": 1}  # Barcelona's station is too short
    assert (india["tmax_stations"], india["tmax_current_long_history"]) == (1, 1)
    assert india["catalogue_places_with_station_within_km"]["25"] == 1  # Delhi yes, Mumbai (PRCP only) no
    assert africa["catalogue_places_with_station_within_km"] == {"25": 0, "50": 0}  # Cape Town station, Durban place
    assert spain["national_service"]["adapter"] == "aemet" and "AEMET" in spain["national_service"]["hold"]
    assert india["national_service"]["schema_status"] == "owner_contract_required"
    assert all("threshold_baseline_unavailable" in p["end_to_end_observed_pilot"] for p in out["pilots"].values())
    assert "not event recall" in out["limits"]


def test_an_unverified_fips_code_is_refused_not_guessed():
    out = rc.qualify(STATIONS, INVENTORY, "SP Spain\nIN India\nSF Swaziland\n")
    assert out["pilots"]["southern_africa"]["status"] == "country_code_unverified"
    assert out["pilots"]["europe"]["status"] == "ghcn_current_coverage_present"


def test_cli_reads_the_byte_pinned_inputs_and_refuses_altered_ones(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    files = {"stations": ("ghcnd-stations.txt", STATIONS), "inventory": ("ghcnd-inventory.txt", INVENTORY),
             "countries": ("ghcnd-countries.txt", COUNTRIES)}
    entries = {}
    for role, (name, text) in files.items():
        (inputs / name).write_text(text)
        entries[role] = {"name": name, "sha256": hashlib.sha256(text.encode()).hexdigest(), "bytes": len(text.encode())}
    manifest = {"schema": rebuild.INPUTS_SCHEMA, "inputs": entries,
                "source_version": {"version": "3.35-upd-2026102817", "update_started_at": "2026-10-28T17:00:00Z"}}
    (inputs / "inputs-manifest.json").write_text(json.dumps(manifest))
    cities = tmp_path / "cities.csv"
    cities.write_text("city,country,lat,lon,elevation_m\n" + "".join(
        f"{c['city']},{c['country']},{c['lat']},{c['lon']},10\n" for c in CATALOGUE))
    assert cli.main(["ghcn-pilots", "--inputs", str(inputs), "--cities", str(cities),
                     "--output", str(tmp_path / "out.json")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["source_version"]["version"] == "3.35-upd-2026102817"
    assert out["inputs"]["inventory"]["sha256"] == entries["inventory"]["sha256"]
    assert json.loads((tmp_path / "out.json").read_text()) == out
    (inputs / "ghcnd-inventory.txt").write_text(INVENTORY + "SPE00000003 37.39 -5.98 TMAX 1950 2026\n")
    assert cli.main(["ghcn-pilots", "--inputs", str(inputs), "--cities", str(cities)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "threshold_inventory_changed_since_fetch"
    with pytest.raises(SystemExit):
        cli.main(["ghcn-pilots", "--bogus"])
