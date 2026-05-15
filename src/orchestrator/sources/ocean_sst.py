"""Source runner for global ocean SST."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_ocean_sst(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 9b. Global ocean SST marine-heatwave streak (every run)
    print("[alerts] Checking global ocean SST...")
    sst_start = time.perf_counter()
    try:
        obs = _fetch_strict(ocean_sst.fetch_global_sst)
        source_promoted = 0
        source_drafted = 0
        event = None
        if obs is not None:
            prior_streak = bot_state.get(
                "ocean_sst_streak",
                state.DEFAULT_STATE["ocean_sst_streak"],
            )
            new_streak, event = ocean_sst.detect_streak_milestone(obs, cast(dict, prior_streak))
            state.update_ocean_sst_streak(bot_state, new_streak)

        if event and not state.is_duplicate(bot_state, event.event_id):
            score = score_marine_heatwave(
                event.days, event.peak_anomaly_c, event.years_of_data,
            )
            if _should_draft(score, event.event_id):
                source_promoted += 1
                review_context = _review_context(
                    source="NOAA OISST v2.1 (ClimateReanalyzer)",
                    source_key="ocean_sst",
                    headline=f"Global ocean SST streak: day {event.days}",
                    current_run=current_run,
                    facts=[
                        _fact("Streak length", f"{event.days} consecutive days above record"),
                        _fact("Today's global-mean SST", f"{event.today_c:.2f}°C"),
                        _fact("Prior daily max", f"{event.archive_max_c:.2f}°C ({event.archive_max_year})"),
                        _fact("Peak anomaly during streak", f"{event.peak_anomaly_c:+.2f}°C"),
                        _fact("Archive span", f"{event.years_of_data} years"),
                    ],
                )
                from src.two_bot.intern import build_marine_heatwave_bundle
                mhw_bundle = build_marine_heatwave_bundle(event)
                if _try_two_bot_draft(
                    mhw_bundle, bot_state, score,
                    legacy_type="marine_heatwave",
                    event_id=event.event_id,
                    review_context=review_context,
                ):
                    state.record_event(bot_state, event.event_id)
                    drafted += 1
                    source_drafted += 1
        _record_source_run(
            current_run, bot_state, "ocean_sst", sst_start,
            status="success",
            observed=1 if obs is not None else 0,
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except Exception as e:
        print(f"[alerts] Ocean SST error: {e}")
        state.log_error(bot_state, "ocean_sst", str(e))
        _record_source_run(
            current_run, bot_state, "ocean_sst", sst_start,
            status="failed", error=str(e),
        )
    return drafted
