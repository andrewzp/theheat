"""W02 02.1-02.3: normals plan, bounded resumable acquisition, admission and install plan.

Invented values only. Provider responses are Meteostat-shaped in-memory frames;
no meteostat import, network, or write to the installed baseline happens.
"""

from __future__ import annotations

import copy
import csv
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from scripts import build_normals
from src.data import acquisition_dependencies as deps
from src.data import normals_acquisition as na
from src.data import open_meteo
from src.editorial import hot10_contract
from tests import live_content_harness as h

ROOT = Path(__file__).resolve().parents[2]
UNAVAILABLE = {"tool": "normals", "status": "unavailable", "requirements": [
    {"name": "meteostat", "required": ">=1.6,<2", "installed": None, "api": ["Normals", "Point"],
     "state": "unavailable"}]}


class Frame:
    """The attributes of a Meteostat ``Normals.fetch()`` frame that the adapter reads."""

    def __init__(self, tmax: dict[int, float | None], columns=("prcp", "tmax", "tmin")):
        self.tmax, self.columns = tmax, list(columns)
        self.empty = not tmax

    def iterrows(self):
        for month, value in self.tmax.items():
            yield month, {"tmax": value, "tmin": None}


class Provider:
    name, version = "meteostat", "1.6.8-invented"

    def __init__(self, script=None):
        self.calls: list[tuple] = []
        self.script = script or (lambda lat, lon, start, end, n: Frame({m: 20.0 + m for m in range(1, 13)}))

    def fetch(self, lat, lon, start, end):
        self.calls.append((lat, lon, start, end))
        return self.script(lat, lon, start, end, len(self.calls))


def limits(**overrides):
    values = {"max_requests": 100, "max_bytes": 1_000_000, "deadline_seconds": 60, "max_retries": 1}
    return na.Limits(**{**values, **overrides})


def world(tmp_path, names=("Riyadh", "Cairo", "Lima"), installed: str | None = "legacy"):
    cities = tmp_path / "cities.csv"
    h.write_catalogue(cities, list(names))
    installed_path = tmp_path / "installed" / "normals.csv"
    installed_path.parent.mkdir()
    if installed == "legacy":
        installed_path.write_text("city,month,avg_high_c\nInventedtown,1,21.5\nInventedtown,2,22.5\n")
    plan = na.build_plan(cities, installed_path, dependency=UNAVAILABLE)
    return cities, installed_path, plan


def test_plan_on_checked_in_files_names_legacy_csv_and_exact_universe():
    first = na.build_plan(ROOT / "data/cities.csv", ROOT / "data/normals.csv", dependency=UNAVAILABLE)
    second = na.build_plan(ROOT / "data/cities.csv", ROOT / "data/normals.csv", dependency=None)
    assert first["plan_sha256"] == second["plan_sha256"]  # dependency/env never changes plan identity
    baseline = first["baseline"]
    assert baseline["format"] == "legacy_name_only" and baseline["loader_accepted_point_months"] == 0
    assert baseline["missing_columns"] and "sampling_point_id" in baseline["missing_columns"]
    assert "never relabelled" in baseline["explanation"]
    assert first["universe"]["points"] == len(na.load_universe(ROOT / "data/cities.csv"))
    assert first["missing"]["point_months"] == first["universe"]["point_months"] == first["universe"]["points"] * 12
    assert first["next_command"][2:4] == ["acquire", "--plan"] and "--max-requests" in first["next_command"]
    outcome = na.plan_result(first)
    assert outcome["status"] == "dependency_unavailable"
    assert outcome["source_health"]["error"] == "dependency_unavailable: meteostat unavailable"
    assert outcome["source_health"]["error_class"] == "dependency"
    assert "installed_baseline_legacy_name_only" in outcome["reasons"]
    # the real loader refuses every legacy row
    assert open_meteo.load_normals(str(ROOT / "data/normals.csv")) == {}


