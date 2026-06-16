"""Source runner for Copernicus EMS floods."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data._witness import degraded_via
from src.orchestrator.common import *


def run_copernicus_ems(bot_state: BotState, current_run: dict | None) -> None:
    # 5a. Copernicus EMS global floods (active Rapid Mapping activations)
    print("[alerts] Checking Copernicus EMS global floods...")
    copernicus_start = time.perf_counter()
    try:
        activations = _fetch_strict(copernicus_ems.fetch_active_flood_activations)
        flood_events = copernicus_ems.detect_flood_events(
            activations,
            cast(dict, bot_state.get("flood_activation_tiers", {})),
        )
        source_promoted = 0
        for activation in flood_events:
            if state.is_duplicate(bot_state, activation.event_id):
                continue
            score = score_global_flood(
                activation.severity,
                activation.populations_affected,
                activation.affected_area_km2,
                activation.country,
            )
            if not _should_draft(score, activation.event_id, summary=activation.name):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="Copernicus EMS Rapid Mapping",
                source_key="copernicus_ems",
                headline=f"{activation.event_type} activation: {activation.name}",
                current_run=current_run,
                facts=[
                    _fact("Activation ID", activation.activation_id),
                    _fact("Country", activation.country),
                    _fact("Event type", activation.event_type),
                    _fact("Severity", activation.severity),
                    _fact("Population affected", f"{activation.populations_affected:,}"),
                    _fact("Affected area", f"{activation.affected_area_km2:.1f} km2"),
                    _fact("Copernicus URL", activation.copernicus_url),
                ],
            )
            from src.two_bot.intern import build_global_flood_bundle

            flood_bundle = build_global_flood_bundle(activation)
            _activation_id = activation.activation_id
            _severity = activation.severity

            def _on_success(
                _bs: BotState = bot_state,
                _activation_id: str = _activation_id,
                _severity: str = _severity,
            ) -> None:
                state.update_flood_activation_tier(
                    _bs, _activation_id, _severity
                )
                state.increment_flood_annual_count(_bs)

            _enqueue_story_candidate(
                bot_state,
                bundle=flood_bundle,
                score=score,
                source="copernicus_ems",
                legacy_type="global_flood",
                event_id=activation.event_id,
                review_context=review_context,
                on_draft_success=_on_success,
            )
        degraded_note = degraded_via(activations)
        _record_source_run(
            current_run, bot_state, "copernicus_ems", copernicus_start,
            status="degraded" if degraded_note else "success",
            observed=len(activations),
            promoted=source_promoted,
            drafted=0,
            note=degraded_note,
        )
    except Exception as e:
        print(f"[alerts] Copernicus EMS flood error: {e}")
        state.log_error(bot_state, "copernicus_ems", str(e))
        _record_source_run(
            current_run, bot_state, "copernicus_ems", copernicus_start,
            status="failed", error=str(e)
        )
    return
