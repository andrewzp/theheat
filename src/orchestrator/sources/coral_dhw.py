"""Source runner for coral DHW."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_coral_dhw(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 9c. Coral Reef Watch DHW threshold crossings (every run)
    print("[alerts] Checking coral bleaching DHW...")
    coral_start = time.perf_counter()
    try:
        readings = _fetch_strict(coral_dhw.fetch_coral_dhw)
        events = coral_dhw.detect_dhw_thresholds(
            readings,
            cast(dict, bot_state.get("coral_dhw_last_tier", {})),
        )
        source_promoted = 0
        source_drafted = 0
        for coral_event in events:
            if state.is_duplicate(bot_state, coral_event.event_id):
                state.update_coral_dhw_tier(bot_state, coral_event.region_id, coral_event.dhw_tier)
                continue
            if _coral_dhw_annual_cap_reached(bot_state):
                break
            score = score_coral_bleaching(
                coral_event.dhw_value,
                coral_event.dhw_tier,
                coral_event.region_full_name,
            )
            if not _should_draft(score, coral_event.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NOAA Coral Reef Watch",
                source_key="coral_dhw",
                headline=f"{coral_event.region_full_name} DHW {coral_event.dhw_value:.1f}",
                current_run=current_run,
                facts=[
                    _fact("Region", coral_event.region_full_name),
                    _fact("Region ID", coral_event.region_id),
                    _fact("DHW", f"{coral_event.dhw_value:.1f} °C-weeks"),
                    _fact("Threshold crossed", f"{coral_event.dhw_tier} °C-weeks"),
                    _fact("Bleaching level", coral_event.bleaching_level),
                ],
            )
            from src.two_bot.intern import build_coral_bleaching_bundle
            coral_bundle = build_coral_bleaching_bundle(coral_event)
            if _try_two_bot_draft(
                coral_bundle,
                bot_state,
                score,
                legacy_type="coral_bleaching",
                event_id=coral_event.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, coral_event.event_id)
                state.update_coral_dhw_tier(bot_state, coral_event.region_id, coral_event.dhw_tier)
                state.increment_coral_dhw_annual_count(bot_state)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "coral_dhw", coral_start,
            status="success",
            observed=len(readings),
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except Exception as e:
        print(f"[alerts] Coral DHW error: {e}")
        state.log_error(bot_state, "coral_dhw", str(e))
        _record_source_run(
            current_run, bot_state, "coral_dhw", coral_start,
            status="failed", error=str(e),
        )
    return drafted
