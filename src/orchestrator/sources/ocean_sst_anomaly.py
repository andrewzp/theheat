"""Source runner for per-region SST anomaly detection."""

from __future__ import annotations

# ruff: noqa: F403,F405
from collections import Counter
from functools import partial

from src.editorial.marine_evidence import record_reading

from src.orchestrator.common import *
from src.two_bot.intern import build_regional_sst_anomaly_bundle


def run_ocean_sst_anomaly(bot_state: BotState, current_run: dict | None) -> None:
    print("[alerts] Checking per-region SST anomaly...")
    start = time.perf_counter()
    try:
        collection = ocean_sst_anomaly.collect_all_regions(strict=False)
        readings = collection.readings
        marine_outcomes = Counter(record_reading(bot_state, "sst_anomaly", r) for r in readings)
        reading_year = readings[0].date[:4] if readings else str(date.today().year)
        prefix = f"{reading_year}/"
        last_tiers = {
            key[len(prefix):]: tier
            for key, tier in bot_state.get("sst_anom_last_tier", {}).items()
            if key.startswith(prefix)
        }
        events = ocean_sst_anomaly.detect_regional_sst_anomaly_events(readings, last_tiers)

        source_promoted = 0
        for event in events:
            if state.is_duplicate(bot_state, event.event_id):
                state.update_sst_anom_tier(
                    bot_state,
                    event.region_slug,
                    event.tier,
                    event.date,
                )
                continue
            if _sst_anom_annual_cap_reached(bot_state, event.date):
                break

            score = score_regional_sst_anomaly(
                event.region_slug,
                event.anomaly_c,
                event.tier,
            )
            if not _should_draft(score, event.event_id):
                continue

            review_context = _review_context(
                source="NOAA Coral Reef Watch 5km SST anomaly (gridded)",
                source_key="ocean_sst_anomaly",
                headline=(
                    f"{event.region_display_name} SST anomaly: "
                    f"{event.anomaly_c:+.2f}°C tier {event.tier}"
                ),
                current_run=current_run,
                facts=[
                    _fact("Region", event.region_display_name),
                    _fact("Sampled regional mean anomaly", f"{event.anomaly_c:+.2f}°C"),
                    _fact("Tier", str(event.tier)),
                    _fact("Grid cells", str(event.cells_used)),
                    _fact("Signal type", "Satellite-analysis sample mean; not a record or Hobday MHW"),
                ],
            )
            bundle = build_regional_sst_anomaly_bundle(event)

            region_slug = event.region_slug
            tier = event.tier
            reading_date = event.date

            def _on_success(
                _bs: BotState = bot_state,
                _slug: str = region_slug,
                _tier: int = tier,
                _date: str = reading_date,
            ) -> None:
                state.update_sst_anom_tier(_bs, _slug, _tier, _date)
                state.increment_sst_anom_annual_count(_bs, _date)

            accepted = _enqueue_story_candidate(
                bot_state,
                bundle=bundle,
                score=score,
                source="ocean_sst_anomaly",
                legacy_type="regional_sst_anomaly",
                event_id=event.event_id,
                review_context=review_context,
                city="",
                tweet_date=event.date,
                cooldown_exempt=False,
                on_draft_success=_on_success,
                annual_cap_check=partial(_sst_anom_annual_cap_reached, bot_state, event.date),
            )
            source_promoted += int(accepted)

        _record_source_run(
            current_run,
            bot_state,
            "ocean_sst_anomaly",
            start,
            status=collection.status,
            observed=collection.observed,
            promoted=source_promoted,
            drafted=0,
            note=collection.note,
            details={**collection.details(), "marine_components": dict(marine_outcomes)},
        )
    except Exception:
        # Source outcomes are fixed codes above. Unexpected runner errors must
        # also avoid persisting arbitrary response/exception payloads.
        error = "regional_sst_runner_error"
        print(f"[alerts] ocean_sst_anomaly error: {error}")
        state.log_error(bot_state, "ocean_sst_anomaly", error)
        _record_source_run(
            current_run,
            bot_state,
            "ocean_sst_anomaly",
            start,
            status="failed",
            error=error,
        )
    return
