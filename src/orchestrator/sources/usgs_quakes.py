"""Source runner for USGS significant earthquakes."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_usgs_quakes(bot_state: BotState, current_run: dict | None) -> None:
    print("[alerts] Checking USGS significant earthquakes...")
    usgs_start = time.perf_counter()
    try:
        quakes = _fetch_strict(usgs_quakes.fetch_significant_earthquakes)
        source_promoted = 0
        for quake in quakes:
            if state.is_duplicate(bot_state, quake.event_id):
                continue
            score = score_usgs_earthquake(
                quake.magnitude,
                quake.alert,
                quake.significance,
                quake.tsunami,
            )
            if not _should_draft(score, quake.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="USGS Earthquake Hazards Program",
                source_key="usgs_quakes",
                headline=f"M{quake.magnitude:.1f} earthquake: {quake.place}",
                current_run=current_run,
                facts=[
                    _fact("USGS event ID", quake.usgs_id),
                    _fact("Magnitude", f"M{quake.magnitude:.1f}"),
                    _fact("Place", quake.place),
                    _fact("Depth", f"{quake.depth_km:.1f} km" if quake.depth_km is not None else None),
                    _fact("PAGER alert", quake.alert or "—"),
                    _fact("Tsunami flag", "yes" if quake.tsunami else "no"),
                    _fact("USGS URL", quake.url),
                ],
            )
            from src.two_bot.intern import build_usgs_earthquake_bundle

            quake_bundle = build_usgs_earthquake_bundle(quake)
            _enqueue_story_candidate(
                bot_state,
                bundle=quake_bundle,
                score=score,
                source="usgs_quakes",
                legacy_type="usgs_earthquake",
                event_id=quake.event_id,
                review_context=review_context,
            )
        _record_source_run(
            current_run,
            bot_state,
            "usgs_quakes",
            usgs_start,
            status="success",
            observed=len(quakes),
            promoted=source_promoted,
            drafted=0,
        )
    except Exception as e:
        print(f"[alerts] USGS earthquake error: {e}")
        state.log_error(bot_state, "usgs_quakes", str(e))
        _record_source_run(
            current_run,
            bot_state,
            "usgs_quakes",
            usgs_start,
            status="failed",
            error=str(e),
        )
