#!/usr/bin/env python3
"""Scheduled-workflow health observer.

Reads the GitHub Actions API for the five scheduled workflows and turns any that
are red on ``main`` into a tracked, auto-closing ``workflow-health`` issue. The
governing idea matches the source-health sentinel: a red scheduled workflow is
OUR problem (a thing the bot can no longer do), and it must surface WITHOUT a
human watching the dashboard. The issue lane is the durable, de-duped signal the
**daily self-heal routine** consumes to investigate and fix.

It also flags the self-heal routine itself when its heartbeat
(``SELFHEAL_BEACON`` repo variable) goes stale, so the watcher cannot silently
die — the exact failure mode that hid voice-regression's five red days and the
daily-plan routine's weeks-long death. To avoid rollout chicken-and-egg and
token-scope false alarms, a *never-set* beacon files nothing; only a beacon that
EXISTS but is older than the freshness window does.

Classification + the create/close PLAN are pure and unit-tested (see
``tests/test_workflow_health.py``). ``main()`` fetches live runs via ``gh`` and
reconciles real issues (live in CI; dry-run locally unless ``--apply``). Always
exits 0 — a reporter, never a gate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
from typing import Any

# The five scheduled workflows. Keep in lockstep with dashboard/lib/automation.js
# WORKFLOWS — both monitor the same set.
MONITORED_WORKFLOWS: list[dict[str, str]] = [
    {"name": "theheat-bot", "file": "bot.yml"},
    {"name": "voice-regression", "file": "voice-regression.yml"},
    {"name": "refresh-thresholds", "file": "refresh-thresholds.yml"},
    {"name": "source-health-sentinel", "file": "source-health-sentinel.yml"},
    {"name": "time-travel-canary", "file": "time-travel-canary.yml"},
]

# Conclusions that mean the run produced a broken result. A single red run trips
# detection — waiting for "two in a row" is the delay that let voice-regression
# rot for five days. ``cancelled`` (manual abort) and ``neutral``/``skipped`` are
# NOT failures and never trip an alarm.
FAILING_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
# A run we can draw a verdict from. Everything else (cancelled, neutral, skipped,
# action_required, in-progress) is noise we skip to reach the last real signal.
DECISIVE_CONCLUSIONS = FAILING_CONCLUSIONS | {"success"}

LABEL = "workflow-health"
CAUSE_LABEL = "ours"  # a red CI workflow is, by repo ethos, our problem to fix.
TITLE_PREFIX = "Workflow failing: "

# Self-heal routine heartbeat (mirrors ROUTINE_BEACON for the daily-plan routine).
BEACON_VARIABLE = "SELFHEAL_BEACON"
SELFHEAL_MAX_AGE_H = 26  # daily routine; flag once it is clearly more than a day late.
SELFHEAL_SOURCE = "_selfheal_liveness"


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _sorted_newest_first(runs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Runs sorted by created_at descending; undated runs sink to the bottom."""
    def key(run: Mapping[str, Any]) -> float:
        parsed = _parse_ts(run.get("created_at"))
        return parsed.timestamp() if parsed is not None else float("-inf")

    return sorted((r for r in runs if isinstance(r, Mapping)), key=key, reverse=True)