def test_plan_credits_existing_qualified_rows_and_lists_only_missing(tmp_path):
    cities, installed, _ = world(tmp_path, installed=None)
    rows = h.normal_rows(7, cities=[("Riyadh", "Asia/Riyadh", 1.0)]) + h.normal_rows(8, cities=[("Riyadh", "Asia/Riyadh", 1.0)])
    h.write_normals(installed, rows)
    plan = na.build_plan(cities, installed, months=[7, 8, 9])
    by_city = {point["city"]: point for point in plan["points"]}
    assert by_city["Riyadh"]["qualified_months"] == [7, 8] and by_city["Riyadh"]["missing_months"] == [9]
    assert by_city["Cairo"]["missing_months"] == [7, 8, 9]
    assert plan["baseline"]["format"] == "qualified_point_normals"
    assert plan["missing"] == {"points": 3, "point_months": 7}
    assert na.plan_result(plan)["status"] == "planned"


def test_altered_plan_or_moved_baseline_is_refused(tmp_path):
    _, installed, plan = world(tmp_path)
    altered = copy.deepcopy(plan)
    altered["months"] = [1]
    with pytest.raises(na.NormalsError, match="normals_plan_altered"):
        na.acquire(altered, tmp_path / "out", Provider(), limits(), installed_path=installed)
    installed.write_text("city,month,avg_high_c\nInventedtown,1,30.0\n")
    with pytest.raises(na.NormalsError, match="baseline_changed_since_plan"):
        na.acquire(plan, tmp_path / "out", Provider(), limits(), installed_path=installed)


def test_transport_failures_resume_only_pending_points_without_touching_installed(tmp_path):
    _, installed, plan = world(tmp_path)
    before = installed.read_bytes()
    lima = next(p for p in plan["points"] if p["city"] == "Lima")

    def flaky(lat, lon, start, end, n):
        if (lat, lon) == (lima["lat"], lima["lon"]):
            raise ConnectionError("invented reset")
        if start == 1991 and lat < 0:
            return Frame({})
        return Frame({m: 25.0 for m in range(1, 13)})

    first = Provider(flaky)
    out = tmp_path / "out"
    result = na.acquire(plan, out, first, limits(max_retries=1), installed_path=installed)
    assert result["status"] == "incomplete" and result["reasons"] == ["transport_failures_remaining"]
    assert not (out / "candidate").exists()
    journal = json.loads((out / "journal.json").read_text())
    assert journal["failures"][f"{lima['place_id']}-{lima['sampling_point_id']}"]["attempts"] == 2
    assert installed.read_bytes() == before
    assert result["source_health"]["status"] == "degraded"

    second = Provider(lambda lat, lon, start, end, n: Frame({} if start == 1991 else {m: 19.0 for m in range(1, 13)}))
    result = na.acquire(plan, out, second, limits(), installed_path=installed)
    assert result["status"] == "ready"
    assert {(c[0], c[1]) for c in second.calls} == {(lima["lat"], lima["lon"])}  # only the pending point
    assert [c[2:] for c in second.calls] == [(1991, 2020), (1961, 1990)]  # explicit fallback, both recorded
    rows = list(csv.DictReader((out / "candidate/normals.csv").open()))
    assert len(rows) == 36 and installed.read_bytes() == before
    lima_rows = [r for r in rows if r["city"] == "Lima"]
    assert {(r["period_start"], r["period_end"]) for r in lima_rows} == {("1961", "1990")}
    assert json.loads((out / "journal.json").read_text())["runs"][-1]["resumed"] == 2


@pytest.mark.parametrize("override,reason", [
    ({"max_requests": 1}, "request_limit"),
    ({"max_bytes": 10}, "byte_limit"),
])
def test_explicit_limits_stop_without_promoting(tmp_path, override, reason):
    _, installed, plan = world(tmp_path)
    result = na.acquire(plan, tmp_path / "out", Provider(), limits(**override), installed_path=installed)
    assert result["status"] == "incomplete" and result["reasons"] == [reason]
    assert not (tmp_path / "out/candidate").exists()


def test_deadline_is_checked_before_every_request(tmp_path):
    _, installed, plan = world(tmp_path)
    ticks = iter([0.0, 1.0, 61.0, 61.0, 61.0])
    provider = Provider()
    result = na.acquire(plan, tmp_path / "out", provider, limits(deadline_seconds=60), installed_path=installed,
                        clock=lambda: next(ticks))
    assert result["reasons"] == ["deadline"] and len(provider.calls) == 1


