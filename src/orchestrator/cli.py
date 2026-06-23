"""CLI dispatch for @theheat."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from src import credentials, state
from src.state_schema import BotState


RunMode = Callable[..., BotState]


def main(dispatchers: dict[str, RunMode]) -> None:
    parser = argparse.ArgumentParser(description="@theheat climate bot")
    parser.add_argument(
        "mode",
        choices=["alerts", "leaderboard", "both", "manual_tweet", "auto_publish_due"],
        help="Which content to generate and post",
    )
    args = parser.parse_args()

    print(f"[main] Starting @theheat in {args.mode} mode")

    try:
        bot_state = state.read_state()
    except state.StateReadError as exc:
        print(f"[main] ERROR: {exc}")
        sys.exit(1)
    current_run = state.init_run(args.mode)
    # Refresh credential-expiry counters (dashboard) from the live env every run.
    # Cheap, never raises; only derived expiry dates are stored, not the tokens.
    bot_state["credential_expiry"] = credentials.collect_credential_expiry()
    final_status = "success"

    def _run(mode: str) -> None:
        nonlocal bot_state
        bot_state = dispatchers[mode](bot_state, current_run=current_run)

    if args.mode in ("alerts", "both"):
        _run("alerts")
    if args.mode in ("leaderboard", "both"):
        _run("leaderboard")
    if args.mode == "manual_tweet":
        _run("manual_tweet")
    if args.mode == "auto_publish_due":
        _run("auto_publish_due")

    if any(source.get("status") in {"failed", "partial_failure"} for source in current_run.get("sources", [])):
        final_status = "partial_failure"

    if not state.write_state(bot_state):
        print("[main] WARNING: State write failed, retrying...")
        if not state.write_state(bot_state):
            print("[main] ERROR: State write failed twice. Drafts from this run may be lost.")
            state.log_error(bot_state, "state", "write_state failed twice")
            final_status = "failed"
    else:
        print("[main] State saved")

    state.finalize_run(bot_state, current_run, status=final_status)
    if not state.write_state(bot_state):
        print("[main] WARNING: Final run history write failed")
    print("[main] Done")
