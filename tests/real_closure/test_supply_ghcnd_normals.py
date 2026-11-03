"""noaa-ghcnd-monthly-mean-tmax-v1: offline build, QC/coverage rules, admission and install planning.

Inputs are invented GHCN-Daily files in the real formats (``supply_ghcnd_fixture``)
bound by Root's ``theheat.threshold-inputs/v1`` manifest shape. The production
builder, loader, admission and install plan run unmodified; the operator CLI is
exercised end to end. No network, no NOAA bytes.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import build_normals
from src.data import ghcnd_monthly_normals as gn, normals_acquisition as na
from tests import live_content_harness as h
from tests.real_closure import supply_ghcnd_fixture as gf

TWELVE = [name for name, _zone, _kind in h.CITIES[:12]]


def _no_gap(_year: int, _month: int) -> float | None:
    return 30.0


def _july_gap(_year: int, month: int) -> float | None:
    return None if month == 7 else 30.0


# ---------------------------------------------------------------------------
# the explicit rules
# ---------------------------------------------------------------------------

def test_year_month_coverage_rule_is_exactly_five_missing_and_runs_of_three():
    full = set(range(1, 31))
    assert gn.month_qualifies(2001, 6, full)
    assert gn.month_qualifies(2001, 6, full - {2, 4, 6, 8, 10})            # 5 missing, none consecutive
    assert not gn.month_qualifies(2001, 6, full - {2, 4, 6, 8, 10, 12})    # 6 missing
    assert gn.month_qualifies(2001, 6, full - {10, 11, 12})                # run of 3
    assert not gn.month_qualifies(2001, 6, full - {10, 11, 12, 13})        # run of 4
    assert not gn.month_qualifies(2001, 6, full - {27, 28, 29, 30})        # a run at the month's end counts
    assert gn.month_qualifies(2000, 2, set(range(1, 30)) - {1, 2, 3, 20, 21})  # leap February: 29 days


def _climatology(text: str, sid: str = "XQW00012345"):
    return gn.station_climatology(text, sid)


def test_value_is_the_mean_daily_maximum_never_the_month_record():
    text = gf.station_text("XQW00012345", lambda y, m: 30.0, years=range(1991, 2021), spread=8.0)
    july = _climatology(text)[7]
    daily = [30.0 + 8.0 * ((d % 5) - 2) / 2 for d in range(1, 32)]
    assert july["mean_tmax_c"] == round(sum(daily) / 31, 1)
    assert july["mean_tmax_c"] < max(daily) - 7  # a monthly record maximum would be 38.0
    assert (july["years_used"], july["first_year"], july["last_year"]) == (30, 1991, 2020)
    assert july["valid_days"] == 30 * 31 and july["flagged_values"] == 0


def test_flagged_values_are_rejected_counted_and_can_fail_coverage():
    flag_hot = gf.station_text("XQW00012345", lambda y, m: 30.0, years=range(1991, 2021), spread=0.0,
                               missing=lambda y, m: {15} if m == 7 else set(),
                               flagged=lambda y, m: {15: 590} if m == 7 else {})
    july = _climatology(flag_hot)[7]
    assert july["mean_tmax_c"] == 30.0  # the flagged 59.0 C day never enters the mean
    assert july["flagged_values"] == 30 and july["valid_days"] == 30 * 30
    # Four consecutive flagged days break the year-month (flagged counts as missing).
    flag_run = gf.station_text("XQW00012345", lambda y, m: 30.0, years=range(1991, 2021), spread=0.0,
                               missing=lambda y, m: {10, 11, 12, 13} if m == 7 else set(),
                               flagged=lambda y, m: dict.fromkeys((10, 11, 12, 13), 300) if m == 7 else {})
    assert 7 not in _climatology(flag_run) and 6 in _climatology(flag_run)


def test_insufficient_years_and_values_outside_the_period_never_count():
    def broken(y, m):  # only 23 years of July qualify inside 1991-2020 (seven months too sparse)
        return set(range(1, 12)) if (m == 7 and y <= 1997) else set()
    text = gf.station_text("XQW00012345", lambda y, m: 30.0, years=range(1960, 2026), missing=broken)
    climatology = _climatology(text)
    assert 7 not in climatology and climatology[6]["years_used"] == 30
    assert climatology[6]["first_year"] == 1991 and climatology[6]["last_year"] == 2020
    twenty_four = gf.station_text("XQW00012345", lambda y, m: 30.0, years=range(1991, 2021),
                                  missing=lambda y, m: set(range(1, 12)) if (m == 7 and y <= 1996) else set())
    assert _climatology(twenty_four)[7]["years_used"] == 24


def test_a_record_of_another_station_or_a_duplicate_month_refuses_the_station():
    good = gf.station_text("XQW00012345", lambda y, m: 30.0, years=range(1991, 1992))
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_station_record_mismatch"):
        gn.station_climatology(good, "XQW00099999")
    line = good.splitlines()[0]
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_duplicate_month_record"):
        gn.station_climatology(line + "\n" + line + "\n", "XQW00012345")


# ---------------------------------------------------------------------------
# build -> admit -> install-plan through the operator CLI
# ---------------------------------------------------------------------------

def _world(tmp_path: Path, names=TWELVE) -> gf.Inputs:
    world = gf.Inputs(tmp_path, names)
    for index, name in enumerate(names):
        world.add(f"XQW0000{index:04d}", name, base=25.0 + index)
    return world


def _rows(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_cli_builds_admits_and_plans_install_of_twelve_places(tmp_path, capsys):
    world = _world(tmp_path)
    manifest_path = world.write()
    out = tmp_path / "out"
    assert build_normals.main(["ghcnd-build", "--cities", str(world.cities), "--inputs-manifest",
                               str(manifest_path), "--out-dir", str(out)]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["status"] == "ready" and built["product"]["product"] == gn.PRODUCT
    assert built["product"]["min_places_per_month"] == 12 and built["product"]["rows"] == 144
    rows = _rows(out / "candidate/normals.csv")
    riyadh = next(r for r in rows if r["city"] == "Riyadh" and r["month"] == "7")
    assert riyadh["source_product"] == gn.PRODUCT and riyadh["statistic"] == "mean_daily_maximum"
    assert (riyadh["period_start"], riyadh["period_end"], riyadh["unit"]) == ("1991", "2020", "C")
    assert riyadh["station_id"] == "XQW00000000" and 4.9 < float(riyadh["distance_km"]) < 5.1
    assert riyadh["source_version"] == "3.35-upd-2026102817" and riyadh["retrieved_at"] == gf.RETRIEVED_AT
    assert riyadh["years_used"] == "30"
    manifest = json.loads((out / "candidate/manifest.json").read_text())
    assert manifest["redistribution"]["status"] == "private_use_release_gated"
    assert manifest["redistribution"]["public_bulk_asset"] == "refused_until_terms_decision"
    assert "gov.noaa.ncdc:C00861" in manifest["attribution"] and "Meteostat" not in json.dumps(manifest)
    assert manifest["inputs"]["archive"]["retrieved_at"] == gf.RETRIEVED_AT

    assert build_normals.main(["admit", "--candidate", str(out / "candidate")]) == 0
    admission = json.loads(capsys.readouterr().out)
    assert admission["status"] == "ready" and admission["product"]["loader_accepted_point_months"] == 144
    installed = tmp_path / "repo" / "data" / gn.INSTALLED_NAME
    assert build_normals.main(["install-plan", "--candidate", str(out / "candidate"),
                               "--installed", str(installed)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["schema"] == gn.INSTALL_SCHEMA and plan["install"]["performed_by"] == "root"
    assert plan["coverage"]["min_places_per_month"] == 12 and plan["previous"] is None
    assert any("THEHEAT_HOT10_NORMALS_PRODUCT=" + gn.PRODUCT in step for step in plan["install"]["steps"])
    assert plan["install"]["requires"][0].startswith("terms decision: committing this file to a public repository")
    assert plan["redistribution"]["status"] == "private_use_release_gated"
    assert not installed.exists()  # Root installs


def test_station_choice_is_nearest_in_range_per_month_and_states_its_station(tmp_path):
    world = gf.Inputs(tmp_path, TWELVE)
    for index, name in enumerate(TWELVE):
        world.add(f"XQW0000{index:04d}", name, north_km=12.0)
    # Riyadh: a nearer station with no July coverage, one beyond 35 km, one 500 m higher.
    world.add("XQW00009001", "Riyadh", north_km=2.0, text=gf.station_text(
        "XQW00009001", lambda y, m: None if m == 7 else 40.0, years=range(1985, 2025)))
    world.add("XQW00009002", "Riyadh", north_km=36.0, base=10.0)
    world.add("XQW00009003", "Riyadh", north_km=1.0, elevation_delta=500.0, base=5.0)
    world.add("XQW00009004", "Riyadh", north_km=0.5, first=1999, last=2024, base=1.0)  # 22 years: never a candidate
    out = tmp_path / "out"
    result = gn.build_candidate(world.cities, world.write(), world.dir, out)
    assert result["status"] == "ready"
    riyadh = {int(r["month"]): r for r in _rows(out / "candidate/normals.csv") if r["city"] == "Riyadh"}
    assert riyadh[6]["station_id"] == "XQW00009001" and float(riyadh[6]["mean_tmax_c"]) > 39
    assert riyadh[7]["station_id"] == "XQW00000000"  # July falls to the next station, which says so
    assert all(r["station_id"] not in {"XQW00009002", "XQW00009003", "XQW00009004"} for r in riyadh.values())


def test_changed_input_bytes_refuse_the_build(tmp_path):
    world = _world(tmp_path)
    manifest_path = world.write()
    stations = world.dir / "ghcnd-stations.txt"
    stations.write_bytes(stations.read_bytes() + b"\n")
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_input_stations_changed"):
        gn.build_candidate(world.cities, manifest_path, world.dir, tmp_path / "out")


def test_fewer_than_ten_places_in_any_month_refuses_install(tmp_path):
    world = gf.Inputs(tmp_path, TWELVE)
    for index, name in enumerate(TWELVE):
        no_july = index < 3  # July: only nine places
        world.add(f"XQW0000{index:04d}", name, text=gf.station_text(
            f"XQW0000{index:04d}", _july_gap if no_july else _no_gap))
    out = tmp_path / "out"
    result = gn.build_candidate(world.cities, world.write(), world.dir, out)
    assert result["product"]["min_places_per_month"] == 9 and result["reasons"] == ["fewer_than_ten_places_in_some_month"]
    assert gn.admit(out / "candidate")["status"] == "ready"  # an honest candidate; just too small to install
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_candidate_fewer_than_ten_places"):
        gn.install_plan(out / "candidate", tmp_path / "data" / gn.INSTALLED_NAME)


def test_nine_places_total_is_refused_and_ten_is_accepted(tmp_path):
    for count, ok in ((9, False), (10, True)):
        world = _world(tmp_path / str(count), TWELVE[:count])
        out = tmp_path / str(count) / "out"
        gn.build_candidate(world.cities, world.write(), world.dir, out)
        target = tmp_path / str(count) / "data" / gn.INSTALLED_NAME
        if ok:
            assert gn.install_plan(out / "candidate", target)["coverage"]["min_places_per_month"] == 10
        else:
            with pytest.raises(gn.GhcndNormalsError, match="ghcnd_candidate_fewer_than_ten_places"):
                gn.install_plan(out / "candidate", target)


def _rebind(candidate: Path, rows: list[dict]) -> None:
    gf.write_rows(candidate / "normals.csv", rows)
    manifest = json.loads((candidate / "manifest.json").read_text())
    body = (candidate / "normals.csv").read_bytes()
    manifest.update(csv_sha256=__import__("hashlib").sha256(body).hexdigest(), csv_bytes=len(body))
    (candidate / "manifest.json").write_text(json.dumps(manifest))


@pytest.mark.parametrize("change,reason", [
    ({"source_product": "meteostat-normals-point-v1"}, "mixed_products"),
    ({"period_start": "1981", "period_end": "2010"}, "wrong_period"),
    ({"years_used": "23"}, "insufficient_coverage"),
    ({"statistic": "monthly_record_maximum"}, "statistic_or_unit_invalid"),
    ({"distance_km": "40.1"}, "station_out_of_range"),
])
def test_admission_refuses_altered_rows(tmp_path, change, reason):
    world = _world(tmp_path)
    out = tmp_path / "out"
    gn.build_candidate(world.cities, world.write(), world.dir, out)
    rows = _rows(out / "candidate/normals.csv")
    rows[5].update(change)
    _rebind(out / "candidate", rows)
    admission = gn.admit(out / "candidate")
    assert admission["status"] == "product_invalid" and reason in admission["reasons"]
    assert na.admit(out / "candidate")["reasons"] == admission["reasons"]  # the shared entry point dispatches


def test_mixed_products_never_share_a_file_or_an_install_target(tmp_path):
    world = _world(tmp_path)
    out = tmp_path / "out"
    gn.build_candidate(world.cities, world.write(), world.dir, out)
    candidate = out / "candidate"
    # The GHCND candidate never targets the Meteostat file ...
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_install_target_not_product_path"):
        na.install_plan(candidate, tmp_path / "data" / "normals.csv")
    # ... never replaces an installed file holding another product's rows ...
    holder = tmp_path / "data" / gn.INSTALLED_NAME
    gf.write_rows(holder, [{**gf.installed_rows(7)[0], "source_product": "meteostat-normals-point-v1"}])
    with pytest.raises(gn.GhcndNormalsError, match="ghcnd_install_target_holds_another_product"):
        gn.install_plan(candidate, holder)
    # ... the loader refuses a mixed file whole (no partial read) ...
    report: dict = {}
    mixed = gf.write_rows(tmp_path / "mixed" / gn.INSTALLED_NAME,
                          gf.installed_rows(7) + [{**gf.installed_rows(7)[0], "source_product": "x"}])
    assert gn.load_normals(mixed, report) == {} and report["status"] == "refused_mixed_products"
    # ... and a Meteostat candidate can never be planned into the GHCND file.
    with pytest.raises(na.NormalsError, match="normals_install_target_holds_another_product"):
        na.install_plan(tmp_path / "no-candidate", holder)


def test_install_plan_over_a_previous_ghcnd_file_retains_a_rollback(tmp_path):
    world = _world(tmp_path)
    out = tmp_path / "out"
    gn.build_candidate(world.cities, world.write(), world.dir, out)
    target = gf.write_rows(tmp_path / "data" / gn.INSTALLED_NAME, gf.installed_rows(7))
    before = target.read_bytes()
    plan = gn.install_plan(out / "candidate", target)
    assert plan["previous"]["sha256"] and Path(plan["rollback"]["retained_copy"]).read_bytes() == before
    assert target.read_bytes() == before
