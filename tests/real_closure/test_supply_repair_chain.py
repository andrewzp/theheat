"""SUPPLY repair: noaa-ghcnd-monthly-mean-tmax-v1 provenance, coverage and station geometry.

Root's review (2026-11-02, SUPPLY.md) ran five mutations of a real builder candidate through
admit -> install_plan -> load_normals -> hot10_contract.qualify -> build_hot10_bundle ->
validate_bundle -> hot10_graphic_spec and every one was accepted. These tests run that exact chain
(``supply_repair_chain``), plus re-fingerprinted retained bulletins, and the valid counterparts that
must keep passing: a station at the 35 km edge within the stored 0.01 km rounding, a legitimate
below-sea-level place and station, a leap February at its exact bounds, and the legacy Meteostat
bulletin. Invented inputs only; no network, no NOAA bytes, no renderer.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from src.data import ghcnd_monthly_normals as gn, open_meteo, places
from src.editorial import hot10_contract as contract
from src.media import gist_hazard_media as media, hot10_graphic_adapter as adapter
from tests import gist_hazard_helpers as gh, live_content_harness as h
from tests.real_closure import supply_ghcnd_fixture as gf, supply_repair_chain as sc

NOW = sc.NOW
TWELVE = [name for name, _zone, _kind in h.CITIES[:12]]
KM_PER_DEGREE = gn.EARTH_RADIUS_M * math.pi / 180 / 1000


def _chain(tmp_path: Path, case: str) -> dict[str, Any]:
    candidate = sc.build(tmp_path)
    sc.CASES[case](candidate)
    return sc.chain(candidate, tmp_path / "scratch")


def _manifest(candidate: Path) -> dict:
    return json.loads((candidate / "manifest.json").read_bytes())


def _edit_manifest(candidate: Path, change) -> None:
    manifest = _manifest(candidate)
    change(manifest)
    sc._write_manifest(candidate, manifest)


def _reasons(candidate: Path) -> list[str]:
    admission = gn.admit(candidate)
    assert admission["status"] == "product_invalid", admission
    return admission["reasons"]


def _load(tmp_path: Path, rows: list[dict]) -> tuple[dict, dict]:
    report: dict = {}
    path = gf.write_rows(tmp_path / gn.INSTALLED_NAME, rows)
    return gn.load_normals(path, report), report


# ---------------------------------------------------------------------------
# the review's table through the real chain
# ---------------------------------------------------------------------------

def test_valid_control_passes_the_whole_chain(tmp_path):
    out = _chain(tmp_path, "Valid control")
    assert out == {"admission": "ready", "admission_reasons": [], "install_plan": "ready",
                   "loader": {"status": "loaded", "accepted": 144, "refused": {}}, "min_monthly_places": 12,
                   "qualified": 12, "bundle_errors": [], "graphic_spec": "accepted"}


@pytest.mark.parametrize("case,reason", [
    ("valid_days=0", "coverage_impossible"),
    ("station_lat=0, station_lon=0, distance_km=0", "station_out_of_range"),
    ("place_elevation_m=nan", "elevation_invalid"),
    ("Row source_version=made-up-version", "candidate_rows_not_bound_to_source_version"),
])
def test_each_reviewed_row_mutation_is_refused_at_every_stage(tmp_path, case, reason):
    out = _chain(tmp_path, case)
    assert out["admission"] == "product_invalid" and reason in out["admission_reasons"], out
    assert out["install_plan"] == "refused:ghcnd_candidate_not_admitted"
    assert out["loader"]["status"] == "loaded" and out["loader"]["accepted"] == 0, out["loader"]
    assert (out["min_monthly_places"], out["qualified"]) == (0, 0)
    assert out["bundle_errors"].startswith("held") and out["graphic_spec"] == "not reached (held)"


def test_made_up_source_version_is_also_malformed_for_the_loader(tmp_path):
    out = _chain(tmp_path, "Row source_version=made-up-version")
    assert out["loader"]["refused"] == {"provenance_malformed": 144}
    assert "provenance_malformed" in out["admission_reasons"]


def test_removed_manifest_provenance_is_refused_by_admission_and_install_plan(tmp_path):
    out = _chain(tmp_path, "Manifest provenance removed")
    assert out["admission"] == "product_invalid" and out["admission_reasons"] == ["candidate_provenance_missing"]
    assert out["install_plan"] == "refused:ghcnd_candidate_not_admitted"
    # The CSV bytes are the genuine builder's; lineage lives in the manifest, so the gate that
    # promotes a candidate to the installed file is where it is enforced (the loader reads only that file).
    assert out["loader"]["accepted"] == 144


# ---------------------------------------------------------------------------
# a retained bulletin re-fingerprinted after the fact never regains qualification
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def control(tmp_path_factory) -> dict:
    bundle = sc.control_bundle(tmp_path_factory.mktemp("control"))
    assert contract.validate_bundle(bundle) == []
    assert sc.graphic(bundle) == "accepted"
    return bundle


@pytest.mark.parametrize("case", [name for name in sc.BUNDLE_CASES if name != "place_elevation_m=nan"])
def test_a_refingerprinted_inconsistent_bulletin_is_refused(control, case):
    out = sc.bundle_case(control, sc.BUNDLE_CASES[case])
    assert out["refingerprint"] == "ok"
    assert "row_unqualified" in out["bundle_errors"] and out["graphic_spec"] == "refused:media_hot10_row_unqualified"
    assert contract.current_hold(sc.refingerprint(_mutated(control, case))) == "hot10_contract_invalid:row_unqualified"


def _mutated(bundle: dict, case: str) -> dict:
    copy = deepcopy(bundle)
    for row in copy["raw_signal_dump"]["cities"]:
        sc.BUNDLE_CASES[case](row["baseline"])
    return copy


def test_a_non_finite_place_elevation_cannot_even_be_fingerprinted(control):
    assert sc.bundle_case(control, sc.BUNDLE_CASES["place_elevation_m=nan"])["refingerprint"] \
        == "impossible:ValueError"


def test_the_bulletin_retains_what_the_validator_rechecks(control):
    baseline = control["raw_signal_dump"]["cities"][0]["baseline"]
    for key in ("place_elevation_m", "station_elevation_m", "station_lat", "station_lon", "distance_km",
                "qualifying_year_mask", "valid_days", "flagged_values", "years_used", "first_year", "last_year",
                "source_version", "retrieved_at"):
        assert key in baseline, key
    assert baseline["qualifying_year_mask"] == "1" * 30 and baseline["valid_days"] == 30 * 31


@pytest.mark.parametrize("change", [{"valid_days": 0}, {"valid_days": 931}, {"flagged_values": -1},
                                    {"station_lat": 0.0, "station_lon": 0.0, "distance_km": 0.0},
                                    {"place_elevation_m": 3000.0, "station_elevation_m": 3000.0},
                                    {"qualifying_year_mask": "0" + "1" * 29},
                                    {"source_version": "made-up-version"}])
def test_the_qualifier_refuses_the_same_baselines_when_the_loader_is_bypassed(tmp_path, change):
    normals: dict = {}
    for row in gf.installed_rows(NOW.month):
        meta = gn.provenance(row, {"sampling_point_id": row["sampling_point_id"]})
        meta.update(change)
        key = places.event_location_key(row["city"], row["country"], row["lat"], row["lon"], place_id=row["place_id"])
        normals[key] = {NOW.month: float(row["mean_tmax_c"]), "_meta": {NOW.month: meta}}
    result = contract.qualify(h.city_temps(NOW), normals, sampled=14, now=NOW, product=contract.GHCND_PRODUCT)
    assert result["rows"] == [] and result["universe"]["excluded"]["unqualified_normal"] == 13


# ---------------------------------------------------------------------------
# C.2 coverage: exact daily bounds from month length, qualifying years and the five-missing-day rule
# ---------------------------------------------------------------------------

def _mask(years) -> str:
    chosen = set(years)
    return "".join("1" if year in chosen else "0" for year in range(1991, 2021))


LEAP_IN_PERIOD = [y for y in range(1991, 2021) if y % 4 == 0]  # 8 leap Februaries in 1991-2020
NON_LEAP = [y for y in range(1991, 2021) if y % 4]  # the other 22 years


@pytest.mark.parametrize("month,overrides,accepted", [
    # October, 30 qualifying years: 30 x (31 - 5) .. 30 x 31
    (10, {"valid_days": "780"}, True), (10, {"valid_days": "779"}, False),
    (10, {"valid_days": "930"}, True), (10, {"valid_days": "931"}, False),
    (10, {"valid_days": "0"}, False), (10, {"valid_days": "-1"}, False),
    # February, all 30 years (8 leap): 30 x 23 + 8 .. 30 x 28 + 8
    (2, {"valid_days": "698"}, True), (2, {"valid_days": "697"}, False),
    (2, {"valid_days": "848"}, True), (2, {"valid_days": "849"}, False),
    # February, 24 years 1991-2014 (6 leap): 24 x 23 + 6 .. 24 x 28 + 6
    (2, {"years_used": "24", "last_year": "2014", "qualifying_year_mask": _mask(range(1991, 2015)),
         "valid_days": "678"}, True),
    (2, {"years_used": "24", "last_year": "2014", "qualifying_year_mask": _mask(range(1991, 2015)),
         "valid_days": "679"}, False),
    (2, {"years_used": "24", "last_year": "2014", "qualifying_year_mask": _mask(range(1991, 2015)),
         "valid_days": "558"}, True),
    (2, {"years_used": "24", "last_year": "2014", "qualifying_year_mask": _mask(range(1991, 2015)),
         "valid_days": "557"}, False),
    # 24 years spanning 1991-2020 with only two leap Februaries (1992, 2020): 24 x 28 + 2 = 674 at most,
    # where years/first/last alone would allow up to 24 x 28 + 8 = 680: the year set decides
    (2, {"years_used": "24", "qualifying_year_mask": _mask(NON_LEAP + [1992, 2020]), "valid_days": "674"}, True),
    (2, {"years_used": "24", "qualifying_year_mask": _mask(NON_LEAP + [1992, 2020]), "valid_days": "675"}, False),
])
def test_valid_days_must_be_possible_for_the_stated_years_and_month(tmp_path, month, overrides, accepted):
    rows = gf.installed_rows(month, **overrides)
    normals, report = _load(tmp_path, rows)
    if accepted:
        assert report["accepted"] == 13 and report["refused"] == {}, report
    else:
        assert report["accepted"] == 0 and report["refused"] == {"coverage_impossible": 13}, report


@pytest.mark.parametrize("overrides,reason", [
    ({"flagged_values": "-1"}, "rejection_count_invalid"),
    ({"flagged_values": "1", "valid_days": "930"}, "rejection_count_invalid"),  # 931 > 30 x 31 day slots
    ({"qualifying_year_mask": "1" * 29}, "coverage_impossible"),
    ({"qualifying_year_mask": "0" + "1" * 29}, "coverage_impossible"),  # 29 years stated as 30
    ({"qualifying_year_mask": "1" * 29 + "2"}, "coverage_impossible"),
    ({"first_year": "1992", "years_used": "29", "valid_days": "870"}, "coverage_impossible"),  # mask says 1991
])
def test_rejection_counts_and_the_year_set_must_agree(tmp_path, overrides, reason):
    _normals, report = _load(tmp_path, gf.installed_rows(10, **overrides))
    assert report["refused"] == {reason: 13}, report


def test_flagged_values_up_to_the_free_day_slots_are_accepted(tmp_path):
    _normals, report = _load(tmp_path, gf.installed_rows(10, valid_days="900", flagged_values="30"))
    assert report["accepted"] == 13


def test_the_builder_records_its_qualifying_years_and_its_output_is_within_bounds():
    def gaps(year, month):  # 1993 July misses 6 days: that year-month does not qualify
        return {1, 3, 5, 7, 9, 11} if (year, month) == (1993, 7) else ({2, 9} if month == 2 else set())
    text = gf.station_text("XQW00012345", lambda y, m: 30.0, years=range(1985, 2025), missing=gaps)
    climatology = gn.station_climatology(text, "XQW00012345")
    july, february = climatology[7], climatology[2]
    assert july["qualifying_year_mask"] == _mask(y for y in range(1991, 2021) if y != 1993)
    assert july["years_used"] == 29 and july["valid_days"] == 29 * 31
    assert february["qualifying_year_mask"] == "1" * 30
    assert february["valid_days"] == 30 * 28 + len(LEAP_IN_PERIOD) - 2 * 30


# ---------------------------------------------------------------------------
# C.3 station geometry: bounded values, the registered elevation and the recomputed distance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("overrides,reason", [
    ({"station_lat": "91.0"}, "coordinates_invalid"),
    ({"station_lon": "inf"}, "coordinates_invalid"),
    ({"station_lat": "nan"}, "coordinates_invalid"),
    ({"station_elevation_m": "-999.9"}, "elevation_invalid"),
    ({"station_elevation_m": "-9999.0"}, "elevation_invalid"),
    ({"place_elevation_m": "-9999.0"}, "elevation_invalid"),
    ({"place_elevation_m": "nan"}, "elevation_invalid"),
    ({"station_elevation_m": "inf"}, "elevation_invalid"),
    ({"distance_km": "5.0"}, "station_distance_misstated"),   # the station is 5.56 km away
    ({"distance_km": "5.55"}, "station_distance_misstated"),  # outside the 0.005 km rounding tolerance
    ({"station_lat": "0.0", "station_lon": "0.0", "distance_km": "0.0"}, "station_out_of_range"),
])
def test_station_geometry_is_recomputed_not_trusted(tmp_path, overrides, reason):
    _normals, report = _load(tmp_path, gf.installed_rows(10, **overrides))
    assert report["refused"] == {reason: 13}, report


def test_place_elevation_is_bound_to_the_registered_catalogue_point(tmp_path):
    rows = gf.installed_rows(10)
    for row in rows:  # place and station agree with each other, 300 m above the registered point
        row.update(place_elevation_m=repr(float(row["place_elevation_m"]) + 300.0),
                   station_elevation_m=repr(float(row["place_elevation_m"]) + 305.0))
    _normals, report = _load(tmp_path, rows)
    assert report["refused"] == {"place_elevation_unregistered": 13}, report


def test_fixture_distances_are_within_the_stored_rounding(tmp_path):
    _normals, report = _load(tmp_path, gf.installed_rows(10, distance_km="5.56"))
    assert report["accepted"] == 13  # haversine 5.5597 km, stored 5.56


def _world(tmp_path: Path, names: list[str], **station_kw) -> tuple[gf.Inputs, Path]:
    world = gf.Inputs(tmp_path, names)
    for index, name in enumerate(names):
        world.add(f"XQW0000{index:04d}", name, base=25.0 + index, **(station_kw.get(name) or {}))
    return world, world.write()


EDGE = (25.0227, 46.7096)  # 4-decimal station coordinates 34.9994 km (haversine) from Riyadh's 24.71, 46.67


def test_a_station_at_the_radius_edge_within_rounding_qualifies_end_to_end(tmp_path):
    assert 34_995 < gn.distance_m(24.71, 46.67, *EDGE) <= gn.MAX_DISTANCE_M  # stored 35.0, truly inside
    world, inputs = _world(tmp_path, TWELVE, Riyadh={"at": EDGE})
    gn.build_candidate(world.cities, inputs, world.dir, tmp_path / "out")
    candidate = tmp_path / "out" / "candidate"
    riyadh = [row for row in sc.read_rows(candidate)[1] if row["city"] == "Riyadh"]
    assert {row["distance_km"] for row in riyadh} == {"35.0"}
    out = sc.chain(candidate, tmp_path / "scratch")
    assert (out["admission"], out["install_plan"], out["qualified"], out["bundle_errors"], out["graphic_spec"]) \
        == ("ready", "ready", 12, [], "accepted"), out


def test_a_station_just_beyond_the_radius_declared_at_the_edge_is_refused(tmp_path):
    world, inputs = _world(tmp_path, TWELVE)
    gn.build_candidate(world.cities, inputs, world.dir, tmp_path / "out")
    candidate = tmp_path / "out" / "candidate"

    def beyond(row: dict) -> None:
        if row["city"] == "Riyadh":  # truly 35.004 km away, which also rounds to the declared 35.0
            row.update(station_lat=repr(float(row["lat"]) + 35.004 / KM_PER_DEGREE), station_lon=row["lon"],
                       distance_km="35.0")
    sc.rewrite_rows(candidate, beyond)
    assert "station_out_of_range" in _reasons(candidate)


def test_a_legitimate_below_sea_level_place_and_station_qualify_end_to_end(tmp_path):
    names = ["Death Valley", *TWELVE[:11]]
    world, inputs = _world(tmp_path, names)  # station 10 m above the registered -58 m point: -48 m
    gn.build_candidate(world.cities, inputs, world.dir, tmp_path / "out")
    candidate = tmp_path / "out" / "candidate"
    death_valley = next(row for row in sc.read_rows(candidate)[1] if row["city"] == "Death Valley")
    assert (death_valley["place_elevation_m"], death_valley["station_elevation_m"]) == ("-58.0", "-48.0")
    cities = (("Death Valley", "America/Los_Angeles", 9.5), *h.CITIES[:11])
    out = sc.chain(candidate, tmp_path / "scratch", cities)
    assert (out["admission"], out["install_plan"], out["qualified"], out["bundle_errors"], out["graphic_spec"]) \
        == ("ready", "ready", 12, [], "accepted"), out


def test_legacy_meteostat_bulletin_and_rows_are_unchanged(tmp_path):
    bundle = gh.hot10_bundle()
    assert contract.validate_bundle(bundle) == []
    assert adapter.hot10_graphic_spec(bundle, expected_bundle_sha256=media.fingerprint(bundle), synthetic=True)
    legacy = tmp_path / "normals.csv"
    h.write_normals(legacy, h.normal_rows(NOW.month))
    normals = open_meteo.load_normals(str(legacy))
    assert sum(1 for entry in normals.values() if NOW.month in entry) == 12  # Sydney's two rows stay ambiguous
    assert set(bundle["raw_signal_dump"]["cities"][0]["baseline"]) == set(contract._BASELINE_KEYS)


def test_the_validator_mirrors_the_builder_rules():
    assert contract.GHCND_MAX_DISTANCE_KM * 1000 == gn.MAX_DISTANCE_M
    assert contract.GHCND_MAX_ELEVATION_DIFF_M == gn.MAX_ELEVATION_DIFF_M
    assert contract.GHCND_MAX_MISSING_DAYS == gn.MAX_MISSING_DAYS
    assert contract.GHCND_DISTANCE_TOLERANCE_KM == gn.DISTANCE_TOLERANCE_KM
    assert contract.GHCND_ELEVATION_RANGE_M == gn.ELEVATION_RANGE_M
    assert (contract.GHCND_PERIOD, contract.GHCND_MIN_YEARS) == (gn.PERIOD, gn.MIN_YEARS)
    for entry in places.registry():  # both sides bind a place to the same registered elevation
        assert contract._registered_elevation(entry["place_id"], entry["lat"], entry["lon"]) \
            == gn.registered_elevation(entry["place_id"], entry["lat"], entry["lon"]) == float(entry["elevation_m"])
    assert contract._registered_elevation("pl0467", 24.0, 46.0) is None  # not the registered point


# ---------------------------------------------------------------------------
# C.1 provenance: the manifest's lineage must be complete, typed and agree with every row
# ---------------------------------------------------------------------------

@pytest.fixture
def candidate(tmp_path) -> Path:
    return sc.build(tmp_path)


@pytest.mark.parametrize("key", sc.REMOVED_PROVENANCE)
def test_each_missing_provenance_field_refuses_admission(candidate, key):
    _edit_manifest(candidate, lambda manifest: manifest.pop(key))
    assert "candidate_provenance_missing" in _reasons(candidate)


@pytest.mark.parametrize("change,reason", [
    (lambda m: m["inputs"].pop("inventory"), "candidate_provenance_missing"),
    (lambda m: m["inputs"]["archive"].update(bytes=str(m["inputs"]["archive"]["bytes"])),
     "candidate_provenance_invalid"),
    (lambda m: m["inputs"]["archive"].update(bytes=True), "candidate_provenance_invalid"),
    (lambda m: m["inputs"]["stations"].update(sha256="not-a-digest"), "candidate_provenance_invalid"),
    (lambda m: m["inputs"]["stations"].update(name="ghcnd-countries.txt"), "candidate_provenance_invalid"),
    (lambda m: m["inputs"]["version"].update(url="https://example.invalid/ghcnd-version.txt"),
     "candidate_provenance_invalid"),
    (lambda m: m["inputs"]["inventory"].update(retrieved_at="yesterday"), "candidate_provenance_invalid"),
    (lambda m: m["inputs"].update(countries=dict(m["inputs"]["version"])), "candidate_provenance_invalid"),
    (lambda m: m["source_version"].update(version="made-up-version"), "candidate_provenance_invalid"),
    (lambda m: m["source_version"].update(text_sha256="0" * 64), "candidate_version_text_unbound"),
    (lambda m: m["source_version"].update(update_started_at="2026-10-28T18:00:00Z"),
     "candidate_version_text_unbound"),
    (lambda m: m.update(input_product="noaa-ghcn-daily-v3"), "candidate_source_mismatch"),
    (lambda m: m.update(dataset="meteostat"), "candidate_source_mismatch"),
    (lambda m: m.update(attribution="Meteostat"), "candidate_source_mismatch"),
    (lambda m: m.update(units={"mean_tmax_c": "degF", "distance_km": "km", "elevation_m": "m"}),
     "candidate_source_mismatch"),
    (lambda m: m["cities"].update(points=11), "candidate_catalogue_contradicted"),
    (lambda m: m["cities"].update(sha256="abc"), "candidate_provenance_invalid"),
    (lambda m: m["stations"].update(read=13), "candidate_station_counts_contradicted"),
    (lambda m: m["stations"].update(with_any_qualified_month=11), "candidate_station_counts_contradicted"),
    (lambda m: m["coverage"]["places_by_month"].update({"7": 13}), "candidate_coverage_misstated"),
    (lambda m: m.update(rows=143), "candidate_coverage_misstated"),
    (lambda m: m.update(assembled_at="2026-10-30T00:00:00Z"), "candidate_retrieval_contradicted"),
])
def test_contradictory_or_malformed_lineage_refuses_admission(candidate, change, reason):
    _edit_manifest(candidate, change)
    assert reason in _reasons(candidate)


def test_a_self_consistent_but_different_manifest_version_contradicts_the_rows(candidate):
    _edit_manifest(candidate, lambda m: m["source_version"].update(version="3.35-upd-2026102900",
                                                                    update_started_at="2026-10-29T00:00:00Z"))
    assert "candidate_rows_not_bound_to_source_version" in _reasons(candidate)


def test_rows_retrieved_elsewhere_contradict_the_archive_retrieval(candidate):
    sc.rewrite_rows(candidate, lambda row: row.update(retrieved_at="2026-10-30T23:00:00Z"))
    assert "candidate_rows_not_bound_to_retrieval" in _reasons(candidate)


def test_inputs_retrieved_before_the_version_update_started_are_contradicted(candidate):
    early = "2026-10-27T00:00:00Z"
    _edit_manifest(candidate, lambda m: [identity.update(retrieved_at=early) for identity in m["inputs"].values()])
    sc.rewrite_rows(candidate, lambda row: row.update(retrieved_at=early))
    assert _reasons(candidate) == ["candidate_retrieval_contradicted"]


def test_install_plan_refuses_unbound_lineage_on_its_own(candidate, tmp_path, monkeypatch):
    real = gn.admit(candidate)
    assert real["status"] == "ready"
    # Rows re-labelled after admission (CSV re-hashed into the manifest): a stale admission is not enough ...
    sc.rewrite_rows(candidate, lambda row: row.update(source_version="3.35-upd-2026102900"))
    monkeypatch.setattr(gn, "admit", lambda _candidate: real)
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_candidate_changed_since_admission"):
        gn.install_plan(candidate, tmp_path / "data" / gn.INSTALLED_NAME)
    # ... and even an admission result naming these exact bytes cannot carry rows the manifest contradicts.
    forged = deepcopy(real)
    forged["product"]["candidate_sha256"] = hashlib.sha256((candidate / "normals.csv").read_bytes()).hexdigest()
    monkeypatch.setattr(gn, "admit", lambda _candidate: forged)
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_candidate_provenance_invalid"):
        gn.install_plan(candidate, tmp_path / "data" / gn.INSTALLED_NAME)
    assert not (tmp_path / "data" / gn.INSTALLED_NAME).exists()


def test_the_install_plan_carries_the_admitted_lineage_and_not_scientific_truth(candidate, tmp_path):
    plan = gn.install_plan(candidate, tmp_path / "data" / gn.INSTALLED_NAME)
    manifest = _manifest(candidate)
    assert plan["candidate"]["source_version"] == manifest["source_version"]
    assert plan["candidate"]["inputs"] == manifest["inputs"] and plan["candidate"]["catalogue"] == manifest["cities"]
    assert plan["scientific_qualification"] == "not_established_by_loader_acceptance"


def test_a_file_mixing_lineages_is_refused_whole(tmp_path):
    rows = gf.installed_rows(10)
    rows[3]["source_version"] = "3.35-upd-2026102900"
    normals, report = _load(tmp_path, rows)
    assert normals == {} and report["status"] == "refused_mixed_lineage"
