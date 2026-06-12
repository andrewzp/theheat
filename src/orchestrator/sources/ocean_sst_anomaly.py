"""Source runner for per-region SST anomaly detection."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *
from src.two_bot.intern import build_regional_sst_anomaly_bundle


def run_ocean_sst_anomaly(bot_state: BotState, current_run: dict | None) -> None:
    print("[alerts] Checking per-region SST anomaly...")
    start = time.perf_counter()
    try:
        readings = ocean_sst_anomaly.fetch_all_regions(strict=False)
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

            source_promoted += 1
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
                    _fact("Area-weighted anomaly", f"{event.anomaly_c:+.2f}°C"),
                    _fact("Tier", str(event.tier)),
                    _fact("Grid cells", str(event.cells_used)),
                    _fact("Signal type", "Area-weighted basin-mean anomaly; not Hobday MHW"),
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

            _enqueue_story_candidate(
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
            )

        _record_source_run(
            current_run,
            bot_state,
            "ocean_sst_anomaly",
            start,
            status="success",
            observed=len(ocean_sst_anomaly.REGION_REGISTRY),
            promoted=source_promoted,
            drafted=0,
        )
    except Exception as exc:
        print(f"[alerts] ocean_sst_anomaly error: {exc}")
        state.log_error(bot_state, "ocean_sst_anomaly", str(exc))
        _record_source_run(
            current_run,
            bot_state,
            "ocean_sst_anomaly",
            start,
            status="failed",
            error=str(exc),
        )
    return
