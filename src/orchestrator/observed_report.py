"""One operator-nominated retrospective C3S story through existing required checks."""
from __future__ import annotations

import os
import time
from typing import cast

from src.data import c3s_monthly
from src.editorial.scoring._shared import _build_score
from src.orchestrator.candidate_budget import CandidateBudget, configured_max_candidates
from src.orchestrator.common import _utc_now
from src.orchestrator.suppression import _suppression_context
from src.orchestrator.telemetry import _record_source_run
from src.orchestrator.triage_queue import _enqueue_story_candidate, _drain_and_write_triage_queue
from src.state_schema import BotState
from src.two_bot.call_inventory import operation_cost_row, operation_scope, record_operation_cost


def run_observed_report(bot_state: BotState, current_run: dict | None = None) -> BotState:
    started = time.perf_counter()
    cast(dict, bot_state).pop("_triage_queue", None)
    # Fixed one-candidate budget independent of the ordinary multi-source ceiling.
    budget = CandidateBudget(operation="alerts", limit=0)
    with operation_scope("alerts") as joined, _suppression_context(
            bot_state, source="c3s_monthly", run_id=(current_run or {}).get("id")):
        try:
            budget.limit = min(1, configured_max_candidates())
            from src.editorial.observed_scope import enabled
            from src.two_bot.pipeline import _critic_enabled
            if os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1":
                raise c3s_monthly.ReportHeld("c3s_generation_paused")
            if not enabled() or not _critic_enabled():
                raise c3s_monthly.ReportHeld("c3s_observed_mode_and_critic_required")
            report = c3s_monthly.fetch_report(os.environ.get("THEHEAT_OBSERVED_REPORT_MONTH", ""), now=_utc_now())
            bundle = c3s_monthly.build_bundle(report)
            score = _build_score(c3s_monthly.KIND, severity=96, novelty=92, timeliness=84,
                                 confidence=90, shareability=90, sensitivity=4, threshold=80,
                                 reasons=["Nominated official completed-month global finding; required checks still apply"])
            admitted = _enqueue_story_candidate(bot_state, bundle=bundle, score=score,
                source="c3s_monthly", legacy_type=c3s_monthly.KIND, event_id=bundle.event_id,
                review_context={"source": report["publisher"], "source_key": "c3s_monthly",
                    "headline": "Completed-month global temperature finding", "facts": [
                        {"label": "Source", "value": report["source_url"]},
                        {"label": "Month", "value": report["report_month"]}]})
            _record_source_run(current_run, bot_state, "c3s_monthly", started, status="success",
                               observed=1, promoted=int(admitted), drafted=0,
                               note="Attributed retrospective ERA5 report; no annual forecast")
            _drain_and_write_triage_queue(bot_state, current_run, candidate_budget=budget)
        except (c3s_monthly.ReportHeld, ValueError, TypeError) as exc:
            _record_source_run(current_run, bot_state, "c3s_monthly", started, status="failed",
                               error=str(exc) if isinstance(exc, c3s_monthly.ReportHeld) else "c3s_report_held",
                               observed=0, promoted=0, drafted=0)
        finally:
            record_operation_cost(current_run, operation_cost_row("alerts", join=joined, candidate_budget=budget))
    return bot_state
