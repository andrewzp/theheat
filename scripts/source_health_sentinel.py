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


def build_coverage_watch_body(findings: list[dict]) -> str:
    lines = [
        COVERAGE_WATCH_MARKER,
        "**A global source may be blind to a region.**",
        "",
        "A signal class the bot covers globally has gone mono-regional (or stopped "
        "recording geography) — the class of failure that hid the US-only heat blind "
        "spot. Advisory; check whether a provider/source regressed. Auto-closes only "
        "when coverage actually diversifies.",
        "",
    ]
    for f in findings:
        if f["kind"] == "no_data":
            lines.append(
                f"- `{f['cls']}`: NO coverage data in {COVERAGE_WINDOW_DAYS}d while "
                f"drafting ({f['events']} records) — recording may be broken."
            )
        elif f["kind"] == "mono_regional":
            dist = ", ".join(f"{k}:{v}" for k, v in f["distribution"].items())
            lines.append(
                f"- `{f['cls']}`: {int(f['share'] * 100)}% concentrated in "
                f"**{f['dominant']}** over {f['events']} events. Distribution: {dist}"
            )
    lines += ["", "_Auto-maintained by the source-health sentinel coverage watch._"]
    return "\n".join(lines)


def _issue_worthy(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("kind") in ("mono_regional", "no_data")]


def _open_coverage_watch_issue() -> dict[str, Any] | None:
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list coverage-watch issue: {exc!r}", file=sys.stderr)
        return None
    for item in items:
        if item.get("title") == COVERAGE_WATCH_TITLE:
            return item
    return None


def plan_coverage_watch_action(
    findings: list[dict],
    open_issue: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    worthy = _issue_worthy(findings)
    if worthy:
        body = build_coverage_watch_body(worthy)
        if open_issue is None:
            return {"action": "create_coverage_watch", "body": body, "labels": [LABEL, "unknown"]}
        if _open_issue_body(open_issue).strip() != body.strip():
            return {
                "action": "update_coverage_watch",
                "number": _open_issue_number(open_issue),
                "body": body,
                "labels": [LABEL, "unknown"],
            }
        return None
    if open_issue is not None:
        return {"action": "close_coverage_watch", "number": _open_issue_number(open_issue)}
    return None


def _create_coverage_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "create", "--title", COVERAGE_WATCH_TITLE, "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] opened coverage-watch issue: {COVERAGE_WATCH_TITLE}")


def _update_coverage_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    for label in action.get("remove_labels") or []:
        args.extend(["--remove-label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] updated coverage-watch issue #{action['number']}")


def _close_coverage_watch_issue(number: int) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         "Coverage watch is clear. Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed coverage-watch issue #{number}")


# ---------------------------------------------------------------------------
# Writer watch — the writer silently down while runs stay green
# ---------------------------------------------------------------------------

WRITER_WATCH_WINDOW_HOURS = 24
WRITER_WATCH_TITLE = "Writer watch: the Anthropic writer is down (budget exhausted)"
WRITER_WATCH_MARKER = "<!-- source-health-writer-watch -->"


def writer_watch(
    suppressions: list[dict] | None,
    run_history: list[dict] | None,
    *,
    now: datetime,
) -> list[dict]:
    """Flag recent budget_exhausted kills — the writer down while runs stay green.

    The 2026-07-03 incident class: the Anthropic credit balance hit zero, every
    draft died with a graceful BudgetExhaustedError, bot runs kept reporting
    ``success``, and nothing alerted for hours. The suppression ledger already
    records each kill with ``stage="budget_exhausted"`` — this watch is the loud
    consumer of those rows. Gated on the bot actually drafting so a paused bot
    cannot false-alarm on stale rows.
    """
    if not _bot_is_drafting(run_history):
        return []
    cutoff = now - timedelta(hours=WRITER_WATCH_WINDOW_HOURS)
    # Parse timestamps (via _parse_ts) rather than comparing strings — a
    # malformed ts must be SKIPPED, not lexically treated as "recent", or a
    # junk row could false-open / pin the advisory issue forever.
    recent: list[str] = []
    for r in suppressions or []:
        if not isinstance(r, Mapping) or r.get("stage") != "budget_exhausted":
            continue
        parsed = _parse_ts(str(r.get("ts") or ""))
        if parsed is not None and parsed >= cutoff:
            recent.append(str(r.get("ts")))
    if not recent:
        return []
    return [{
        "kind": "budget_exhausted",
        "count": len(recent),
        "last_ts": max(recent),
    }]


