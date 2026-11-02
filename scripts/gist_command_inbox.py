#!/usr/bin/env python3
"""P00c inbox drain input: download admitted ``theheat-command-*`` artifacts (ROUTE-CONTRACT-v2 §4,
dated note c).

Run by a job of the ``theheat-bot`` group before the Node consumer. It never writes a Gist; the
consumer decides everything, and only the consumer acknowledges (deletes) an artifact, after its
terminal result is durably in the Gist.

SELECTIVE, RUN-SCOPED SCAN (root checkpoint R1). A repository-wide artifact listing let unrelated
artifacts consume a bounded page budget forever. Instead, every admitted command artifact is
uploaded by the ``admit`` job of exactly one ``workflow_dispatch`` run of
``.github/workflows/gist-commands.yml``; so the scan lists ONLY those runs:

* ``GET /repos/{repo}/actions/workflows/gist-commands.yml/runs?event=workflow_dispatch&branch=main``
  ``&created=>=<now - horizon>`` (≤ ``MAX_RUN_PAGES`` pages of 100). Runs created before the horizon
  can only hold expired commands. Each run's own ``path``/``event``/``head_branch``/repository fields
  are checked at the source (provenance; review P2-2) — no unrelated artifact is ever examined.
* ``GET /repos/{repo}/actions/runs/{id}/artifacts`` for each run not already SETTLED, oldest first,
  at most ``MAX_RUNS_EXAMINED`` per drain.

The durable continuation is the consumer's ``inbox_settled_runs`` in the existing state-Gist results
file (read here with the read token the job already holds): a run is recorded settled only after
its command artifacts were acknowledged (their results durable), or once it completed with no
command artifact (an admission refusal). Settled runs cost no request, so the examined set shrinks
as commands are consumed and every unsettled run is reached within a bounded number of drains. A
settled-run read failure only costs requests. ``scan.json`` reports exactly what was not examined
(``scan_complete``, ``deferred_runs``); an unseen command is deferred, never acknowledged.
Assumption (no further documentation was consulted, see LANE-ROUTE.md): the workflow-runs listing
honours ``event``, ``branch`` and ``created`` exactly, and a run's artifacts listing returns that
run's artifacts.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable
from urllib import parse, request
import zipfile

NAME = re.compile(r"theheat-command-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
GIST = re.compile(r"[A-Za-z0-9_]{1,100}")
PER_PAGE = 100
MAX_RUN_PAGES = 20          # <= 2,000 gist-commands dispatches inside one horizon
MAX_RUNS_EXAMINED = 150     # > the 100-command drain budget; one artifacts request per unsettled run
# A command expires <= 24 h after its request, which precedes admission by <= 5 min.
SCAN_HORIZON = timedelta(hours=24, minutes=15)
COMMAND_WORKFLOW = ".github/workflows/gist-commands.yml"
COMMAND_WORKFLOW_FILE = "gist-commands.yml"
COMMAND_EVENT = "workflow_dispatch"
DEFAULT_BRANCH = "main"
RESULTS_FILE = "gist-command-results.json"
MAX_FILE_BYTES = 128 * 1024
MAX_ZIP_BYTES = 512 * 1024

Runner = Callable[[list[str]], bytes]
GistReader = Callable[[str], dict]


class InboxError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def gh(args: list[str]) -> bytes:
    result = subprocess.run(["gh", "api", *args], capture_output=True, timeout=60)
    if result.returncode:
        raise InboxError("github_request_failed")
    return result.stdout


def _created(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def workflow_paths(branch: str = DEFAULT_BRANCH) -> frozenset[str]:
    """The exact workflow-run ``path`` forms accepted: the file, or the file ``@<branch>`` /
    ``@refs/heads/<branch>`` (some REST responses append the ref). No other suffix, ref or prefix."""
    return frozenset({COMMAND_WORKFLOW, f"{COMMAND_WORKFLOW}@{branch}", f"{COMMAND_WORKFLOW}@refs/heads/{branch}"})


def run_provenance(run: dict, branch: str = DEFAULT_BRANCH) -> str | None:
    """A refusal code, or ``None`` for a gist-commands workflow_dispatch run of this repository on ``branch``."""
    if type(run.get("id")) is not int:
        return "provenance_unknown"
    if run.get("path") not in workflow_paths(branch):
        return "provenance_workflow"
    if run.get("event") != COMMAND_EVENT:
        return "provenance_event"
    if run.get("head_branch") != branch:
        return "provenance_branch"
    own, head = run.get("repository"), run.get("head_repository")
    if not isinstance(own, dict) or not isinstance(head, dict) or type(own.get("id")) is not int or head.get("id") != own["id"]:
        return "provenance_fork"
    return None


def list_runs(repo: str, run: Runner = gh, *, now: datetime | None = None, branch: str = DEFAULT_BRANCH) -> dict:
    """Bounded listing of the command workflow's dispatch runs inside the horizon (no order assumed)."""
    if not REPO.fullmatch(repo or ""):
        raise InboxError("invalid_repository")
    since = parse.quote(f">={_utc((now or datetime.now(UTC)) - SCAN_HORIZON)}", safe="")
    runs: dict[int, dict] = {}
    complete, pages, total = False, 0, None
    for page in range(1, MAX_RUN_PAGES + 1):
        try:
            data = json.loads(run([f"repos/{repo}/actions/workflows/{COMMAND_WORKFLOW_FILE}/runs?event={COMMAND_EVENT}"
                                   f"&branch={parse.quote(branch, safe='')}&created={since}&per_page={PER_PAGE}&page={page}"]))
        except (ValueError, TypeError):
            raise InboxError("run_listing_invalid") from None
        batch = data.get("workflow_runs") if isinstance(data, dict) else None
        if not isinstance(batch, list):
            raise InboxError("run_listing_invalid")
        pages = page
        if type(data.get("total_count")) is int:
            total = data["total_count"]
        for row in batch:
            if isinstance(row, dict) and type(row.get("id")) is int:
                runs[row["id"]] = row  # a run moving between pages is seen once
        if len(batch) < PER_PAGE:
            complete = True
            break
    # Runs that moved between page requests may be missed: the reported total exposes that (truthful).
    if total is not None and len(runs) < total:
        complete = False
    return {"runs": list(runs.values()), "complete": complete, "pages": pages, "total_count": total}


