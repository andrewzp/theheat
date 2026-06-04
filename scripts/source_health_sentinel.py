#!/usr/bin/env python3
"""Daily source-health sentinel.

Reads the bot's gist ``state.json`` and classifies every source's recent health
so the operator does not have to triage the dashboard by hand. The core question
for each failing source: is this UPSTREAM (NASA / gov / network — transient,
self-heals, stay silent) or OUR_BUG (a code error, expired credential, moved
endpoint, or an abnormally long outage — open an issue and ping)?

The whole point is to stop crying wolf on NASA flakiness — which is the
overwhelming majority of red on the dashboard — while never missing a failure
that is actually ours to fix.

Classification is deterministic and unit-tested (see
``tests/test_source_health_sentinel.py``). ``main()`` is the thin I/O wrapper the
GitHub Actions workflow calls; it stays silent on upstream-only days and writes
an issue body only when ``has_our_bugs`` is true.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import sys
from typing import Any

# Recent sub-window: how many of the last ACTIVE (non-skip) attempts decide
# whether a source is "currently failing". Mirrors the dashboard's RECENT_WINDOW.
RECENT_WINDOW = 5
# How long a source may be dark before even an upstream outage escalates. A
# transient NASA/gov outage self-heals within hours; one that lasts this many
# WALL-CLOCK days is no longer safely "just NASA" — a moved/decommissioned
# endpoint or a persistently rejected request needs a look (switch product,
# update the endpoint, find an alternate source). Wall-clock, not a raw
# consecutive-failure count, because cadence varies wildly (one count means ~1.5
# days for gpm but ~10 weeks for weekly ice_mass). Tunable via SENTINEL_OUTAGE_DAYS.
OUTAGE_DAYS = 3.0

# Statuses that count as a real attempt. "skipped" is a deliberate cadence idle
# (e.g. "runs Mondays only") and must never consume the window or trip an alarm.
_ACTIVE_STATUSES = {"success", "failed", "degraded", "partial_failure"}

# OUR_BUG: actionable on our side. Checked FIRST so an auth/code/parse failure
# wins over a coincidental network token in the same string.
#   - \b401|404|410\b : auth / moved-endpoint HTTP codes (403 is a gov rate-limit
#     and lives in UPSTREAM, not here).
#   - EARTHDATA_TOKEN (the env-var name) NOT bare "EARTHDATA" — the NASA hostname
#     earthdata.nasa.gov appears in upstream URLs and must not match.
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

# UPSTREAM: external and transient. NASA 5xx, read/connect timeouts, connection
# failures, and gov rate-limits (403/429 — empirically rate-limits, not UA/auth
# blocks, for theheat's sources).
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

def _days_since(ts: str | None, now: datetime) -> float | None:
    """Wall-clock days between an ISO timestamp and ``now``. None if unparseable
    or absent (e.g. a source that has never once succeeded)."""
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).total_seconds() / 86400.0


def _is_hard_upstream(last_error: str | None) -> bool:
    """True when the error means the server is down/unreachable (5xx, timeout,
    connection) — definitively external, regardless of how long it persists."""
    return bool(_HARD_UPSTREAM_RE.search(str(last_error or "")))


def classify_error(last_error: str | None) -> str:
    """Classify a ``last_error`` string into none / our_bug / upstream / unknown.

    OUR_BUG is checked before UPSTREAM so an auth/code/parse failure is never
    masked by a network word in the same message. A non-empty string that
    matches neither is ``unknown`` — the sentinel escalates unknowns (better to
    glance at a novel failure than silently file it as upstream).
    """
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


def _verdict(
    name: str,
    category: str,
    reason: str,
    health: dict[str, Any],
    error_class: str,
    recent_success_rate: float | None = None,
    days_since_success: float | None = None,
) -> dict[str, Any]:
    return {
        "source": name,
        "category": category,
        "reason": reason,
        "error_class": error_class,
        "last_error": (health.get("last_error") or "")[:300],
        "last_success_ts": health.get("last_success_ts"),
        "recent_success_rate": recent_success_rate,
        "days_since_success": (
            round(days_since_success, 1) if days_since_success is not None else None
        ),
    }


def classify_source(
    name: str,
    health: dict[str, Any],
    *,
    now: datetime | None = None,
    outage_days: float = OUTAGE_DAYS,
    recent_window: int = RECENT_WINDOW,
) -> dict[str, Any]:
    """Classify one source into healthy / degraded / idle / upstream / our_bug.

    Only ``upstream`` and ``our_bug`` describe a currently-failing source;
    ``our_bug`` is the only category that escalates. ``idle`` means the recent
    rows are all cadence skips (e.g. a Monday-only source mid-week) — never an
    alarm.

    A currently-failing source escalates when the error is ours (code/auth/moved
    endpoint/unknown) OR when it has been dark for ``outage_days`` wall-clock days
    — even on an upstream error. A transient upstream outage stays silent; one
    that has lasted that long is no longer safely "just NASA".
    """
    now = now or datetime.now(timezone.utc)
    runs = health.get("runs") or []
    statuses = [r.get("status") for r in runs if isinstance(r, dict)]
    active = [s for s in statuses if s in _ACTIVE_STATUSES]
    last_error = health.get("last_error") or ""
    error_class = classify_error(last_error)
    days_dark = _days_since(health.get("last_success_ts"), now)

    if not active:
        return _verdict(name, "idle", "no active attempts (cadence skips only)",
                        health, error_class, days_since_success=days_dark)

    recent = active[-recent_window:]
    recent_rate = recent.count("success") / len(recent)

    if recent_rate >= 0.5:
        category = "healthy" if recent_rate == 1.0 else "degraded"
        return _verdict(name, category, f"recent success rate {recent_rate:.0%}",
                        health, error_class, recent_rate, days_dark)

    # Currently failing (most recent active attempts are failures).
    if error_class in ("our_bug", "unknown"):
        return _verdict(name, "our_bug", f"{error_class} failure — {last_error[:140]}",
                        health, error_class, recent_rate, days_dark)

    # Upstream error. Escalate only if the outage has lasted a significant length
    # of WALL-CLOCK time (or the source has never once succeeded) — at that point
    # a server outage is more likely a real upstream change (moved/decommissioned
    # endpoint, persistently rejected request) that needs a fix on our side, not
    # a transient blip. Below the threshold it self-heals → stay silent.
    if days_dark is None:
        return _verdict(name, "our_bug",
                        f"has never succeeded and is failing — {last_error[:120]}",
                        health, error_class, recent_rate, days_dark)
    if days_dark >= outage_days:
        return _verdict(name, "our_bug",
                        f"down {days_dark:.1f} days — an outage this long likely "
                        f"means a real upstream change (moved/decommissioned endpoint "
                        f"or persistently rejected request), not transient "
                        f"({last_error[:90]})",
                        health, error_class, recent_rate, days_dark)
    return _verdict(name, "upstream", f"upstream failure — {last_error[:140]}",
                    health, error_class, recent_rate, days_dark)


def run_sentinel(
    source_health: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    outage_days: float = OUTAGE_DAYS,
    recent_window: int = RECENT_WINDOW,
) -> dict[str, Any]:
    """Classify all sources and bucket them. ``has_our_bugs`` gates the alert."""
    now = now or datetime.now(timezone.utc)
    verdicts = [
        classify_source(
            name, health,
            now=now,
            outage_days=outage_days,
            recent_window=recent_window,
        )
        for name, health in sorted((source_health or {}).items())
        if isinstance(health, dict)
    ]
    our_bug = [v for v in verdicts if v["category"] == "our_bug"]
    upstream = [v for v in verdicts if v["category"] == "upstream"]
    healthy = [v for v in verdicts if v["category"] in ("healthy", "degraded", "idle")]
    return {
        "has_our_bugs": len(our_bug) > 0,
        "our_bug": our_bug,
        "upstream": upstream,
        "healthy": healthy,
        "summary": {
            "our_bug": len(our_bug),
            "upstream": len(upstream),
            "healthy": len(healthy),
            "total": len(verdicts),
        },
    }


def build_issue_body(report: dict[str, Any]) -> str:
    """Markdown body for the GitHub issue opened when there are our-side bugs."""
    lines = [
        "The daily source-health sentinel found a failure that looks like **ours to fix**, "
        "not upstream NASA/gov flakiness.",
        "",
        "## Needs a fix",
    ]
    for v in report["our_bug"]:
        lines += [
            f"### `{v['source']}` — {v['error_class']}",
            f"- **Why flagged:** {v['reason']}",
            f"- **Last error:** `{v['last_error']}`",
            f"- **Recent success rate:** {v['recent_success_rate']:.0%}"
            if v["recent_success_rate"] is not None else "- **Recent success rate:** n/a",
            f"- **Days since last success:** {v['days_since_success']}"
            if v["days_since_success"] is not None else "- **Days since last success:** never succeeded",
            f"- **Last success:** `{v['last_success_ts'] or 'never'}`",
            "",
        ]
    if report["upstream"]:
        names = ", ".join(f"`{v['source']}`" for v in report["upstream"])
        lines += [
            "## Upstream (no action — self-heals)",
            f"Failing but external, left alone: {names}",
            "",
        ]
    lines.append(
        "_Auto-filed by `scripts/source_health_sentinel.py`. Upstream-only days file nothing._"
    )
    return "\n".join(lines)


def _print_report(report: dict[str, Any]) -> None:
    s = report["summary"]
    print(
        f"[sentinel] {s['total']} sources: "
        f"{s['our_bug']} our_bug, {s['upstream']} upstream, {s['healthy']} healthy/idle"
    )
    for v in report["our_bug"]:
        print(f"  OUR_BUG  {v['source']}: {v['reason']}")
    for v in report["upstream"]:
        print(f"  upstream {v['source']}: {v['last_error'][:80]}")


def main(argv: list[str] | None = None) -> int:
    """CLI for CI: read state.json, classify, emit report + GitHub Actions outputs.

    Always exits 0 — the sentinel is a reporter, never a gate. Usage:
        python scripts/source_health_sentinel.py <state.json> [issue_body_out.md]
    """
    argv = argv if argv is not None else sys.argv[1:]
    state_path = argv[0] if argv else "state.json"
    issue_out = argv[1] if len(argv) > 1 else "/tmp/sentinel-issue.md"

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[sentinel] could not read {state_path}: {exc!r}", file=sys.stderr)
        return 0  # never fail the workflow on a read hiccup

    try:
        outage_days = float(os.environ.get("SENTINEL_OUTAGE_DAYS") or OUTAGE_DAYS)
    except ValueError:
        outage_days = OUTAGE_DAYS
    report = run_sentinel(state.get("source_health") or {}, outage_days=outage_days)
    _print_report(report)

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"has_our_bugs={'true' if report['has_our_bugs'] else 'false'}\n")
            f.write(f"our_bug_count={report['summary']['our_bug']}\n")

    if report["has_our_bugs"]:
        with open(issue_out, "w", encoding="utf-8") as f:
            f.write(build_issue_body(report))
        print(f"[sentinel] wrote issue body to {issue_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