def test_interruption_keeps_completed_partitions_and_discards_torn_writes(tmp_path):
    _, installed, plan = world(tmp_path)

    def interrupt(lat, lon, start, end, n):
        if n == 2:
            raise KeyboardInterrupt
        return Frame({m: 22.0 for m in range(1, 13)})

    out = tmp_path / "out"
    with pytest.raises(KeyboardInterrupt):
        na.acquire(plan, out, Provider(interrupt), limits(), installed_path=installed)
    journal = json.loads((out / "journal.json").read_text())
    assert journal["runs"][-1]["status"] == "incomplete" and journal["runs"][-1]["reasons"] == ["interrupted"]
    assert len(list((out / "partitions").glob("*.json"))) == 1
    torn = out / "partitions" / ".torn.json.123.tmp"
    torn.write_text("{")
    resumed = Provider()
    result = na.acquire(plan, out, resumed, limits(), installed_path=installed)
    assert result["status"] == "ready" and len(resumed.calls) == 2 and not torn.exists()


def test_incomplete_and_invalid_products_are_reported_never_admitted(tmp_path):
    _, installed, plan = world(tmp_path)
    cairo = next(p for p in plan["points"] if p["city"] == "Cairo")
    lima = next(p for p in plan["points"] if p["city"] == "Lima")

    def script(lat, lon, start, end, n):
        if (lat, lon) == (cairo["lat"], cairo["lon"]):
            return Frame({m: 30.0 for m in range(1, 12)})  # December absent from the source
        if (lat, lon) == (lima["lat"], lima["lon"]):
            return Frame({1: 99.0})  # physically implausible
        return Frame({m: 30.0 for m in range(1, 13)})

    result = na.acquire(plan, tmp_path / "out", Provider(script), limits(), installed_path=installed)
    manifest = json.loads((tmp_path / "out/candidate/manifest.json").read_text())
    assert result["status"] == "ready" and manifest["rows"] == 12
    assert sorted(m["status"] for m in manifest["missing_points"]) == ["incomplete_source", "invalid_product"]
    assert result["reasons"] == ["points_without_source_data"]


def test_no_source_data_anywhere_is_source_absent(tmp_path):
    _, installed, plan = world(tmp_path)
    result = na.acquire(plan, tmp_path / "out", Provider(lambda *a: None), limits(), installed_path=installed)
    assert result["status"] == "source_absent" and result["source_health"]["error_class"] == "source_absent"


@pytest.fixture
def admitted(tmp_path):
    _, installed, plan = world(tmp_path)
    out = tmp_path / "out"
    na.acquire(plan, out, Provider(), limits(), installed_path=installed)
    return out / "candidate", installed


