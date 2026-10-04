"""Invented SQLite/HTTP fixtures. Never upload or download a real release asset."""

from datetime import date
import gzip
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import zlib

import pytest
import yaml

from scripts import threshold_artifacts as artifact

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def baseline(tmp_path):
    db = tmp_path / "station_thresholds.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            "CREATE TABLE stations(is_active INTEGER); CREATE TABLE thresholds(value INTEGER); CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
        )
        conn.executemany("INSERT INTO stations VALUES(?)", [(1,)] * 1000)
        conn.executemany("INSERT INTO thresholds VALUES(?)", [(0,)] * 1000)
        conn.execute("INSERT INTO meta VALUES('last_diff_date','2026-09-28')")
    manifest = {
        "release": "thresholds-latest",
        "sha256": artifact.digest(db)[0],
        "bytes": str(db.stat().st_size),
        **artifact.database_stats(db),
    }
    path = tmp_path / "station_thresholds.version"
    save_manifest(path, manifest)
    return db, path, manifest


def save_manifest(path, values):
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))


class FakeGitHub:
    def __init__(self):
        self.rows = []
        self.blobs = {}
        self.calls = []
        self.upload_error = False
        self.missing_digest = False
        self.no_upload = False
        self.after_upload = None

    def assets(self, tag):
        self.calls.append(("assets", tag))
        return self.rows

    def add(self, name, raw):
        self.blobs[name] = raw
        self.rows.append(
            {
                "name": name,
                "state": "uploaded",
                "size": len(raw),
                "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}",
            }
        )

    def upload(self, tag, path):
        self.calls.append(("upload", tag, path.name))
        if not self.no_upload:
            self.add(path.name, path.read_bytes())
        if self.missing_digest:
            self.rows[-1]["digest"] = None
        if self.after_upload:
            self.after_upload()
        if self.upload_error:
            raise artifact.ArtifactError("threshold_transport_unavailable")

    def download(self, tag, name, directory):
        self.calls.append(("download", tag, name))
        (directory / name).write_bytes(self.blobs[name])


def test_verified_cache_needs_no_network_and_keeps_all_bytes(baseline):
    db, path, manifest = baseline
    before = (db.read_bytes(), path.read_bytes())
    github = FakeGitHub()
    assert artifact.ensure_database(db, manifest, github) == "verified_local_cache"
    assert github.calls == [] and before == (db.read_bytes(), path.read_bytes())


@pytest.mark.parametrize(
    "mutation",
    [
        {"release": "unsafe/../tag"},
        {"sha256": "x" * 64},
        {"bytes": "0"},
        {"bytes": "2147483648"},
        {"bytes": "12; printf unsafe"},
        {"active_stations": "-1"},
        {"threshold_rows": "01"},
        {"last_diff_date": "2026-02-30"},
        {"last_diff_date": "20260928"},
        {"unexpected": "PRIVATE"},
    ],
)
def test_manifest_rejects_unsafe_missing_and_wrong_fields(baseline, mutation):
    _, path, manifest = baseline
    save_manifest(path, {**manifest, **mutation})
    with pytest.raises(artifact.ArtifactError):
        artifact.read_manifest(path)


@pytest.mark.parametrize(
    "raw",
    [b"", b"a=1\na=2\n", b"x" * 4097, b"\xff", b"bytes=1\n"],
    ids=["empty", "duplicate", "oversized", "nonascii", "incomplete"],
)
def test_malformed_manifest_is_bounded(tmp_path, raw):
    path = tmp_path / "input"
    path.write_bytes(raw)
    with pytest.raises(artifact.ArtifactError):
        artifact.read_manifest(path)


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_active_journal_blocks_verification_and_replacement(baseline, suffix):
    db, _, manifest = baseline
    Path(str(db) + suffix).write_bytes(b"active-synthetic-writer")
    github = FakeGitHub()
    with pytest.raises(artifact.ArtifactError, match="uncheckpointed"):
        artifact.verify_database(db, manifest)
    with pytest.raises(artifact.ArtifactError, match="not_replaceable"):
        artifact.ensure_database(db, manifest, github)
    assert github.calls == []


def test_symlink_database_is_not_replaced(baseline, tmp_path):
    db, _, manifest = baseline
    link = tmp_path / "link.sqlite"
    link.symlink_to(db)
    with pytest.raises(artifact.ArtifactError, match="not_replaceable"):
        artifact.ensure_database(link, manifest, FakeGitHub())
    assert link.is_symlink()


