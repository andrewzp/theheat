"""Source runner for Methane milestones."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_methane(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 3b. CH4 methane milestones.
    print("[alerts] Checking CH4 methane...")
    ch4_drafted_today = any(
        d.get("type", "").startswith("ch4")
        and d.get("created_at", "").startswith(date.today().isoformat())
        for d in bot_state.get("drafts", [])
    )
    ch4_start = time.perf_counter()
    try:
        readings = _fetch_strict(methane.fetch_ch4_milestones)
        last_milestone_raw = bot_state.get("ch4_last_milestone")
        last_milestone = int(last_milestone_raw) if last_milestone_raw is not None else None
        ch4_milestone = methane.detect_milestone(readings, last_milestone=last_milestone)
        source_promoted = 0
        source_drafted = 0
        if ch4_milestone and state.is_duplicate(bot_state, ch4_milestone.event_id):
            state.update_ch4_last_milestone(bot_state, ch4_milestone.ppb_crossed)
        elif (
            ch4_milestone
            and not ch4_drafted_today
            and not _ch4_annual_cap_reached(bot_state)
        ):
            score = score_ch4_milestone(ch4_milestone.ppb_crossed, ch4_milestone.actual_ppb)
            if _should_draft(score, ch4_milestone.event_id):
                source_promoted += 1
                review_context = _review_context(
                    source="NOAA GML",
                    source_key="ch4_milestone",
                    headline=f"Methane crossed {ch4_milestone.ppb_crossed} ppb",
                    current_run=current_run,
                    facts=[
                        _fact("Actual reading", f"{ch4_milestone.actual_ppb:.1f} ppb"),
                        _fact("Milestone crossed", f"{ch4_milestone.ppb_crossed} ppb"),
                        _fact("Pre-industrial baseline", "722 ppb"),
                    ],
                )
                from src.two_bot.intern import build_ch4_milestone_bundle
                ch4_bundle = build_ch4_milestone_bundle(ch4_milestone)
                _ppb_crossed = ch4_milestone.ppb_crossed

                def _on_success(
                    _bs: BotState = bot_state,
                    _ppb: int = _ppb_crossed,
                ) -> None:
                    state.update_ch4_last_milestone(_bs, _ppb)
                    state.increment_ch4_annual_count(_bs)

                _enqueue_story_candidate(
                    bot_state,
                    bundle=ch4_bundle,
                    score=score,
                    source="ch4_milestone",
                    legacy_type="ch4_milestone",
                    event_id=ch4_milestone.event_id,
                    review_context=review_context,
                    on_draft_success=_on_success,
                )
        _record_source_run(
            current_run, bot_state, "ch4_milestone", ch4_start,
            status="success", observed=len(readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] CH4 error: {e}")
        state.log_error(bot_state, "ch4_milestone", str(e))
        _record_source_run(
            current_run, bot_state, "ch4_milestone", ch4_start,
            status="failed", error=str(e)
        )
    return drafted
