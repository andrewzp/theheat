"""Source runner for coastal water levels."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_water_levels(bot_state: BotState, current_run: dict | None) -> None:
    # 10. Storm surge / abnormal water levels (every run)
    print("[alerts] Checking coastal water levels...")
    water_levels_start = time.perf_counter()
    try:
        metrics: dict = {}
        wl_readings = _fetch_strict(water_levels.fetch_water_levels, metrics_out=metrics)
        surges = water_levels.detect_storm_surge(wl_readings)
        source_promoted = 0
        for surge in surges:
            if state.is_duplicate(bot_state, surge.event_id):
                continue
            score = score_storm_surge(surge.anomaly_m)
            if not _should_draft(score, surge.event_id):
                continue
            review_context = _review_context(
                source="NOAA CO-OPS",
                source_key="water_levels",
                headline=f"Observed coastal water-level residual at {surge.station_name}",
                current_run=current_run,
                facts=[
                    _fact("Station", surge.station_name),
                    _fact("State", surge.state),
                    _fact("Observed time GMT", surge.evidence.get("valid_time")),
                    _fact("Source quality", surge.evidence.get("quality_status")),
                    _fact("Claim scope", surge.evidence.get("claim_scope")),
                    _fact("Anomaly", f"{surge.anomaly_m:.2f}m / {surge.anomaly_m * 3.281:.1f}ft above predicted"),
                    _fact("Observed vs predicted", f"{surge.observed_m:.2f}m vs {surge.predicted_m:.2f}m"),
                ],
            )
            from src.two_bot.intern import build_storm_surge_bundle
            ss_bundle = build_storm_surge_bundle(surge)
            admitted = _enqueue_story_candidate(
                bot_state,
                bundle=ss_bundle,
                score=score,
                source="water_levels",
                legacy_type="storm_surge",
                event_id=surge.event_id,
                review_context=review_context,
            )
            source_promoted += int(admitted)
        _record_source_run(
            current_run, bot_state, "water_levels", water_levels_start,
            status="degraded" if metrics.get("stations_withheld") else "success",
            observed=len(wl_readings), promoted=source_promoted, drafted=0,
            note=f"{metrics['stations_withheld']} station(s) withheld" if metrics.get("stations_withheld") else None,
            details={"coastal_observations": metrics}
        )
    except Exception as e:
        print(f"[alerts] Water levels error: {e}")
        state.log_error(bot_state, "water_levels", str(e))
        _record_source_run(
            current_run, bot_state, "water_levels", water_levels_start,
            status="failed", error=str(e)
        )
    return
