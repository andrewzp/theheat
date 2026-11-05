"""Retain exact threshold adoption files for a protected pull request."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from src.evaluation.file_boundary import read_regular, write_private_directory

MANIFEST = "station_thresholds.version"
INVENTORY = "stations.csv"
RECEIPT = "handoff.json"
LIMITS = {MANIFEST: 4096, INVENTORY: 32 * 1024**2}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(directory: Path) -> dict[str, bytes]:
    files = {name: read_regular(str(directory / name), limit) for name, limit in LIMITS.items()}
    if not all(files.values()):
        raise ValueError("empty_handoff_file")
    return files


def _base_manifest(base: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{base}:data/{MANIFEST}"],
        capture_output=True, check=True, timeout=10,
    )
    if not 0 < len(result.stdout) <= LIMITS[MANIFEST]:
        raise ValueError("invalid_base_manifest")
    return result.stdout


def _receipt(
    repo: str, run_id: str, base: str, baseline: bytes, files: dict[str, bytes],
) -> bytes:
    value = {
        "schema_version": 1,
        "repository": repo,
        "run_id": run_id,
        "base_sha": base,
        "base_manifest_sha256": _digest(baseline),
        "files": {name: {"sha256": _digest(data), "bytes": len(data)} for name, data in files.items()},
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pack", "verify"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args(argv)
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", args.repo)
        or not re.fullmatch(r"[1-9][0-9]{0,19}", args.run_id)
        or not re.fullmatch(r"[0-9a-f]{40}", args.base_sha)
    ):
        parser.error("invalid handoff identity")
    try:
        baseline = _base_manifest(args.base_sha)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, check=True, timeout=10,
        ).stdout.decode("ascii").strip()
        if args.command == "pack":
            if head != args.base_sha:
                raise ValueError("handoff_base_mismatch")
            files = _files(args.data)
            receipt = _receipt(args.repo, args.run_id, args.base_sha, baseline, files)
            write_private_directory(str(args.directory), {**files, RECEIPT: receipt})
        else:
            installed = read_regular(str(args.data / MANIFEST), LIMITS[MANIFEST])
            if installed != baseline or _base_manifest(head) != baseline:
                raise ValueError("installed_threshold_baseline_changed")
            files = _files(args.directory)
            expected = _receipt(args.repo, args.run_id, args.base_sha, baseline, files)
            if read_regular(str(args.directory / RECEIPT), 4096) != expected:
                raise ValueError("threshold_handoff_mismatch")
    except (ValueError, OSError, subprocess.SubprocessError):
        print("threshold_handoff_refused")
        return 1
    print("threshold_handoff_packed" if args.command == "pack" else "threshold_handoff_verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
