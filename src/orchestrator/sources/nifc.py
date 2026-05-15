"""Source runner for NIFC fire footprint alerts."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_fire_footprint(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 2b. Fire footprint / acreage (NIFC, once per day)
    today_iso = date.today().isoformat()
    if bot_state.get("fire_footprint_last_run") != today_iso:
        print("[alerts] Checking fire footprints (NIFC)...")
        ff_start = time.perf_counter()
        source_promoted = 0
        source_drafted = 0
        try:
            complexes = _fetch_strict(fire_footprint.fetch_active_fire_perimeters)
            crossings = fire_footprint.detect_tier_crossings(complexes, cast(dict, bot_state))
            for fc in crossings:
                try:
                    if state.is_duplicate(bot_state, fc.event_id):
                        continue
                    score = score_fire_footprint(
                        hectares=fc.hectares,
                        tier=fc.tier,
                        region=fc.region,
                        has_name=bool(fc.name),
                    )
                    if not _should_draft(score, fc.event_id):
                        continue
                    source_promoted += 1
                    tier_idx = min(fc.tier, len(fire_footprint.TIERS_HECTARES) - 1)
                    tier_threshold = fire_footprint.TIERS_HECTARES[tier_idx]
                    review_context = _review_context(
                        source="NIFC",
                        source_key="fire_footprint",
                        headline=f"Fire complex crossed {tier_threshold:,} ha",
                        current_run=current_run,
                        facts=[
                            _fact("Complex", fc.name or fc.complex_id),
                            _fact("Country", fc.country),
                            _fact("Region", fc.region),
                            _fact("Cumulative burn area", f"{int(fc.hectares):,} ha"),
                            _fact("Tier crossed", f"{tier_threshold:,} ha"),
                            _fact("Ignition date", fc.start_date.isoformat() if fc.start_date else "—"),
                        ],
                    )
                    from src.two_bot.intern import build_fire_footprint_bundle
                    ff_bundle = build_fire_footprint_bundle(fc)
                    if _try_two_bot_draft(
                        ff_bundle, bot_state, score,
                        legacy_type="fire_footprint",
                        event_id=fc.event_id,
                        review_context=review_context,
                    ):
                        state.record_event(bot_state, fc.event_id)
                        state.update_fire_complex_tier(bot_state, fc.complex_id, fc.tier)
                        drafted += 1
                        source_drafted += 1
                except Exception as fc_err:
                    print(f"[alerts] Fire footprint: error processing {fc.complex_id}: {fc_err}")
                    state.log_error(bot_state, "fire_footprint", f"{fc.complex_id}: {fc_err}")
            # Only mark as run-today on success — failed fetches retry on next cron tick.
            bot_state["fire_footprint_last_run"] = today_iso
            _record_source_run(
                current_run, bot_state, "fire_footprint", ff_start,
                status="success", observed=len(complexes),
                promoted=source_promoted, drafted=source_drafted,
            )
        except Exception as e:
            print(f"[alerts] Fire footprint error: {e}")
            state.log_error(bot_state, "fire_footprint", str(e))
            _record_source_run(
                current_run, bot_state, "fire_footprint", ff_start,
                status="failed", error=str(e),
            )
    else:
        ff_skipped_start = time.perf_counter()
        _record_source_run(
            current_run, bot_state, "fire_footprint", ff_skipped_start,
            status="skipped", note="Already ran today",
        )
    return drafted
