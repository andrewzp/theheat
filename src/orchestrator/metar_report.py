"""One nominated observed pair, sharing the ordinary checks and spend accounting."""
from __future__ import annotations

import os
import time
from typing import cast

from src.orchestrator.candidate_budget import CandidateBudget
from src.orchestrator.sources.awc_observed import run_awc_observed, settings_hold
from src.orchestrator.suppression import _suppression_context
from src.orchestrator.telemetry import _record_source_run
from src.orchestrator.triage_queue import _automatic_selection_intent_hold, _drain_and_write_triage_queue
from src.state_schema import BotState
from src.two_bot.call_inventory import operation_cost_row, operation_scope, record_operation_cost


def run_metar_report(bot_state: BotState, current_run: dict | None = None) -> BotState:
    cast(dict, bot_state).pop("_triage_queue", None)
    budget = CandidateBudget(operation="alerts", limit=1)
    with operation_scope("alerts") as joined, _suppression_context(
            bot_state, source="awc_observed", run_id=(current_run or {}).get("id")):
        try:
            # Invalid limits/intent stop before acquisition and cannot silently
            # turn this nominated route into a manual draft or multi-source run.
            hold = settings_hold()
            if os.environ.get("THEHEAT_AUTOMATIC_SELECTION_ONLY") != "1":
                hold = "awc_explicit_automatic_selection_required"
            if not hold:
                hold = _automatic_selection_intent_hold(bot_state, current_run)
            if hold:
                _record_source_run(current_run, bot_state, "awc_observed", time.perf_counter(),
                    status="skipped" if hold == "awc_source_disabled" else "failed", error=hold)
                return bot_state
            run_awc_observed(bot_state, current_run)
            _drain_and_write_triage_queue(bot_state, current_run, candidate_budget=budget)
        finally:
            record_operation_cost(current_run, operation_cost_row("alerts", join=joined, candidate_budget=budget))
    return bot_state
