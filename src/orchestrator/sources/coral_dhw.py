"""Source runner for coral DHW."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data._witness import degraded_via
from src.orchestrator.common import *
from src.two_bot.intern import build_coral_bleaching_bundle


def run_coral_dhw(bot_state: BotState, current_run: dict | None) -> None:
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
            if coral_event.dhw_tier >= 8:
                state.record_synthesis_component(
                    bot_state,
                    kind="coral",
                    region=coral_event.region_id,
                    event_id=coral_event.event_id,
                    metadata={
                        "region_id": coral_event.region_id,
                        "region_full_name": coral_event.region_full_name,
                        "dhw_value": float(coral_event.dhw_value),
                        "dhw_tier": int(coral_event.dhw_tier),
                        "bleaching_level": coral_event.bleaching_level,
                        "stress_level": coral_event.stress_level,
                        "date": coral_event.date,
                    },
                    timestamp=f"{coral_event.date}T00:00:00Z",
                )
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
            coral_bundle = build_coral_bleaching_bundle(coral_event)
            # Enqueue for triage rather than calling _try_two_bot_draft directly.
            # The drain step (_drain_and_write_triage_queue) handles ranking,
            # capping, writing, and credits this source's `drafted` counter.
            #
            # state.record_event, state.update_coral_dhw_tier, and the annual
            # count must ALL fire only when a draft actually ships. If we updated
            # tier on enqueue, triage-spilled candidates would mark their crossing
            # as "consumed" and never re-detect on the next cron — violating spec
            # § 7 ("Spilled candidates are NOT auto-queued for next cron —
            # re-detection is the source's responsibility"). For coral_dhw the
            # tier update IS the re-detection cooldown; gating it on draft success
            # preserves the contract.
            #
            # `state.record_event` is fired by the drain step directly.
            # `state.update_coral_dhw_tier` and `state.increment_coral_dhw_annual_count`
            # fire in the on_draft_success callback below.
            # Capture loop variables for the closure (avoid late-binding bug).
            _region_id = coral_event.region_id
            _dhw_tier = coral_event.dhw_tier

            def _on_success(
                _bs: BotState = bot_state,
                _rid: str = _region_id,
                _tier: int = _dhw_tier,
            ) -> None:
                """Fire side effects gated on a successful draft.

                Runs only if _try_two_bot_draft() returns True in the drain step.
                Triage-spilled candidates skip this callback entirely, so the
                tier update stays unmade and `detect_dhw_events` will re-detect
                the same crossing on the next cron (until it eventually drafts
                or is naturally superseded by a higher tier).
                """
                state.update_coral_dhw_tier(_bs, _rid, _tier)
                state.increment_coral_dhw_annual_count(_bs)

            _enqueue_story_candidate(
                bot_state,
                bundle=coral_bundle,
                score=score,
                event_id=coral_event.event_id,
                source="coral_dhw",
                review_context=review_context,
                city="",
                tweet_date=coral_event.date,
                cooldown_exempt=False,
                legacy_type="coral_bleaching",
                on_draft_success=_on_success,
            )
        degraded_note = degraded_via(readings)
        _record_source_run(
            current_run, bot_state, "coral_dhw", coral_start,
            status="degraded" if degraded_note else "success",
            note=degraded_note,
            observed=len(readings),
            promoted=source_promoted,
            drafted=0,  # drafted credited by _drain_and_write_triage_queue
        )
    except Exception as e:
        print(f"[alerts] Coral DHW error: {e}")
        state.log_error(bot_state, "coral_dhw", str(e))
        _record_source_run(
            current_run, bot_state, "coral_dhw", coral_start,
            status="failed", error=str(e),
        )
    return
