"""Source runner for GDACS global disasters."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data import gdacs_intake
from src.data._witness import degraded_via
from src.editorial import hazard_episodes
from src.orchestrator.common import *

# Per-capture admission dispositions. For every fetched event exactly one holds:
# observed = witness_skipped + history_duplicates + score_withheld
#            + queue_new + queue_reused + queue_refused, and promoted = queue_new.
INTAKE_COUNTS = ("witness_skipped", "history_duplicates", "score_withheld",
                 "queue_new", "queue_reused", "queue_refused")


def run_gdacs(bot_state: BotState, current_run: dict | None) -> None:
    # 5. GDACS global disasters (Red only — Orange isn't extraordinary)
    print("[alerts] Checking GDACS global disasters...")
    gdacs_start = time.perf_counter()
    try:
        disasters = _fetch_strict(gdacs.fetch_disasters, min_severity="Red")
        diagnostics = getattr(disasters, "source_diagnostics", None)
        selection = (diagnostics or {}).get("current_selection") or {}
        capture = selection.get("capture_sha256")
        intake = {**dict.fromkeys(INTAKE_COUNTS, 0), "pending_disagreements": 0}
        # One returned capture stages in exact source-key order, so its XML item
        # order cannot change admission. Inputs without a capture keep theirs.
        for disaster in gdacs_intake.staged_order(disasters) if capture else disasters:
            if disaster.source_leg == gdacs.GDACS_SUBTYPE_LEG:
                intake["witness_skipped"] += 1
                continue
            if state.is_duplicate(bot_state, disaster.event_id):
                intake["history_duplicates"] += 1
                continue
            score = score_global_disaster(disaster.severity, disaster.disaster_type)
            if not _should_draft(score, disaster.event_id):
                intake["score_withheld"] += 1
                continue
            # W07 (THEHEAT_HAZARD_EPISODES, default off): a repeat poll without new facts buys no writer.
            episode = hazard_episodes.admit(bot_state, hazard_episodes.gdacs_assertion(disaster), source="gdacs",
                                            event_id=disaster.event_id, score=score, summary=disaster.name)
            if not episode.allowed:
                intake["queue_refused"] += 1
                continue
            review_context = _review_context(
                source="GDACS",
                source_key="gdacs",
                headline=f"{disaster.disaster_type} alert: {disaster.name}",
                current_run=current_run,
                facts=[
                    _fact("Alert tier", disaster.severity),
                    _fact("Disaster type", disaster.disaster_type),
                    _fact("Country", disaster.country),
                    _fact("Name", disaster.name),
                ],
            )
            hazard_episodes.bind(review_context, episode)
            # Event-scoped repetition now flows through the two-bot
            # memory slice as ``recent_tweets_same_event``.
            from src.two_bot.intern import build_global_disaster_bundle
            gd_bundle = build_global_disaster_bundle(disaster)
            admission: dict = {}
            admitted = _enqueue_story_candidate(
                bot_state,
                bundle=gd_bundle,
                score=score,
                source="gdacs",
                legacy_type="global_disaster",
                event_id=disaster.event_id,
                review_context=review_context,
                intake_identity=gdacs_intake.intake_identity(disaster, capture) if capture else None,
                admission_out=admission,
            )
            disposition = admission.get("disposition") or ("new" if admitted else "refused")
            intake["queue_new" if disposition == "new" else "queue_reused" if disposition == "reused" else "queue_refused"] += 1
            intake["pending_disagreements"] += admission.get("pending_disagreements", 0)
        degraded_note = degraded_via(disasters)
        if diagnostics and diagnostics.get("source_leg") == gdacs.GDACS_GEORSS_LEG:
            product_note = (
                "configured limited GeoRSS product; MAP withdrawn pending qualification"
                if diagnostics.get("configured_product") == "gdacs-georss"
                else "served via georss"
            )
            degraded_note = (
                f"{product_note}; validated_feed_items:{diagnostics['feed_items_validated']} "
                f"selected_alerts:{diagnostics['selected_alerts']} "
                f"unknown_country_items:{diagnostics['unknown_country_items']}"
            )
            if diagnostics.get("withheld_selected_alerts"):
                degraded_note += (
                    f" withheld_selected_alerts:{diagnostics['withheld_selected_alerts']}"
                )
            if diagnostics.get("quarantined_items"):
                degraded_note += f" quarantined_items:{diagnostics['quarantined_items']}"
            if diagnostics.get("withheld_current_alerts"):
                degraded_note += f" withheld_current_alerts:{diagnostics['withheld_current_alerts']}"
            for key in ("withheld_ambiguous_alerts", "ambiguous_groups", "exact_duplicate_items"):
                if selection.get(key):
                    degraded_note += f" {key}:{selection[key]}"
            for key in ("queue_reused", "queue_refused", "pending_disagreements"):
                if intake[key]:
                    degraded_note += f" {key}:{intake[key]}"
        elif diagnostics and diagnostics.get("source_leg") == gdacs.GDACS_SUBTYPE_LEG:
            legs = diagnostics["legs"]
            failed_legs = [name for name, result in legs.items() if result["status"] == "failed"]
            degraded_note = (
                "served via subtype_witnesses (GeoRSS primary unavailable); "
                "earthquake/cyclone scope only; "
                f"successful_legs:{len(legs) - len(failed_legs)} "
                f"failed_legs:{','.join(failed_legs) or 'none'} "
                f"selected_alerts:{diagnostics['selected_alerts']}"
            )
        _record_source_run(
            current_run, bot_state, "gdacs", gdacs_start,
            status="degraded" if degraded_note else "success",
            observed=len(disasters),
            promoted=intake["queue_new"],
            drafted=0,
            note=degraded_note,
            details={"feed_diagnostics": diagnostics, "intake": intake} if diagnostics else None,
        )
    except Exception as e:
        print(f"[alerts] GDACS error: {e}")
        state.log_error(bot_state, "gdacs", str(e))
        _record_source_run(
            current_run, bot_state, "gdacs", gdacs_start,
            status="failed", error=str(e)
        )
    return
