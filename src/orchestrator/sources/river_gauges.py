"""Source runner for river gauges."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data._witness import degraded_via
from src.orchestrator.common import *


def run_river_gauges(bot_state: BotState, current_run: dict | None) -> None:
    # 11. River flood stages (every run)
    print("[alerts] Checking river flood stages...")
    river_start = time.perf_counter()
    try:
        river_readings = _fetch_strict(river_gauges.fetch_river_levels)
        floods = river_gauges.detect_floods(river_readings)
        source_promoted = 0
        for flood in floods:
            if state.is_duplicate(bot_state, flood.event_id):
                continue
            is_model_fallback = flood.source_leg == "open_meteo_flood"
            score = (
                score_river_flood(discharge_ratio=flood.discharge_ratio)
                if is_model_fallback
                else score_river_flood(flood.above_by_ft)
            )
            if not _should_draft(score, flood.event_id):
                continue
            source_promoted += 1
            if is_model_fallback:
                review_source = "Open-Meteo Flood / GloFAS"
                review_facts = [
                    _fact("River", flood.river),
                    _fact("Location", flood.location),
                    _fact("Modeled discharge", f"{flood.discharge_m3s:.0f} m3/s" if flood.discharge_m3s is not None else None),
                    _fact("Model threshold", f"{flood.discharge_threshold_m3s:.0f} m3/s" if flood.discharge_threshold_m3s is not None else None),
                    _fact("Evidence", "model fallback; not a gauge reading"),
                ]
            else:
                review_source = "USGS Water"
                review_facts = [
                    _fact("River", flood.river),
                    _fact("Location", flood.location),
                    _fact("Gauge height", f"{flood.gauge_height_ft:.1f}ft" if flood.gauge_height_ft is not None else None),
                    _fact("Above flood stage", f"{flood.above_by_ft:.1f}ft" if flood.above_by_ft is not None else None),
                ]
            review_context = _review_context(
                source=review_source,
                source_key="river_gauges",
                headline=(
                    f"{flood.river} modeled high-discharge signal"
                    if is_model_fallback
                    else f"{flood.river} flood-stage exceedance"
                ),
                current_run=current_run,
                facts=review_facts,
            )
            from src.two_bot.intern import build_river_flood_bundle
            rf_bundle = build_river_flood_bundle(flood)
            _enqueue_story_candidate(
                bot_state,
                bundle=rf_bundle,
                score=score,
                source="river_gauges",
                legacy_type="river_flood",
                event_id=flood.event_id,
                review_context=review_context,
            )
        served = degraded_via(river_readings)
        _record_source_run(
            current_run, bot_state, "river_gauges", river_start,
            status="degraded" if served else "success",
            observed=len(river_readings), promoted=source_promoted, drafted=0,
            note=served,
        )
    except Exception as e:
        print(f"[alerts] River gauges error: {e}")
        state.log_error(bot_state, "river_gauges", str(e))
        _record_source_run(
            current_run, bot_state, "river_gauges", river_start,
            status="failed", error=str(e)
        )
    return
