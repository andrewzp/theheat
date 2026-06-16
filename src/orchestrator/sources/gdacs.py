"""Source runner for GDACS global disasters."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data._witness import degraded_via
from src.orchestrator.common import *


def run_gdacs(bot_state: BotState, current_run: dict | None) -> None:
    # 5. GDACS global disasters (Red only — Orange isn't extraordinary)
    print("[alerts] Checking GDACS global disasters...")
    gdacs_start = time.perf_counter()
    try:
        disasters = _fetch_strict(gdacs.fetch_disasters, min_severity="Red")
        source_promoted = 0
        for disaster in disasters:
            if disaster.source_leg == gdacs.GDACS_SUBTYPE_LEG:
                continue
            if state.is_duplicate(bot_state, disaster.event_id):
                continue
            score = score_global_disaster(disaster.severity, disaster.disaster_type)
            if not _should_draft(score, disaster.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="GDACS",
                source_key="gdacs",
                headline=f"{disaster.disaster_type} alert: {disaster.name}",
                current_run=current_run,
                facts=[
                    _fact("Alert tier", disaster.severity),
                    _fact("Disaster type", disaster.disaster_type),
                    _fact("Country", disaster.country),
                    _fact("Name", disaster.name),
                ],
            )
            # Event-scoped repetition now flows through the two-bot
            # memory slice as ``recent_tweets_same_event``.
            from src.two_bot.intern import build_global_disaster_bundle
            gd_bundle = build_global_disaster_bundle(disaster)
            _enqueue_story_candidate(
                bot_state,
                bundle=gd_bundle,
                score=score,
                source="gdacs",
                legacy_type="global_disaster",
                event_id=disaster.event_id,
                review_context=review_context,
            )
        degraded_note = degraded_via(disasters)
        _record_source_run(
            current_run, bot_state, "gdacs", gdacs_start,
            status="degraded" if degraded_note else "success",
            observed=len(disasters),
            promoted=source_promoted,
            drafted=0,
            note=degraded_note,
        )
    except Exception as e:
        print(f"[alerts] GDACS error: {e}")
        state.log_error(bot_state, "gdacs", str(e))
        _record_source_run(
            current_run, bot_state, "gdacs", gdacs_start,
            status="failed", error=str(e)
        )
    return