def build_writer_watch_body(findings: list[dict]) -> str:
    f = findings[0]
    return "\n".join([
        WRITER_WATCH_MARKER,
        "**The writer is down: the Anthropic credit balance is exhausted.**",
        "",
        f"{f['count']} draft(s) died with `budget_exhausted` in the last "
        f"{WRITER_WATCH_WINDOW_HOURS}h (latest `{f['last_ts']}`). Bot runs keep "
        "reporting success while nothing drafts — this issue is the loud version.",
        "",
        "**Fix:** top up Anthropic API credits (the writer is the metered Anthropic "
        "API, separate from the operator's Claude Code plan), then confirm the next "
        "voice-regression run is green and fresh drafts appear.",
        "",
        "_Auto-maintained by the source-health sentinel writer watch. Auto-closes "
        "when no budget_exhausted kill lands in the window._",
    ])


def _open_writer_watch_issue() -> dict[str, Any] | None:
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list writer-watch issue: {exc!r}", file=sys.stderr)
        return None
    for item in items:
        if item.get("title") == WRITER_WATCH_TITLE:
            return item
    return None


def plan_writer_watch_action(
    findings: list[dict],
    open_issue: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if findings:
        body = build_writer_watch_body(findings)
        if open_issue is None:
            return {"action": "create_writer_watch", "body": body, "labels": [LABEL, "ours"]}
        if _open_issue_body(open_issue).strip() != body.strip():
            return {
                "action": "update_writer_watch",
                "number": _open_issue_number(open_issue),
                "body": body,
                "labels": [LABEL, "ours"],
            }
        return None
    if open_issue is not None:
        return {"action": "close_writer_watch", "number": _open_issue_number(open_issue)}
    return None


def _create_writer_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "create", "--title", WRITER_WATCH_TITLE, "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] opened writer-watch issue: {WRITER_WATCH_TITLE}")


def _update_writer_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] updated writer-watch issue #{action['number']}")


def _close_writer_watch_issue(number: int) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         "No budget_exhausted kills in the window — the writer is drafting again. "
         "Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed writer-watch issue #{number}")


# ---------------------------------------------------------------------------
# Queue watch — human-gated drafts aging unreviewed in the pending queue
# ---------------------------------------------------------------------------

QUEUE_WATCH_HOURS = 24
QUEUE_WATCH_TITLE = "Review-queue watch: manual drafts are aging unreviewed"
QUEUE_WATCH_MARKER = "<!-- source-health-queue-watch -->"


AUTO_OWNED_MODES = frozenset({"auto", "policy_auto"})


def _is_auto_owned(draft: Mapping[str, Any]) -> bool:
    """True only when the auto-post path actively owns this draft.

    The runnable state is ``auto_approve_at`` present AND an auto
    ``approval_mode`` — ``"auto"`` (Phase-B autoship / operator-requested
    suggested_auto) or ``"policy_auto"`` (the legacy armed_auto path, which
    draft_save.py sets alongside ``auto_approve_at``). Every demotion path
    clears both (posting.py). ``approval_policy.mode`` alone is only the
    RECOMMENDATION: an armed_auto-policy draft that failed closed to manual
    (no critic PASS, or demoted) must count as human-gated, or it ages out
    silently — exactly the blind spot this watch exists to close.
    """
    return (
        str(draft.get("approval_mode") or "") in AUTO_OWNED_MODES
        and bool(draft.get("auto_approve_at"))
    )


