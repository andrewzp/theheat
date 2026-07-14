"""CLI dispatch for @theheat."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from src import credentials, state
from src.orchestrator import budget
from src.state_schema import BotState
from src.two_bot import usage_ledger


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

    # Economics P0.6: fold this run's buffered per-call LLM usage into
    # state["llm_usage"] before the save. Never raises; a no-call run drains 0.
    drained = usage_ledger.drain_into_state(bot_state)
    if drained:
        print(f"[main] usage ledger: {drained} call(s) recorded")

    # Economics P1.1: budget watch — surfaces 70%/90% alerts through the
    # source-health lane (sentinel auto-issues + dashboard). Never raises.
    budget_state = budget.record_budget_health(bot_state)
    print(
        f"[main] budget: est ${budget_state['mtd_usd']:.2f} MTD "
        f"({budget_state['pct_of_budget']:.0%} of ${budget_state['budget_usd']:.0f}), "
        f"projected ${budget_state['projected_usd']:.2f}/mo [{budget_state['level']}]"
    )

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
