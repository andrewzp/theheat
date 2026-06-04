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

from datetime import datetime, timezone
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

LABEL = "source-health-sentinel"
TITLE_PREFIX = "Source down: "

# "skipped" is a deliberate cadence idle (e.g. "runs Mondays only") and must
# never count as an attempt or trip an alarm.
_ACTIVE_STATUSES = {"success", "failed", "degraded", "partial_failure"}

# OUR_BUG: actionable in our code. Checked FIRST so auth/code/parse wins over a
# coincidental network token. EARTHDATA_TOKEN (the env-var name) NOT bare
# "EARTHDATA" — the NASA hostname earthdata.nasa.gov appears in upstream URLs.
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
# UPSTREAM: external. NASA 5xx, read/connect timeouts, connection failures, gov
# rate-limits (403/429 — empirically rate-limits, not UA/auth blocks here).
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
    if _UPSTREAM_RE.search(text):
        return "upstream"
    return "unknown"


def _days_since(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).total_seconds() / 86400.0


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
    active = [s for s in statuses if s in _ACTIVE_STATUSES]
    last_error = health.get("last_error") or ""
    error_class = classify_error(last_error)
    days_dark = _days_since(health.get("last_success_ts"), now)

    if not active:
        category = "idle"
    else:
        recent = active[-recent_window:]
        rate = recent.count("success") / len(recent)
        if rate >= 1.0:
            category = "healthy"
        elif rate >= FAILING_RATE:
            category = "degraded"
        else:
            category = "failing"
        recent_rate = rate

    if not active:
        recent_rate = None  # type: ignore[assignment]

    cause, action = _CAUSE.get(error_class, _CAUSE["unknown"])
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
    }


def run_sentinel(
    source_health: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    recent_window: int = RECENT_WINDOW,
) -> dict[str, Any]:
    """Classify all sources and bucket them. ``has_failures`` gates the issues."""
    now = now or datetime.now(timezone.utc)
    verdicts = [
        classify_source(name, health, now=now, recent_window=recent_window)
        for name, health in sorted((source_health or {}).items())
        if isinstance(health, dict)
    ]
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


def plan_issue_actions(
    failing: set[str],
    open_issues: dict[str, int],
) -> list[dict[str, Any]]:
    """Reconcile the failing set against currently-open sentinel issues.

    Create an issue for every failing source without one; close the issue of
    every source that has recovered (open issue but no longer failing). Sources
    that are still failing and already have an issue are left untouched (no spam).
    """
    actions: list[dict[str, Any]] = []
    for source in sorted(failing - set(open_issues)):
        actions.append({"action": "create", "source": source})
    for source in sorted(set(open_issues) - failing):
        actions.append({"action": "close", "source": source, "number": open_issues[source]})
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


def _print_report(report: dict[str, Any]) -> None:
    s = report["summary"]
    print(
        f"[sentinel] {s['total']} sources: "
        f"{s['failing']} failing, {s['degraded']} degraded, {s['healthy']} healthy/idle"
    )
    for v in report["failing"]:
        print(f"  FAILING  {v['source']} [{v['cause']}]: {v['last_error'][:80]}")


def _run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def _list_open_sentinel_issues() -> dict[str, int]:
    """Map source name -> open issue number, from issues this sentinel filed."""
    try:
        out = _run_gh(
            ["issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title", "--limit", "200"]
        ).stdout
        items = json.loads(out or "[]")
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[sentinel] could not list issues: {exc!r}", file=sys.stderr)
        return {}
    result: dict[str, int] = {}
    for it in items:
        title = it.get("title", "")
        if title.startswith(TITLE_PREFIX):
            result[title[len(TITLE_PREFIX):].strip()] = it["number"]
    return result


def _create_issue(v: dict[str, Any]) -> None:
    title = f"{TITLE_PREFIX}{v['source']}"
    body = build_issue_body(v)
    base = ["issue", "create", "--title", title, "--label", LABEL, "--body", body]
    r = _run_gh([*base, "--assignee", "andrewzp"], check=False)
    if r.returncode != 0:  # assignee may be invalid in some envs — file anyway
        _run_gh(base, check=False)
    print(f"[sentinel] opened issue: {title}")


def _close_issue(number: int, source: str) -> None:
    _run_gh(
        ["issue", "close", str(number), "--comment",
         f"`{source}` is succeeding again — recovered. Auto-closed by the source-health sentinel."],
        check=False,
    )
    print(f"[sentinel] closed issue #{number} ({source} recovered)")


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

    report = run_sentinel(state.get("source_health") or {})
    _print_report(report)

    if not apply:
        print("[sentinel] dry-run — pass --apply or run in CI to open/close issues.")
        return 0

    _run_gh(["label", "create", LABEL, "-c", "B60205",
             "-d", "Auto-filed by the daily source-health sentinel"], check=False)
    failing_map = {v["source"]: v for v in report["failing"]}
    open_issues = _list_open_sentinel_issues()
    for action in plan_issue_actions(set(failing_map), open_issues):
        if action["action"] == "create":
            _create_issue(failing_map[action["source"]])
        else:
            _close_issue(action["number"], action["source"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