def select_latest_decisive_run(
    runs: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """The most recent run with a decisive conclusion (success/failure-class)."""
    for run in _sorted_newest_first(runs):
        if run.get("conclusion") in DECISIVE_CONCLUSIONS:
            return run
    return None


def count_leading_failures(runs: Iterable[Mapping[str, Any]]) -> int:
    """How many consecutive decisive runs from newest are failures (skips noise)."""
    count = 0
    for run in _sorted_newest_first(runs):
        conclusion = run.get("conclusion")
        if conclusion in FAILING_CONCLUSIONS:
            count += 1
        elif conclusion in DECISIVE_CONCLUSIONS:  # a success ends the streak
            break
        # else: cancelled/in-progress/neutral — skip without ending the streak
    return count


def _latest_success(runs: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for run in _sorted_newest_first(runs):
        if run.get("conclusion") == "success":
            return run
    return None


def classify_workflow_run(
    name: str,
    file: str,
    runs: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify one workflow into healthy / failing / unknown from its run list.

    ``failing`` = the latest decisive run is in FAILING_CONCLUSIONS. ``healthy`` =
    the latest decisive run is a success. ``unknown`` = no decisive run at all
    (never ran, or only cancelled/in-progress) — never files noise.
    """
    runs = list(runs)
    latest = select_latest_decisive_run(runs)
    last_success = _latest_success(runs)
    last_success_url = last_success.get("html_url") if last_success else None
    last_success_at = last_success.get("created_at") if last_success else None

    if latest is None:
        category = "unknown"
        conclusion = None
        run_url = None
        run_created_at = None
    elif latest.get("conclusion") in FAILING_CONCLUSIONS:
        category = "failing"
        conclusion = latest.get("conclusion")
        run_url = latest.get("html_url")
        run_created_at = latest.get("created_at")
    else:
        category = "healthy"
        conclusion = latest.get("conclusion")
        run_url = latest.get("html_url")
        run_created_at = latest.get("created_at")

    return {
        "workflow": name,
        "file": file,
        "category": category,
        "conclusion": conclusion,
        "run_url": run_url,
        "run_created_at": run_created_at,
        "consecutive_failures": count_leading_failures(runs),
        "last_success_url": last_success_url,
        "last_success_at": last_success_at,
    }


def selfheal_liveness_verdict(
    beacon: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Flag the self-heal routine as failing only if its beacon EXISTS but is stale.

    A never-set beacon (None) returns None — the routine may simply not be
    configured yet, and we refuse to file rollout noise or alarm on a token-scope
    read failure. A beacon with an unparseable timestamp is treated as quiet for
    the same reason.
    """
    if beacon is None or not isinstance(beacon, Mapping):
        return None
    now = now or datetime.now(timezone.utc)
    run_at = _parse_ts(beacon.get("run_at"))
    if run_at is None:
        return None
    age_h = (now - run_at).total_seconds() / 3600.0
    if age_h <= SELFHEAL_MAX_AGE_H:
        return None
    return {
        "workflow": SELFHEAL_SOURCE,
        "file": None,
        "category": "failing",
        "conclusion": "stale_heartbeat",
        "run_url": None,
        "run_created_at": None,
        "consecutive_failures": 0,
        "last_success_url": None,
        "last_success_at": beacon.get("run_at"),
        "age_hours": round(age_h, 1),
    }


def run_workflow_health(
    runs_by_workflow: Mapping[str, Mapping[str, Any]],
    *,
    beacon: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify every workflow + the self-heal heartbeat; bucket and summarize."""
    now = now or datetime.now(timezone.utc)
    verdicts: list[dict[str, Any]] = []
    for name, info in runs_by_workflow.items():
        file = str(info.get("file") or "")
        runs = info.get("runs") or []
        verdicts.append(classify_workflow_run(name, file, runs, now=now))

    liveness = selfheal_liveness_verdict(beacon, now=now)
    if liveness is not None:
        verdicts.append(liveness)

    failing = [v for v in verdicts if v["category"] == "failing"]
    healthy = [v for v in verdicts if v["category"] == "healthy"]
    unknown = [v for v in verdicts if v["category"] == "unknown"]
    return {
        "has_failures": len(failing) > 0,
        "failing": failing,
        "healthy": healthy,
        "unknown": unknown,
        "summary": {
            "failing": len(failing),
            "healthy": len(healthy),
            "unknown": len(unknown),
            "total": len(verdicts),
        },
    }


def build_workflow_issue_body(v: Mapping[str, Any]) -> str:
    """Markdown body for one failing workflow's issue."""
    if v["workflow"] == SELFHEAL_SOURCE:
        age = v.get("age_hours")
        age_note = f"{age}h old" if age is not None else "missing"
        return "\n".join([
            "**The self-heal routine's heartbeat is stale** "
            f"(last beacon {age_note}; threshold {SELFHEAL_MAX_AGE_H}h).",
            "",
            "The daily workflow-self-heal routine has not checked in. Until it "
            "recovers, red scheduled workflows will NOT be auto-fixed.",
            "",
            "- **What to do:** confirm the routine still exists and is bound to "
            "`andrewzp/theheat`; re-run it; check `docs/runbooks/workflow-self-heal.md`.",
            f"- **Last beacon:** `{v.get('last_success_at') or 'never'}`",
            "",
            "_Auto-filed by the workflow-health observer. Auto-closes when the "
            "routine writes a fresh beacon._",
        ])

    conclusion = v.get("conclusion") or "failure"
    run_url = v.get("run_url") or "(unknown run)"
    streak = v.get("consecutive_failures") or 0
    streak_note = f"{streak} consecutive failed run(s)" if streak else "failing"
    last_success = v.get("last_success_url")
    last_success_note = (
        f"[last green run]({last_success}) at `{v.get('last_success_at')}`"
        if last_success else "no green run in the recent window"
    )
    return "\n".join([
        f"**`{v['workflow']}` is failing on `main`** — `{conclusion}` ({streak_note}).",
        "",
        f"- **Latest red run:** {run_url}",
        f"- **Last success:** {last_success_note}",
        f"- **Workflow file:** `.github/workflows/{v.get('file')}`",
        "",
        "_Auto-filed by the workflow-health observer. The daily self-heal routine "
        f"will attempt a fix. Auto-closes when `{v['workflow']}` is green again._",
    ])


def _issue_labels() -> list[str]:
    return [LABEL, CAUSE_LABEL]


def _open_issue_number(issue: Any) -> int:
    if isinstance(issue, Mapping):
        return int(issue["number"])
    return int(issue)


def _open_issue_body(issue: Any) -> str:
    if isinstance(issue, Mapping):
        return str(issue.get("body") or "")
    return ""


def _open_issue_labels(issue: Any) -> set[str]:
    labels = issue.get("labels") if isinstance(issue, Mapping) else []
    names: set[str] = set()
    for label in labels or []:
        name = label.get("name") if isinstance(label, Mapping) else label
        if name:
            names.add(str(name))
    return names


def _normalise_failing(
    failing: Mapping[str, Mapping[str, Any]] | set[str] | Iterable[str],
) -> dict[str, Mapping[str, Any] | None]:
    if isinstance(failing, Mapping):
        return dict(failing)
    return {workflow: None for workflow in failing}


def plan_workflow_issue_actions(
    failing: Mapping[str, Mapping[str, Any]] | set[str] | Iterable[str],
    recovered: Iterable[str],
    open_issues: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Reconcile open ``workflow-health`` issues against observed state.

    - Create for every failing workflow without an issue.
    - Update a still-failing workflow's issue only when its body/labels drifted.
    - **Close ONLY a workflow we positively observed RECOVERED** (a green decisive
      run, or a fresh self-heal beacon). A workflow that is merely *not failing*
      — e.g. its run fetch failed and it classified ``unknown`` — is LEFT ALONE,
      never auto-closed. Closing on "not failing" was a false-recovery bug: a
      transient Actions-API blip would close a still-red workflow's issue with a
      "recovered" comment, then re-open it next hour (and could make the self-heal
      routine stand down on a still-broken workflow). Keyed by workflow name.
    """
    failing_map = _normalise_failing(failing)
    failing_workflows = set(failing_map)
    recovered_set = set(recovered)
    actions: list[dict[str, Any]] = []

    for workflow in sorted(failing_workflows - set(open_issues)):
        verdict = failing_map[workflow]
        action: dict[str, Any] = {"action": "create", "workflow": workflow}
        if verdict is not None:
            action["labels"] = _issue_labels()
            action["body"] = build_workflow_issue_body(verdict)
        actions.append(action)

    for workflow in sorted(failing_workflows & set(open_issues)):
        verdict = failing_map[workflow]
        if verdict is None:
            continue
        issue = open_issues[workflow]
        expected_body = build_workflow_issue_body(verdict)
        expected_labels = _issue_labels()
        existing_labels = _open_issue_labels(issue)
        labels_current = set(expected_labels).issubset(existing_labels)
        body_current = _open_issue_body(issue) == expected_body
        if labels_current and body_current:
            continue
        actions.append({
            "action": "update",
            "workflow": workflow,
            "number": _open_issue_number(issue),
            "labels": expected_labels,
            "body": expected_body,
        })

    for workflow in sorted(recovered_set & set(open_issues)):
        actions.append({
            "action": "close",
            "workflow": workflow,
            "number": _open_issue_number(open_issues[workflow]),
        })
    return actions


# --------------------------------------------------------------------------- #
# Live reconciliation via gh (mirrors scripts/source_health_sentinel.py).
# --------------------------------------------------------------------------- #

def _repo() -> str:
    return os.environ.get("THEHEAT_REPO") or "andrewzp/theheat"


def _branch() -> str:
    return os.environ.get("THEHEAT_AUTOMATION_BRANCH") or "main"


def _run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def _gh_api(path: str) -> Any:
    """GET a GitHub REST path via ``gh api``; returns parsed JSON or None on error."""
    try:
        out = _run_gh(["api", path], check=True).stdout
        return json.loads(out or "null")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[workflow-health] gh api {path} failed: {exc!r}", file=sys.stderr)
        return None


def fetch_runs_by_workflow(per_page: int = 20) -> dict[str, dict[str, Any]]:
    """Fetch recent ``main`` runs for each monitored workflow via the Actions API.

    Each entry carries ``fetch_ok``: False marks a failed/empty gh-api call so a
    transient outage is never mistaken for "no runs / recovered" downstream.
    """
    repo = _repo()
    branch = _branch()
    result: dict[str, dict[str, Any]] = {}
    for wf in MONITORED_WORKFLOWS:
        path = (
            f"repos/{repo}/actions/workflows/{wf['file']}/runs"
            f"?branch={branch}&per_page={per_page}&exclude_pull_requests=true"
        )
        data = _gh_api(path)
        if not isinstance(data, Mapping):
            result[wf["name"]] = {"file": wf["file"], "runs": [], "fetch_ok": False}
            continue
        runs = data.get("workflow_runs") or []
        result[wf["name"]] = {"file": wf["file"], "runs": runs, "fetch_ok": True}
    return result


def fetch_selfheal_beacon() -> dict[str, Any] | None:
    """Read the SELFHEAL_BEACON beacon; None if unset, empty, or unparseable.

    Env-first: in CI the repo variable is injected via ``vars.SELFHEAL_BEACON``
    (the default GITHUB_TOKEN cannot read the Actions *variables* REST endpoint —
    that needs a dedicated Variables permission that is not even a grantable
    GITHUB_TOKEN scope, so an API read would silently return None and the
    meta-guard would never fire). When the env var is present it is authoritative.
    Locally (no env var) fall back to ``gh api``, which uses the user's PAT.
    """
    if BEACON_VARIABLE in os.environ:
        raw = os.environ[BEACON_VARIABLE].strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    data = _gh_api(f"repos/{_repo()}/actions/variables/{BEACON_VARIABLE}")
    if not isinstance(data, Mapping):
        return None
    value = data.get("value")
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _list_open_workflow_issues() -> dict[str, dict[str, Any]] | None:
    """Map workflow name -> open issue, for issues this observer filed.

    Returns None (not {}) when the listing itself fails, so the caller can tell
    "no open issues" from "couldn't list" and skip mutations rather than create
    duplicates of every still-open issue.
    """
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[workflow-health] could not list issues: {exc!r}", file=sys.stderr)
        return None
    result: dict[str, dict[str, Any]] = {}
    for it in items:
        title = it.get("title", "")
        if title.startswith(TITLE_PREFIX):
            labels = [
                label["name"] for label in it.get("labels") or []
                if isinstance(label, dict) and label.get("name")
            ]
            result[title[len(TITLE_PREFIX):].strip()] = {
                "number": it["number"],
                "body": it.get("body") or "",
                "labels": labels,
            }
    return result


def _create_issue(workflow: str, verdict: Mapping[str, Any]) -> None:
    title = f"{TITLE_PREFIX}{workflow}"
    body = build_workflow_issue_body(verdict)
    base = ["issue", "create", "--title", title, "--body", body]
    for label in _issue_labels():
        base.extend(["--label", label])
    r = _run_gh([*base, "--assignee", "andrewzp"], check=False)
    if r.returncode != 0:  # assignee may be invalid in some envs — file anyway
        _run_gh(base, check=False)
    print(f"[workflow-health] opened issue: {title}")


def _update_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    _run_gh(args, check=False)
    print(f"[workflow-health] updated issue #{action['number']} ({action['workflow']} still failing)")


def _close_issue(number: int, workflow: str) -> None:
    if workflow == SELFHEAL_SOURCE:
        comment = "Self-heal routine wrote a fresh beacon — recovered. Auto-closed."
    else:
        comment = (
            f"`{workflow}` is green again — recovered. "
            "Auto-closed by the workflow-health observer."
        )
    _run_gh(["issue", "close", str(number), "--comment", comment], check=False)
    print(f"[workflow-health] closed issue #{number} ({workflow} recovered)")


def _ensure_labels() -> None:
    _run_gh(["label", "create", LABEL, "-c", "B60205",
             "-d", "A scheduled workflow is red on main; auto-filed by the workflow-health observer"],
            check=False)
    _run_gh(["label", "create", CAUSE_LABEL, "-c", "D73A49",
             "-d", "Failure likely fixable in our code/CI/config"], check=False)


def _print_report(report: Mapping[str, Any]) -> None:
    s = report["summary"]
    print(
        f"[workflow-health] {s['total']} checks: "
        f"{s['failing']} failing, {s['healthy']} healthy, {s['unknown']} unknown"
    )
    for v in report["failing"]:
        print(f"  FAILING  {v['workflow']} [{v.get('conclusion')}]: {v.get('run_url')}")


def main(argv: list[str] | None = None) -> int:
    """Fetch live runs, classify, and reconcile per-workflow issues via gh.

    Live in CI (GITHUB_ACTIONS=true) or with --apply; otherwise dry-run (prints
    the failing set, mutates nothing). Always exits 0 — a reporter, never a gate.
    """
    argv = argv if argv is not None else sys.argv[1:]
    apply = "--apply" in argv or os.environ.get("GITHUB_ACTIONS") == "true"

    runs_by_workflow = fetch_runs_by_workflow()
    beacon = fetch_selfheal_beacon()
    report = run_workflow_health(runs_by_workflow, beacon=beacon)
    _print_report(report)

    if not apply:
        print("[workflow-health] dry-run — pass --apply or run in CI to open/close issues.")
        return 0

    # Total Actions-API outage: every workflow fetch failed. Reconciling now would
    # be reconciling against no information — bail like the source sentinel does on
    # an unreadable state.json. Mutate nothing.
    if runs_by_workflow and all(not info.get("fetch_ok", True) for info in runs_by_workflow.values()):
        print("[workflow-health] all workflow-run fetches failed — skipping reconcile.", file=sys.stderr)
        return 0

    open_issues = _list_open_workflow_issues()
    if open_issues is None:
        print("[workflow-health] could not list open issues — skipping reconcile.", file=sys.stderr)
        return 0

    _ensure_labels()
    failing_map = {v["workflow"]: v for v in report["failing"]}
    # Close ONLY workflows we positively observed recovered: a green decisive run,
    # or (for the self-heal heartbeat) a fresh beacon. Never close on "not failing"
    # — an unknown/fetch-failed workflow keeps its open issue.
    recovered = {v["workflow"] for v in report["healthy"]}
    if beacon is not None and selfheal_liveness_verdict(beacon) is None:
        recovered.add(SELFHEAL_SOURCE)

    for action in plan_workflow_issue_actions(failing_map, recovered, open_issues):
        if action["action"] == "create":
            _create_issue(action["workflow"], failing_map[action["workflow"]])
        elif action["action"] == "update":
            _update_issue(action)
        else:
            _close_issue(action["number"], action["workflow"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
