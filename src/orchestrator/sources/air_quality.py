"""Source runner for Open-Meteo Air Quality PM2.5 and dust signals."""

from __future__ import annotations

import os

# ruff: noqa: F403,F405
from src.orchestrator.common import *
from src.data import air_quality
from src.two_bot.intern import build_dust_event_bundle, build_pm25_hazard_bundle

# A 638-city sweep routinely loses its rate-limited tail chunk to Open-Meteo's
# per-minute budget even after recovery retries (see src/data/air_quality.py).
# Losing a small fraction of cities is still a successful run — the source
# delivered the bulk of the data — so only a meaningful coverage shortfall is
# "degraded" and only zero observed is "failed". Without this, a permanently
# partial source reads as 0% success to the health sentinel and false-alarms.
AQ_MIN_COVERAGE: float = 0.90


def _enabled(env_name: str) -> bool:
    return os.environ.get(env_name, "1").strip().lower() not in {"0", "false", "no", "off"}


def _get_city_tier(bot_state: BotState, tier_key: str, city_slug: str) -> tuple[int, str | None]:
    tiers = bot_state.get(tier_key, {})
    entry = tiers.get(city_slug) if isinstance(tiers, dict) else None
    if not isinstance(entry, dict):
        return 0, None
    return int(entry.get("tier", 0)), entry.get("date")


def _set_city_tier(
    bot_state: BotState,
    tier_key: str,
    city_slug: str,
    tier: int,
    obs_date: str,
) -> None:
    """Record a city tier only after a draft succeeds."""
    tiers = cast(dict, bot_state).setdefault(tier_key, {})
    tiers[city_slug] = {"tier": tier, "date": obs_date}


def _should_emit_tier(
    bot_state: BotState,
    *,
    tier_key: str,
    city_slug: str,
    tier: int,
    event_date: str,
    event_id: str,
) -> bool:
    last_tier, last_date = _get_city_tier(bot_state, tier_key, city_slug)
    return (
        (last_date != event_date or tier > last_tier)
        and not state.is_duplicate(bot_state, event_id)
    )


