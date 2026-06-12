"""Source runner for NSIDC Snow Today extremes."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data import last_good
from src.orchestrator.common import *


def run_nsidc_snow(bot_state: BotState, current_run: dict | None) -> None:
    print("[alerts] Checking NSIDC Snow Today...")
    started = time.perf_counter()
    source_promoted = 0
    fetch_completed = False
    try:
        readings = _fetch_strict(nsidc_snow.fetch_snow_today)
        fetch_completed = True
        if readings:
            last_good.write(
                bot_state,
                "nsidc_snow",
                readings[0].date,
                _snow_last_good_payload(readings),
            )
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
            _event_kind = event.kind

            def _on_success(
                _bs: BotState = bot_state,
                _kind: str = _event_kind,
            ) -> None:
                if _kind == "seasonal_snow_record":
                    _increment_snow_annual_count(_bs)

            _enqueue_story_candidate(
                bot_state,
                bundle=bundle,
                score=score,
                source="nsidc_snow",
                legacy_type=legacy_type,
                event_id=event.event_id,
                review_context=review_context,
                city=event.station,
                tweet_date=event.date,
                on_draft_success=_on_success,
            )

        nsidc_snow.update_snow_tracking(cast(dict, bot_state), readings)
        _record_source_run(
            current_run,
            bot_state,
            "nsidc_snow",
            started,
            status="success",
            observed=len(readings),
            promoted=source_promoted,
            drafted=0,
        )
    except Exception as exc:
        print(f"[alerts] NSIDC Snow Today error: {exc}")
        cached = (
            last_good.read(bot_state, "nsidc_snow", max_age_days=21)
            if not fetch_completed else None
        )
        if cached is not None:
            _record_source_run(
                current_run,
                bot_state,
                "nsidc_snow",
                started,
                status="degraded",
                error=f"served last-good ({cached.data_date})",
            )
            return
        state.log_error(bot_state, "nsidc_snow", str(exc))
        _record_source_run(
            current_run,
            bot_state,
            "nsidc_snow",
            started,
            status="failed",
            error=str(exc),
        )
    return


def _snow_last_good_payload(readings: list) -> dict:
    strongest_delta = max(
        (row for row in readings if row.swe_delta_mm is not None),
        key=lambda row: float(row.swe_delta_mm or 0.0),
        default=None,
    )
    strongest_swe = max(
        (row for row in readings if row.swe_mm is not None),
        key=lambda row: float(row.swe_mm or 0.0),
        default=None,
    )
    return {
        "date": readings[0].date,
        "point_count": len(readings),
        "max_delta": _snow_payload_row(strongest_delta, "swe_delta_mm"),
        "max_swe": _snow_payload_row(strongest_swe, "swe_mm"),
    }


def _snow_payload_row(reading, metric: str) -> dict | None:
    if reading is None:
        return None
    value = getattr(reading, metric)
    if value is None:
        return None
    return {
        "station": reading.station,
        metric: round(float(value), 1),
        "lat": round(float(reading.lat), 3),
        "lon": round(float(reading.lon), 3),
    }