def test_invalid_cache_is_replaced_only_by_exact_verified_download(baseline):
    db, _, manifest = baseline
    expected = db.read_bytes()
    github = FakeGitHub()
    github.add("station_thresholds.sqlite", expected)
    db.write_bytes(b"old-invalid-synthetic-cache")
    assert artifact.ensure_database(db, manifest, github) == "verified_download"
    assert db.read_bytes() == expected


@pytest.mark.parametrize("failure", ["missing", "wrong_size", "corrupt", "duplicate", "partial"])
def test_failed_download_preserves_existing_file(baseline, failure):
    db, _, manifest = baseline
    raw = db.read_bytes()
    github = FakeGitHub()
    if failure != "missing":
        github.add("station_thresholds.sqlite", raw)
        if failure == "wrong_size":
            github.rows[0]["size"] += 1
        if failure == "partial":
            github.rows[0]["state"] = "starter"
        if failure == "duplicate":
            github.rows.append(dict(github.rows[0]))
        if failure == "corrupt":
            github.blobs["station_thresholds.sqlite"] = b"X" * len(raw)
    db.write_bytes(b"keep-old-evidence")
    with pytest.raises(artifact.ArtifactError):
        artifact.ensure_database(db, manifest, github)
    assert db.read_bytes() == b"keep-old-evidence"


@pytest.mark.parametrize(
    "watermark,reason",
    [
        ("", "lineage_unknown"),
        ("2026-09-24", "gap_requires_rebuild"),
        ("2026-10-01", "ahead_of_update_window"),
        ("2026-10-10", "ahead_of_update_window"),
    ],
)
def test_unknown_or_gapped_lineage_blocks_before_update(baseline, watermark, reason):
    db, _, _ = baseline
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE meta SET value=?", (watermark,))
    before = db.read_bytes()
    with pytest.raises(artifact.ArtifactError, match=reason):
        artifact.require_lineage(db, days=8, today=date(2026, 10, 4))
    assert before == db.read_bytes()


@pytest.mark.parametrize("watermark", ["2026-09-25", "2026-09-26", "2026-09-30"])
def test_contiguous_lineage_boundaries(baseline, watermark):
    db, _, _ = baseline
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE meta SET value=?", (watermark,))
    artifact.require_lineage(db, days=8, today=date(2026, 10, 4))


@pytest.mark.parametrize("days", [-1, 0, 3, 32, 100])
def test_update_window_is_bounded(baseline, days):
    with pytest.raises(artifact.ArtifactError, match="invalid_threshold_update_window"):
        artifact.require_lineage(baseline[0], days=days)


def test_missing_legacy_asset_can_be_restored_exactly_once_even_with_unknown_lineage(baseline):
    db, path, manifest = baseline
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM meta")
    manifest.update(sha256=artifact.digest(db)[0], **artifact.database_stats(db))
    save_manifest(path, manifest)
    before = (db.read_bytes(), path.read_bytes())
    github = FakeGitHub()
    assert artifact.restore_baseline(db, manifest, github) == "verified_upload"
    assert artifact.restore_baseline(db, manifest, github) == "existing_verified_asset"
    assert sum(call[0] == "upload" for call in github.calls) == 1
    assert github.blobs["station_thresholds.sqlite"] == before[0]
    assert before == (db.read_bytes(), path.read_bytes())
    with pytest.raises(artifact.ArtifactError, match="lineage_unknown"):
        artifact.require_lineage(db, days=8)


@pytest.mark.parametrize("mode", ["wrong_digest", "missing_digest", "partial", "wrong_size"])
def test_existing_conflicting_asset_is_never_replaced(baseline, mode):
    db, _, manifest = baseline
    github = FakeGitHub()
    github.add("station_thresholds.sqlite", db.read_bytes())
    key, value = {
        "wrong_digest": ("digest", "sha256:" + "0" * 64),
        "missing_digest": ("digest", None),
        "partial": ("state", "starter"),
        "wrong_size": ("size", 0),
    }[mode]
    github.rows[0][key] = value
    with pytest.raises(artifact.ArtifactError, match="identity_conflict"):
        artifact.restore_baseline(db, manifest, github)
    assert all(call[0] != "upload" for call in github.calls)


