#!/usr/bin/env python3
"""P00c inbox drain input: download admitted ``theheat-command-*`` artifacts.

Run by a job of the ``theheat-bot`` group before the Node consumer. It lists the
repository's unexpired admission artifacts (bounded), downloads each zip through the
ordinary authenticated ``gh api`` CLI with the job's ``GH_TOKEN`` (actions read),
and extracts exactly ``command.json`` and ``admission.json`` into one directory per
artifact. It never reads or writes a Gist; the consumer decides everything.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable
import zipfile

NAME = re.compile(r"theheat-command-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
MAX_ARTIFACTS = 200
MAX_PAGES = 3
MAX_FILE_BYTES = 128 * 1024
MAX_ZIP_BYTES = 512 * 1024

Runner = Callable[[list[str]], bytes]


class InboxError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def gh(args: list[str]) -> bytes:
    result = subprocess.run(["gh", "api", *args], capture_output=True, timeout=60)
    if result.returncode:
        raise InboxError("github_request_failed")
    return result.stdout


def list_admitted(repo: str, run: Runner = gh) -> list[dict]:
    if not REPO.fullmatch(repo or ""):
        raise InboxError("invalid_repository")
    rows: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            data = json.loads(run([f"repos/{repo}/actions/artifacts?per_page=100&page={page}"]))
        except (ValueError, TypeError):
            raise InboxError("artifact_listing_invalid") from None
        batch = data.get("artifacts") if isinstance(data, dict) else None
        if not isinstance(batch, list):
            raise InboxError("artifact_listing_invalid")
        for row in batch:
            if (isinstance(row, dict) and isinstance(row.get("name"), str) and NAME.fullmatch(row["name"])
                    and row.get("expired") is False and type(row.get("id")) is int):
                rows.append(row)
        if len(batch) < 100:
            break
    rows.sort(key=lambda row: (str(row.get("created_at", "")), row["id"]))
    return rows[:MAX_ARTIFACTS]


def extract(artifact: dict, blob: bytes, out: Path) -> Path:
    if len(blob) > MAX_ZIP_BYTES:
        raise InboxError("artifact_too_large")
    command_id = NAME.fullmatch(artifact["name"]).group(1)  # type: ignore[union-attr]
    target = out / f"{command_id}-{artifact['id']}"
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = {info.filename: info for info in archive.infolist()}
            if set(names) != {"command.json", "admission.json"}:
                raise InboxError("artifact_contents_unexpected")
            files = {}
            for name, info in names.items():
                if info.file_size > MAX_FILE_BYTES:
                    raise InboxError("artifact_too_large")
                files[name] = archive.read(info)
    except zipfile.BadZipFile:
        raise InboxError("artifact_unreadable") from None
    admission = json.loads(files["admission.json"])
    if not isinstance(admission, dict) or admission.get("command_id") != command_id:
        raise InboxError("artifact_identity_mismatch")
    target.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        (target / name).write_bytes(data)
    return target


def fetch(repo: str, out: Path, run: Runner = gh) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    fetched, skipped = [], []
    for artifact in list_admitted(repo, run):
        try:
            blob = run([f"repos/{repo}/actions/artifacts/{artifact['id']}/zip"])
            fetched.append(extract(artifact, blob, out).name)
        except InboxError as exc:
            # One unreadable artifact must not block the others; the consumer never sees it.
            skipped.append({"artifact_id": artifact["id"], "code": exc.code})
    return {"fetched": len(fetched), "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=("fetch",))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(fetch(args.repo, args.out), sort_keys=True))
        return 0
    except InboxError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
