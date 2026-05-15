"""Source runner for river gauges."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_river_gauges(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 11. River flood stages (every run)
    print("[alerts] Checking river flood stages...")
    river_start = time.perf_counter()
    try:
        river_readings = _fetch_strict(river_gauges.fetch_river_levels)
        floods = river_gauges.detect_floods(river_readings)
        source_promoted = 0
        source_drafted = 0
        for flood in floods:
            if state.is_duplicate(bot_state, flood.event_id):
                continue
            score = score_river_flood(flood.above_by_ft)
            if not _should_draft(score, flood.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="USGS Water",
                source_key="river_gauges",
                headline=f"{flood.river} flood-stage exceedance",
                current_run=current_run,
                facts=[
                    _fact("River", flood.river),
                    _fact("Location", flood.location),
                    _fact("Gauge height", f"{flood.gauge_height_ft:.1f}ft"),
                    _fact("Above flood stage", f"{flood.above_by_ft:.1f}ft"),
                ],
            )
            from src.two_bot.intern import build_river_flood_bundle
            rf_bundle = build_river_flood_bundle(flood)
            if _try_two_bot_draft(
                rf_bundle, bot_state, score,
                legacy_type="river_flood",
                event_id=flood.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, flood.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "river_gauges", river_start,
            status="success", observed=len(river_readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] River gauges error: {e}")
        state.log_error(bot_state, "river_gauges", str(e))
        _record_source_run(
            current_run, bot_state, "river_gauges", river_start,
            status="failed", error=str(e)
        )
    return drafted
