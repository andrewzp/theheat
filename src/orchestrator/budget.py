"""Monthly LLM budget watch (economics master plan P1.1).

Reads retained model-response estimates and their incomplete coverage. Thresholds
at 70% / 90% are alerts on a recorded subtotal, not account totals or enforced
caps. Lower subtotals and absent accounting never establish budget health.

Alerting rides the EXISTING source-health machinery: the cycle records a
``budget`` source-health row (``degraded`` at 70%, ``failed`` at 90%/over).
Acknowledged incomplete coverage is a classified skip, not a provider outage,
which the hourly sentinel already turns into auto-filed/auto-closed GitHub
issues and the dashboard already renders — no new alert plumbing.

Budget default: $14/month — the top of the master plan's operational band
(§0: operational budget ≤ $10–14/month, hard ceiling $13–18). Override with
``THEHEAT_MONTHLY_BUDGET_USD``.
"""

from __future__ import annotations

import calendar
import math
import os
from datetime import datetime, timezone
from typing import Any

from src.two_bot.usage_summary import summarize_usage

_DEFAULT_MONTHLY_BUDGET_USD = 14.0

WARN_PCT = 0.70
ALARM_PCT = 0.90


def monthly_budget_usd() -> float:
    raw = os.environ.get("THEHEAT_MONTHLY_BUDGET_USD", "")
    try:
        value = float(raw) if raw else _DEFAULT_MONTHLY_BUDGET_USD
    except (TypeError, ValueError):
        return _DEFAULT_MONTHLY_BUDGET_USD
    return value if math.isfinite(value) and value > 0 else _DEFAULT_MONTHLY_BUDGET_USD


def month_to_date_usd(state: Any, *, now: datetime | None = None) -> float | None:
    """Retained estimate subtotal only; missing or inconsistent accounting is null."""
    return summarize_usage(state, now=now)["recorded_estimate_usd"]


def budget_status(state: Any, *, now: datetime | None = None) -> dict:
    """One structured verdict for the cycle hook, the API, and tests."""
    now = now or datetime.now(timezone.utc)
    budget = monthly_budget_usd()
    coverage = summarize_usage(state, now=now)
    mtd = coverage["recorded_estimate_usd"]
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    projected = round(mtd / max(now.day, 1) * days_in_month, 2) if mtd is not None else None
    pct = mtd / budget if mtd is not None else None
    if pct is not None and pct >= ALARM_PCT:
        level = "alarm_90"
    elif pct is not None and pct >= WARN_PCT:
        level = "warn_70"
    else:
        level = "coverage_incomplete"
    return {
        **coverage,
        "budget_usd": budget,
        "mtd_usd": mtd,
        "projected_usd": projected,
        "pct_of_budget": round(pct, 4) if pct is not None else None,
        "level": level,
    }


def status_message(status: dict) -> str:
    def amount(value):
        return "unavailable" if value is None else f"${value:.2f}"
    return (f"recorded estimate subtotal {amount(status['mtd_usd'])} MTD; "
            f"priced {amount(status['known_cost_usd'])}, legacy {amount(status['legacy_estimate_usd'])}; "
            f"projected recorded subtotal {amount(status['projected_usd'])}/month. "
            f"Unpriced responses {status['unpriced_calls'] if status['unpriced_calls'] is not None else 'unknown'}; "
            f"accounting {status['coverage']}, account totals incomplete. "
            f"Reporting comparison ${status['budget_usd']:.2f}/month, budget not enforced.")


def record_budget_health(state: Any, *, now: datetime | None = None) -> dict:
    """Cycle hook: compute the status and surface threshold alerts through the
    source-health lane (sentinel auto-issues + dashboard rows come free).
    Never raises — the status computation itself sits inside the fail-open
    boundary too (codex P1: an unexpected value class in raw state must not
    abort the CLI before write_state)."""
    try:
        status = budget_status(state, now=now)
    except Exception as exc:  # noqa: BLE001 — accounting never blocks a cycle
        print(f"[budget] status error (ignored): {exc!r}")
        status = budget_status({}, now=now)
        return status
    try:
        from src import state as _state

        message = status_message(status)
        if status["level"] == "alarm_90":
            _state.record_source_health(state, "budget", "failed", message)
        elif status["level"] == "warn_70":
            _state.record_source_health(state, "budget", "degraded", message)
        else:
            _state.record_source_health(state, "budget", "skipped", message, error_class="accounting_coverage")
    except Exception as exc:  # noqa: BLE001 — accounting never blocks a cycle
        print(f"[budget] health record error (ignored): {exc!r}")
    return status
