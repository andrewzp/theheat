"""Source runner for GPM IMERG precipitation extremes."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_gpm_imerg(
    bot_state: BotState,
    current_run: dict | None,
    cities: list[dict],
) -> int:
    print("[alerts] Checking GPM IMERG precipitation...")
    started = time.perf_counter()
    source_drafted = 0
    source_promoted = 0
    try:
        max_cities_raw = os.environ.get("GPM_IMERG_MAX_CITIES")
        max_cities = int(max_cities_raw) if max_cities_raw else None
        readings = _fetch_strict(
            gpm_imerg.fetch_daily_precip,
            cities=cities,
            max_cities=max_cities,
        )
        events = gpm_imerg.detect_precip_records(readings, cast(dict, bot_state))
        for event in events:
            if state.is_duplicate(bot_state, event.event_id):
                continue
            score = score_precipitation_extreme(
                event.mm_total,
                event.period_days,
                event.deviation_from_record_mm,
                event.country,
            )
            if not _should_draft(score, event.event_id, summary=event.location):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NASA GPM IMERG",
                source_key="gpm_imerg",
                headline=f"{event.location}: {event.mm_total:.0f} mm rainfall signal",
                current_run=current_run,
                facts=[
                    _fact("Location", event.location),
                    _fact("Country", event.country),
                    _fact("Rainfall", f"{event.mm_total:.1f} mm"),
                    _fact("Period", f"{event.period_days} day(s)"),
                    _fact("Previous record", (
                        f"{event.previous_record_mm:.1f} mm"
                        if event.previous_record_mm is not None
                        else None
                    )),
                    _fact("City count", event.city_count),
                ],
            )
            from src.two_bot.intern import build_precipitation_bundle

            bundle = build_precipitation_bundle(event)
            if _try_two_bot_draft(
                bundle,
                bot_state,
                score,
                legacy_type="precipitation_extreme",
                event_id=event.event_id,
                review_context=review_context,
                city=event.location if event.kind != "country_precip_event" else "",
                tweet_date=event.date,
                cooldown_exempt=event.kind == "country_precip_event",
            ):
                state.record_event(bot_state, event.event_id)
                source_drafted += 1

        gpm_imerg.update_precip_tracking(cast(dict, bot_state), readings)
        _record_source_run(
            current_run,
            bot_state,
            "gpm_imerg",
            started,
            status="success",
            observed=len(readings),
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except SourceSkipped as exc:
        print(f"[alerts] GPM IMERG skipped: {exc}")
        _record_source_run(
            current_run,
            bot_state,
            "gpm_imerg",
            started,
            status="skipped",
            note=str(exc),
        )
    except Exception as exc:
        print(f"[alerts] GPM IMERG error: {exc}")
        state.log_error(bot_state, "gpm_imerg", str(exc))
        _record_source_run(
            current_run,
            bot_state,
            "gpm_imerg",
            started,
            status="failed",
            error=str(exc),
        )
    return source_drafted
