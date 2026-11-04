"""Decide whether an hourly scheduled run must collect alerts because GitHub skipped the alert slots.

GitHub drops many scheduled runs under load (on 3 November only 8 of ~30 slots fired), so the
alerts lane can go stale for half a day while hourly sender runs keep succeeding. The bot
workflow's mode step calls this with a read-only copy of state.json on the hourly slot:

    python scripts/alerts_lane_catchup.py <state.json> [--max-age-minutes N]

Exit 0  -> the newest alerts/both run STARTED more than N minutes ago (or none exists): collect now.
Exit 1  -> the lane is fresh: keep the hourly sender role.
Exit 2  -> the state could not be read or parsed: keep the hourly sender role (never escalate on doubt).

Measured from the newest *started* alerts/both run, whatever its outcome, the same rule as the
source-health sentinel's liveness check. A failing collection run therefore still resets the clock,
so catch-up never runs alerts more often than once per window (no cost runaway). The default window
(285 min) exceeds the 4 h alert cadence by enough that a merely delayed alert slot does not also
trigger a catch-up run.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_AGE_MINUTES = 285
ALERT_MODES = ("alerts", "both")


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def newest_alerts_start(state: dict[str, Any]) -> datetime | None:
    newest: datetime | None = None
    for run in state.get("run_history") or []:
        if not isinstance(run, dict) or run.get("mode") not in ALERT_MODES:
            continue
        started = _parse_ts(run.get("started_at"))
        if started is not None and (newest is None or started > newest):
            newest = started
    return newest


def catchup_due(state: dict[str, Any], *, now: datetime, max_age: timedelta) -> bool:
    if not isinstance(state.get("run_history"), list):
        raise ValueError("state has no run_history list")
    newest = newest_alerts_start(state)
    return newest is None or now - newest > max_age


def main(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("state", type=Path)
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    args = parser.parse_args(argv)
    if args.max_age_minutes < 1:
        print("alerts-lane catch-up: invalid window; keeping hourly role", file=sys.stderr)
        return 2
    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("state is not an object")
        due = catchup_due(state, now=now or datetime.now(timezone.utc),
                          max_age=timedelta(minutes=args.max_age_minutes))
    except (OSError, ValueError) as error:
        print(f"alerts-lane catch-up: state unreadable ({type(error).__name__}); keeping hourly role", file=sys.stderr)
        return 2
    newest = newest_alerts_start(state)
    print(f"alerts-lane catch-up: newest alerts/both start {newest.isoformat() if newest else 'none'}; "
          f"{'collect now' if due else 'fresh'}")
    return 0 if due else 1


if __name__ == "__main__":
    raise SystemExit(main())
