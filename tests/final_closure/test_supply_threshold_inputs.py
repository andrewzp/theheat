"""A2: byte-pinned NOAA GHCN-Daily inputs -> verified package -> guarded manifest install -> ensure.

A loopback server imitates the NCEI directory index, ``ghcnd-version.txt`` and
small invented ("ZZ" network) station/inventory/country files and archive. The
real CLI, bounded transport, range-resumable archive fetch, rebuild, package
verification and the bot's ``threshold_artifacts.ensure_database`` consumer
run unmodified. Nothing is uploaded; the release is an operator-saved JSON.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import random
import tarfile
from typing import Any, cast

import pytest
import requests

from scripts import build_station_thresholds as cli
from scripts import threshold_artifacts as artifacts
from src.data import threshold_rebuild as rebuild
from tests.final_closure import supply_http_fixture as fx
from tests.remaining_campaign.test_w02_threshold_rebuild import STATIONS, FakeRelease, _dly, _sid

FAST = {"poll_seconds": 0.05, "backoff_seconds": 0.01, "connect_wait": 2.0}
VERSION = (b"The current version of GHCN Daily is 3.35-upd-2026102817 (i.e, an update that started at "
           b"2026102817 [yyyymmddhh] UTC),\ncreated by appending recent updates to the last fully reprocessed "
           b"version: 3.35-por-2026102323.\n")
PREFIX = "/pub/data/ghcn/daily/"


def _files() -> dict[str, bytes]:
    stations = "".join(f"{_sid(i)} {10 + i / 1000:8.4f} {20 + i / 1000:9.4f}  100.0    INVENTED STATION {i:<12d}\n"
                       for i in range(STATIONS)).encode()
    inventory = "".join(f"{_sid(i)} 10.0000  20.0000 {el} 1990 {2026 if i < STATIONS - 10 else 1999}\n"
                        for i in range(STATIONS) for el in ("TMAX", "TMIN")).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for i in range(STATIONS):
            body = (_dly(_sid(i), "TMAX", 250 + i % 40) + _dly(_sid(i), "TMIN", 100 + i % 30)).encode()
            info = tarfile.TarInfo(f"ghcnd_all/{_sid(i)}.dly")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
        # An incompressible non-station member makes the archive span several 1 MiB fetch chunks,
        # so a dropped transfer leaves real bytes to resume from.
        padding = random.Random(7).randbytes(3_000_000)
        info = tarfile.TarInfo("ghcnd_all/invented-padding.bin")
        info.size = len(padding)
        tar.addfile(info, io.BytesIO(padding))
    return {"ghcnd-version.txt": VERSION, "ghcnd-countries.txt": b"ZZ Invented Land\n",
            "ghcnd-stations.txt": stations, "ghcnd-inventory.txt": inventory, "ghcnd_all.tar.gz": buffer.getvalue()}


def _listing(files: dict[str, bytes], *, omit: str | None = None) -> bytes:
    rows = "".join(f'<tr>\n<td><a href="{name}">{name}</a></td>\n<td align="right">2026-10-29 22:15</td>\n'
                   f'<td align="right">{len(body)}</td>\n<td> </td>\n</tr>\n'
                   for name, body in sorted(files.items()) if name != omit)
    return f"<html><body><table>\n{rows}</table></body></html>".encode()


@pytest.fixture
def noaa():
    server = fx.Fixture()
    files = _files()
    server.route(PREFIX, fx.ok(_listing(files)))
    for name, body in files.items():
        if name != "ghcnd_all.tar.gz":
            server.route(PREFIX + name, fx.ok(body))
    archive = files["ghcnd_all.tar.gz"]
    # The first transfer drops after 40%; the resume must carry If-Range and get the same entity.
    server.route(PREFIX + "ghcnd_all.tar.gz", fx.truncated(archive, len(archive) * 2 // 5, '"e1"'),
                 fx.ranged(archive, '"e1"'))
    cast(Any, server).files = files
    yield server
    server.close()


def run(argv, server, capsys, **kwargs):
    code = cli.main(argv, base_url=f"{server.origin}{PREFIX}", transport_options=FAST,
                    session_factory=requests.Session, **kwargs)
    out = capsys.readouterr().out
    return code, json.loads(out)


def _release(asset: Path, *, digest: str | None = None) -> dict:
    raw = asset.read_bytes()
    return {"assets": [{"name": asset.name, "state": "uploaded", "size": len(raw),
                        "digest": digest or f"sha256:{hashlib.sha256(raw).hexdigest()}"}]}


def test_resolve_fetch_package_install_then_the_bot_consumer_verifies(tmp_path, noaa, capsys):
    plan_path, inputs, work, out = tmp_path / "fetch-plan.json", tmp_path / "inputs", tmp_path / "work", tmp_path / "out"
    code, resolved = run(["resolve-inputs", "--output", str(plan_path)], noaa, capsys)
    assert code == 0 and resolved["status"] == "planned"
    assert resolved["source"]["source_version"] == "3.35-upd-2026102817"
    assert resolved["product"]["suggested_snapshot_date"] == "2026-10-24"  # update start minus 4-day lag
    assert resolved["counters"]["transport"]["physical_requests"] == 2  # index + version only
    plan = json.loads(plan_path.read_text())
    assert {a["bytes"] for a in plan["assets"].values()} == {len(b) for b in noaa.files.values()}

    code, fetched = run(["fetch-inputs", "--fetch-plan", str(plan_path), "--dest", str(inputs),
                         "--deadline-seconds", "60", "--max-retries", "2"], noaa, capsys)
    assert code == 0 and fetched["status"] == "ready"
    archive_requests = [h for (_t, p), h in zip(noaa.requests, noaa.request_headers) if p.endswith("ghcnd_all.tar.gz")]
    assert len(archive_requests) == 2 and archive_requests[1]["if-range"] == '"e1"'
    assert archive_requests[1]["range"].startswith("bytes=")
    manifest = json.loads((inputs / "inputs-manifest.json").read_text())
    assert manifest["source_version"]["version"] == "3.35-upd-2026102817"
    for role, entry in manifest["inputs"].items():
        assert entry["sha256"] == hashlib.sha256(noaa.files[entry["name"]]).hexdigest()

    installed = tmp_path / "installed" / "station_thresholds.version"
    installed.parent.mkdir()
    legacy = (Path(__file__).resolve().parents[2] / "data/station_thresholds.version").read_bytes()
    installed.write_bytes(legacy)
    code, packaged = run(["package", "--inputs", str(inputs), "--work-dir", str(work), "--out-dir", str(out),
                          "--partitions", "2", "--deadline-seconds", "600", "--installed-manifest", str(installed)],
                         noaa, capsys)
    assert code == 0 and packaged["status"] == "ready"
    product = packaged["product"]
    assert product["snapshot_date"] == "2026-10-24"
    build = json.loads((out / "build-manifest.json").read_text())
    assert build["source_version"]["version"] == "3.35-upd-2026102817"
    upload = product["upload_plan"]
    assert upload["executed"] is False and any(step["action"] == "upload" for step in upload["steps"])
    assert product["install_command"][2] == "install-manifest"
    # Re-running package is resumable and reproduces the same verified package.
    code, again = run(["package", "--inputs", str(inputs), "--work-dir", str(work), "--out-dir", str(out),
                       "--partitions", "2", "--deadline-seconds", "600", "--installed-manifest", str(installed)],
                      noaa, capsys)
    assert code == 0 and again["product"]["asset"] == product["asset"]

    asset = out / product["asset"]["name"]
    release = tmp_path / "release.json"
    # Before the asset is verifiably on the release, the old manifest stays installed.
    release.write_text(json.dumps({"assets": []}))
    code, refused = run(["install-manifest", "--manifest", str(out / "station_thresholds.version"),
                         "--build-manifest", str(out / "build-manifest.json"), "--release-assets", str(release),
                         "--installed", str(installed)], noaa, capsys)
    assert code == 2 and refused["error"] == "threshold_install_requires_verified_remote_asset"
    assert installed.read_bytes() == legacy
    release.write_text(json.dumps(_release(asset, digest="sha256:" + "0" * 64)))
    code, refused = run(["install-manifest", "--manifest", str(out / "station_thresholds.version"),
                         "--build-manifest", str(out / "build-manifest.json"), "--release-assets", str(release),
                         "--installed", str(installed)], noaa, capsys)
    assert code == 2 and installed.read_bytes() == legacy
    release.write_text(json.dumps(_release(asset)))
    code, done = run(["install-manifest", "--manifest", str(out / "station_thresholds.version"),
                      "--build-manifest", str(out / "build-manifest.json"), "--release-assets", str(release),
                      "--installed", str(installed)], noaa, capsys)
    assert code == 0 and done["status"] == "installed"
    assert Path(done["previous"]["retained_copy"]).read_bytes() == legacy
    # The bot's own ensure step now resolves the baseline (threshold_baseline_unavailable cleared).
    manifest_fields = artifacts.read_manifest(installed)
    cache = tmp_path / "cache" / "station_thresholds.sqlite"
    fake = FakeRelease(rows=_release(asset)["assets"], blobs={asset.name: asset.read_bytes()})
    assert artifacts.ensure_database(cache, manifest_fields, cast(Any, fake)) == "verified_download"
    # With the legacy manifest the same consumer refuses: the release has no such asset.
    with pytest.raises(artifacts.ArtifactError, match="threshold_baseline_asset_unavailable"):
        artifacts.ensure_database(tmp_path / "other.sqlite", artifacts.read_manifest(
            Path(done["previous"]["retained_copy"])), cast(Any, FakeRelease()))


def test_a_version_change_between_resolve_and_fetch_refuses_the_input_set(tmp_path, noaa, capsys):
    plan_path = tmp_path / "fetch-plan.json"
    assert run(["resolve-inputs", "--output", str(plan_path)], noaa, capsys)[0] == 0
    noaa.route(PREFIX + "ghcnd-version.txt", fx.ok(VERSION.replace(b"2026102817", b"2026102917")))
    code, refused = run(["fetch-inputs", "--fetch-plan", str(plan_path), "--dest", str(tmp_path / "in"),
                         "--deadline-seconds", "30", "--max-retries", "0"], noaa, capsys)
    assert code == 2 and refused["error"] == "threshold_version_changed_since_plan"
    assert not (tmp_path / "in/inputs-manifest.json").exists()


def test_an_archive_other_than_the_planned_bytes_is_rejected_not_promoted(tmp_path, noaa, capsys):
    plan_path = tmp_path / "fetch-plan.json"
    assert run(["resolve-inputs", "--output", str(plan_path)], noaa, capsys)[0] == 0
    other = noaa.files["ghcnd_all.tar.gz"][:-100]
    noaa.route(PREFIX + "ghcnd_all.tar.gz", fx.ok(other))
    code, outcome = run(["fetch-inputs", "--fetch-plan", str(plan_path), "--dest", str(tmp_path / "in"),
                         "--deadline-seconds", "30", "--max-retries", "0"], noaa, capsys)
    assert code == 1 and outcome["status"] == "product_invalid"
    assert outcome["reasons"] == ["archive_size_differs_from_plan"]
    assert (tmp_path / "in/ghcnd_all.tar.gz.rejected").exists() and not (tmp_path / "in/ghcnd_all.tar.gz").exists()
    assert not (tmp_path / "in/inputs-manifest.json").exists()


def test_a_dataset_update_during_the_archive_transfer_is_not_bound(tmp_path, noaa, capsys):
    plan_path = tmp_path / "fetch-plan.json"
    assert run(["resolve-inputs", "--output", str(plan_path)], noaa, capsys)[0] == 0
    newer = VERSION.replace(b"2026102817", b"2026102917")
    noaa.route(PREFIX + "ghcnd-version.txt", fx.ok(VERSION), fx.ok(newer))
    code, outcome = run(["fetch-inputs", "--fetch-plan", str(plan_path), "--dest", str(tmp_path / "in"),
                         "--deadline-seconds", "60", "--max-retries", "2"], noaa, capsys)
    assert code == 1 and outcome["reasons"] == ["version_changed_during_fetch"]
    assert not (tmp_path / "in/inputs-manifest.json").exists()


def test_changed_inputs_after_fetch_and_tampered_plans_refuse(tmp_path, noaa, capsys):
    plan_path, inputs = tmp_path / "fetch-plan.json", tmp_path / "inputs"
    assert run(["resolve-inputs", "--output", str(plan_path)], noaa, capsys)[0] == 0
    assert run(["fetch-inputs", "--fetch-plan", str(plan_path), "--dest", str(inputs), "--deadline-seconds", "60",
                "--max-retries", "2"], noaa, capsys)[0] == 0
    (inputs / "ghcnd-countries.txt").write_bytes(b"ZZ Altered Land\n")
    with pytest.raises(rebuild.RebuildError, match="countries_changed_since_fetch"):
        rebuild.verify_inputs(inputs)
    plan = json.loads(plan_path.read_text())
    plan["assets"]["archive"]["bytes"] += 1
    with pytest.raises(rebuild.RebuildError, match="fetch_plan_invalid_or_altered"):
        rebuild._check_fetch_plan(plan)


def test_resolution_refuses_an_index_without_every_primary_asset(tmp_path, noaa, capsys):
    noaa.route(PREFIX, fx.ok(_listing(noaa.files, omit="ghcnd-inventory.txt")))
    code, refused = run(["resolve-inputs", "--output", str(tmp_path / "plan.json")], noaa, capsys)
    assert code == 2 and refused["error"] == "threshold_listing_asset_missing"
    assert rebuild.parse_version(VERSION)["update_started_at"] == "2026-10-28T17:00:00Z"
    with pytest.raises(rebuild.RebuildError, match="version_unrecognized"):
        rebuild.parse_version(b"no version here")