def test_published_compressed_artifact_roundtrips_and_exact_retry_reuses_it(baseline, tmp_path):
    db, path, _ = baseline
    original = db.read_bytes()
    github = FakeGitHub()
    result = artifact.publish_database(db, path, github)
    assert result == artifact.read_manifest(path)
    assert result["format"] == "sqlite-gzip"
    assert gzip.decompress(github.blobs[result["asset"]]) == original
    assert artifact.publish_database(db, path, github) == result
    assert sum(call[0] == "upload" for call in github.calls) == 1
    target = tmp_path / "download.sqlite"
    assert artifact.ensure_database(target, result, github) == "verified_download"
    assert target.read_bytes() == original and db.read_bytes() == original


def test_unchanged_database_reuses_prior_encoded_bytes_without_recompression(baseline, monkeypatch):
    db, path, _ = baseline
    github = FakeGitHub()
    result = artifact.publish_database(db, path, github)
    before = path.read_bytes()
    monkeypatch.setattr(gzip, "GzipFile", lambda **kw: pytest.fail("unexpected recompression"))
    assert artifact.publish_database(db, path, github) == result
    assert path.read_bytes() == before
    github.rows.clear()
    with pytest.raises(artifact.ArtifactError, match="compressed_baseline_missing_or_conflicting"):
        artifact.publish_database(db, path, github)
    assert path.read_bytes() == before
    assert sum(call[0] == "upload" for call in github.calls) == 1


@pytest.mark.parametrize("failure", ["overflow", "invalid_gzip", "wrong_database"])
def test_verified_compressed_transport_cannot_promote_invalid_database(baseline, tmp_path, failure):
    db, _, manifest = baseline
    github = FakeGitHub()
    raw = db.read_bytes()
    payload = (
        b"not-gzip"
        if failure == "invalid_gzip"
        else gzip.compress(raw + b"X" if failure == "overflow" else b"X" * len(raw), mtime=0)
    )
    name = f"station_thresholds-{manifest['sha256']}.sqlite.gz"
    manifest.update(
        format="sqlite-gzip",
        asset=name,
        asset_sha256=hashlib.sha256(payload).hexdigest(),
        asset_bytes=str(len(payload)),
    )
    github.add(name, payload)
    target = tmp_path / "prior.sqlite"
    target.write_bytes(b"prior-evidence")
    with pytest.raises((artifact.ArtifactError, gzip.BadGzipFile)):
        artifact.ensure_database(target, manifest, github)
    assert target.read_bytes() == b"prior-evidence" and db.read_bytes() == raw


def test_database_change_while_compressing_never_uploads(baseline, monkeypatch):
    db, path, _ = baseline
    before = path.read_bytes()
    github = FakeGitHub()
    original = gzip.GzipFile.write
    changed = False

    def mutate_after_read(stream, data):
        nonlocal changed
        result = original(stream, data)
        if not changed:
            changed = True
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE thresholds SET value=1")
        return result

    monkeypatch.setattr(gzip.GzipFile, "write", mutate_after_read)
    with pytest.raises(artifact.ArtifactError, match="database_changed"):
        artifact.publish_database(db, path, github)
    assert path.read_bytes() == before and not github.calls


@pytest.mark.parametrize("mode", ["unavailable", "unverified", "changed_manifest", "capacity"])
def test_publication_failure_never_changes_authoritative_manifest(baseline, mode):
    db, path, _ = baseline
    before = path.read_bytes()
    github = FakeGitHub()
    if mode == "unavailable":
        github.no_upload = github.upload_error = True
    if mode == "unverified":
        github.missing_digest = True
    if mode == "changed_manifest":
        github.after_upload = lambda: path.write_bytes(before + b"#concurrent-change\n")
    if mode == "capacity":
        github.rows = [{"name": f"previous-{n}"} for n in range(artifact.MAX_ASSETS)]
    with pytest.raises(artifact.ArtifactError):
        artifact.publish_database(db, path, github)
    assert path.read_bytes() == before + (
        b"#concurrent-change\n" if mode == "changed_manifest" else b""
    )
    assert sum(call[0] == "upload" for call in github.calls) <= 1


def test_lost_upload_ack_recovers_by_exact_server_digest_without_a_second_upload(baseline):
    db, path, _ = baseline
    github = FakeGitHub()
    github.upload_error = True
    result = artifact.publish_database(db, path, github)
    assert result == artifact.read_manifest(path)
    assert sum(call[0] == "upload" for call in github.calls) == 1


def test_compression_limit_fails_before_network_or_manifest_change(baseline, monkeypatch):
    db, path, _ = baseline
    before = path.read_bytes()
    github = FakeGitHub()
    monkeypatch.setattr(artifact, "MAX_ASSET_BYTES", 10)
    with pytest.raises(artifact.ArtifactError, match="too_large"):
        artifact.publish_database(db, path, github)
    assert path.read_bytes() == before and not github.calls


