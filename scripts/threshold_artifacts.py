#!/usr/bin/env python3
"""Checksum-bound threshold artifacts. Never clobber the last good release asset.

Only the existing scheduled maintenance workflow invokes upload commands. Local
verification and tests do not publish files. Integrity is not scientific lineage.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from typing import Any, NoReturn
import zlib

MAX_DB_BYTES = 2 * 1024**3 - 1
MAX_ASSET_BYTES = 512 * 1024**2
MAX_ASSETS = 900
LEGACY_FIELDS = {
    "release",
    "sha256",
    "bytes",
    "last_diff_date",
    "active_stations",
    "threshold_rows",
}
V2_FIELDS = LEGACY_FIELDS | {"format", "asset", "asset_sha256", "asset_bytes"}
SHA = re.compile(r"[0-9a-f]{64}")


class ArtifactError(ValueError):
    """Fixed public error labels only; never echo provider bodies or local data."""


def fail(label: str) -> NoReturn:
    raise ArtifactError(label)


def _integer(value: str, maximum: int) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,12}", value) or int(value) > maximum:
        fail("invalid_threshold_manifest")
    return int(value)


def _day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        fail("invalid_threshold_checkpoint")
    if parsed.isoformat() != value:
        fail("invalid_threshold_checkpoint")
    return parsed


def read_manifest(path: Path) -> dict[str, str]:
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        fail("invalid_threshold_manifest")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError:
        fail("invalid_threshold_manifest")
    fields: dict[str, str] = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if not sep or key in fields:
            fail("invalid_threshold_manifest")
        fields[key] = value
    if set(fields) not in (LEGACY_FIELDS, V2_FIELDS) or fields["release"] != "thresholds-latest":
        fail("invalid_threshold_manifest")
    if not SHA.fullmatch(fields["sha256"]):
        fail("invalid_threshold_manifest")
    _integer(fields["bytes"], MAX_DB_BYTES)
    _integer(fields["active_stations"], 10**8)
    _integer(fields["threshold_rows"], 10**10)
    if fields["last_diff_date"]:
        _day(fields["last_diff_date"])
    if set(fields) == V2_FIELDS:
        if (
            fields["format"] != "sqlite-gzip"
            or not SHA.fullmatch(fields["asset_sha256"])
            or fields["asset"] != f"station_thresholds-{fields['sha256']}.sqlite.gz"
        ):
            fail("invalid_threshold_manifest")
        _integer(fields["asset_bytes"], MAX_ASSET_BYTES)
    return fields


def digest(path: Path, limit: int = MAX_DB_BYTES) -> tuple[str, int]:
    total = 0
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024**2):
            total += len(chunk)
            if total > limit:
                fail("threshold_artifact_too_large")
            result.update(chunk)
    if not total:
        fail("threshold_artifact_empty")
    return result.hexdigest(), total


def database_stats(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        fail("threshold_database_unavailable")
    # Hashing only the main file must never omit uncheckpointed WAL state.
    for suffix in ("-wal", "-journal"):
        journal = Path(str(path) + suffix)
        if journal.exists() and journal.stat().st_size:
            fail("threshold_database_uncheckpointed")
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
            conn.execute("PRAGMA query_only=ON")
            active = conn.execute("SELECT COUNT(*) FROM stations WHERE is_active=1").fetchone()[0]
            rows = conn.execute("SELECT COUNT(*) FROM thresholds").fetchone()[0]
            values = conn.execute("SELECT value FROM meta WHERE key='last_diff_date'").fetchall()
    except sqlite3.Error:
        fail("threshold_database_invalid")
    if active < 1000 or rows < 1000 or len(values) > 1:
        fail("threshold_database_invalid")
    watermark = values[0][0] if values else ""
    if not isinstance(watermark, str):
        fail("invalid_threshold_checkpoint")
    if watermark:
        _day(watermark)
    return {
        "active_stations": str(active),
        "threshold_rows": str(rows),
        "last_diff_date": watermark,
    }


def verify_database(path: Path, manifest: dict[str, str]) -> dict[str, str]:
    actual, size = digest(path)
    if actual != manifest["sha256"] or size != int(manifest["bytes"]):
        fail("threshold_database_digest_mismatch")
    stats = database_stats(path)
    if any(stats[key] != manifest[key] for key in stats):
        fail("threshold_database_manifest_mismatch")
    return stats


def pending_diff_dates(
    watermark: str | None, *, days: int, lag_days: int = 4, today: date | None = None
) -> list[date]:
    """Bound candidate snapshot endpoints after a known baseline through the lag cutoff."""
    if type(days) is not int or type(lag_days) is not int or not 1 <= lag_days <= days <= 31:
        fail("invalid_threshold_update_window")
    today = today or datetime.now(timezone.utc).date()
    if not watermark:
        fail("threshold_baseline_lineage_unknown")
    checkpoint = _day(watermark)
    if checkpoint < today - timedelta(days=days + 1):
        fail("threshold_baseline_gap_requires_rebuild")
    if checkpoint > today - timedelta(days=lag_days):
        fail("threshold_checkpoint_ahead_of_update_window")
    cutoff = today - timedelta(days=lag_days)
    return [checkpoint + timedelta(days=i) for i in range(1, (cutoff - checkpoint).days + 1)]


def require_lineage(path: Path, *, days: int, lag_days: int = 4, today: date | None = None) -> None:
    pending_diff_dates(
        database_stats(path)["last_diff_date"], days=days, lag_days=lag_days, today=today
    )


class GitHub:
    def __init__(self, repo: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            fail("invalid_threshold_repository")
        self.repo = repo

    def run(self, args: list[str], *, timeout: int = 30, metadata: bool = False) -> Any:
        try:
            result = subprocess.run(
                ["gh", *args],
                check=False,
                stdout=subprocess.PIPE if metadata else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            fail("threshold_transport_unavailable")
        if result.returncode:
            fail("threshold_transport_failed")
        if not metadata:
            return None
        if len(result.stdout) > 4 * 1024**2:
            fail("threshold_metadata_too_large")
        try:
            return json.loads(result.stdout)
        except (ValueError, UnicodeError):
            fail("threshold_metadata_invalid")

    def assets(self, tag: str) -> list[dict]:
        result = self.run(["api", f"repos/{self.repo}/releases/tags/{tag}"], metadata=True)
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("assets"), list)
            or len(result["assets"]) > MAX_ASSETS
        ):
            fail("threshold_asset_capacity_or_metadata_invalid")
        if any(not isinstance(row, dict) for row in result["assets"]):
            fail("threshold_metadata_invalid")
        return result["assets"]

    def download(self, tag: str, name: str, directory: Path) -> None:
        self.run(
            [
                "release",
                "download",
                tag,
                "--repo",
                self.repo,
                "--pattern",
                name,
                "--dir",
                str(directory),
            ],
            timeout=300,
        )

    def upload(self, tag: str, path: Path) -> None:
        # No --clobber, delete, rename or automatic second upload after ambiguity.
        self.run(["release", "upload", tag, str(path), "--repo", self.repo], timeout=300)


def _asset(manifest: dict[str, str]) -> tuple[str, str, int]:
    return (
        manifest.get("asset", "station_thresholds.sqlite"),
        manifest.get("asset_sha256", manifest["sha256"]),
        int(manifest.get("asset_bytes", manifest["bytes"])),
    )


def _matching_asset(rows: list[dict], name: str) -> dict | None:
    matches = [row for row in rows if row.get("name") == name]
    if len(matches) > 1:
        fail("threshold_asset_identity_conflict")
    return matches[0] if matches else None


def _verified_asset(row: dict | None, sha256: str, size: int) -> bool:
    return (
        row is not None
        and row.get("state") == "uploaded"
        and type(row.get("size")) is int
        and row["size"] == size
        and row.get("digest") == f"sha256:{sha256}"
    )


def ensure_database(
    path: Path, manifest: dict[str, str], github: GitHub,
    *, diagnostics: dict[str, str] | None = None,
) -> str:
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics["cache_validation"] = "missing"
    if path.is_symlink() or any(
        (journal := Path(str(path) + suffix)).exists() and journal.stat().st_size
        for suffix in ("-wal", "-journal")
    ):
        diagnostics["cache_validation"] = "not_replaceable"
        fail("threshold_database_not_replaceable")
    if path.exists():
        try:
            verify_database(path, manifest)
            diagnostics["cache_validation"] = "verified"
            return "verified_local_cache"
        except ArtifactError as error:
            # Fixed categories only; keep old bytes until a verified replacement
            # is ready, and retain the initial cache reason if recovery fails.
            diagnostics["cache_validation"] = {
                "threshold_database_digest_mismatch": "digest_mismatch",
                "threshold_database_manifest_mismatch": "metadata_mismatch",
                "threshold_database_invalid": "metadata_invalid",
                "invalid_threshold_checkpoint": "checkpoint_invalid",
                "threshold_artifact_too_large": "size_invalid",
                "threshold_artifact_empty": "empty",
            }.get(str(error), "unavailable")
        except OSError:
            diagnostics["cache_validation"] = "unreadable"
            raise
    name, asset_sha, asset_size = _asset(manifest)
    found = _matching_asset(github.assets(manifest["release"]), name)
    if not found or found.get("state") != "uploaded" or found.get("size") != asset_size:
        fail("threshold_baseline_asset_unavailable")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".threshold-download-", dir=path.parent) as temporary:
        directory = Path(temporary)
        github.download(manifest["release"], name, directory)
        downloaded = directory / name
        if digest(downloaded, MAX_DB_BYTES if "format" not in manifest else MAX_ASSET_BYTES) != (
            asset_sha,
            asset_size,
        ):
            fail("threshold_download_digest_mismatch")
        candidate = downloaded
        if manifest.get("format") == "sqlite-gzip":
            candidate = directory / "verified.sqlite"
            total = 0
            with gzip.open(downloaded, "rb") as source, candidate.open("wb") as target:
                while chunk := source.read(1024**2):
                    total += len(chunk)
                    if total > int(manifest["bytes"]):
                        fail("threshold_expanded_size_mismatch")
                    target.write(chunk)
        verify_database(candidate, manifest)
        os.replace(candidate, path)
    return "verified_download"


def _publish_asset(path: Path, manifest: dict[str, str], github: GitHub) -> str:
    name, expected_sha, expected_size = _asset(manifest)
    if path.name != name:
        fail("threshold_asset_filename_mismatch")
    rows = github.assets(manifest["release"])
    found = _matching_asset(rows, name)
    if found is not None:
        if not _verified_asset(found, expected_sha, expected_size):
            fail("threshold_asset_identity_conflict")
        return "existing_verified_asset"
    if len(rows) >= MAX_ASSETS:
        fail("threshold_asset_capacity_exhausted")
    upload_failed = False
    try:
        github.upload(manifest["release"], path)
    except ArtifactError:
        upload_failed = True
    # A timeout may have completed remotely. One read can recover the exact receipt;
    # no retry upload or deletion is allowed when the outcome remains uncertain.
    found = _matching_asset(github.assets(manifest["release"]), name)
    if not _verified_asset(found, expected_sha, expected_size):
        fail("threshold_upload_uncertain" if upload_failed else "threshold_upload_unverified")
    return "verified_upload"


def restore_baseline(path: Path, manifest: dict[str, str], github: GitHub) -> str:
    verify_database(path, manifest)
    name, sha256, size = _asset(manifest)
    found = _matching_asset(github.assets(manifest["release"]), name)
    if found is not None:
        if not _verified_asset(found, sha256, size):
            fail("threshold_asset_identity_conflict")
        return "existing_verified_asset"
    # Recreate only the old uncompressed manifest asset. A lost compressed asset
    # cannot be recreated merely by assuming a byte-identical gzip encoder.
    if "format" in manifest:
        fail("threshold_compressed_baseline_missing")
    with tempfile.TemporaryDirectory(prefix=".threshold-baseline-", dir=path.parent) as temporary:
        staged = Path(temporary) / name
        os.link(path, staged)
        return _publish_asset(staged, manifest, github)


def publish_database(path: Path, manifest_path: Path, github: GitHub) -> dict[str, str]:
    previous = read_manifest(manifest_path)
    stats = database_stats(path)
    if not stats["last_diff_date"] or not previous["last_diff_date"]:
        fail("threshold_baseline_lineage_unknown")
    if _day(stats["last_diff_date"]) < _day(previous["last_diff_date"]):
        fail("threshold_checkpoint_regressed")
    sha256, size = digest(path)
    if (
        previous.get("format") == "sqlite-gzip"
        and (sha256, size) == (previous["sha256"], int(previous["bytes"]))
        and all(stats[key] == previous[key] for key in stats)
    ):
        # Do not assume another zlib/Python version reproduces identical gzip bytes.
        name, asset_sha, asset_size = _asset(previous)
        found = _matching_asset(github.assets(previous["release"]), name)
        if not _verified_asset(found, asset_sha, asset_size):
            fail("threshold_compressed_baseline_missing_or_conflicting")
        return previous
    with tempfile.TemporaryDirectory(prefix=".threshold-upload-", dir=path.parent) as temporary:
        name = f"station_thresholds-{sha256}.sqlite.gz"
        asset = Path(temporary) / name
        streamed = hashlib.sha256()
        streamed_bytes = 0
        with path.open("rb") as source, asset.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
                while chunk := source.read(1024**2):
                    streamed.update(chunk)
                    streamed_bytes += len(chunk)
                    compressed.write(chunk)
                    if output.tell() > MAX_ASSET_BYTES:
                        fail("threshold_artifact_too_large")
        asset_sha, asset_size = digest(asset, MAX_ASSET_BYTES)
        # Refuse a concurrent writer changing the DB during compression.
        if (
            (streamed.hexdigest(), streamed_bytes) != (sha256, size)
            or digest(path) != (sha256, size)
            or database_stats(path) != stats
        ):
            fail("threshold_database_changed")
        manifest = {
            "release": previous["release"],
            "sha256": sha256,
            "bytes": str(size),
            **stats,
            "format": "sqlite-gzip",
            "asset": name,
            "asset_sha256": asset_sha,
            "asset_bytes": str(asset_size),
        }
        _publish_asset(asset, manifest, github)
        if read_manifest(manifest_path) != previous:
            fail("threshold_manifest_changed")
        with tempfile.NamedTemporaryFile(
            mode="w", prefix=".threshold-manifest-", dir=manifest_path.parent, delete=False
        ) as output:
            temporary_manifest = Path(output.name)
            output.write("".join(f"{key}={value}\n" for key, value in manifest.items()))
            output.flush()
            os.fsync(output.fileno())
        try:
            os.replace(temporary_manifest, manifest_path)
        finally:
            temporary_manifest.unlink(missing_ok=True)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["ensure", "restore-baseline", "require-lineage", "publish"]
    )
    parser.add_argument("--db", type=Path, default=Path("data/station_thresholds.sqlite"))
    parser.add_argument("--manifest", type=Path, default=Path("data/station_thresholds.version"))
    parser.add_argument("--repo", default="andrewzp/theheat")
    parser.add_argument("--days", type=int, default=12)
    args = parser.parse_args(argv)
    diagnostics: dict[str, str] = {}
    try:
        manifest = read_manifest(args.manifest)
        github = GitHub(args.repo)
        if args.command == "ensure":
            status = ensure_database(args.db, manifest, github, diagnostics=diagnostics)
        elif args.command == "restore-baseline":
            status = restore_baseline(args.db, manifest, github)
        elif args.command == "require-lineage":
            verify_database(args.db, manifest)
            require_lineage(args.db, days=args.days)
            status = "incremental_lineage_available"
        else:
            publish_database(args.db, args.manifest, github)
            status = "immutable_artifact_verified_manifest_prepared"
        print(
            json.dumps(
                {
                    "status": status,
                    "scientific_qualification": "not_established_by_artifact_integrity",
                    **diagnostics,
                }
            )
        )
        return 0
    except (ArtifactError, OSError, sqlite3.Error, EOFError, zlib.error) as error:
        label = str(error) if isinstance(error, ArtifactError) else "threshold_artifact_unavailable"
        print(json.dumps({"status": "blocked", "error": label, **diagnostics}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