def queue_watch(
    drafts: list[dict] | None,
    *,
    now: datetime,
) -> list[dict]:
    """Flag pending human-gated drafts older than the window.

    The 2026-06-29→07-03 incident class: good drafts (a Prudhoe Bay all-time
    high, a marine-heatwave record) sat unreviewed in an unwatched manual queue
    until they went stale. The per-type TTL sweep eventually auto-rejects them
    (7d fast / 21d slow), so the un-alerted gap is the days in between — this
    watch closes it. Human-gated = anything the auto-post path does not
    actively own (see ``_is_auto_owned``); missing/unknown state counts as
    human-gated — nothing ages silently.
    """
    cutoff = now - timedelta(hours=QUEUE_WATCH_HOURS)
    stale: list[tuple[str, datetime]] = []
    for d in drafts or []:
        if not isinstance(d, Mapping) or d.get("status") != "pending":
            continue
        if _is_auto_owned(d):
            continue
        parsed = _parse_ts(str(d.get("created_at") or ""))
        if parsed is not None and parsed < cutoff:
            stale.append((str(d.get("type") or "unknown"), parsed))
    if not stale:
        return []
    oldest = min(ts for _, ts in stale)
    types: dict[str, int] = {}
    for t, _ in stale:
        types[t] = types.get(t, 0) + 1
    return [{
        "kind": "stale_reviews",
        "count": len(stale),
        "oldest_age_h": int((now - oldest).total_seconds() // 3600),
        "types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
    }]


def build_queue_watch_body(findings: list[dict]) -> str:
    f = findings[0]
    types = ", ".join(f"{k}:{v}" for k, v in f["types"].items())
    return "\n".join([
        QUEUE_WATCH_MARKER,
        "**Human-gated drafts are aging unreviewed in the pending queue.**",
        "",
        f"{f['count']} pending draft(s) have waited longer than {QUEUE_WATCH_HOURS}h "
        f"for review (oldest ≈ {f['oldest_age_h']}h). By type: {types}.",
        "",
        "**Fix:** review them on the dashboard — Approve+Post the good ones, Reject "
        "the rest. If nothing is done, the per-type TTL sweep auto-rejects them "
        "(default 7d; slow signals 21d), which silently discards any good story.",
        "",
        "_Auto-maintained by the source-health sentinel queue watch. Auto-closes "
        "when no human-gated pending draft is older than the window._",
    ])


def _open_queue_watch_issue() -> dict[str, Any] | None:
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list queue-watch issue: {exc!r}", file=sys.stderr)
        return None
    for item in items:
        if item.get("title") == QUEUE_WATCH_TITLE:
            return item
    return None


def plan_queue_watch_action(
    findings: list[dict],
    open_issue: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if findings:
        body = build_queue_watch_body(findings)
        if open_issue is None:
            return {"action": "create_queue_watch", "body": body, "labels": [LABEL, "ours"]}
        if _open_issue_body(open_issue).strip() != body.strip():
            return {
                "action": "update_queue_watch",
                "number": _open_issue_number(open_issue),
                "body": body,
                "labels": [LABEL, "ours"],
            }
        return None
    if open_issue is not None:
        return {"action": "close_queue_watch", "number": _open_issue_number(open_issue)}
    return None


def _create_queue_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "create", "--title", QUEUE_WATCH_TITLE, "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] opened queue-watch issue: {QUEUE_WATCH_TITLE}")


def _update_queue_watch_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] updated queue-watch issue #{action['number']}")


def _close_queue_watch_issue(number: int) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         "No human-gated pending draft is older than the review window. "
         "Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed queue-watch issue #{number}")


# ---------------------------------------------------------------------------
# Editor brief — ranked needs-you-now view of the pending queue
# ---------------------------------------------------------------------------

EDITOR_BRIEF_TITLE = "Editor brief: what the queue needs from you"
EDITOR_BRIEF_MARKER = "<!-- source-health-editor-brief -->"
EDITOR_BRIEF_MAX_ROWS = 10
EDITOR_BRIEF_URGENT_AGE_H = 24


