"""Monthly LLM budget watch (economics master plan P1.1).

Reads the P0.6 usage ledger (``state["llm_usage"]``) and turns it into the
plan's caps-and-alerts lane: month-to-date estimated spend, a straight-line
month projection, and an alert level at 70% / 90% of the configured budget.

Alerting rides the EXISTING source-health machinery: the cycle records a
``budget`` source-health row (``degraded`` at 70%, ``failed`` at 90%/over),
which the hourly sentinel already turns into auto-filed/auto-closed GitHub
issues and the dashboard already renders — no new alert plumbing.

Budget default: $14/month — the top of the master plan's operational band
(§0: operational budget ≤ $10–14/month, hard ceiling $13–18). Override with
``THEHEAT_MONTHLY_BUDGET_USD``.
"""

from __future__ import annotations

import calendar
import os
from datetime import datetime, timezone
from typing import Any

_DEFAULT_MONTHLY_BUDGET_USD = 14.0

WARN_PCT = 0.70
ALARM_PCT = 0.90


def monthly_budget_usd() -> float:
    raw = os.environ.get("THEHEAT_MONTHLY_BUDGET_USD", "")
    try:
        value = float(raw) if raw else _DEFAULT_MONTHLY_BUDGET_USD
    except (TypeError, ValueError):
        return _DEFAULT_MONTHLY_BUDGET_USD
    return value if value > 0 else _DEFAULT_MONTHLY_BUDGET_USD


def month_to_date_usd(state: Any, *, now: datetime | None = None) -> float:
    """Sum the ledger's est. $ for the current UTC month. Never raises."""
    now = now or datetime.now(timezone.utc)
    prefix = now.strftime("%Y-%m-")
    ledger = state.get("llm_usage") if hasattr(state, "get") else None
    if not isinstance(ledger, dict):
        return 0.0
    total = 0.0
    for day, bucket in ledger.items():
        if not isinstance(day, str) or not day.startswith(prefix):
            continue
        if not isinstance(bucket, dict):
            continue
        for agg in bucket.values():
            if isinstance(agg, dict):
                try:
                    total += float(agg.get("usd", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
    return round(total, 6)


def budget_status(state: Any, *, now: datetime | None = None) -> dict:
    """One structured verdict for the cycle hook, the API, and tests."""
    now = now or datetime.now(timezone.utc)
    budget = monthly_budget_usd()
    mtd = month_to_date_usd(state, now=now)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    projected = round(mtd / max(now.day, 1) * days_in_month, 2)
    pct = mtd / budget if budget else 0.0
    if pct >= ALARM_PCT:
        level = "alarm_90"
    elif pct >= WARN_PCT:
        level = "warn_70"
    else:
        level = "ok"
    return {
        "budget_usd": budget,
        "mtd_usd": mtd,
        "projected_usd": projected,
        "pct_of_budget": round(pct, 4),
        "level": level,
    }


def record_budget_health(state: Any, *, now: datetime | None = None) -> dict:
    """Cycle hook: compute the status and surface non-ok levels through the
    source-health lane (sentinel auto-issues + dashboard rows come free).
    Never raises."""
    status = budget_status(state, now=now)
    try:
        from src import state as _state

        message = (
            f"est ${status['mtd_usd']:.2f} MTD "
            f"({status['pct_of_budget']:.0%} of ${status['budget_usd']:.0f} budget); "
            f"projected ${status['projected_usd']:.2f}/month"
        )
        if status["level"] == "alarm_90":
            _state.record_source_health(state, "budget", "failed", message)
        elif status["level"] == "warn_70":
            _state.record_source_health(state, "budget", "degraded", message)
        else:
            _state.record_source_health(state, "budget", "success", None)
    except Exception as exc:  # noqa: BLE001 — accounting never blocks a cycle
        print(f"[budget] health record error (ignored): {exc!r}")
    return status
