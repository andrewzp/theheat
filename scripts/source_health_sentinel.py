#!/usr/bin/env python3
"""Daily source-health sentinel.

Reads the bot's gist ``state.json`` and turns every currently-failing source into
a tracked GitHub issue, so the operator never has to watch the dashboard. The
governing idea: EVERY failure is our problem, because every failure is a gap in
the product (a tweet we can't make). The sentinel does not decide whether a
failure is "worth" surfacing — if a source is failing, it gets an issue.

The upstream/ours classification survives only as a LABEL on the issue that tells
the operator the right fix:
  - ``ours``     — patch our code, rotate a credential, update a moved endpoint.
  - ``external`` — NASA/gov is down; confirm the outage and, if it persists,
    switch product/endpoint or find an alternate feed so the product stays whole.

Issues auto-close when the source succeeds again, so the open-issues list is a
self-maintaining view of what is broken right now.

Classification + the create/close PLAN are pure and unit-tested (see
``tests/test_source_health_sentinel.py``). ``main()`` reconciles real issues via
``gh`` (live in CI; dry-run locally unless ``--apply``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess
import sys
from typing import Any

# How many of the last ACTIVE (non-skip) attempts decide a source's state.
RECENT_WINDOW = 5
# Below this recent success rate, a source is "failing" (mostly broken → issue).
# At or above it the source is degraded (occasional blips) or healthy — still
# producing data, so no issue. A single transient blip never opens an issue.
FAILING_RATE = 0.5
LIVENESS_MAX_AGE_H = 6
LIVENESS_SOURCE = "_pipeline_liveness"
BOT_ACTIONS_URL = "https://github.com/andrewzp/theheat/actions/workflows/bot.yml"
YIELD_WATCH_MIN_RUNS = 10
YIELD_WATCH_TITLE = "Yield watch: sources succeeding with zero observations"
YIELD_WATCH_MARKER = "<!-- source-health-yield-watch -->"
YIELD_QUIET_OK = frozenset({
    "synthesis_fire_drought_heat",
    "manual_publish",
    "auto_publish_due",
    "copernicus_ems",
    "leaderboard",
    "load_cities",
    "ozone_hole",
    "nao",
    "ao",
    "pdo",
    "enso",
    "nao_ao_alignment",
})

LABEL = "source-health-sentinel"
TITLE_PREFIX = "Source down: "
CAUSE_LABELS = frozenset({"ours", "external", "unknown"})

# "skipped" is a deliberate cadence idle (e.g. "runs Mondays only") and must
# never count as an attempt or trip an alarm.
_ACTIVE_STATUSES = {"success", "failed", "degraded", "partial_failure"}

# OUR_BUG: actionable in our code. Checked FIRST so auth/code/parse wins over a
# coincidental network token. Bare Earthdata host text is handled only when paired
# with 403 by the credential-class override below.
_OUR_BUG_RE = re.compile(
    r"\b(401|404|410)\b"
    r"|Unauthorized|EARTHDATA_TOKEN|invalid token|token expired|expired token|credential"
    r"|AttributeError|KeyError|TypeError|ValueError|IndexError|NameError"
    r"|UnboundLocalError|ZeroDivisionError|RecursionError|JSONDecodeError"
    r"|Expecting value"
    r"|schema drift|missing required field|expected JSON object"
    r"|could not parse|invalid literal|Not Found",
    re.IGNORECASE,
)
# UPSTREAM: external. NASA 5xx, read/connect timeouts, connection failures, and
# generic gov rate-limits (403/429). Earthdata 403 credential failures are checked
# before this regex.
_UPSTREAM_RE = re.compile(
    r"\b(403|429|50\d)\b"
    r"|Server Error|Bad Gateway|Service Unavailable|Gateway Time"
    r"|ReadTimeout|ConnectTimeout|Timeout|timed out"
    r"|ConnectionError|Connection refused|Connection reset|Max retries"
    r"|Network is unreachable|Name or service not known"
    r"|Temporary failure in name resolution|HTTPSConnectionPool|HTTPConnectionPool"
    r"|Forbidden|Too Many Requests",
    re.IGNORECASE,
)
_EARTHDATA_CREDENTIAL_HOST_RE = re.compile(r"earthdata|urs\.earthdata|EDL|podaac", re.IGNORECASE)
_HTTP_403_RE = re.compile(r"\b403\b")

# A run served by a redundancy witness (src/data/_witness.py) records status
# "degraded" with the diagnostic "served via <leg>". Surfacing the leg lets the
# dashboard render "firms — degraded (served via noaa_hms)" instead of an error,
# and warns the operator the primary is down even while backup drafts still flow.
# Kept byte-equivalent with dashboard/lib/source-health.js parseServedVia.
_SERVED_VIA_RE = re.compile(r"served via (\S+)")


def parse_served_via(diagnostic: str | None) -> str | None:
    """Return the backup leg from a ``served via <leg>`` degraded diagnostic, else None."""
    if not diagnostic:
        return None
    match = _SERVED_VIA_RE.search(str(diagnostic))
    return match.group(1) if match else None

# error_class -> (cause label, what-to-do hint shown in the issue)
_CAUSE = {
    "our_bug": ("ours", "Patch on our side — a code error, expired credential, or a moved endpoint."),
    "upstream": ("external", "NASA/gov is down. Confirm the outage; if it persists, switch product/endpoint or find an alternate feed so the product doesn't go dark."),
    "unknown": ("unknown", "Unrecognized failure — investigate the error directly."),
    "none": ("unknown", "Failing with no recorded error — investigate."),
}


def classify_error(last_error: str | None) -> str:
    """none / our_bug / upstream / unknown. our_bug is checked first; a non-empty
    string matching neither is ``unknown`` (escalated, never silently filed)."""
    if last_error is None:
        return "none"
    text = str(last_error).strip()
    if not text or text == "-":
        return "none"
    if _OUR_BUG_RE.search(text):
        return "our_bug"
    if _HTTP_403_RE.search(text) and _EARTHDATA_CREDENTIAL_HOST_RE.search(text):
        return "our_bug"
    if _UPSTREAM_RE.search(text):
        return "upstream"
    return "unknown"


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days_since(ts: str | None, now: datetime) -> float | None:
    parsed = _parse_ts(ts)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 86400.0


def _alerts_liveness_verdict(
    run_history: list[dict[str, Any]] | None,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    if run_history is None:
        return None

    newest_alerts: datetime | None = None
    for run in run_history:
        if not isinstance(run, Mapping):
            continue
        if run.get("mode") not in ("alerts", "both"):
            continue
        parsed = _parse_ts(run.get("started_at"))
        if parsed is None:
            continue
        if newest_alerts is None or parsed > newest_alerts:
            newest_alerts = parsed

    max_age = timedelta(hours=LIVENESS_MAX_AGE_H)
    if newest_alerts is not None and now - newest_alerts <= max_age:
        return None

    last_success = (
        newest_alerts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if newest_alerts is not None else None
    )
    age_note = (
        f"{(now - newest_alerts).total_seconds() / 3600:.1f}h old"
        if newest_alerts is not None else "missing"
    )
    return {
        "source": LIVENESS_SOURCE,
        "category": "failing",
        "cause": "ours",
        "suggested_action": (
            f"Alerts lane is stale ({age_note}). Inspect the bot workflow Actions page: {BOT_ACTIONS_URL}."
        ),
        "error_class": "other",
        "last_error": (
            "alerts/both lane stale; hourly auto_publish_due can keep run_history fresh "
            f"without proving alert ingestion. Actions: {BOT_ACTIONS_URL}"
        ),
        "last_success_ts": last_success,
        "days_since_success": round((now - newest_alerts).total_seconds() / 86400.0, 1)
        if newest_alerts is not None else None,
        "recent_success_rate": 0.0,
    }


def classify_source(
    name: str,
    health: dict[str, Any],
    *,
    now: datetime | None = None,
    recent_window: int = RECENT_WINDOW,
) -> dict[str, Any]:
    """Classify one source into healthy / degraded / idle / failing.

    Only ``failing`` opens an issue. ``failing`` = the source is broken right now
    (recent active success rate below FAILING_RATE), regardless of cause or how
    long it has been down. ``idle`` = recent rows are all cadence skips.
    """
    now = now or datetime.now(timezone.utc)
    runs = health.get("runs") or []
    statuses = [r.get("status") for r in runs if isinstance(r, dict)]
    last_error = health.get("last_error") or ""
    error_class = classify_error(last_error)
    days_dark = _days_since(health.get("last_success_ts"), now)

    # Judge the RECENT run window (skips included), not all-time active attempts.
    # A source whose recent runs are all cadence skips is IDLE — it isn't
    # attempting right now, so it isn't currently failing, no matter how its last
    # attempt (days ago, outside the window) went. Reaching back past the skips to
    # stale attempts is what wrongly flagged idle low-cadence sources as failing.
    recent = [s for s in statuses[-recent_window:] if s in _ACTIVE_STATUSES]
    recent_rate: float | None
    if not recent:
        category = "idle"
        recent_rate = None
    else:
        rate = recent.count("success") / len(recent)
        recent_rate = rate
        # `failing` (the issue-filing trigger) requires HARD failures — runs that
        # produced no data. A source that runs `degraded` every cycle is still
        # producing data (just partial), so it stays `degraded`, never `failing`,
        # regardless of its clean-success rate. Mirrors the dashboard's
        # classifyHealth, which gates `unhealthy` on hard failures the same way.
        # (`partial_failure` folds into `degraded` in record_source_health, so the
        # `failed` counter is the complete hard-failure count.) Without this, a
        # permanently-partial source reads as 0% success → false `failing` issue
        # (air_quality #201, which loses a rate-limited tail chunk every run).
        has_hard_failure = int(health.get("failed") or 0) > 0
        if rate >= 1.0:
            category = "healthy"
        elif has_hard_failure and rate < FAILING_RATE:
            category = "failing"
        else:
            category = "degraded"

    cause, action = _CAUSE.get(error_class, _CAUSE["unknown"])
    # Only meaningful while degraded — a recovered primary (back to healthy)
    # clears the stale "served via" diagnostic so it can't masquerade.
    served_via = parse_served_via(last_error) if category == "degraded" else None
    return {
        "source": name,
        "category": category,
        "cause": cause if category == "failing" else None,
        "suggested_action": action if category == "failing" else None,
        "error_class": error_class,
        "last_error": (last_error or "")[:300],
        "last_success_ts": health.get("last_success_ts"),
        "days_since_success": round(days_dark, 1) if days_dark is not None else None,
        "recent_success_rate": recent_rate,
        "served_via": served_via,
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def yield_watch_sources(source_health: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Advisory sources that report green while yielding zero observations."""
    watched: list[dict[str, Any]] = []
    for source, health in sorted((source_health or {}).items()):
        if source in YIELD_QUIET_OK or not isinstance(health, Mapping):
            continue
        runs = [run for run in health.get("runs") or [] if isinstance(run, Mapping)]
        if len(runs) < YIELD_WATCH_MIN_RUNS:
            continue
        if any(str(run.get("status") or "") != "success" for run in runs):
            continue
        if _int_or_zero(health.get("total_observed")) != 0:
            continue
        watched.append({
            "source": source,
            "runs": len(runs),
            "total_observed": 0,
            "last_success_ts": health.get("last_success_ts"),
        })
    return watched


