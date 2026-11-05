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

* List runs of the command workflow with event, branch and creation filters. A full tenth page
  or a reported count of 1,000 means the filtered listing may be capped. The next drain uses
  the same workflow endpoint with only pagination parameters, outside that search cap. An
  unfinished unfiltered scan records its next page separately from settlement. It revisits the
  head for new arrivals and overlaps the previous page before continuing.
* Apply the creation horizon and check each run's path, event, branch and repository before
  examining its artifacts. The fallback may see older runs or other refs of this one workflow.
* ``GET /repos/{repo}/actions/runs/{id}/artifacts`` for each run not already SETTLED, oldest first,
  at most ``MAX_RUNS_EXAMINED`` per drain.

The durable continuation is the consumer's ``inbox_settled_runs`` in the existing state-Gist results
file (read here with the read token the job already holds): a run is recorded settled only after
its command artifacts were acknowledged (their results durable), or once it completed with no
command artifact (an admission refusal). Settled runs cost no request, so the examined set shrinks
as commands are consumed and every unsettled run is reached within a bounded number of drains. A
settled-run read failure only costs requests. ``scan.json`` reports exactly what was not examined
(``scan_complete``, ``deferred_runs``); an unseen command is deferred, never acknowledged.
GitHub documents the 1,000-result cap for filtered workflow searches:
https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow
Offset pagination can move between requests. Only a complete, distinct listing observed within
one drain certifies completion. A partial traversal can discover commands but proves no absence.
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
from typing import TypedDict
from urllib import parse, request
import zipfile

