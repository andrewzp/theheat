#!/usr/bin/env python3
"""P00c inbox drain input: download admitted ``theheat-command-*`` artifacts (ROUTE-CONTRACT-v2 §4).

Run by a job of the ``theheat-bot`` group before the Node consumer. It lists the
repository's artifacts through the ordinary authenticated ``gh api`` CLI with the job's
``GH_TOKEN`` and extracts exactly ``command.json`` and ``admission.json`` into one
directory ``<command_id>-<artifact_id>`` per admitted artifact. It never reads or writes a
Gist; the consumer decides everything, and only the consumer acknowledges (deletes) an
artifact, after its terminal result is durably in the Gist.

The scan does NOT rely on the listing's order. It pages until a short page (the complete
listing) or the hard page cap, keeps only unexpired command artifacts that are not older
than the scan horizon (older ones can only hold commands that already expired), and fetches
the oldest of them first, bounded. ``scan.json`` records whether the listing was complete;
an incomplete scan is reported (the consumer exits non-zero) and can only defer, never
acknowledge, a command it did not see.

Provenance (independent review P2-2): a name proves nothing. A candidate is accepted only when
its producing run is a ``workflow_dispatch`` run of ``.github/workflows/gist-commands.yml`` in
THIS repository (not a fork) on the default branch. The listing's ``workflow_run`` fields are
checked first (``repository_id == head_repository_id``, ``head_branch``); the run itself is
then confirmed with ``GET /actions/runs/{id}`` (cached per run id, at most ``MAX_RUN_LOOKUPS``
per drain). Anything refused or unverifiable is skipped and reported, never trusted.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
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
PER_PAGE = 100
MAX_PAGES = 30
MAX_ARTIFACTS = 300
# A command expires <= 24 h after its request, which precedes admission by <= 5 min.
SCAN_HORIZON = timedelta(hours=24, minutes=15)
COMMAND_WORKFLOW = ".github/workflows/gist-commands.yml"
COMMAND_EVENT = "workflow_dispatch"
DEFAULT_BRANCH = "main"
# > the 100-command drain budget: one lookup per distinct producing run (each dispatch is its own run).
MAX_RUN_LOOKUPS = 120
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


def _created(row: dict) -> datetime | None:
    value = row.get("created_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _listed_provenance(row: dict, branch: str) -> str | None:
    """Cheap check on the listing's own ``workflow_run`` fields; a refusal code or ``None``."""
    origin = row.get("workflow_run")
    if not isinstance(origin, dict) or type(origin.get("id")) is not int:
        return "provenance_unknown"
    if type(origin.get("repository_id")) is not int or origin.get("head_repository_id") != origin["repository_id"]:
        return "provenance_fork"
    if origin.get("head_branch") != branch:
        return "provenance_branch"
    return None


def verify_provenance(repo: str, rows: list[dict], run: Runner, *, branch: str = DEFAULT_BRANCH,
                      limit: int = MAX_ARTIFACTS) -> dict:
    """Accept (oldest first, at most ``limit``) only artifacts of a gist-commands.yml workflow_dispatch run
    of this repository on ``branch``; everything else is refused or left unverified, and reported."""
    accepted: list[dict] = []
    refused: dict[str, int] = {}
    unverified = 0
    cache: dict[int, str | None] = {}
    lookups = 0
    for row in rows:
        if len(accepted) >= limit:
            break
        code = _listed_provenance(row, branch)
        if code is None:
            run_id = row["workflow_run"]["id"]
            if run_id not in cache:
                if lookups >= MAX_RUN_LOOKUPS:
                    unverified += 1
                    continue
                lookups += 1
                try:
                    detail = json.loads(run([f"repos/{repo}/actions/runs/{run_id}"]))
                except (InboxError, ValueError, TypeError):
                    unverified += 1
                    continue
                if not isinstance(detail, dict):
                    unverified += 1
                    continue
                head = detail.get("head_repository") if isinstance(detail.get("head_repository"), dict) else {}
                own = detail.get("repository") if isinstance(detail.get("repository"), dict) else {}
                cache[run_id] = ("provenance_workflow" if detail.get("path") != COMMAND_WORKFLOW
                                 else "provenance_event" if detail.get("event") != COMMAND_EVENT
                                 # Branch and fork were checked on the listing; the run detail must not contradict them.
                                 else "provenance_branch" if "head_branch" in detail and detail["head_branch"] != branch
                                 else "provenance_fork" if (head or own) and head.get("id") != own.get("id")
                                 else None)
            code = cache[run_id]
        if code is None:
            accepted.append(row)
        else:
            refused[code] = refused.get(code, 0) + 1
    return {"artifacts": accepted, "provenance_refused": refused, "unverified": unverified, "run_lookups": lookups}