def run_sentinel(
    source_health: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    recent_window: int = RECENT_WINDOW,
    run_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify all sources and bucket them. ``has_failures`` gates the issues."""
    now = now or datetime.now(timezone.utc)
    verdicts = [
        classify_source(name, health, now=now, recent_window=recent_window)
        for name, health in sorted((source_health or {}).items())
        if isinstance(health, dict)
    ]
    liveness = _alerts_liveness_verdict(run_history, now=now)
    if liveness is not None:
        verdicts.append(liveness)
    failing = [v for v in verdicts if v["category"] == "failing"]
    degraded = [v for v in verdicts if v["category"] == "degraded"]
    healthy = [v for v in verdicts if v["category"] in ("healthy", "idle")]
    return {
        "has_failures": len(failing) > 0,
        "failing": failing,
        "degraded": degraded,
        "healthy": healthy,
        "summary": {
            "failing": len(failing),
            "degraded": len(degraded),
            "healthy": len(healthy),
            "total": len(verdicts),
        },
    }


def _issue_labels(v: Mapping[str, Any]) -> list[str]:
    cause = str(v.get("cause") or "unknown")
    if cause not in CAUSE_LABELS:
        cause = "unknown"
    return [LABEL, cause]


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
        if isinstance(label, Mapping):
            name = label.get("name")
        else:
            name = label
        if name:
            names.add(str(name))
    return names


def _normalise_failing(
    failing: Mapping[str, Mapping[str, Any]] | set[str],
) -> dict[str, Mapping[str, Any] | None]:
    if isinstance(failing, Mapping):
        return dict(failing)
    return {source: None for source in failing}


def plan_issue_actions(
    failing: Mapping[str, Mapping[str, Any]] | set[str],
    open_issues: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reconcile the failing set against currently-open sentinel issues.

    Create an issue for every failing source without one; close the issue of
    every source that has recovered (open issue but no longer failing). Sources
    that are still failing and already have an issue are updated only if their
    cause label or body changed, so issues don't go stale when an external outage
    turns into an ours/auth/code failure.
    """
    failing_map = _normalise_failing(failing)
    failing_sources = set(failing_map)
    actions: list[dict[str, Any]] = []
    for source in sorted(failing_sources - set(open_issues)):
        verdict = failing_map[source]
        action = {"action": "create", "source": source}
        if verdict is not None:
            action["labels"] = _issue_labels(verdict)
            action["body"] = build_issue_body(verdict)
        actions.append(action)

    for source in sorted(failing_sources & set(open_issues)):
        verdict = failing_map[source]
        if verdict is None:
            continue
        issue = open_issues[source]
        expected_body = build_issue_body(verdict)
        expected_labels = _issue_labels(verdict)
        existing_labels = _open_issue_labels(issue)
        stale_cause_labels = sorted((existing_labels & CAUSE_LABELS) - set(expected_labels))
        labels_current = set(expected_labels).issubset(existing_labels) and not stale_cause_labels
        body_current = _open_issue_body(issue) == expected_body
        if labels_current and body_current:
            continue
        action = {
            "action": "update",
            "source": source,
            "number": _open_issue_number(issue),
            "labels": expected_labels,
            "body": expected_body,
        }
        if stale_cause_labels:
            action["remove_labels"] = stale_cause_labels
        actions.append(action)

    for source in sorted(set(open_issues) - failing_sources):
        actions.append({
            "action": "close",
            "source": source,
            "number": _open_issue_number(open_issues[source]),
        })
    return actions


def build_issue_body(v: dict[str, Any]) -> str:
    """Markdown body for a single failing source's issue."""
    days = v["days_since_success"]
    last_success = v["last_success_ts"] or "never"
    when = f"{last_success} ({days} days ago)" if days is not None else last_success
    rate = v["recent_success_rate"]
    rate_str = f"{rate:.0%}" if rate is not None else "n/a"
    return "\n".join([
        f"**`{v['source']}` is failing** — it can't contribute to the product right now.",
        "",
        f"- **Cause:** {v['cause']} ({v['error_class']})",
        f"- **What to do:** {v['suggested_action']}",
        f"- **Last error:** `{v['last_error']}`",
        f"- **Last success:** `{when}`",
        f"- **Recent success rate:** {rate_str}",
        "",
        f"_Auto-filed by the source-health sentinel. Auto-closes when `{v['source']}` succeeds again._",
    ])


def build_yield_watch_body(watched: list[dict[str, Any]]) -> str:
    lines = [
        YIELD_WATCH_MARKER,
        "**Sources succeeding with zero observations**",
        "",
        "These sources are green but have produced zero observations across their retained source-health window.",
        "This is advisory and labeled `unknown`; investigate whether the source is seasonal/quiet or silently empty.",
        "",
        "## Yield watch",
    ]
    for row in watched:
        last_success = row.get("last_success_ts") or "unknown"
        lines.append(f"- `{row['source']}`: {row['runs']} success runs, 0 observed, last success {last_success}")
    lines.extend([
        "",
        "_Auto-maintained by the source-health sentinel. The issue closes when the watch list is empty._",
    ])
    return "\n".join(lines)


def _print_report(report: dict[str, Any]) -> None:
    s = report["summary"]
    print(
        f"[sentinel] {s['total']} sources: "
        f"{s['failing']} failing, {s['degraded']} degraded, {s['healthy']} healthy/idle"
    )
    for v in report["failing"]:
        print(f"  FAILING  {v['source']} [{v['cause']}]: {v['last_error'][:80]}")
    for v in report["degraded"]:
        if v.get("served_via"):
            print(
                f"  BACKUP   {v['source']} primary down — served via {v['served_via']} "
                f"(drafts still flow; manual queue still gates)"
            )


def _run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def _list_open_sentinel_issues() -> dict[str, dict[str, Any]]:
    """Map source name -> open issue number, from issues this sentinel filed."""
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list issues: {exc!r}", file=sys.stderr)
        return {}
    result: dict[str, dict[str, Any]] = {}
    for it in items:
        title = it.get("title", "")
        if title.startswith(TITLE_PREFIX):
            labels = []
            for label in it.get("labels") or []:
                if isinstance(label, dict) and label.get("name"):
                    labels.append(label["name"])
            result[title[len(TITLE_PREFIX):].strip()] = {
                "number": it["number"],
                "body": it.get("body") or "",
                "labels": labels,
            }
    return result


def _open_yield_watch_issue() -> dict[str, Any] | None:
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list yield-watch issue: {exc!r}", file=sys.stderr)
        return None
    for item in items:
        if item.get("title") == YIELD_WATCH_TITLE:
            return item
    return None


def plan_yield_watch_action(
    watched: list[dict[str, Any]],
    open_issue: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if watched:
        body = build_yield_watch_body(watched)
        labels = [LABEL, "unknown"]
        if open_issue is None:
            return {"action": "create_yield_watch", "body": body, "labels": labels}
        existing_labels = _open_issue_labels(open_issue)
        stale_cause_labels = sorted((existing_labels & CAUSE_LABELS) - set(labels))
        labels_current = set(labels).issubset(existing_labels) and not stale_cause_labels
        body_current = _open_issue_body(open_issue) == body
        if labels_current and body_current:
            return None
        action = {
            "action": "update_yield_watch",
            "number": _open_issue_number(open_issue),
            "body": body,
            "labels": labels,
        }
        if stale_cause_labels:
            action["remove_labels"] = stale_cause_labels
        return action
    if open_issue is not None:
        return {"action": "close_yield_watch", "number": _open_issue_number(open_issue)}
    return None


def _create_issue(v: dict[str, Any]) -> None:
    title = f"{TITLE_PREFIX}{v['source']}"
    body = build_issue_body(v)
    base = ["issue", "create", "--title", title, "--body", body]
    for label in _issue_labels(v):
        base.extend(["--label", label])
    r = _run_gh([*base, "--assignee", "andrewzp"], check=False)
    if r.returncode != 0:  # assignee may be invalid in some envs — file anyway
        _run_gh(base, check=False)
    print(f"[sentinel] opened issue: {title}")


def _create_yield_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "create", "--title", YIELD_WATCH_TITLE, "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] opened yield-watch issue: {YIELD_WATCH_TITLE}")


def _update_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    for label in action.get("remove_labels") or []:
        args.extend(["--remove-label", str(label)])
    _run_gh(args)
    print(f"[sentinel] updated issue #{action['number']} ({action['source']} still failing)")


def _update_yield_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    for label in action.get("remove_labels") or []:
        args.extend(["--remove-label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] updated yield-watch issue #{action['number']}")


def _close_issue(number: int, source: str) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         f"`{source}` is succeeding again — recovered. Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed issue #{number} ({source} recovered)")


def _close_yield_watch_issue(number: int) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         "Yield watch is empty. Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed yield-watch issue #{number}")


