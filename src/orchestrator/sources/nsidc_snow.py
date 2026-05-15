"""Source runner for NSIDC Snow Today extremes."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_nsidc_snow(bot_state: BotState, current_run: dict | None) -> int:
    print("[alerts] Checking NSIDC Snow Today...")
    started = time.perf_counter()
    source_drafted = 0
    source_promoted = 0
    try:
        readings = _fetch_strict(nsidc_snow.fetch_snow_today)
        events = nsidc_snow.detect_snow_extremes(readings, cast(dict, bot_state))
        for event in events:
            if state.is_duplicate(bot_state, event.event_id):
                continue
            if event.kind == "seasonal_snow_record":
                if _snow_annual_cap_reached(bot_state):
                    continue
                score = score_seasonal_snow_record(
                    event.mm_swe,
                    event.years_of_archive or 1,
                    event.station,
                )
            else:
                score = score_snow_extreme(
                    event.mm_swe,
                    event.deviation_from_record_mm,
                    event.station,
                )
            if not _should_draft(score, event.event_id, summary=event.station):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NSIDC Snow Today",
                source_key="nsidc_snow",
                headline=f"{event.station}: {event.mm_swe:.0f} mm SWE signal",
                current_run=current_run,
                facts=[
                    _fact("Station", event.station),
                    _fact("Event kind", event.kind),
                    _fact("SWE", f"{event.mm_swe:.1f} mm"),
                    _fact("Current SWE", (
                        f"{event.swe_mm:.1f} mm" if event.swe_mm is not None else None
                    )),
                    _fact("Previous record", (
                        f"{event.previous_record_mm:.1f} mm"
                        if event.previous_record_mm is not None
                        else None
                    )),
                    _fact("Elevation", (
                        f"{event.elevation_m:.0f} m" if event.elevation_m is not None else None
                    )),
                ],
            )
            from src.two_bot.intern import build_seasonal_snow_bundle, build_snow_extreme_bundle

            bundle = (
                build_seasonal_snow_bundle(event)
                if event.kind == "seasonal_snow_record"
                else build_snow_extreme_bundle(event)
            )
            legacy_type = (
                "seasonal_snow_record"
                if event.kind == "seasonal_snow_record"
                else "snow_extreme"
            )
            if _try_two_bot_draft(
                bundle,
                bot_state,
                score,
                legacy_type=legacy_type,
                event_id=event.event_id,
                review_context=review_context,
                city=event.station,
                tweet_date=event.date,
            ):
                state.record_event(bot_state, event.event_id)
                if event.kind == "seasonal_snow_record":
                    _increment_snow_annual_count(bot_state)
                source_drafted += 1

        nsidc_snow.update_snow_tracking(cast(dict, bot_state), readings)
        _record_source_run(
            current_run,
            bot_state,
            "nsidc_snow",
            started,
            status="success",
            observed=len(readings),
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except Exception as exc:
        print(f"[alerts] NSIDC Snow Today error: {exc}")
        state.log_error(bot_state, "nsidc_snow", str(exc))
        _record_source_run(
            current_run,
            bot_state,
            "nsidc_snow",
            started,
            status="failed",
            error=str(exc),
        )
    return source_drafted