def test_checkpoint_regression_or_missing_prior_lineage_never_uploads(baseline):
    db, path, manifest = baseline
    github = FakeGitHub()
    for watermark, label in [("2026-09-27", "regressed"), ("", "lineage_unknown")]:
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE meta SET value=?", (watermark,))
        with pytest.raises(artifact.ArtifactError, match=label):
            artifact.publish_database(db, path, github)
    assert not github.calls and artifact.read_manifest(path) == manifest


def test_cli_errors_are_fixed_and_lineage_check_has_no_process_io(baseline, monkeypatch, capsys):
    db, path, manifest = baseline
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM meta")
    manifest.update(sha256=artifact.digest(db)[0], **artifact.database_stats(db))
    save_manifest(path, manifest)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("unexpected process"))
    assert artifact.main(["require-lineage", "--db", str(db), "--manifest", str(path)]) == 1
    output = capsys.readouterr().out
    assert "threshold_baseline_lineage_unknown" in output and str(path) not in output


def test_cli_reports_corrupt_deflate_without_provider_or_path_details(
    baseline, monkeypatch, capsys
):
    db, path, _ = baseline

    def corrupt(*args):
        raise zlib.error("private-provider-body-or-path")

    monkeypatch.setattr(artifact, "ensure_database", corrupt)
    assert artifact.main(["ensure", "--db", str(db), "--manifest", str(path)]) == 1
    assert (
        capsys.readouterr().out
        == '{"status": "blocked", "error": "threshold_artifact_unavailable"}\n'
    )


def test_failed_workflow_push_is_not_reported_as_success(tmp_path):
    # Exercise the exact workflow shell step against a synthetic failing git;
    # no credentials, repository mutation or outbound Git operation is involved.
    refresh = yaml.safe_load((ROOT / ".github/workflows/refresh-thresholds.yml").read_text())
    command = next(
        s["run"] for s in refresh["jobs"]["refresh"]["steps"] if "git push" in s.get("run", "")
    )
    git = tmp_path / "git"
    git.write_text('#!/bin/sh\nif [ "$1" = push ]; then exit 73; fi\nexit 0\n')
    git.chmod(0o700)
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", command],
        cwd=tmp_path,
        env={"PATH": str(tmp_path)},
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 73
    assert not result.stdout


def test_cli_upload_is_one_bounded_argv_call_without_clobber(baseline, monkeypatch):
    calls = []

    def fake(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake)
    artifact.GitHub("example/synthetic").upload("thresholds-latest", baseline[0])
    assert calls[0][0] == [
        "gh",
        "release",
        "upload",
        "thresholds-latest",
        str(baseline[0]),
        "--repo",
        "example/synthetic",
    ]
    assert calls[0][1]["timeout"] == 300 and "shell" not in calls[0][1]


def test_workflow_uses_exact_cache_and_guards_mutation_then_non_destructive_publish():
    bot = yaml.safe_load((ROOT / ".github/workflows/bot.yml").read_text())
    refresh = yaml.safe_load((ROOT / ".github/workflows/refresh-thresholds.yml").read_text())
    steps = refresh["jobs"]["refresh"]["steps"]
    cache = next(s for s in steps if s.get("uses") == "actions/cache/restore@v4")
    assert "restore-keys" not in cache["with"]
    assert (
        cache["with"]["key"]
        == next(s for s in bot["jobs"]["run"]["steps"] if s.get("uses") == "actions/cache@v4")[
            "with"
        ]["key"]
    )
    commands = [s.get("run", "") for s in steps]

    def index(text):
        return next(i for i, command in enumerate(commands) if text in command)

    assert (
        index(" ensure ")
        < index(" restore-baseline ")
        < index(" require-lineage ")
        < index("scripts.refresh_station_inventory")
        < index("scripts.update_thresholds_incremental")
        < index(" publish ")
        < index("git push")
    )
    assert refresh["jobs"]["refresh"]["timeout-minutes"] == 30
    assert "timeout 900" in commands[index("scripts.update_thresholds_incremental")]
    assert '--days "$THRESHOLD_DAYS"' in commands[index("scripts.update_thresholds_incremental")]
    source = (ROOT / ".github/workflows/refresh-thresholds.yml").read_text()
    assert "--clobber" not in source and '|| echo "Nothing to push"' not in source
    assert all("${{ github.event.inputs.days" not in command for command in commands)