COVERAGE_WINDOW_DAYS = 21
COVERAGE_MIN_EVENTS = 20
COVERAGE_CONCENTRATION = 0.85
COVERAGE_DATA_FLOOR = 5
COVERAGE_WATCHED_CLASSES = ("heat",)  # extend per source instrumentation (Future)
COVERAGE_WATCH_TITLE = "Coverage watch: a global source may be blind to a region"
COVERAGE_WATCH_MARKER = "<!-- source-health-coverage-watch -->"


def _bot_is_drafting(run_history: list[dict] | None) -> bool:
    return any(
        str(r.get("mode") or "") in ("alerts", "both")
        for r in (run_history or [])
        if isinstance(r, Mapping)
    )


def coverage_watch(
    coverage_log: list[dict] | None,
    run_history: list[dict] | None,
    *,
    now: datetime,
) -> list[dict]:
    """Classify geographic concentration of events in the coverage_log.

    Returns a list of findings, each with shape:
        {cls, kind, dominant, share, events, distribution}

    Kinds:
      - ``no_data``          — bot is drafting but zero events (< DATA_FLOOR)
      - ``insufficient_data``— too few events to judge (>= DATA_FLOOR, < MIN_EVENTS)
      - ``mono_regional``    — >= MIN_EVENTS and one country or continent dominates
    """
    cutoff = (now - timedelta(days=COVERAGE_WINDOW_DAYS)).date().isoformat()
    drafting = _bot_is_drafting(run_history)
    findings: list[dict] = []
    for cls in COVERAGE_WATCHED_CLASSES:
        recs = [
            r for r in (coverage_log or [])
            if isinstance(r, Mapping)
            and r.get("cls") == cls
            and str(r.get("date") or "") >= cutoff
        ]
        n = len(recs)
        if n < COVERAGE_DATA_FLOOR:
            if drafting:
                findings.append({
                    "cls": cls,
                    "kind": "no_data",
                    "dominant": "—",
                    "share": 0.0,
                    "events": n,
                    "distribution": {},
                })
            continue
        if n < COVERAGE_MIN_EVENTS:
            findings.append({
                "cls": cls,
                "kind": "insufficient_data",
                "dominant": "—",
                "share": 0.0,
                "events": n,
                "distribution": {},
            })
            continue
        for axis in ("country", "continent"):  # country takes precedence
            counts: dict[str, int] = {}
            for r in recs:
                key = str(r.get(axis) or "Unknown")
                counts[key] = counts.get(key, 0) + 1
            dominant, top = max(counts.items(), key=lambda kv: kv[1])
            if dominant != "Unknown" and top / n >= COVERAGE_CONCENTRATION:
                findings.append({
                    "cls": cls,
                    "kind": "mono_regional",
                    "dominant": dominant,
                    "share": round(top / n, 3),
                    "events": n,
                    "distribution": dict(
                        sorted(counts.items(), key=lambda kv: -kv[1])
                    ),
                })
                break
    return findings


