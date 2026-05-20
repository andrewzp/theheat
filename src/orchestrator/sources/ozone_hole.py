"""Source runner for Antarctic ozone hole seasonal peaks."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


OZONE_HOLE_ANNUAL_CAP = 2


def run_ozone_hole(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    if date.today().month not in {8, 9, 10, 11}:
        skipped_start = time.perf_counter()
        _record_source_run(
            current_run, bot_state, "ozone_hole", skipped_start,
            status="skipped", note="Runs daily during Aug-Nov",
        )
        return drafted

    print("[alerts] Checking Antarctic ozone hole...")
    source_start = time.perf_counter()
    try:
        readings = _fetch_strict(ozone_hole.fetch_ozone_hole_data)
        annual_peaks = _fetch_strict(ozone_hole.fetch_ozone_hole_annual_peaks)
        event = ozone_hole.detect_seasonal_peak(
            readings,
            annual_peaks,
            last_peaks=cast(dict, bot_state.get("ozone_hole_last_peak", {})),
        )
        source_promoted = 0
        source_drafted = 0
        if event and state.is_duplicate(bot_state, event.event_id):
            state.record_ozone_hole_peak(bot_state, event)
        elif event and not _ozone_hole_annual_cap_reached(bot_state):
            score = score_ozone_hole_peak(event.area_million_km2, event.record_year)
            if _should_draft(score, event.event_id):
                source_promoted = 1
                review_context = _review_context(
                    source="NASA Ozone Watch",
                    source_key="ozone_hole",
                    headline=f"Antarctic ozone hole peaked at {event.area_million_km2:.1f} million km2",
                    current_run=current_run,
                    facts=[
                        _fact("Peak date", event.peak_date),
                        _fact("Area", f"{event.area_million_km2:.1f} million km2"),
                        _fact("Previous year", event.previous_year),
                        _fact("Previous area", event.previous_area_million_km2),
                        _fact("Record year", event.record_year),
                    ],
                )
                from src.two_bot.intern import build_ozone_hole_bundle
                bundle = build_ozone_hole_bundle(event)
                _event = event

                def _on_success(
                    _bs: BotState = bot_state,
                    _ev = _event,
                ) -> None:
                    state.record_ozone_hole_peak(_bs, _ev)
                    state.increment_ozone_hole_annual_count(_bs)

                _enqueue_story_candidate(
                    bot_state,
                    bundle=bundle,
                    score=score,
                    source="ozone_hole",
                    legacy_type="ozone_hole_peak",
                    event_id=event.event_id,
                    review_context=review_context,
                    on_draft_success=_on_success,
                )
        _record_source_run(
            current_run, bot_state, "ozone_hole", source_start,
            status="success",
            observed=len(readings),
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except Exception as e:
        print(f"[alerts] Ozone hole error: {e}")
        state.log_error(bot_state, "ozone_hole", str(e))
        _record_source_run(
            current_run, bot_state, "ozone_hole", source_start,
            status="failed", error=str(e),
        )
    return drafted


def _ozone_hole_annual_cap_reached(bot_state: BotState) -> bool:
    year_key = str(date.today().year)
    count = int(bot_state.get("ozone_hole_annual_count", {}).get(year_key, 0) or 0)
    if count >= OZONE_HOLE_ANNUAL_CAP:
        print(f"[ozone_hole] Annual cap reached ({count}/{OZONE_HOLE_ANNUAL_CAP} for {year_key}), skipping")
        return True
    return False
