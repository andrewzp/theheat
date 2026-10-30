"""W02 02.4-02.6: bounded threshold rebuild, package verification, upload plan, dependency contract.

Invented GHCN-shaped station/inventory/archive files ("ZZ" invented network);
fake release metadata and a fake HTTP session. Nothing downloads or uploads.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile
from typing import Any, cast

import pytest

from scripts import build_station_thresholds as cli
from scripts import threshold_artifacts as artifacts
from scripts import threshold_package
from src.data import acquisition_dependencies as deps
from src.data import ghcn_format
from src.data import threshold_rebuild as rebuild

ROOT = Path(__file__).resolve().parents[2]
STATIONS = 1050


def _sid(i: int) -> str:
    return f"ZZX{i:08d}"


def _dly(sid: str, element: str, base: int) -> str:
    values = "".join(f"{base + day:5d}  S" for day in range(31))
    return f"{sid}2025{7:02d}{element}{values}\n"


@pytest.fixture
def inputs(tmp_path):
    src = tmp_path / "inputs"
    src.mkdir()
    (src / "stations.txt").write_text("".join(
        f"{_sid(i)} {10 + i / 1000:8.4f} {20 + i / 1000:9.4f}  100.0    INVENTED STATION {i:<12d}\n"
        for i in range(STATIONS)))
    inventory = "".join(f"{_sid(i)} 10.0000  20.0000 {el} 1990 {2026 if i < STATIONS - 10 else 1999}\n"
                        for i in range(STATIONS) for el in ("TMAX", "TMIN"))
    (src / "inventory.txt").write_text(inventory)
    (src / "countries.txt").write_text("ZZ Invented Land\n")
    archive = src / "ghcnd_all.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for i in range(STATIONS):
            body = (_dly(_sid(i), "TMAX", 250 + i % 40) + _dly(_sid(i), "TMIN", 100 + i % 30)).encode()
            info = tarfile.TarInfo(f"ghcnd_all/{_sid(i)}.dly")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    paths = {"stations": src / "stations.txt", "inventory": src / "inventory.txt",
             "countries": src / "countries.txt", "archive": archive}
    return paths


def make_plan(paths, partitions=3):
    return rebuild.build_plan(stations=paths["stations"], inventory=paths["inventory"],
                              countries=paths["countries"], archive=paths["archive"],
                              snapshot_date="2026-10-01", partitions=partitions)


def test_plan_is_deterministic_with_exact_inputs_cutoff_qc_and_partitions(inputs, tmp_path):
    plan = make_plan(inputs)
    assert plan["plan_sha256"] == make_plan(inputs)["plan_sha256"]
    assert plan["active_stations"] == STATIONS - 10  # inventory last year below the cutoff stays inactive
    assert plan["comparison_before"] == plan["watermark_last_diff_date"] == "2026-10-01"
    assert plan["qc_policy"]["accepted_quality_flag"] == "blank" and plan["missing_inputs"] == []
    assert [p["stations"] for p in plan["partitions"]] == [347, 347, 346]
    assert plan["inputs"]["archive"]["sha256"] == hashlib.sha256(inputs["archive"].read_bytes()).hexdigest()
    missing = rebuild.build_plan(stations=inputs["stations"], inventory=inputs["inventory"],
                                 countries=inputs["countries"], archive=tmp_path / "absent.tar.gz",
                                 snapshot_date="2026-10-01", partitions=2)
    assert missing["missing_inputs"] == ["archive"]
    with pytest.raises(rebuild.RebuildError, match="inputs_missing"):
        rebuild.build_partitions(missing, paths=inputs, work_dir=tmp_path / "w")
    with pytest.raises(rebuild.RebuildError, match="snapshot_date_invalid"):
        rebuild.build_plan(stations=inputs["stations"], inventory=inputs["inventory"], countries=inputs["countries"],
                           archive=inputs["archive"], snapshot_date="2026-10-1", partitions=2)


def test_partitions_are_bounded_restartable_and_never_promoted_unfinished(inputs, tmp_path, monkeypatch):
    plan, work = make_plan(inputs), tmp_path / "work"
    first = rebuild.build_partitions(plan, paths=inputs, work_dir=work, select=[1])
    assert first["status"] == "incomplete" and first["counters"] == {"built": 1, "pending": 2, "complete": 1}
    assert rebuild.partition_state(plan, work) == {0: "pending", 1: "complete", 2: "pending"}

    real = ghcn_format.compute_thresholds
    seen = []

    def interrupt(*args, **kwargs):
        seen.append(1)
        if len(seen) == 400:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(rebuild, "compute_thresholds", interrupt)
    with pytest.raises(KeyboardInterrupt):
        rebuild.build_partitions(plan, paths=inputs, work_dir=work)
    assert rebuild.partition_state(plan, work) == {0: "pending", 1: "complete", 2: "pending"}
    assert not list(work.glob("*.building*"))

    ticks = iter([0.0] + [0.0] * 50 + [99.0] * 5000)
    monkeypatch.setattr(rebuild, "compute_thresholds", real)
    late = rebuild.build_partitions(plan, paths=inputs, work_dir=work, deadline_seconds=60, clock=lambda: next(ticks))
    assert late["status"] == "incomplete" and late["reasons"] == ["deadline"]
    assert rebuild.partition_state(plan, work)[0] == "pending" and not list(work.glob("*.building*"))

    done = rebuild.build_partitions(plan, paths=inputs, work_dir=work)
    assert done["status"] == "ready" and done["counters"]["built"] == 2

    def no_stream(*_a, **_k):
        raise AssertionError("complete partitions must not be rebuilt")

    monkeypatch.setattr(rebuild, "stream_station_obs_from_tar", no_stream)
    again = rebuild.build_partitions(plan, paths=inputs, work_dir=work)
    assert again["reasons"] == ["no_pending_partitions"]
    # a tampered partition is pending again, never trusted
    (work / "part-0002.sqlite").write_bytes(b"invented damage")
    assert rebuild.partition_state(plan, work)[2] == "pending"


def test_changed_input_after_plan_is_refused(inputs, tmp_path):
    plan = make_plan(inputs)
    inputs["inventory"].write_text(inputs["inventory"].read_text() + f"{_sid(1)} 1 1 PRCP 1990 2026\n")
    with pytest.raises(rebuild.RebuildError, match="inventory_changed_since_plan"):
        rebuild.build_partitions(plan, paths=inputs, work_dir=tmp_path / "w")


@pytest.fixture
def package(inputs, tmp_path):
    plan, work, out = make_plan(inputs), tmp_path / "work", tmp_path / "out"
    rebuild.build_partitions(plan, paths=inputs, work_dir=work)
    build = rebuild.assemble(plan, paths=inputs, work_dir=work, out_dir=out)
    return {"plan": plan, "build": build, "db": out / "station_thresholds.sqlite",
            "manifest": out / "station_thresholds.version", "asset": out / build["asset"]["name"],
            "build_manifest": out / "build-manifest.json", "out": out, "work": work, "inputs": inputs}


class FakeRelease:
    def __init__(self, rows=None, blobs=None):
        self.rows, self.blobs, self.calls = rows or [], blobs or {}, []

    def assets(self, tag):
        self.calls.append(("assets", tag))
        return self.rows

    def download(self, tag, name, directory):
        self.calls.append(("download", tag, name))
        (directory / name).write_bytes(self.blobs[name])

    def upload(self, *_a):  # pragma: no cover - must never be reached
        raise AssertionError("no upload in this campaign")


def _row(path: Path) -> dict:
    raw = path.read_bytes()
    return {"name": path.name, "state": "uploaded", "size": len(raw),
            "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}"}


def test_assembled_artifact_passes_the_actual_ensure_and_consumer_contract(package, tmp_path):
    build = package["build"]
    assert build["coverage"]["active_stations"] == STATIONS - 10
    assert build["coverage"]["active_with_thresholds"] == STATIONS - 10
    assert build["coverage"]["orphan_threshold_stations"] == 0
    manifest = artifacts.read_manifest(package["manifest"])
    assert manifest["last_diff_date"] == "2026-10-01" and manifest["format"] == "sqlite-gzip"
    verified = rebuild.verify_package(package["db"], package["manifest"], asset=package["asset"],
                                      build_manifest=package["build_manifest"])
    assert verified["status"] == "ready", verified["reasons"]
    assert verified["product"]["comparison_before"] == ["2026-10-01"]
    assert verified["product"]["coverage"]["consumer_threshold_rows_sha256"]
    # The workflow's actual `ensure` path downloads, expands and verifies the asset.
    cache = tmp_path / "cache" / "station_thresholds.sqlite"
    release = FakeRelease([_row(package["asset"])], {package["asset"].name: package["asset"].read_bytes()})
    assert artifacts.ensure_database(cache, manifest, cast(Any, release)) == "verified_download"
    assert cache.read_bytes() == package["db"].read_bytes()
    # Incremental lineage is now known instead of the legacy empty watermark.
    artifacts.pending_diff_dates(manifest["last_diff_date"], days=12,
                                 today=__import__("datetime").date(2026, 10, 9))
    # Reassembly into an existing output is refused rather than overwritten.
    with pytest.raises(rebuild.RebuildError, match="output_exists"):
        rebuild.assemble(package["plan"], paths=package["inputs"], work_dir=package["work"], out_dir=package["out"])


def test_wrong_asset_and_unrelated_sqlite_fail_before_use(package, tmp_path):
    other = tmp_path / package["asset"].name
    other.write_bytes(gzip.compress(b"invented other bytes", mtime=0))
    wrong = rebuild.verify_package(package["db"], package["manifest"], asset=other)
    assert wrong["status"] == "product_invalid" and wrong["reasons"] == ["threshold_asset_digest_mismatch"]
    renamed = tmp_path / "station_thresholds.sqlite.gz"
    renamed.write_bytes(package["asset"].read_bytes())
    assert rebuild.verify_package(package["db"], package["manifest"], asset=renamed)["reasons"] == [
        "threshold_asset_filename_mismatch"]
    # An unrelated SQLite file with enough rows and a manifest computed for it.
    unrelated = tmp_path / "unrelated" / "station_thresholds.sqlite"
    unrelated.parent.mkdir()
    with sqlite3.connect(unrelated) as conn:
        conn.executescript("CREATE TABLE stations(is_active INTEGER); CREATE TABLE thresholds(value INTEGER);"
                           "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
        conn.executemany("INSERT INTO stations VALUES(1)", [()] * 1000)
        conn.executemany("INSERT INTO thresholds VALUES(0)", [()] * 1000)
        conn.execute("INSERT INTO meta VALUES('last_diff_date','2026-10-01')")
    fields = {"release": "thresholds-latest", "sha256": artifacts.digest(unrelated)[0],
              "bytes": str(unrelated.stat().st_size), **artifacts.database_stats(unrelated)}
    manifest = unrelated.parent / "station_thresholds.version"
    manifest.write_text("".join(f"{k}={v}\n" for k, v in fields.items()))
    result = rebuild.verify_package(unrelated, manifest)
    assert result["status"] == "product_invalid" and result["reasons"] == ["threshold_schema_unrecognized"]
    # The real database with somebody else's manifest fails its digest first.
    assert rebuild.verify_package(package["db"], manifest)["reasons"] == ["threshold_database_digest_mismatch"]


def test_checked_in_legacy_manifest_and_empty_release_stay_unavailable(tmp_path):
    legacy = ROOT / "data" / "station_thresholds.version"
    fields = artifacts.read_manifest(legacy)
    assert (artifacts._asset(fields)[0], fields["bytes"], fields["last_diff_date"]) == (
        "station_thresholds.sqlite", "957243392", "")
    result = rebuild.verify_package(tmp_path / "absent.sqlite", legacy, release_assets={"assets": []})
    assert result["status"] == "source_absent"
    assert result["source"]["disposition"] == {"asset_count": 0, "release_empty": True,
                                               "state": "asset_absent_upload_required"}
    assert result["source"]["required_asset_bytes"] == 957243392
    with pytest.raises(artifacts.ArtifactError, match="threshold_baseline_asset_unavailable"):
        artifacts.ensure_database(tmp_path / "cache.sqlite", fields, cast(Any, FakeRelease([])))
    assert not (tmp_path / "cache.sqlite").exists()
    unknown = rebuild.verify_package(tmp_path / "absent.sqlite", legacy)
    assert unknown["source"]["disposition"] == {"state": "unknown_requires_owner_read"}


def test_upload_plan_is_explicit_never_executed_and_keeps_legacy_rollback(package, tmp_path, capsys):
    installed = tmp_path / "installed.version"
    installed.write_bytes((ROOT / "data" / "station_thresholds.version").read_bytes())
    verified = rebuild.verify_package(package["db"], package["manifest"], asset=package["asset"],
                                      release_assets={"assets": []})
    plan = rebuild.upload_plan(verified, asset=package["asset"], manifest_path=package["manifest"],
                               installed_manifest=installed)
    upload = next(step for step in plan["steps"] if step["action"] == "upload")
    assert plan["executed"] is False and "--clobber" not in upload["argv"]
    assert upload["argv"][:4] == ["gh", "release", "upload", "thresholds-latest"]
    assert plan["release_disposition"]["release_empty"] is True
    assert plan["rollback"]["previous_required_asset_bytes"] == 957243392
    conflict = dict(_row(package["asset"]), digest="sha256:" + "0" * 64)
    conflicted = rebuild.verify_package(package["db"], package["manifest"], asset=package["asset"],
                                        release_assets={"assets": [conflict]})
    with pytest.raises(rebuild.RebuildError, match="asset_identity_conflict"):
        rebuild.upload_plan(conflicted, asset=package["asset"], manifest_path=package["manifest"],
                            installed_manifest=installed)
    assert threshold_package.main(["upload-plan", "--db", str(package["db"]), "--manifest",
                                   str(package["manifest"]), "--asset", str(package["asset"]),
                                   "--installed-manifest", str(installed)]) == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False


class Response:
    def __init__(self, status, chunks, headers=None, fail_after=None):
        self.status_code, self.chunks, self.headers, self.fail_after = status, chunks, headers or {}, fail_after

    def iter_content(self, chunk_size):
        for i, chunk in enumerate(self.chunks):
            if self.fail_after is not None and i == self.fail_after:
                raise ConnectionError("invented reset")
            yield chunk


class Session:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


def test_archive_fetch_is_explicit_bounded_resumable_and_receipted(tmp_path):
    body = b"invented-archive-" * 64
    dest = tmp_path / "ghcnd_all.tar.gz"
    first = Response(200, [body[:300], body[300:]], {"Content-Length": str(len(body))}, fail_after=1)
    second = Response(206, [body[300:]], {"Content-Length": str(len(body) - 300),
                                          "Content-Range": f"bytes 300-{len(body) - 1}/{len(body)}",
                                          "Last-Modified": "Wed, 01 Oct 2026 00:00:00 GMT"})
    session = Session([first, second])
    result = rebuild.fetch_archive(dest, session=session, max_bytes=10_000, deadline_seconds=60, max_retries=1)
    assert result["status"] == "ready" and dest.read_bytes() == body
    assert session.requests[1][1]["headers"] == {"Range": "bytes=300-"}
    assert all(kw["allow_redirects"] is False for _, kw in session.requests)
    receipt = json.loads((tmp_path / "ghcnd_all.tar.gz.receipt.json").read_text())
    assert receipt["sha256"] == hashlib.sha256(body).hexdigest() and receipt["last_modified"].startswith("Wed")
    with pytest.raises(rebuild.RebuildError, match="archive_exists"):
        rebuild.fetch_archive(dest, session=Session([]), max_bytes=10_000, deadline_seconds=60, max_retries=0)
    big = rebuild.fetch_archive(tmp_path / "big.tar.gz", session=Session([Response(200, [], {"Content-Length": "99999"})]),
                                max_bytes=10_000, deadline_seconds=60, max_retries=0)
    assert big["status"] == "incomplete" and big["reasons"] == ["byte_limit"]
    gone = rebuild.fetch_archive(tmp_path / "gone.tar.gz", session=Session([Response(404, [])]), max_bytes=10_000,
                                 deadline_seconds=60, max_retries=0)
    assert gone["status"] == "source_absent"
    with pytest.raises(rebuild.RebuildError, match="unexpected_status"):
        rebuild.fetch_archive(tmp_path / "moved.tar.gz", session=Session([Response(302, [])]), max_bytes=10_000,
                              deadline_seconds=60, max_retries=0)


def test_cli_end_to_end_plan_build_assemble_then_package_verify(inputs, tmp_path, capsys):
    common = [f"--{k}={v}" for k, v in inputs.items()]
    plan_path, work, out = tmp_path / "plan.json", tmp_path / "work", tmp_path / "out"
    assert cli.main(["plan", *common, "--snapshot-date", "2026-10-01", "--partitions", "2",
                     "--output", str(plan_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert cli.main(["build", *common, "--plan", str(plan_path), "--work-dir", str(work), "--partition", "0",
                     "--deadline-seconds", "600"]) == 1
    capsys.readouterr()
    assert cli.main(["assemble", *common, "--plan", str(plan_path), "--work-dir", str(work), "--out-dir", str(out)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "threshold_partitions_incomplete"
    assert cli.main(["build", *common, "--plan", str(plan_path), "--work-dir", str(work),
                     "--deadline-seconds", "600"]) == 0
    capsys.readouterr()
    assert cli.main(["assemble", *common, "--plan", str(plan_path), "--work-dir", str(work), "--out-dir", str(out)]) == 0
    assembled = json.loads(capsys.readouterr().out)
    asset = out / assembled["product"]["asset"]["name"]
    assert threshold_package.main(["verify", "--db", str(out / "station_thresholds.sqlite"), "--manifest",
                                   str(out / "station_thresholds.version"), "--asset", str(asset),
                                   "--build-manifest", str(out / "build-manifest.json")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_dependency_manifest_distinguishes_unavailable_incompatible_and_available():
    rows = deps.read_manifest()
    assert {row["tool"] for row in rows} == {"normals", "thresholds"}
    assert next(r for r in rows if r["name"] == "meteostat")["spec"] == ">=1.6,<2"

    class Module:
        Normals = Point = staticmethod(lambda *a: None)

    absent = deps.check("normals", installed=lambda name: None)
    old_major = deps.check("normals", installed=lambda name: "2.0.1")
    no_api = deps.check("normals", installed=lambda name: "1.6.8", importer=lambda name: object())
    broken = deps.check("normals", installed=lambda name: "1.6.8",
                        importer=lambda name: (_ for _ in ()).throw(ImportError("invented")))
    good = deps.check("normals", installed=lambda name: "1.6.8", importer=lambda name: Module)
    assert [absent["status"], old_major["status"], no_api["status"], broken["status"], good["status"]] == [
        "unavailable", "incompatible", "incompatible", "incompatible", "available"]
    assert no_api["requirements"][0]["missing_api"] == ["Normals", "Point"]
    assert deps.dependency_status(absent) == "dependency_unavailable"
    assert deps.dependency_status(old_major) == "dependency_incompatible"
    assert deps.dependency_status(good) is None
    assert deps.satisfies("1.10.0", ">=1.6,<2") and not deps.satisfies("1.5.9", ">=1.6,<2")
    with pytest.raises(deps.AcquisitionError, match="tool_unknown"):
        deps.check("unknown-tool")


def test_dependency_manifest_refuses_unknown_syntax(tmp_path):
    bad = tmp_path / "requirements-acquisition.txt"
    bad.write_text("meteostat @ https://invented.example/x.whl  # tool=normals\n")
    with pytest.raises(deps.AcquisitionError, match="manifest_invalid"):
        deps.read_manifest(bad)
