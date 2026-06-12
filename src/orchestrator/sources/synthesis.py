"""Source runner for cross-source synthesis."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_synthesis(bot_state: BotState, current_run: dict | None) -> None:
    # --- Cross-source synthesis (runs after every per-source section) ---
    print("[alerts] Running cross-source synthesis...")
    synthesis_start = time.perf_counter()
    synthesis_observed = 0
    synthesis_promoted = 0
    try:
        signals = [
            *synthesis.detect_fire_drought_heat(bot_state),
            *synthesis.detect_marine_compound(bot_state),
        ]
        synthesis_observed = len(signals)
        for sig in signals:
            if state.is_duplicate(bot_state, sig.event_id):
                continue
            if state.is_synthesis_on_cooldown(
                bot_state,
                sig.rule_name,
                sig.region,
                days=synthesis.cooldown_days_for_rule(sig.rule_name),
            ):
                continue
            comps = sig.components
            if sig.rule_name == synthesis.RULE_MARINE_COMPOUND:
                score = score_synthesis_marine_compound(
                    dhw_value=comps["coral_dhw_value"],
                    dhw_tier=comps["coral_dhw_tier"],
                    sst_anomaly_c=comps["sst_anomaly_c"],
                    coral_region=comps["coral_region_full_name"],
                    sst_region=comps["sst_region_display_name"],
                )
                review_context = _review_context(
                    source="Cross-source synthesis (CRW DHW + regional SST anomaly)",
                    source_key="synthesis_fire_drought_heat",
                    headline=sig.headline,
                    current_run=current_run,
                    facts=[
                        _fact("Coral region", comps["coral_region_full_name"]),
                        _fact("DHW", f"{comps['coral_dhw_value']:.1f} C-weeks"),
                        _fact("DHW tier", str(comps["coral_dhw_tier"])),
                        _fact("SST region", comps["sst_region_display_name"]),
                        _fact("SST anomaly", f"{comps['sst_anomaly_c']:+.1f}C"),
                        _fact("Window", f"{comps['window_days']} days"),
                    ],
                )
                synth_payload = {
                    "event_id": sig.event_id,
                    "region": comps["coral_region_full_name"],
                    "kind": "marine_compound",
                    "headline": sig.headline,
                    "rule_name": sig.rule_name,
                    "components": [
                        {
                            "kind": "coral",
                            "region_id": comps["coral_region_id"],
                            "region": comps["coral_region_full_name"],
                            "dhw_value": comps["coral_dhw_value"],
                            "dhw_tier": comps["coral_dhw_tier"],
                        },
                        {
                            "kind": "sst_anomaly",
                            "region_slug": comps["sst_region_slug"],
                            "region": comps["sst_region_display_name"],
                            "anomaly_c": comps["sst_anomaly_c"],
                            "tier": comps["sst_tier"],
                        },
                    ],
                    "window_days": comps["window_days"],
                    "total_score": score.total if hasattr(score, "total") else None,
                }
                legacy_type = "synthesis_marine_compound"
            else:
                score = score_synthesis_fire_drought_heat(
                    drought_d4_pct=comps["drought_d4_pct"],
                    fire_peak_frp=comps["fire_peak_frp"],
                    heat_peak_anomaly_c=comps.get(
                        "heat_peak_anomaly_c",
                        # Fallback for any legacy (pre-fix) components: treat
                        # absolute as zero-anomaly to avoid absurd severity.
                        0.0,
                    ),
                    component_count={
                        "fires": comps["fire_count"],
                        "heats": comps["heat_count"],
                    },
                    heat_kind=comps["heat_peak_kind"],
                )
                review_context = _review_context(
                    source="Cross-source synthesis (FIRMS + USDM + Open-Meteo)",
                    source_key="synthesis_fire_drought_heat",
                    headline=sig.headline,
                    current_run=current_run,
                    facts=[
                        _fact("State", sig.region),
                        _fact("D4 drought %", f"{comps['drought_d4_pct']:.1f}"),
                        _fact("Peak fire FRP", f"{comps['fire_peak_frp']:.0f} MW"),
                        _fact("Peak heat city", comps["heat_peak_city"]),
                        _fact("Peak heat value", f"{comps['heat_peak_value_c']:.1f}C"),
                        _fact("Window", f"{comps['window_days']} days"),
                    ],
                )
                synth_payload = {
                    "event_id": sig.event_id,
                    "region": sig.region,
                    "kind": "fire_drought_heat",
                    "headline": sig.headline,
                    "rule_name": sig.rule_name,
                    "components": [
                        {"kind": "drought", "d4_pct": comps["drought_d4_pct"]},
                        {"kind": "fire", "peak_frp_mw": comps["fire_peak_frp"], "peak_region": comps["fire_peak_region"]},
                        {"kind": "heat", "peak_city": comps["heat_peak_city"], "peak_kind": comps["heat_peak_kind"], "peak_value_c": comps["heat_peak_value_c"]},
                    ],
                    "window_days": comps["window_days"],
                    "total_score": score.total if hasattr(score, "total") else None,
                }
                legacy_type = "synthesis_fire_drought_heat"
            synthesis_promoted += 1
            if not _should_draft(score, sig.event_id):
                continue
            from src.two_bot.intern import build_synthesis_bundle
            synth_bundle = build_synthesis_bundle(synth_payload)
            _rule_name = sig.rule_name
            _region = sig.region

            def _on_success(
                _bs: BotState = bot_state,
                _rule: str = _rule_name,
                _region: str = _region,
            ) -> None:
                state.record_synthesis_fired(_bs, _rule, _region)

            _enqueue_story_candidate(
                bot_state,
                bundle=synth_bundle,
                score=score,
                source="synthesis_fire_drought_heat",
                legacy_type=legacy_type,
                event_id=sig.event_id,
                review_context=review_context,
                on_draft_success=_on_success,
            )
        state.prune_stale_synthesis_components(bot_state)
        _record_source_run(
            current_run, bot_state, "synthesis_fire_drought_heat", synthesis_start,
            status="success",
            observed=synthesis_observed,
            promoted=synthesis_promoted,
            drafted=0,
        )
    except Exception as e:
        print(f"[alerts] Synthesis error: {e}")
        state.log_error(bot_state, "synthesis_fire_drought_heat", str(e))
        _record_source_run(
            current_run, bot_state, "synthesis_fire_drought_heat", synthesis_start,
            status="failed", error=str(e),
        )
    return