def editor_brief(drafts: list[dict] | None, *, now: datetime) -> list[dict]:
    """One finding per human-gated pending draft, ranked needs-you-first.

    Ranking key (descending urgency):
      1. forecast window closing (tweet_date == today or tomorrow, for any
         draft — an elapsed-forecast draft is row 3's sweep's job, not ours)
      2. age >= EDITOR_BRIEF_URGENT_AGE_H
      3. score.total
    Auto-owned drafts (approval_mode auto/policy_auto with auto_approve_at)
    are excluded — the machine already owns them.
    Returns [] when nothing is pending → the issue auto-closes.
    """
    today = now.date()
    tomorrow = today + timedelta(days=1)
    closing_dates = {today.isoformat(), tomorrow.isoformat()}

    findings: list[dict] = []
    for d in drafts or []:
        if not isinstance(d, Mapping) or d.get("status") != "pending":
            continue
        if _is_auto_owned(d):
            continue
        parsed = _parse_ts(str(d.get("created_at") or ""))
        age_h = int((now - parsed).total_seconds() // 3600) if parsed is not None else 0
        tweet_date = d.get("tweet_date")
        closing = tweet_date in closing_dates
        urgent = age_h >= EDITOR_BRIEF_URGENT_AGE_H
        score = int((d.get("score") or {}).get("total") or 0)
        text = str(d.get("text") or "")
        findings.append({
            "id": d.get("id"),
            "type": str(d.get("type") or "unknown"),
            "age_h": age_h,
            "score": score,
            "tweet_date": tweet_date,
            "urgent": urgent,
            "closing": closing,
            "preview": text[:140],
        })
    findings.sort(key=lambda f: (not f["closing"], not f["urgent"], -f["score"]))
    return findings


def build_editor_brief_body(findings: list[dict]) -> str:
    total = len(findings)
    shown = findings[:EDITOR_BRIEF_MAX_ROWS]
    needs_now, fresh = [], []
    for f in shown:
        (needs_now if f["urgent"] or f["closing"] else fresh).append(f)

    def _row(f: dict) -> str:
        forecast = f' · forecast {f["tweet_date"]}' if f.get("tweet_date") else ""
        return (
            f"- **{f['type']}** · score {f['score']} · {f['age_h']}h old{forecast}\n"
            f"  > {f['preview']}"
        )

    lines = [EDITOR_BRIEF_MARKER, "**What the pending queue needs from you.**", ""]
    if needs_now:
        lines.append("### ⚡ Needs you now")
        lines.extend(_row(f) for f in needs_now)
        lines.append("")
    if fresh:
        lines.append("### — Fresh")
        lines.extend(_row(f) for f in fresh)
        lines.append("")
    remaining = total - len(shown)
    if remaining > 0:
        lines.append(f"_(+{remaining} more on the dashboard)_")
        lines.append("")
    lines.extend([
        "**Fix:** review on the dashboard — Approve+Post the good ones, Reject the "
        "rest.",
        "",
        "_Auto-maintained by the source-health sentinel. Closes itself when the "
        "queue is empty._",
    ])
    return "\n".join(lines)


def _open_editor_brief_issue() -> dict[str, Any] | None:
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list editor-brief issue: {exc!r}", file=sys.stderr)
        return None
    for item in items:
        if item.get("title") == EDITOR_BRIEF_TITLE:
            return item
    return None


def plan_editor_brief_action(
    findings: list[dict],
    open_issue: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if findings:
        body = build_editor_brief_body(findings)
        if open_issue is None:
            return {"action": "create_editor_brief", "body": body, "labels": [LABEL, "ours"]}
        if _open_issue_body(open_issue).strip() != body.strip():
            return {
                "action": "update_editor_brief",
                "number": _open_issue_number(open_issue),
                "body": body,
                "labels": [LABEL, "ours"],
            }
        return None
    if open_issue is not None:
        return {"action": "close_editor_brief", "number": _open_issue_number(open_issue)}
    return None


def _create_editor_brief_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "create", "--title", EDITOR_BRIEF_TITLE, "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] opened editor-brief issue: {EDITOR_BRIEF_TITLE}")


def _update_editor_brief_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] updated editor-brief issue #{action['number']}")


def _close_editor_brief_issue(number: int) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         "The pending queue is empty. Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed editor-brief issue #{number}")


# ---------------------------------------------------------------------------
# News-gap watch — the world reported an event; did our sensors even see it?
# (Bet A phase 0 miss-detector: read-only, zero editorial surface.)
# ---------------------------------------------------------------------------

NEWS_GAP_WINDOW_DAYS = 3
NEWS_GAP_TITLE = "News-gap watch: the world reported an event the bot may have missed"
NEWS_GAP_MARKER = "<!-- source-health-news-gap-watch -->"
# Candidate categories/types each news kind may match. Conservative on purpose:
# a WRONG match hides a real gap, an over-flag is one advisory issue.
_NEWS_KIND_FAMILIES = {
    "fire": ("fire",),
    "heat_mortality": ("heat", "temp", "anomaly", "extreme"),
}
# Static US state-code -> name map for matching WFIGS admin1 codes against
# candidate `where` strings (which carry expanded state names). Kept in sync
# by hand with src/data/ghcn.py _US_STATE_NAMES — the sentinel stays
# dependency-free, and state names do not drift.
_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _news_match_tokens(ev: Mapping[str, Any]) -> list[str]:
    place = ev.get("place") if isinstance(ev.get("place"), Mapping) else {}
    tokens: list[str] = []
    name = str(place.get("name") or "")
    if len(name) >= 4:
        tokens.append(name.lower())
    admin1 = str(place.get("admin1") or "")
    state_name = _STATE_NAMES.get(admin1.upper())
    if state_name:
        tokens.append(state_name.lower())
    country = str(place.get("country") or "")
    if country and country != "United States":
        tokens.append(country.lower())
    return tokens


