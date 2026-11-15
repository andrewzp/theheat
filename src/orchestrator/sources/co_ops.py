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
        report_holds = 0
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
            from src.editorial.observed_scope import enabled as observed_mode
            from src.data import coastal_observed
            if observed_mode():
                report_id = f"coastal_report_{surge.station_id}_{surge.date}"
                aliases = {report_id, f"surge_notable_{surge.station_id}_{surge.date}",
                           f"surge_major_{surge.station_id}_{surge.date}"}
                if (any(state.is_duplicate(bot_state, key) for key in aliases)
                        or any(d.get("event_id") in aliases for d in bot_state.get("drafts", []))
                        or any(key in bot_state.get("publish_ledger", {}) for key in aliases)):
                    continue
                # Reacquire a stable exact-time snapshot before constructing the
                # new report; never relabel the broad discovery window as a receipt.
                try:
                    point = coastal_observed.fetch_point(surge.station_id, surge.evidence.get("valid_time"))
                    ss_bundle = coastal_observed.build_bundle(point)
                except Exception:  # noqa: BLE001 — one unavailable gauge cannot stop its peers
                    report_holds += 1
                    continue
                score = score_storm_surge(ss_bundle.headline_metric["value"])
                if not _should_draft(score, ss_bundle.event_id):
                    continue
                review_context = _review_context(
                    source="NOAA CO-OPS", source_key="water_levels",
                    headline=f"Observed gauge residual at {ss_bundle.where}", current_run=current_run,
                    facts=[_fact("Station", ss_bundle.where),
                           _fact("Observed time UTC", point["valid_time"]),
                           _fact("Source quality", point["quality_status"]),
                           _fact("Claim scope", point["claim_scope"])])
            else:
                ss_bundle = build_storm_surge_bundle(surge)
            admitted = _enqueue_story_candidate(
                bot_state,
                bundle=ss_bundle,
                score=score,
                source="water_levels",
                legacy_type=ss_bundle.signal_kind,
                event_id=ss_bundle.event_id,
                review_context=review_context,
            )
            source_promoted += int(admitted)
        _record_source_run(
            current_run, bot_state, "water_levels", water_levels_start,
            status="degraded" if metrics.get("stations_withheld") or report_holds else "success",
            observed=len(wl_readings), promoted=source_promoted, drafted=0,
            note=(f"{metrics.get('stations_withheld', 0)} station(s) withheld; "
                  f"{report_holds} exact snapshot(s) held") if metrics.get("stations_withheld") or report_holds else None,
            details={"coastal_observations": metrics, "exact_snapshot_holds": report_holds}
        )
    except Exception as e:
        print(f"[alerts] Water levels error: {e}")
        state.log_error(bot_state, "water_levels", str(e))
        _record_source_run(
            current_run, bot_state, "water_levels", water_levels_start,
            status="failed", error=str(e)
        )
    return
