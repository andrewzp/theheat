"""Source runner for CO2 milestones."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_co2(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 3. CO2 milestones.
    # Annual cap: at most CO2_ANNUAL_CAP tweets/year. Milestone crossings are
    # the only CO2 signal type we tweet — weekly telemetry was deemed too
    # routine ("we should only talk about CO2 in the extreme"). Growth rate is
    # ~2-3 ppm/year so natural milestone rate is well under cap; the guardrail
    # covers future signal types and pathological multi-crossing weeks.
    print("[alerts] Checking CO2...")
    co2_drafted_today = any(
        d.get("type", "").startswith("co2")
        and d.get("created_at", "").startswith(date.today().isoformat())
        for d in bot_state.get("drafts", [])
    )
    co2_start = time.perf_counter()
    try:
        readings = _fetch_strict(co2.fetch_co2_data)
        milestone = co2.detect_milestone(readings)
        source_promoted = 0
        source_drafted = 0
        if (
            milestone
            and not co2_drafted_today
            and not state.is_duplicate(bot_state, milestone.event_id)
            and not _co2_annual_cap_reached(bot_state)
        ):
            score = score_co2_milestone(milestone.ppm_crossed, milestone.actual_ppm)
            if _should_draft(score, milestone.event_id):
                source_promoted += 1
                review_context = _review_context(
                    source="NOAA GML",
                    source_key="co2",
                    headline=f"Mauna Loa crossed {milestone.ppm_crossed} ppm",
                    current_run=current_run,
                    facts=[
                        _fact("Actual reading", f"{milestone.actual_ppm:.2f} ppm"),
                        _fact("Milestone crossed", f"{milestone.ppm_crossed} ppm"),
                        _fact("Pre-industrial baseline", "280 ppm"),
                    ],
                )
                from src.two_bot.intern import build_co2_milestone_bundle
                co2_bundle = build_co2_milestone_bundle(milestone)
                if _try_two_bot_draft(
                    co2_bundle, bot_state, score,
                    legacy_type="co2_milestone",
                    event_id=milestone.event_id,
                    review_context=review_context,
                ):
                    state.record_event(bot_state, milestone.event_id)
                    _increment_co2_annual_count(bot_state)
                    drafted += 1
                    co2_drafted_today = True
                    source_drafted += 1
        _record_source_run(
            current_run, bot_state, "co2", co2_start,
            status="success", observed=len(readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] CO2 error: {e}")
        state.log_error(bot_state, "co2", str(e))
        _record_source_run(
            current_run, bot_state, "co2", co2_start,
            status="failed", error=str(e)
        )
    return drafted