def run_air_quality(bot_state: BotState, current_run: dict | None, cities: list[dict]) -> None:
    """Check batched CAMS air-quality data and enqueue qualifying candidates."""
    print("[alerts] Checking air quality (PM2.5 24h-mean / dust peak)...")
    aq_start = time.perf_counter()
    source_promoted = 0
    observed = 0
    failures = 0
    pm25_enabled = _enabled("THEHEAT_AQ_PM25_ENABLED")
    dust_enabled = _enabled("THEHEAT_AQ_DUST_ENABLED")

    try:
        observations = air_quality.fetch_batch_air_quality(cities)

        for city_row, obs in zip(cities, observations, strict=False):
            city_name = str(city_row.get("city", ""))
            country = str(city_row.get("country", ""))
            if obs is None:
                failures += 1
                continue
            observed += 1

            if pm25_enabled:
                pm25_event = air_quality.detect_pm25_hazard(obs)
                if pm25_event is not None:
                    city_slug = air_quality._city_slug(pm25_event.city)
                    if _should_emit_tier(
                        bot_state,
                        tier_key="air_quality_pm25_tiers",
                        city_slug=city_slug,
                        tier=pm25_event.tier,
                        event_date=pm25_event.date,
                        event_id=pm25_event.event_id,
                    ):
                        score = score_pm25_hazard(
                            pm25_event.pm25_24h_mean,
                            pm25_event.tier,
                            pm25_event.who_multiple,
                        )
                        if _should_draft(score, pm25_event.event_id):
                            source_promoted += 1
                            review_context = _review_context(
                                source="CAMS via Open-Meteo Air Quality API (model estimate)",
                                source_key="air_quality",
                                headline=(
                                    f"PM2.5 hazard: {city_name} "
                                    f"{pm25_event.pm25_24h_mean:.0f} μg/m³ 24h-mean "
                                    f"({pm25_event.who_multiple:.1f}x WHO; tier {pm25_event.tier})"
                                ),
                                current_run=current_run,
                                facts=[
                                    _fact("City", city_name),
                                    _fact("Country", country),
                                    _fact("PM2.5 24h-mean", f"{pm25_event.pm25_24h_mean:.1f} μg/m³"),
                                    _fact("WHO 2021 24h multiple", f"{pm25_event.who_multiple:.1f}x"),
                                    _fact("Tier", f"{pm25_event.tier}/3"),
                                    _fact("US AQI daily-max", pm25_event.us_aqi_daily_max),
                                    _fact("Evidence grade", "model_estimated; CAMS 0.4 degree grid"),
                                ],
                            )
                            bundle = build_pm25_hazard_bundle(pm25_event)

                            def _on_success_pm25(
                                _bs: BotState = bot_state,
                                _slug: str = city_slug,
                                _tier: int = pm25_event.tier,
                                _date: str = pm25_event.date,
                            ) -> None:
                                _set_city_tier(_bs, "air_quality_pm25_tiers", _slug, _tier, _date)

                            _enqueue_story_candidate(
                                bot_state,
                                bundle=bundle,
                                score=score,
                                source="air_quality",
                                legacy_type="air_quality_hazard",
                                event_id=pm25_event.event_id,
                                review_context=review_context,
                                on_draft_success=_on_success_pm25,
                            )

            if dust_enabled:
                dust_event = air_quality.detect_dust_event(obs)
                if dust_event is not None:
                    city_slug = air_quality._city_slug(dust_event.city)
                    if _should_emit_tier(
                        bot_state,
                        tier_key="air_quality_dust_tiers",
                        city_slug=city_slug,
                        tier=dust_event.tier,
                        event_date=dust_event.date,
                        event_id=dust_event.event_id,
                    ):
                        score = score_dust_event(dust_event.dust_daily_max, dust_event.tier)
                        if _should_draft(score, dust_event.event_id):
                            source_promoted += 1
                            review_context = _review_context(
                                source="CAMS via Open-Meteo Air Quality API (model estimate)",
                                source_key="air_quality",
                                headline=(
                                    f"Dust event: {city_name} "
                                    f"{dust_event.dust_daily_max:.0f} μg/m³ daily-max "
                                    f"(tier {dust_event.tier})"
                                ),
                                current_run=current_run,
                                facts=[
                                    _fact("City", city_name),
                                    _fact("Country", country),
                                    _fact("Dust daily-max", f"{dust_event.dust_daily_max:.0f} μg/m³"),
                                    _fact("Tier", f"{dust_event.tier}/3"),
                                    _fact("AOD", f"{dust_event.aod_daily_max:.2f}" if dust_event.aod_daily_max else None),
                                    _fact("Evidence grade", "model_estimated; CAMS 0.4 degree grid"),
                                ],
                            )
                            bundle = build_dust_event_bundle(dust_event)

                            def _on_success_dust(
                                _bs: BotState = bot_state,
                                _slug: str = city_slug,
                                _tier: int = dust_event.tier,
                                _date: str = dust_event.date,
                            ) -> None:
                                _set_city_tier(_bs, "air_quality_dust_tiers", _slug, _tier, _date)

                            _enqueue_story_candidate(
                                bot_state,
                                bundle=bundle,
                                score=score,
                                source="air_quality",
                                legacy_type="dust_event",
                                event_id=dust_event.event_id,
                                review_context=review_context,
                                on_draft_success=_on_success_dust,
                            )

        status = "success"
        error = None
        note = None
        total = len(cities)
        if total and observed == 0:
            status = "failed"
            error = f"all {total} air-quality city fetches failed"
            state.log_error(bot_state, "air_quality", error)
        elif failures:
            coverage = observed / total if total else 1.0
            note = (
                f"{failures} air-quality city fetches failed "
                f"({coverage:.0%} coverage)"
            )
            if coverage < AQ_MIN_COVERAGE:
                status = "degraded"

        _record_source_run(
            current_run,
            bot_state,
            "air_quality",
            aq_start,
            status=status,
            observed=observed,
            promoted=source_promoted,
            drafted=0,
            error=error,
            note=note,
            details={
                "failed_cities": failures,
                "pm25_enabled": pm25_enabled,
                "dust_enabled": dust_enabled,
            },
        )
    except Exception as exc:
        print(f"[alerts] Air quality error: {exc}")
        state.log_error(bot_state, "air_quality", str(exc))
        _record_source_run(
            current_run,
            bot_state,
            "air_quality",
            aq_start,
            status="failed",
            error=str(exc),
        )
    return
