"""Cyclone source orchestration helpers."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import cast

from src import state
from src.data._witness import degraded_via
from src.data.cyclones import (
    BasinRecordEvent,
    CycloneAdvisory,
    LandfallEvent,
    LandThreatEvent,
    RapidIntensificationEvent,
    TierCrossingEvent,
    _landmass_slug,
    detect_land_threats,
    latest_advisories_by_storm,
    tracking_key,
)
from src.data.open_meteo import load_cities
from src.editorial.scoring import (
    EditorialScore,
    score_cyclone_basin_record,
    score_cyclone_land_threat,
    score_cyclone_landfall,
    score_cyclone_rapid_intensification,
    score_cyclone_tier_crossing,
)
from src.orchestrator.common import _fact, _fetch_strict, _review_context
from src.orchestrator.suppression import _should_draft
from src.orchestrator.telemetry import _record_source_run
from src.state_schema import BotState


def _cyclone_history_advisories(
    bot_state: BotState,
    current_advisories: list[CycloneAdvisory],
) -> list[CycloneAdvisory]:
    """Rehydrate retained wind observations as advisories for RI detection."""

    latest = latest_advisories_by_storm(current_advisories)
    history_rows = bot_state.get("cyclone_wind_history", {})
    historical: list[CycloneAdvisory] = []
    for storm_id, rows in history_rows.items():
        current = latest.get(storm_id)
        if current is None:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                wind_kt = int(row.get("wind_kt", 0))
            except (TypeError, ValueError):
                continue
            issued_at = str(row.get("issued_at") or "")
            if not issued_at:
                continue
            historical.append(CycloneAdvisory(
                source=current.source,
                storm_id=current.storm_id,
                storm_name=current.storm_name,
                basin=current.basin,
                advisory_number=f"history_{issued_at}",
                issued_at=issued_at,
                wind_kt=wind_kt,
                pressure_mb=None,
                lat=current.lat,
                lon=current.lon,
                classification=current.classification,
                public_advisory_url=current.public_advisory_url,
                advisory_text="",
            ))
    return historical + current_advisories


def _score_cyclone_event(
    event: RapidIntensificationEvent | TierCrossingEvent | LandfallEvent | BasinRecordEvent,
) -> EditorialScore:
    if isinstance(event, RapidIntensificationEvent):
        return score_cyclone_rapid_intensification(
            event.delta_kt_24h,
            event.current_category,
            event.basin,
        )
    if isinstance(event, TierCrossingEvent):
        return score_cyclone_tier_crossing(
            event.from_category,
            event.to_category,
            event.basin,
        )
    if isinstance(event, LandfallEvent):
        return score_cyclone_landfall(event.category, event.location, event.basin)
    return score_cyclone_basin_record(
        event.category,
        event.basin,
        event.record_label,
    )


def _bundle_for_cyclone_event(
    event: RapidIntensificationEvent | TierCrossingEvent | LandfallEvent | BasinRecordEvent,
):
    from src.two_bot.intern import (
        build_cyclone_basin_record_bundle,
        build_cyclone_landfall_bundle,
        build_cyclone_rapid_intensification_bundle,
        build_cyclone_tier_crossing_bundle,
    )

    if isinstance(event, RapidIntensificationEvent):
        return build_cyclone_rapid_intensification_bundle(event)
    if isinstance(event, TierCrossingEvent):
        return build_cyclone_tier_crossing_bundle(event)
    if isinstance(event, LandfallEvent):
        return build_cyclone_landfall_bundle(event)
    return build_cyclone_basin_record_bundle(event)


def _cyclone_review_context(
    event: RapidIntensificationEvent | TierCrossingEvent | LandfallEvent | BasinRecordEvent | LandThreatEvent,
    *,
    source_label: str,
    source_key: str,
    current_run: dict | None,
) -> dict:
    if isinstance(event, RapidIntensificationEvent):
        headline = f"{event.storm_name}: +{event.delta_kt_24h} kt in 24h"
        facts = [
            _fact("Storm", event.storm_name),
            _fact("Basin", event.basin),
            _fact("Current wind", f"{event.current_wind_kt} kt"),
            _fact("Previous wind", f"{event.previous_wind_kt} kt"),
            _fact("Public advisory", event.public_advisory_url or "—"),
        ]
    elif isinstance(event, TierCrossingEvent):
        headline = f"{event.storm_name}: Category {event.from_category} to {event.to_category}"
        facts = [
            _fact("Storm", event.storm_name),
            _fact("Basin", event.basin),
            _fact("Wind", f"{event.wind_kt} kt"),
            _fact("Category crossed", f"{event.from_category} -> {event.to_category}"),
            _fact("Public advisory", event.public_advisory_url or "—"),
        ]
    elif isinstance(event, LandfallEvent):
        headline = f"{event.storm_name}: Category {event.category} landfall"
        facts = [
            _fact("Storm", event.storm_name),
            _fact("Basin", event.basin),
            _fact("Landfall location", event.location),
            _fact("Wind", f"{event.wind_kt} kt"),
            _fact("Public advisory", event.public_advisory_url or "—"),
        ]
    elif isinstance(event, LandThreatEvent):
        headline = (
            f"{event.storm_name}: forecast within {event.min_distance_nm:g} NM "
            f"of {event.landmass_country}"
        )
        facts = [
            _fact("Storm", event.storm_name),
            _fact("Basin", event.basin),
            _fact("Current wind", f"{event.current_wind_kt} kt"),
            _fact("Landmass", f"{event.landmass_country} (near {event.nearest_city})"),
            _fact("Closest approach", f"{event.min_distance_nm:g} NM"),
            _fact("Lead time", f"{event.closest_tau_h}h" if event.closest_tau_h is not None else event.closest_valid_at),
        ]
    else:
        headline = f"{event.storm_name}: {event.record_label}"
        facts = [
            _fact("Storm", event.storm_name),
            _fact("Basin", event.basin),
            _fact("Record", event.record_label),
            _fact("Wind", f"{event.wind_kt} kt"),
            _fact("Public advisory", event.public_advisory_url or "—"),
        ]
    return _review_context(
        source=source_label,
        source_key=source_key,
        headline=headline,
        current_run=current_run,
        facts=facts,
    )


def _process_cyclone_source(
    bot_state: BotState,
    current_run: dict | None,
    *,
    source_key: str,
    source_label: str,
    fetch_fn,
    detect_module,
) -> None:
    """Fetch, detect, and draft NHC/JTWC cyclone events."""

    from src.orchestrator.common import _enqueue_story_candidate

    print(f"[alerts] Checking {source_label} tropical cyclones...")
    source_start = time.perf_counter()
    source_promoted = 0
    try:
        advisories = _fetch_strict(fetch_fn)
        advisory_history = _cyclone_history_advisories(bot_state, advisories)
        events: list[RapidIntensificationEvent | TierCrossingEvent | LandfallEvent | BasinRecordEvent] = [
            *detect_module.detect_rapid_intensification(advisory_history),
            *detect_module.detect_tier_crossings(
                advisories,
                cast(dict, bot_state.get("cyclone_tiers", {})),
            ),
            *detect_module.detect_landfalls(advisories),
        ]
        for event in events:
            if state.is_duplicate(bot_state, event.event_id):
                continue
            score = _score_cyclone_event(event)
            if not _should_draft(score, event.event_id):
                continue
            source_promoted += 1
            review_context = _cyclone_review_context(
                event,
                source_label=source_label,
                source_key=source_key,
                current_run=current_run,
            )
            bundle = _bundle_for_cyclone_event(event)
            _event = event

            def _on_success(
                _bs: BotState = bot_state,
                _event = _event,
            ) -> None:
                if isinstance(_event, TierCrossingEvent):
                    state.update_cyclone_tier(
                        _bs,
                        f"{_event.source}:{_event.storm_id}".lower(),
                        _event.to_category,
                    )
                state.increment_cyclone_annual_count(_bs)

            _enqueue_story_candidate(
                bot_state,
                bundle=bundle,
                score=score,
                source=source_key,
                legacy_type=event.kind,
                event_id=event.event_id,
                review_context=review_context,
                cooldown_exempt=True,
                on_draft_success=_on_success,
            )

        # Land-threat detection (#375): a warned storm whose OFFICIAL forecast
        # track approaches a named landmass. Separate from the events loop —
        # its dedup is the (storm, landmass) pair state, recorded ONLY on
        # draft success so a killed draft retries on the next advisory.
        land_threats = detect_land_threats(
            advisories,
            cast(dict, bot_state.get("cyclone_land_threat_pairs", {})),
            load_cities(),
            now=datetime.now(UTC),
        )
        for lt in land_threats:
            if state.is_duplicate(bot_state, lt.event_id):
                continue
            lt_score = score_cyclone_land_threat(
                current_wind_kt=lt.current_wind_kt,
                min_distance_nm=lt.min_distance_nm,
                closest_tau_h=lt.closest_tau_h,
                landmass_country=lt.landmass_country,
            )
            if not _should_draft(lt_score, lt.event_id):
                continue
            source_promoted += 1
            from src.two_bot.intern import build_cyclone_land_threat_bundle

            lt_bundle = build_cyclone_land_threat_bundle(lt)
            _lt_review_context = _cyclone_review_context(
                lt,
                source_label=source_label,
                source_key=source_key,
                current_run=current_run,
            )
            # Neither tracking_key nor slug rides LandThreatEvent — derive
            # both, bound as closure defaults (the nifc.py pattern).
            _tk = tracking_key(lt.source, lt.storm_id)
            _slug = _landmass_slug(lt.landmass_country)

            def _on_lt_success(
                _bs: BotState = bot_state, _k: str = _tk, _s: str = _slug
            ) -> None:
                state.record_land_threat_pair(_bs, _k, _s)
                state.increment_cyclone_annual_count(_bs)

            _enqueue_story_candidate(
                bot_state,
                bundle=lt_bundle,
                score=lt_score,
                source=source_key,
                legacy_type="cyclone_land_threat",
                event_id=lt.event_id,
                review_context=_lt_review_context,
                on_draft_success=_on_lt_success,
            )

        for advisory in advisories:
            state.record_cyclone_wind_observation(
                bot_state,
                advisory.tracking_key,
                advisory.issued_at,
                advisory.wind_kt,
            )
            if advisory.category >= 1:
                state.update_cyclone_tier(bot_state, advisory.tracking_key, advisory.category)

        degraded_note = degraded_via(advisories)
        _record_source_run(
            current_run, bot_state, source_key, source_start,
            status="degraded" if degraded_note else "success",
            observed=len(advisories),
            promoted=source_promoted,
            drafted=0,
            note=degraded_note,
            details={
                "events": [
                    {
                        "event_id": event.event_id,
                        "kind": event.kind,
                        "storm_id": event.storm_id,
                        "storm_name": event.storm_name,
                        "basin": event.basin,
                    }
                    for event in events[:50]
                ]
            } if events else None,
        )
    except Exception as e:
        print(f"[alerts] {source_label} cyclone error: {e}")
        state.log_error(bot_state, source_key, str(e))
        _record_source_run(
            current_run, bot_state, source_key, source_start,
            status="failed", error=str(e),
        )


__all__ = [
    "_bundle_for_cyclone_event",
    "_cyclone_history_advisories",
    "_cyclone_review_context",
    "_process_cyclone_source",
    "_score_cyclone_event",
]