NAME = re.compile(r"theheat-command-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
GIST = re.compile(r"[A-Za-z0-9_]{1,100}")
PER_PAGE = 100
MAX_RUN_PAGES = 20          # <= 2,000 gist-commands dispatches inside one horizon
FILTERED_RUN_LIMIT = 1000
MAX_RUNS_EXAMINED = 150     # > the 100-command drain budget; one artifacts request per unsettled run
# A command expires <= 24 h after its request, which precedes admission by <= 5 min.
SCAN_HORIZON = timedelta(hours=24, minutes=15)
COMMAND_WORKFLOW = ".github/workflows/gist-commands.yml"
COMMAND_WORKFLOW_FILE = "gist-commands.yml"
COMMAND_EVENT = "workflow_dispatch"
DEFAULT_BRANCH = "main"
RESULTS_FILE = "gist-command-results.json"
DISCOVERY_FILE = "gist-command-discovery.json"
MAX_FILE_BYTES = 128 * 1024
MAX_ZIP_BYTES = 512 * 1024

Runner = Callable[[list[str]], bytes]
GistReader = Callable[[str], dict]


class DiscoveryCursor(TypedDict):
    repo: str
    branch: str
    page: int
    started_at: str


class InboxError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def gh(args: list[str]) -> bytes:
    try:
        result = subprocess.run(["gh", "api", *args], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise InboxError("github_request_timeout") from None
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


def _run_page(endpoint: str, page: int, run: Runner) -> tuple[list, int | None]:
    try:
        data = json.loads(run([f"{endpoint}per_page={PER_PAGE}&page={page}"]))
    except (ValueError, TypeError):
        raise InboxError("run_listing_invalid") from None
    batch = data.get("workflow_runs") if isinstance(data, dict) else None
    if not isinstance(batch, list) or len(batch) > PER_PAGE:
        raise InboxError("run_listing_invalid")
    total = data.get("total_count")
    return batch, total if type(total) is int and total >= 0 else None


def _remember_runs(runs: dict[int, dict], batch: list) -> None:
    for row in batch:
        if isinstance(row, dict) and type(row.get("id")) is int:
            runs[row["id"]] = row


def _list_unfiltered(endpoint: str, run: Runner, cursor: DiscoveryCursor) -> dict:
    first = cursor["page"]
    pages = [1, *range(first, first + MAX_RUN_PAGES - 1)] if first > 1 else range(1, MAX_RUN_PAGES + 1)
    runs: dict[int, dict] = {}
    totals = set()
    scanned = 0
    for page in pages:
        scanned += 1
        try:
            batch, total = _run_page(endpoint, page, run)
        except InboxError as exc:
            return {"runs": list(runs.values()), "complete": False, "pages": scanned,
                    "total_count": None, "code": exc.code,
                    "cursor": {**cursor, "page": max(1, page - 1) if page != 1 else first}}
        totals.add(total)
        _remember_runs(runs, batch)
        if len(batch) < PER_PAGE or (total is not None and page * PER_PAGE >= total):
            complete = first == 1 and total is not None and totals == {len(runs)}
            return {"runs": list(runs.values()), "complete": complete, "pages": scanned,
                    "total_count": total, "code": None if complete else "unfiltered_scan_partial", "cursor": None}
    # Leave one overlapping page between drains. A new sweep later also revisits
    # any page affected by larger shifts or changes in the provider's ordering.
    return {"runs": list(runs.values()), "complete": False, "pages": scanned,
            "total_count": None, "code": "unfiltered_scan_pending", "cursor": {**cursor, "page": page}}


def list_runs(repo: str, run: Runner = gh, *, now: datetime | None = None, branch: str = DEFAULT_BRANCH,
              cursor: DiscoveryCursor | None = None) -> dict:
    """List within the existing request budget without assuming workflow-run order."""
    if not REPO.fullmatch(repo or ""):
        raise InboxError("invalid_repository")
    now = now or datetime.now(UTC)
    endpoint = f"repos/{repo}/actions/workflows/{COMMAND_WORKFLOW_FILE}/runs?"
    started = _created(cursor["started_at"]) if cursor else None
    if cursor and cursor["repo"] == repo and cursor["branch"] == branch and started and now - SCAN_HORIZON <= started <= now:
        return _list_unfiltered(endpoint, run, cursor)

    since = parse.quote(f">={_utc(now - SCAN_HORIZON)}", safe="")
    filtered = f"{endpoint}event={COMMAND_EVENT}&branch={parse.quote(branch, safe='')}&created={since}&"
    runs: dict[int, dict] = {}
    totals = set()
    limit = min(MAX_RUN_PAGES, FILTERED_RUN_LIMIT // PER_PAGE)
    possibly_capped = False
    for page in range(1, limit + 1):
        batch, total = _run_page(filtered, page, run)
        totals.add(total)
        _remember_runs(runs, batch)
        possibly_capped |= total is not None and total >= FILTERED_RUN_LIMIT
        if page < limit and len(batch) == PER_PAGE:
            continue
        if possibly_capped or len(batch) == PER_PAGE:
            return {"runs": list(runs.values()), "complete": False, "pages": page,
                    "total_count": total, "code": "filtered_search_capped",
                    "cursor": {"repo": repo, "branch": branch, "page": 1, "started_at": _utc(now)}}
        complete = total is not None and totals == {len(runs)}
        return {"runs": list(runs.values()), "complete": complete, "pages": page,
                "total_count": total, "code": None if complete else "filtered_scan_partial", "cursor": None}
    raise InboxError("run_listing_invalid")


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
          settled: set[int] | None = None, cursor: DiscoveryCursor | None = None) -> dict:
    """Scan the command workflow's runs, skip settled ones, fetch live command artifacts (oldest run first).

    Writes one ``<command_id>-<artifact_id>`` directory per artifact, ``manifest.json`` (directory ->
    artifact/run ids) and ``scan.json`` (what was and was not examined)."""
    out.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(UTC)
    cutoff = (now - SCAN_HORIZON).replace(microsecond=0)
    listed = list_runs(repo, run, now=now, branch=branch, cursor=cursor)
    refused: dict[str, int] = {}
    candidates: list[dict] = []
    skipped_settled = 0
    invalid_timestamps = 0
    in_horizon = 0
    for row in listed["runs"]:
        created = _created(row.get("created_at"))
        if created is None:
            invalid_timestamps += 1
            continue
        if created < cutoff:
            continue
        in_horizon += 1
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
    summary = {"scan_complete": listed["complete"] and not deferred and not unreadable_runs and not invalid_timestamps and not skipped,
               "run_pages": listed["pages"], "listing_code": listed["code"], "invalid_timestamps": invalid_timestamps,
               "runs_listed": in_horizon, "runs_settled_skipped": skipped_settled, "runs_examined": len(examined),
               "deferred_runs": len(deferred), "unreadable_runs": unreadable_runs, "provenance_refused": refused,
               "settled_cursor": "unavailable" if settled is None else "read", "empty_completed_runs": empty_completed,
               "incomplete_artifact_runs": sorted({row["run_id"] for row in skipped})}
    if listed["cursor"] is not None or cursor is not None:
        summary["discovery_cursor"] = listed["cursor"]
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


def discovery_from_files(files: dict) -> DiscoveryCursor | None:
    meta = files.get(DISCOVERY_FILE)
    if not isinstance(meta, dict) or meta.get("truncated") or not isinstance(meta.get("content"), str):
        return None
    try:
        value = json.loads(meta["content"])
    except ValueError:
        return None
    if not isinstance(value, dict) or set(value) != {"repo", "branch", "page", "started_at"}:
        return None
    repo, branch, page, started_at = (value[key] for key in ("repo", "branch", "page", "started_at"))
    if (not isinstance(repo, str) or not REPO.fullmatch(repo) or not isinstance(branch, str) or not branch
            or type(page) is not int or not 1 <= page <= 2**53 - 1 - MAX_RUN_PAGES or _created(started_at) is None):
        return None
    return {"repo": repo, "branch": branch, "page": page, "started_at": started_at}


def load_inbox_progress(env: Mapping[str, str] = os.environ,
                        reader: GistReader | None = None) -> tuple[set[int] | None, DiscoveryCursor | None]:
    gist_id, token = env.get("GIST_ID", ""), env.get("THEHEAT_GIST_READ_TOKEN", "")
    if not GIST.fullmatch(gist_id) or not token:
        return None, None
    try:
        files = (reader or (lambda gid: read_gist_files(gid, token)))(gist_id)
    except Exception:  # noqa: BLE001 - progress is optional; don't infer settlement.
        return None, None
    try:
        settled = settled_runs_from_files(files)
    except (InboxError, ValueError):
        settled = None
    return settled, discovery_from_files(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=("fetch",))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    args = parser.parse_args(argv)
    try:
        settled, cursor = load_inbox_progress()
        print(json.dumps(fetch(args.repo, args.out, branch=args.branch, settled=settled, cursor=cursor), sort_keys=True))
        return 0
    except InboxError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
