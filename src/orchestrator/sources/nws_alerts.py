"""Source runner for NWS severe weather alerts."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_nws_alerts(bot_state: BotState, current_run: dict | None) -> None:
    # 4. NWS severe weather alerts (US)
    print("[alerts] Checking NWS severe weather...")
    nws_start = time.perf_counter()
    try:
        alerts = _fetch_strict(nws_alerts.fetch_alerts)
        source_promoted = 0
        for alert in alerts:
            if state.is_duplicate(bot_state, alert.event_id):
                continue
            score = score_severe_weather(alert.event_type, alert.severity)
            if not _should_draft(score, alert.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NWS Alerts",
                source_key="nws_alerts",
                headline=f"{alert.event_type} for {alert.area}",
                current_run=current_run,
                facts=[
                    _fact("Event", alert.event_type),
                    _fact("Area", alert.area),
                    _fact("Severity", alert.severity),
                    _fact("Max wind gust", alert.max_wind_gust or "—"),
                    _fact("Max hail", alert.max_hail_size or "—"),
                    _fact("Tornado detection", alert.tornado_detection or "—"),
                ],
            )
            # Severe weather: ported to two-bot writer 2026-05-03.
            # Event-scoped repetition now flows through the two-bot
            # memory slice as ``recent_tweets_same_event``.
            from src.two_bot.intern import build_severe_weather_bundle
            sw_bundle = build_severe_weather_bundle(alert)
            _enqueue_story_candidate(
                bot_state,
                bundle=sw_bundle,
                score=score,
                source="nws_alerts",
                legacy_type="severe_weather",
                event_id=alert.event_id,
                review_context=review_context,
            )
        _record_source_run(
            current_run, bot_state, "nws_alerts", nws_start,
            status="success", observed=len(alerts), promoted=source_promoted, drafted=0
        )
    except Exception as e:
        print(f"[alerts] NWS error: {e}")
        state.log_error(bot_state, "nws_alerts", str(e))
        _record_source_run(
            current_run, bot_state, "nws_alerts", nws_start,
            status="failed", error=str(e)
        )
    return