def run_artifacts(repo: str, run_id: int, run: Runner = gh) -> list[dict]:
    try:
        data = json.loads(run([f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page={PER_PAGE}"]))
    except (ValueError, TypeError):
        raise InboxError("artifact_listing_invalid") from None
    rows = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise InboxError("artifact_listing_invalid")
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("name"), str) and NAME.fullmatch(row["name"])
            and row.get("expired") is False and type(row.get("id")) is int]


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


def fetch(repo: str, out: Path, run: Runner = gh, *, now: datetime | None = None, branch: str = DEFAULT_BRANCH,
          settled: set[int] | None = None) -> dict:
    """Scan the command workflow's runs, skip settled ones, fetch live command artifacts (oldest run first).

    Writes one ``<command_id>-<artifact_id>`` directory per artifact, ``manifest.json`` (directory ->
    artifact/run ids) and ``scan.json`` (what was and was not examined)."""
    out.mkdir(parents=True, exist_ok=True)
    listed = list_runs(repo, run, now=now, branch=branch)
    refused: dict[str, int] = {}
    candidates: list[dict] = []
    skipped_settled = 0
    for row in listed["runs"]:
        code = run_provenance(row, branch)
        if code:
            refused[code] = refused.get(code, 0) + 1
        elif settled is not None and row["id"] in settled:
            skipped_settled += 1
        else:
            candidates.append(row)
    candidates.sort(key=lambda row: (str(row.get("created_at", "")), row["id"]))
    examined, deferred = candidates[:MAX_RUNS_EXAMINED], candidates[MAX_RUNS_EXAMINED:]
    fetched, skipped, manifest = [], [], {}
    empty_completed, unreadable_runs = [], 0
    for row in examined:
        try:
            artifacts = run_artifacts(repo, row["id"], run)
        except InboxError:
            unreadable_runs += 1
            continue
        if not artifacts:
            # A completed run without a command artifact (an admission refusal, or already acknowledged)
            # can never produce one: the consumer records it settled. A running one is looked at again.
            if row.get("status") == "completed":
                empty_completed.append({"run_id": row["id"], "created_at": row.get("created_at")})
            continue
        for artifact in artifacts:
            try:
                blob = run([f"repos/{repo}/actions/artifacts/{artifact['id']}/zip"])
                name = extract(artifact, blob, out).name
                fetched.append(name)
                manifest[name] = {"artifact_id": artifact["id"], "run_id": row["id"], "run_created_at": row.get("created_at")}
            except InboxError as exc:
                # One unreadable artifact must not block the others; the consumer never sees it.
                skipped.append({"artifact_id": artifact["id"], "run_id": row["id"], "code": exc.code})
    summary = {"scan_complete": listed["complete"] and not deferred and not unreadable_runs, "run_pages": listed["pages"],
               "runs_listed": len(listed["runs"]), "runs_settled_skipped": skipped_settled, "runs_examined": len(examined),
               "deferred_runs": len(deferred), "unreadable_runs": unreadable_runs, "provenance_refused": refused,
               "settled_cursor": "unavailable" if settled is None else "read", "empty_completed_runs": empty_completed}
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    (out / "scan.json").write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    return {"fetched": len(fetched), "skipped": skipped, **summary}


def read_gist_files(gist_id: str, token: str, opener: Callable = request.urlopen) -> dict:
    """GET /gists/{id} with the job's read token (stdlib only: this step installs no packages)."""
    req = request.Request(f"https://api.github.com/gists/{gist_id}", headers={
        "Accept": "application/vnd.github+json", "Authorization": f"token {token}", "User-Agent": "theheat-inbox"})
    with opener(req, timeout=30) as response:  # noqa: S310 - fixed https API host
        value = json.loads(response.read())
    files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(files, dict):
        raise InboxError("gist_unreadable")
    return files


def settled_runs_from_files(files: dict) -> set[int]:
    """The consumer's durable ``inbox_settled_runs`` (absent file = nothing settled yet)."""
    meta = files.get(RESULTS_FILE)
    if meta is None:
        return set()
    if not isinstance(meta, dict) or meta.get("truncated") or not isinstance(meta.get("content"), str):
        raise InboxError("settled_runs_unreadable")
    document = json.loads(meta["content"])
    rows = document.get("inbox_settled_runs", {}) if isinstance(document, dict) else None
    if not isinstance(rows, dict):
        raise InboxError("settled_runs_unreadable")
    return {int(key) for key in rows if key.isdigit()}


def load_settled(env: Mapping[str, str] = os.environ, reader: GistReader | None = None) -> set[int] | None:
    gist_id, token = env.get("GIST_ID", ""), env.get("THEHEAT_GIST_READ_TOKEN", "")
    if not GIST.fullmatch(gist_id) or not token:
        return None
    try:
        files = (reader or (lambda gid: read_gist_files(gid, token)))(gist_id)
        return settled_runs_from_files(files)
    except Exception:  # noqa: BLE001 - an unreadable cursor only costs requests; never trust a partial value.
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=("fetch",))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(fetch(args.repo, args.out, branch=args.branch, settled=load_settled()), sort_keys=True))
        return 0
    except InboxError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
