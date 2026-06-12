"""Per-cycle finalize and pruning helpers."""

from __future__ import annotations

# ruff: noqa: F403,F405
import os

from src.orchestrator.common import *


try:
    MAX_DRAFTS_PER_CYCLE = int(os.environ.get("THEHEAT_MAX_DRAFTS_PER_CYCLE", "3"))
except ValueError:
    MAX_DRAFTS_PER_CYCLE = 3


_PRUNE_SOURCE_KEY_BY_TYPE = {
    "all_time_high": "open_meteo_extreme_signals",
    "all_time_low": "open_meteo_extreme_signals",
    "monthly_high": "open_meteo_extreme_signals",
    "monthly_low": "open_meteo_extreme_signals",
    "anomaly_hot": "open_meteo_extreme_signals",
    "anomaly_cold": "open_meteo_extreme_signals",
    "record": "open_meteo_extreme_signals",
    "record_low": "open_meteo_extreme_signals",
    "record_streak": "open_meteo_extreme_signals",
    "simultaneous_records": "open_meteo_extreme_signals",
    "country_high": "open_meteo_extreme_signals",
    "country_low": "open_meteo_extreme_signals",
    "fire": "firms",
    "fire_footprint": "fire_footprint",
    "co2_milestone": "co2",
    "ch4_milestone": "ch4_milestone",
    "coral_bleaching": "coral_dhw",
    "severe_weather": "nws_alerts",
    "global_disaster": "gdacs",
    "global_flood": "copernicus_ems",
    "sea_ice_record": "sea_ice",
    "drought": "drought",
    "enso": "enso",
    "extreme_wave": "ocean",
    "storm_surge": "water_levels",
    "river_flood": "river_gauges",
    "marine_heatwave": "ocean_sst",
    "ice_mass_record": "ice_mass",
    "cyclone_rapid_intensification": "nhc",
    "cyclone_tier_crossing": "nhc",
    "cyclone_landfall": "nhc",
    "cyclone_basin_record": "nhc",
    "precipitation_extreme": "gpm_imerg",
    "snow_extreme": "nsidc_snow",
    "seasonal_snow_record": "nsidc_snow",
    "oscillation_alignment": "nao_ao_alignment",
    "ozone_hole_peak": "ozone_hole",
    "synthesis_fire_drought_heat": "synthesis_fire_drought_heat",
}


def _prune_source_keys_for_draft(draft: dict) -> list[str]:
    source_keys: list[str] = []
    mapped_source = _PRUNE_SOURCE_KEY_BY_TYPE.get(draft.get("type") or "")
    if mapped_source:
        source_keys.append(mapped_source)
    review_context = draft.get("review_context")
    if isinstance(review_context, dict):
        source_key = review_context.get("source_key")
        if isinstance(source_key, str) and source_key and source_key not in source_keys:
            source_keys.append(source_key)
    return source_keys


def _prune_weakest_cycle_drafts(
    bot_state: BotState,
    drafts_before: int,
    current_run: dict | None,
    drafted: int,
    *,
    pruned_ids_out: set | None = None,
) -> int:
    """Enforce MAX_DRAFTS_PER_CYCLE by dropping the weakest drafts added
    this cycle.

    When a draft is pruned, its ``event_id`` must also be removed from
    ``posted_events`` — each source block records the event as "seen"
    as soon as it saves a draft, so leaving pruned IDs in the list
    permanently blocks future cycles from re-drafting that event even
    though no tweet ever shipped. Also rolls back overstated
    source-level ``drafted`` telemetry in the run record.

    Returns the post-prune drafted count the caller should report.
    """
    drafts = bot_state.get("drafts", [])
    new_drafts = drafts[drafts_before:]
    if len(new_drafts) <= MAX_DRAFTS_PER_CYCLE:
        return drafted

    scored = [(d, d.get("score", {}).get("total", 0)) for d in new_drafts]
    scored.sort(key=lambda x: x[1], reverse=True)
    keep = {id(d) for d, _ in scored[:MAX_DRAFTS_PER_CYCLE]}
    pruned = [d for d, _ in scored[MAX_DRAFTS_PER_CYCLE:]]
    bot_state["drafts"] = drafts[:drafts_before] + [d for d in new_drafts if id(d) in keep]

    pruned_event_ids = {d.get("event_id") for d in pruned if d.get("event_id")}
    if pruned_ids_out is not None:
        pruned_ids_out.update(pruned_event_ids)
    if pruned_event_ids:
        bot_state["posted_events"] = [
            e for e in bot_state.get("posted_events", [])
            if e not in pruned_event_ids
        ]
        if current_run is not None:
            for d in pruned:
                source_keys = _prune_source_keys_for_draft(d)
                for s_run in current_run.get("sources", []):
                    for src in source_keys:
                        if (
                            s_run.get("source") == src
                            or s_run.get("source", "").startswith(f"{src}_")
                        ) and s_run.get("drafted", 0) > 0:
                            s_run["drafted"] -= 1
                            break
                    else:
                        continue
                    break

    print(f"[alerts] Pruned {len(pruned)} weaker drafts, kept top {MAX_DRAFTS_PER_CYCLE}")
    for d, s in scored[MAX_DRAFTS_PER_CYCLE:]:
        print(f"[alerts]   Pruned: score={s} {d.get('text', '')[:50]}...")
        ctx = _current_suppression_ctx()
        if ctx is not None:
            _record_downstream_suppression(
                bot_state=bot_state,
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=d.get("event_id", ""),
                score=d.get("score") or {},
                kill_stage="cycle_cap",
                kill_reason=f"Pruned by MAX_DRAFTS_PER_CYCLE={MAX_DRAFTS_PER_CYCLE}",
                summary=d.get("text", "")[:120] or d.get("event_id"),
            )
    return MAX_DRAFTS_PER_CYCLE


def _fire_surviving_draft_callbacks(pending: list, pruned_event_ids: set) -> None:
    """Fire deferred ``on_draft_success`` callbacks EXCEPT for drafts that were
    pruned by the cycle cap (Codex #5).

    ``pending`` is a list of ``(event_id, callback)`` collected by
    ``_drain_and_write_triage_queue(..., defer_callbacks=pending)``. A draft pruned
    by ``_prune_weakest_cycle_drafts`` must not consume dedup/cap state (annual
    counters, per-region/-city tiers) for a tweet that was never queued — so its
    callback is skipped. When nothing was pruned (the common case), every callback
    fires, exactly as before the deferral.
    """
    for event_id, callback in pending:
        if event_id in pruned_event_ids:
            continue
        try:
            callback()
        except Exception as cb_exc:  # noqa: BLE001
            print(f"[alerts] deferred on_draft_success callback error: {cb_exc!r}")