def _token_in(token: str, hay: str) -> bool:
    """Boundary-guarded token match. A bare substring check reads a France
    heat event as matched by a 'Fort-de-France, Martinique' candidate (codex
    P1) — the token must not be glued to a neighboring word by a letter,
    digit, or hyphen on either side."""
    return re.search(
        rf"(?<![\w-]){re.escape(token)}(?![\w-])", hay
    ) is not None


def _news_event_matched(
    ev: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    drafts: list[Mapping[str, Any]],
) -> bool:
    kind = str(ev.get("kind") or "")
    families = _NEWS_KIND_FAMILIES.get(kind, ())
    tokens = _news_match_tokens(ev)
    if not tokens:
        # No usable place token — cannot match responsibly; treat as matched
        # rather than flag noise on an unmatchable event.
        return True
    for row in candidates:
        hay = f"{row.get('city') or ''} {row.get('where') or ''}".lower()
        cat = f"{row.get('category') or ''} {row.get('type') or ''}".lower()
        if any(f in cat for f in families) and any(_token_in(t, hay) for t in tokens):
            return True
    for d in drafts:
        hay = f"{d.get('text') or ''} {d.get('type') or ''}".lower()
        if any(_token_in(t, hay) for t in tokens):
            return True
    return False


def news_gap_watch(
    news_events: list[dict] | None,
    candidates_log: list[dict] | None,
    drafts: list[dict] | None,
    *,
    now: datetime,
) -> list[dict]:
    """Flag recent sourced world events with no matching detected candidate.

    Only ``structured``/``verified`` events can flag (the retrieval lane's
    verification ladder is upstream); matching is conservative — no match
    beats a wrong match, because a wrong match hides a real coverage gap.
    """
    cutoff = (now - timedelta(days=NEWS_GAP_WINDOW_DAYS)).date().isoformat()
    cands = [r for r in (candidates_log or []) if isinstance(r, Mapping)]
    live_drafts = [
        d for d in (drafts or [])
        if isinstance(d, Mapping) and d.get("status") in ("pending", "posted")
    ]
    findings: list[dict] = []
    for ev in news_events or []:
        if not isinstance(ev, Mapping):
            continue
        if ev.get("confidence") not in ("structured", "verified"):
            continue
        if str(ev.get("window_end") or "") < cutoff:
            continue
        if _news_event_matched(ev, cands, live_drafts):
            continue
        findings.append({
            "kind": str(ev.get("kind") or ""),
            "headline": str(ev.get("headline") or ""),
            "sources": [
                str(i.get("source_name") or "")
                for i in (ev.get("impact") or [])
                if isinstance(i, Mapping)
            ][:3],
        })
    return findings


def build_news_gap_body(findings: list[dict]) -> str:
    lines = [
        NEWS_GAP_MARKER,
        "**The world is reporting events the bot has not detected.**",
        "",
        "Each entry below is a sourced, verified news event from the "
        "newsworthiness lane with NO matching candidate in the bot's recent "
        "detection log, pending queue, or posts — the miss-detector for the "
        "class of failure where @theheat was silent on the European heat "
        "deaths. Advisory; check whether a sensor, threshold, or coverage "
        "gap is hiding the story.",
        "",
    ]
    for f in findings:
        sources = ", ".join(s for s in f.get("sources", []) if s) or "sourced"
        lines.append(f"- `{f['kind']}`: {f['headline']} (per {sources})")
    lines += ["", "_Auto-maintained by the source-health sentinel news-gap watch._"]
    return "\n".join(lines)


def _open_news_gap_issue() -> dict[str, Any] | None:
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title,body,labels", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list news-gap issue: {exc!r}", file=sys.stderr)
        return None
    for item in items:
        if item.get("title") == NEWS_GAP_TITLE:
            return item
    return None