def _rewrite(candidate: Path, mutate, *, rebind=True):
    rows = list(csv.DictReader((candidate / "normals.csv").open()))
    header = list(na.FIELDS)
    rows, header = mutate(rows, header)
    with (candidate / "normals.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    if rebind:
        manifest = json.loads((candidate / "manifest.json").read_text())
        body = (candidate / "normals.csv").read_bytes()
        manifest.update(csv_sha256=na._sha(body), csv_bytes=len(body))
        (candidate / "manifest.json").write_text(json.dumps(manifest))


@pytest.mark.parametrize("mutate,rebind,reason", [
    (lambda rows, header: (rows + [rows[0]], header), True, "duplicate_point_month"),
    (lambda rows, header: ([{**r, "period_start": "1981", "period_end": "2010"} if i == 0 else r
                            for i, r in enumerate(rows)], header), True, "row_provenance_invalid"),
    (lambda rows, header: ([{**r, "retrieved_at": "2020-01-01T00:00:00Z"} if i == 0 else r
                            for i, r in enumerate(rows)], header), True, "altered_provenance"),
    (lambda rows, header: (rows[1:], header), True, "incomplete_period"),
    (lambda rows, header: ([{**r, "avg_high_c": "26.5"} if i == 0 else r for i, r in enumerate(rows)], header),
     True, "altered_provenance"),
    (lambda rows, header: ([{**r, "avg_high_c": "26.5"} if i == 0 else r for i, r in enumerate(rows)], header),
     False, "candidate_csv_not_bound_by_manifest"),
    (lambda rows, header: ([{**r, "extra": "x"} for r in rows], header + ["extra"]), True,
     "candidate_schema_incompatible"),
])
def test_admission_refuses_each_counterexample(admitted, mutate, rebind, reason):
    candidate, _ = admitted
    assert na.admit(candidate, partitions_dir=candidate.parent / "partitions")["status"] == "ready"
    _rewrite(candidate, mutate, rebind=rebind)
    result = na.admit(candidate, partitions_dir=candidate.parent / "partitions")
    assert result["status"] == "product_invalid" and reason in result["reasons"]


def test_admitted_candidate_is_what_the_actual_loader_and_hot10_contract_consume(tmp_path):
    now = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    names = [name for name, _zone, _kind in h.CITIES]
    _, installed, plan = world(tmp_path, names=names)
    out = tmp_path / "out"
    provider = Provider(lambda *a: Frame({m: h.NORMAL_C for m in range(1, 13)}))
    assert na.acquire(plan, out, provider, limits(max_requests=200), installed_path=installed)["status"] == "ready"
    admission = na.admit(out / "candidate", partitions_dir=out / "partitions")
    assert admission["status"] == "ready" and admission["product"]["loader_accepted_point_months"] == 12 * len(names)
    normals = open_meteo.load_normals(str(out / "candidate/normals.csv"))
    qualified = hot10_contract.qualify(h.city_temps(now), normals, sampled=len(names), now=now)
    assert qualified["complete"] and len(qualified["rows"]) == hot10_contract.SIZE
    assert all(row["baseline"]["source_product"] == na.PRODUCT for row in qualified["rows"])
    legacy = hot10_contract.qualify(h.city_temps(now), open_meteo.load_normals(str(installed)), sampled=len(names),
                                    now=now)
    assert not legacy["complete"]


def test_install_plan_compares_identity_and_retains_rollback_without_installing(tmp_path):
    cities, installed, _ = world(tmp_path, installed=None)
    h.write_normals(installed, h.normal_rows(1, cities=[("Riyadh", "Asia/Riyadh", 1.0)]))
    plan = na.build_plan(cities, installed, months=[1, 2])
    out = tmp_path / "out"
    na.acquire(plan, out, Provider(lambda *a: Frame({1: 18.0, 2: 19.0})), limits(), installed_path=installed)
    before = installed.read_bytes()
    report = na.install_plan(out / "candidate", installed)
    assert installed.read_bytes() == before
    assert report["previous"]["sha256"] == (na.file_identity(installed) or {})["sha256"]
    assert report["comparison"] == {"added": 5, "removed": 0, "changed": 0, "unchanged": 1, "largest_changes": []}
    assert Path(report["rollback"]["retained_copy"]).read_bytes() == before
    assert report["install"]["performed_by"] == "root"
    installed.write_bytes(before + b"\n")
    with pytest.raises(na.NormalsError, match="changed_since_plan"):
        na.install_plan(out / "candidate", installed)


def test_cli_refuses_missing_dependency_and_runs_with_an_explicit_provider(tmp_path, monkeypatch, capsys):
    _, installed, _ = world(tmp_path)
    plan_path = tmp_path / "plan.json"
    cities = tmp_path / "cities.csv"
    monkeypatch.setattr(build_normals.deps, "check", lambda tool: UNAVAILABLE)
    assert build_normals.main(["plan", "--cities", str(cities), "--installed", str(installed),
                               "--output", str(plan_path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "dependency_unavailable"
    args = ["acquire", "--plan", str(plan_path), "--out-dir", str(tmp_path / "out"), "--installed", str(installed),
            "--max-requests", "10", "--max-bytes", "100000", "--deadline-seconds", "60", "--max-retries", "0"]
    assert build_normals.main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "dependency_unavailable"
    assert not (tmp_path / "out").exists()
    assert build_normals.main(args, provider_factory=Provider) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert build_normals.main(["admit", "--candidate", str(tmp_path / "out/candidate")]) == 0
    capsys.readouterr()
    assert build_normals.main(args[:-2] + ["--max-retries", "9"], provider_factory=Provider) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "normals_limit_invalid"


def test_tool_result_lands_in_existing_source_health_shape():
    from src.state import DEFAULT_STATE

    state = copy.deepcopy(DEFAULT_STATE)
    outcome = deps.result("normals", "source_absent", reasons=["points_without_source_data"], observed=24)
    deps.record_acquisition_health(state, outcome, timestamp="2026-10-29T00:00:00Z")
    run = state["source_health"]["acquisition:normals"]["runs"][-1]
    assert run["status"] == "failed" and run["error_class"] == "source_absent" and run["observed"] == 24
    with pytest.raises(deps.AcquisitionError):
        deps.record_acquisition_health(state, {"schema": "other"})
