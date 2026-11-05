"""Check whether a retained alerts or both run is old enough for catch-up.

Exit 0 means a verified start is older than the configured window. Exit 1
keeps the sender role because the retained start is recent. Exit 2 keeps that
role because the evidence is unknown. A retained failed run also resets the
clock. Interrupted runs that never save a receipt are outside this evidence.
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
RUN_MODES = (*ALERT_MODES, "leaderboard", "manual_tweet", "auto_publish_due")


def catchup_due(state: dict[str, Any], *, now: datetime, max_age: timedelta) -> bool:
    history = state.get("run_history")
    if not isinstance(history, list):
        raise ValueError("state has no run_history list")
    newest: datetime | None = None
    for run in history:
        if not isinstance(run, dict) or run.get("mode") not in RUN_MODES:
            raise ValueError("unknown run mode")
        if run["mode"] not in ALERT_MODES:
            continue
        value = run.get("started_at")
        if not isinstance(value, str):
            raise ValueError("missing alerts start")
        started = datetime.fromisoformat(value)
        if started.tzinfo is None or started > now:
            raise ValueError("invalid alerts start")
        if newest is None or started > newest:
            newest = started
    if newest is None:
        raise ValueError("no retained alerts start")
    return now - newest > max_age


def main(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("state", type=Path, nargs="?")
    parser.add_argument("--reserve", action="store_true")
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    args = parser.parse_args(argv)
    if args.reserve:
        if args.state is not None or args.max_age_minutes != DEFAULT_MAX_AGE_MINUTES:
            parser.error("reservation uses the fixed catch-up window")
        from src.state import reserve_scheduled_alerts_catchup

        reserved = reserve_scheduled_alerts_catchup(window=timedelta(minutes=DEFAULT_MAX_AGE_MINUTES))
        print(f"alerts-lane catch-up: reservation {'confirmed' if reserved else 'held'}")
        return 0 if reserved else 2
    if args.state is None:
        parser.error("a retained state file is required")
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
    print(f"alerts-lane catch-up: retained alerts/both history {'is stale' if due else 'is recent'}")
    return 0 if due else 1


if __name__ == "__main__":
    raise SystemExit(main())
