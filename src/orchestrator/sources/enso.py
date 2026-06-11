"""Source runner for ENSO transitions."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_enso(bot_state: BotState, current_run: dict | None) -> None:
    # 8. ENSO transitions (monthly, check on 1st of month)
    if date.today().day == 1:
        print("[alerts] Checking ENSO status...")
        enso_start = time.perf_counter()
        try:
            enso_readings = _fetch_strict(enso.fetch_enso_data)
            transition = enso.detect_transition(enso_readings)
            enso_score: EditorialScore | None = None
            if transition and not state.is_duplicate(bot_state, transition["event_id"]):
                enso_score = score_enso_transition(
                    transition["oni_value"],
                    transition["previous_duration_months"],
                )
            source_promoted = 1 if enso_score and transition and _should_draft(enso_score, transition["event_id"]) else 0
            if transition and source_promoted:
                review_context = _review_context(
                    source="NOAA CPC",
                    source_key="enso",
                    headline=f"ENSO shifted to {transition['to_status']}",
                    current_run=current_run,
                    facts=[
                        _fact("New phase", transition["to_status"]),
                        _fact("ONI", f"{transition['oni_value']:+.1f}"),
                        _fact("Previous duration", f"{transition['previous_duration_months']} months"),
                    ],
                )
                from src.two_bot.intern import build_enso_bundle
                enso_bundle = build_enso_bundle(transition)
                _enqueue_story_candidate(
                    bot_state,
                    bundle=enso_bundle,
                    score=enso_score,
                    source="enso",
                    legacy_type="enso",
                    event_id=transition["event_id"],
                    review_context=review_context,
                )
            observed = len(enso_readings) if hasattr(enso_readings, "__len__") else 0
            _record_source_run(
                current_run, bot_state, "enso", enso_start,
                status="success", observed=observed, promoted=source_promoted, drafted=0
            )
        except Exception as e:
            print(f"[alerts] ENSO error: {e}")
            state.log_error(bot_state, "enso", str(e))
            _record_source_run(
                current_run, bot_state, "enso", enso_start,
                status="failed", error=str(e)
            )
    else:
        skipped_start = time.perf_counter()
        _record_source_run(
            current_run, bot_state, "enso", skipped_start,
            status="skipped", note="Runs on the 1st of the month"
        )
    return
