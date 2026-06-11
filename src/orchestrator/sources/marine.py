"""Source runner for marine waves."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_ocean(bot_state: BotState, current_run: dict | None) -> None:
    # 9. Extreme ocean waves (every run)
    print("[alerts] Checking ocean conditions...")
    ocean_start = time.perf_counter()
    try:
        ocean_readings = _fetch_strict(ocean.fetch_ocean_conditions)
        extreme_waves = ocean.detect_extreme_waves(ocean_readings)
        source_promoted = 0
        for wave in extreme_waves:
            if state.is_duplicate(bot_state, wave.event_id):
                continue
            score = score_extreme_wave(wave.wave_height_m)
            if not _should_draft(score, wave.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="Open-Meteo Marine",
                source_key="ocean",
                headline=f"Extreme wave signal in {wave.location}",
                current_run=current_run,
                facts=[
                    _fact("Location", wave.location),
                    _fact("Ocean", wave.ocean),
                    _fact("Wave height", f"{wave.wave_height_m:.1f}m / {wave.wave_height_m * 3.281:.0f}ft"),
                ],
            )
            from src.two_bot.intern import build_extreme_wave_bundle
            wave_bundle = build_extreme_wave_bundle(wave)
            _enqueue_story_candidate(
                bot_state,
                bundle=wave_bundle,
                score=score,
                source="ocean",
                legacy_type="extreme_wave",
                event_id=wave.event_id,
                review_context=review_context,
            )
        _record_source_run(
            current_run, bot_state, "ocean", ocean_start,
            status="success", observed=len(ocean_readings), promoted=source_promoted, drafted=0
        )
    except Exception as e:
        print(f"[alerts] Ocean error: {e}")
        state.log_error(bot_state, "ocean", str(e))
        _record_source_run(
            current_run, bot_state, "ocean", ocean_start,
            status="failed", error=str(e)
        )
    return