def main(argv: list[str] | None = None) -> int:
    """Read state.json, classify, and reconcile per-source issues via gh.

    Live in CI (GITHUB_ACTIONS=true) or with --apply; otherwise dry-run (prints
    the failing set, mutates nothing). Always exits 0 — a reporter, never a gate.
    """
    argv = argv if argv is not None else sys.argv[1:]
    positional = [a for a in argv if not a.startswith("--")]
    state_path = positional[0] if positional else "state.json"
    apply = "--apply" in argv or os.environ.get("GITHUB_ACTIONS") == "true"

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[sentinel] could not read {state_path}: {exc!r}", file=sys.stderr)
        return 0

    source_health = state.get("source_health") or {}
    report = run_sentinel(
        source_health,
        run_history=state.get("run_history") or [],
    )
    watched = yield_watch_sources(source_health)
    _print_report(report)
    if watched:
        print(f"[sentinel] yield-watch advisory: {len(watched)} zero-observed green source(s)")

    if not apply:
        print("[sentinel] dry-run — pass --apply or run in CI to open/close issues.")
        return 0

    _run_gh(["label", "create", LABEL, "-c", "B60205",
             "-d", "Auto-filed by the daily source-health sentinel"], check=False)
    _run_gh(["label", "create", "ours", "-c", "D73A49",
             "-d", "Source-health failure likely fixable in our code/auth/config"], check=False)
    _run_gh(["label", "create", "external", "-c", "FBCA04",
             "-d", "Source-health failure caused by upstream NASA/gov/provider outage"], check=False)
    _run_gh(["label", "create", "unknown", "-c", "6A737D",
             "-d", "Source-health failure cause is not classified yet"], check=False)
    failing_map = {v["source"]: v for v in report["failing"]}
    open_issues = _list_open_sentinel_issues()
    for action in plan_issue_actions(failing_map, open_issues):
        if action["action"] == "create":
            _create_issue(failing_map[action["source"]])
        elif action["action"] == "update":
            _update_issue(action)
        else:
            _close_issue(action["number"], action["source"])
    yield_action = plan_yield_watch_action(watched, _open_yield_watch_issue())
    if yield_action:
        if yield_action["action"] == "create_yield_watch":
            _create_yield_watch_issue(yield_action)
        elif yield_action["action"] == "update_yield_watch":
            _update_yield_watch_issue(yield_action)
        else:
            _close_yield_watch_issue(yield_action["number"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