def plan_news_gap_action(
    findings: list[dict],
    open_issue: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if findings:
        body = build_news_gap_body(findings)
        if open_issue is None:
            return {"action": "create_news_gap", "body": body, "labels": [LABEL, "unknown"]}
        if _open_issue_body(open_issue).strip() != body.strip():
            return {
                "action": "update_news_gap",
                "number": _open_issue_number(open_issue),
                "body": body,
                "labels": [LABEL, "unknown"],
            }
        return None
    if open_issue is not None:
        return {"action": "close_news_gap", "number": _open_issue_number(open_issue)}
    return None


def _create_news_gap_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "create", "--title", NEWS_GAP_TITLE, "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] opened news-gap issue: {NEWS_GAP_TITLE}")


def _update_news_gap_issue(action: Mapping[str, Any]) -> None:
    args = ["issue", "edit", str(action["number"]), "--body", str(action["body"])]
    for label in action.get("labels") or []:
        args.extend(["--add-label", str(label)])
    _run_gh(args, check=False)
    print(f"[sentinel] updated news-gap issue #{action['number']}")


def _close_news_gap_issue(number: int) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         "Every recent sourced news event matches a detected candidate or post. "
         "Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed news-gap issue #{number}")


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
    cov = coverage_watch(
        state.get("coverage_log"),
        state.get("run_history"),
        now=datetime.now(timezone.utc),
    )
    cov_action = plan_coverage_watch_action(cov, _open_coverage_watch_issue())
    if cov_action:
        if cov_action["action"] == "create_coverage_watch":
            _create_coverage_watch_issue(cov_action)
        elif cov_action["action"] == "update_coverage_watch":
            _update_coverage_watch_issue(cov_action)
        else:
            _close_coverage_watch_issue(cov_action["number"])
    ww = writer_watch(
        state.get("suppressions"),
        state.get("run_history"),
        now=datetime.now(timezone.utc),
    )
    if ww:
        print(
            f"[sentinel] writer-watch: {ww[0]['count']} budget_exhausted kill(s) "
            f"in {WRITER_WATCH_WINDOW_HOURS}h (latest {ww[0]['last_ts']})"
        )
    ww_action = plan_writer_watch_action(ww, _open_writer_watch_issue())
    if ww_action:
        if ww_action["action"] == "create_writer_watch":
            _create_writer_watch_issue(ww_action)
        elif ww_action["action"] == "update_writer_watch":
            _update_writer_watch_issue(ww_action)
        else:
            _close_writer_watch_issue(ww_action["number"])
    qw = queue_watch(
        state.get("drafts"),
        now=datetime.now(timezone.utc),
    )
    if qw:
        print(
            f"[sentinel] queue-watch: {qw[0]['count']} human-gated draft(s) older "
            f"than {QUEUE_WATCH_HOURS}h (oldest ≈ {qw[0]['oldest_age_h']}h)"
        )
    qw_action = plan_queue_watch_action(qw, _open_queue_watch_issue())
    if qw_action:
        if qw_action["action"] == "create_queue_watch":
            _create_queue_watch_issue(qw_action)
        elif qw_action["action"] == "update_queue_watch":
            _update_queue_watch_issue(qw_action)
        else:
            _close_queue_watch_issue(qw_action["number"])
    eb = editor_brief(
        state.get("drafts"),
        now=datetime.now(timezone.utc),
    )
    if eb:
        print(f"[sentinel] editor-brief: {len(eb)} pending draft(s) need a decision")
    eb_action = plan_editor_brief_action(eb, _open_editor_brief_issue())
    if eb_action:
        if eb_action["action"] == "create_editor_brief":
            _create_editor_brief_issue(eb_action)
        elif eb_action["action"] == "update_editor_brief":
            _update_editor_brief_issue(eb_action)
        else:
            _close_editor_brief_issue(eb_action["number"])
    ng = news_gap_watch(
        state.get("news_events"),
        state.get("candidates_log"),
        state.get("drafts"),
        now=datetime.now(timezone.utc),
    )
    if ng:
        print(f"[sentinel] news-gap watch: {len(ng)} unmatched sourced event(s)")
    ng_action = plan_news_gap_action(ng, _open_news_gap_issue())
    if ng_action:
        if ng_action["action"] == "create_news_gap":
            _create_news_gap_issue(ng_action)
        elif ng_action["action"] == "update_news_gap":
            _update_news_gap_issue(ng_action)
        else:
            _close_news_gap_issue(ng_action["number"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