def scan_admitted(repo: str, run: Runner = gh, *, now: datetime | None = None) -> dict:
    """Bounded, order-independent listing of live admitted command artifacts.

    Returns ``{"artifacts": [...oldest first, at most MAX_ARTIFACTS...], "scan_complete": bool,
    "pages": n, "candidates": n, "beyond_horizon": n}``.
    """
    if not REPO.fullmatch(repo or ""):
        raise InboxError("invalid_repository")
    horizon = (now or datetime.now(UTC)) - SCAN_HORIZON
    rows: list[dict] = []
    complete, pages, old = False, 0, 0
    for page in range(1, MAX_PAGES + 1):
        try:
            data = json.loads(run([f"repos/{repo}/actions/artifacts?per_page={PER_PAGE}&page={page}"]))
        except (ValueError, TypeError):
            raise InboxError("artifact_listing_invalid") from None
        batch = data.get("artifacts") if isinstance(data, dict) else None
        if not isinstance(batch, list):
            raise InboxError("artifact_listing_invalid")
        pages = page
        for row in batch:
            if not (isinstance(row, dict) and isinstance(row.get("name"), str) and NAME.fullmatch(row["name"])
                    and row.get("expired") is False and type(row.get("id")) is int):
                continue
            created = _created(row)
            if created is not None and created < horizon:
                old += 1  # Filtered, never a stop condition: the order is not relied upon.
                continue
            rows.append(row)
        if len(batch) < PER_PAGE:
            complete = True
            break
    rows.sort(key=lambda row: (str(row.get("created_at", "")), row["id"]))
    return {"artifacts": rows[:MAX_ARTIFACTS], "all": rows, "scan_complete": complete, "pages": pages,
            "candidates": len(rows), "beyond_horizon": old}


def list_admitted(repo: str, run: Runner = gh, *, now: datetime | None = None) -> list[dict]:
    return scan_admitted(repo, run, now=now)["artifacts"]


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


def fetch(repo: str, out: Path, run: Runner = gh, *, now: datetime | None = None, branch: str = DEFAULT_BRANCH) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    scan = scan_admitted(repo, run, now=now)
    # scan_admitted keeps every in-horizon candidate (oldest first) for the provenance pass below.
    proven = verify_provenance(repo, scan["all"], run, branch=branch)
    fetched, skipped = [], []
    for artifact in proven["artifacts"]:
        try:
            blob = run([f"repos/{repo}/actions/artifacts/{artifact['id']}/zip"])
            fetched.append(extract(artifact, blob, out).name)
        except InboxError as exc:
            # One unreadable artifact must not block the others; the consumer never sees it.
            skipped.append({"artifact_id": artifact["id"], "code": exc.code})
    refused = sum(proven["provenance_refused"].values())
    summary = {"scan_complete": scan["scan_complete"], "pages": scan["pages"], "candidates": scan["candidates"],
               "beyond_horizon": scan["beyond_horizon"], "provenance_refused": proven["provenance_refused"],
               "unverified": proven["unverified"],
               "deferred": max(0, scan["candidates"] - len(proven["artifacts"]) - refused - proven["unverified"])}
    (out / "scan.json").write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    return {"fetched": len(fetched), "skipped": skipped, **summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=("fetch",))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(fetch(args.repo, args.out, branch=args.branch), sort_keys=True))
        return 0
    except InboxError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
