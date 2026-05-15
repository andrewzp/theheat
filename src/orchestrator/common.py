"""Shared orchestration helpers for @theheat run modes."""



from __future__ import annotations



# ruff: noqa: F401

import argparse
import contextlib
import os
import secrets
import sys
import time
from typing import Any, cast
from datetime import UTC, date, datetime, timedelta

from src import state
from src.data import open_meteo, ghcn, firms, fire_footprint, co2, coral_dhw, copernicus_ems, methane, nws_alerts, gdacs, nhc, jtwc, sea_ice, drought, enso, ocean, ocean_sst, water_levels, river_gauges, ice_mass, climate_indices, ozone_hole, gpm_imerg, nsidc_snow
from src.data.cyclones import (
    BasinRecordEvent,
    CycloneAdvisory,
    LandfallEvent,
    RapidIntensificationEvent,
    TierCrossingEvent,
    latest_advisories_by_storm,
)
from src.data.open_meteo import AllTimeRecord, AnomalyEvent, MonthlyRecord, RecordEvent
from src.state_schema import BotState
from src.data.source_status import SourceSkipped
from src.editorial import synthesis
from src.editorial.approval import recommend_approval_policy
from src.editorial.candidates import CandidateBundle
from src.editorial._regions import cities_to_state_map, lat_lon_to_state
from src.editorial.simultaneous_format import select_roll_call_subset
from src.editorial.scoring import (
    EditorialScore,
    score_all_time_record,
    score_anomaly,
    score_ch4_milestone,
    score_co2_milestone,
    score_coral_bleaching,
    score_cyclone_basin_record,
    score_cyclone_landfall,
    score_cyclone_rapid_intensification,
    score_cyclone_tier_crossing,
    score_drought,
    score_enso_transition,
    score_oscillation_transition,
    score_oscillation_extreme,
    score_ozone_hole_peak,
    score_extreme_wave,
    score_marine_heatwave,
    score_precipitation_extreme,
    score_fire_event,
    score_fire_footprint,
    score_global_disaster,
    score_global_flood,
    score_hot10,
    score_monthly_record,
    score_country_record,
    score_record_event,
    score_record_low_event,
    score_record_streak,
    score_river_flood,
    score_sea_ice_record,
    score_seasonal_snow_record,
    score_ice_mass_event,
    score_severe_weather,
    score_simultaneous_records,
    score_snow_extreme,
    score_storm_surge,
    score_synthesis_fire_drought_heat,
)
from src.voice import generator  # noqa: F401 — referenced via @patch("src.main.generator") in tests
from src.voice.safety import run_safety_pipeline
from src.posting.bluesky import post_to_bluesky
from src.posting.twitter import post_tweet



MAX_DRAFTS = 200

_CURRENT_SUPPRESSION_CTX: dict | None = None

CITY_COOLDOWN_DAYS = 3

ELITE_COPY_SCORE = 95

CO2_ANNUAL_CAP = 12

CH4_ANNUAL_CAP = 12

CORAL_DHW_ANNUAL_CAP = 16

ICE_ANNUAL_CAP = 8

SNOW_ANNUAL_CAP = 8



def _utc_now() -> datetime:
    return datetime.now(UTC)

def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")

def _utc_after_minutes_iso(minutes: int) -> str:
    return (_utc_now() + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

def _parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO timestamp with optional Z suffix."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

def _find_draft(bot_state: BotState, draft_id: str = "", tweet_text: str = "") -> dict | None:
    """Find a draft by explicit id first, then by approved tweet text fallback."""
    drafts = bot_state.get("drafts", [])
    if draft_id:
        for draft in drafts:
            if draft.get("id") == draft_id:
                return draft

    for draft in drafts:
        if draft.get("text") == tweet_text and draft.get("status") == "approved":
            return draft
    return None

def _record_source_run(
    current_run: dict | None,
    bot_state: BotState | None,
    source: str,
    started_at: float,
    *,
    status: str,
    observed: int = 0,
    promoted: int = 0,
    drafted: int = 0,
    error: str | None = None,
    note: str | None = None,
    details: dict | None = None,
) -> None:
    """Track a source result when run telemetry is enabled."""
    if bot_state is not None:
        health_error = error
        if not health_error and status in {"failed", "degraded", "partial_failure"}:
            health_error = note
        state.record_source_health(bot_state, source, status, health_error)

    if current_run is None:
        return

    duration_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
    state.add_source_run(
        current_run,
        source=source,
        status=status,
        duration_ms=duration_ms,
        observed=observed,
        promoted=promoted,
        drafted=drafted,
        error=error,
        note=note,
        details=details,
    )

def _previous_drafts_for_event(bot_state: BotState, event_base: str) -> list[str]:
    """Find text of previous drafts for the same base event.

    For evolving events (e.g. cyclones), the event_id changes with each
    intensity tier but shares a common base like "gdacs_TC_1001270".
    Returns up to 5 most recent draft texts to avoid repeating comparisons.
    """
    drafts = bot_state.get("drafts", [])
    matches = []
    for d in drafts:
        eid = d.get("event_id", "")
        if event_base and event_base in eid:
            text = d.get("text", "")
            if text:
                matches.append(text)
    return matches[-5:]

def _near_miss_gap() -> int:
    """Max (threshold - total) gap to record. Smaller = stricter."""
    try:
        return int(os.environ.get("SUPPRESSION_NEAR_MISS_GAP", "15"))
    except (TypeError, ValueError):
        return 15

def _suppression_context(bot_state: BotState, *, source: str, run_id: str | None = None):
    """Activate suppression capture for `_should_draft()` calls inside the block."""
    global _CURRENT_SUPPRESSION_CTX
    prev = _CURRENT_SUPPRESSION_CTX
    _CURRENT_SUPPRESSION_CTX = {"bot_state": bot_state, "source": source, "run_id": run_id}
    try:
        yield
    finally:
        _CURRENT_SUPPRESSION_CTX = prev

def _activate_suppression_ctx(bot_state: BotState, *, source: str, run_id: str | None = None) -> None:
    """Set the suppression context for the rest of the process.

    Used at the top of each top-level run function (run_alerts, run_leaderboard,
    etc.) so all `_should_draft()` calls during the run capture suppressions.
    No auto-cleanup — relies on the bot exiting after each invocation. Tests
    should call `_clear_suppression_ctx()` between cases.
    """
    global _CURRENT_SUPPRESSION_CTX
    _CURRENT_SUPPRESSION_CTX = {"bot_state": bot_state, "source": source, "run_id": run_id}

def _clear_suppression_ctx() -> None:
    """Clear the current suppression context. Mainly for tests."""
    global _CURRENT_SUPPRESSION_CTX
    _CURRENT_SUPPRESSION_CTX = None

def _score_field(score, key: str, default=None):
    if isinstance(score, dict):
        return score.get(key, default)
    return getattr(score, key, default)

def _score_int(score, key: str) -> int:
    try:
        return int(_score_field(score, key, 0) or 0)
    except (TypeError, ValueError):
        return 0

def _score_reasons(score) -> list[str]:
    raw = _score_field(score, "reasons", []) or []
    if not isinstance(raw, list):
        return [str(raw)]
    return [str(item) for item in raw]

def _record_suppression(
    *,
    bot_state: BotState,
    source: str | None,
    run_id: str | None,
    event_id: str,
    score: EditorialScore,
    summary: str | None,
) -> None:
    """Append an editorial-gate near-miss suppression record (stage=score_gate),
    capped to last 200.
    """
    suppressions = bot_state.setdefault("suppressions", [])
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    suppressions.append({
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": run_id,
        "source": source,
        "stage": "score_gate",
        "event_id": event_id or None,
        "category": _score_field(score, "category"),
        "score_total": _score_int(score, "total"),
        "threshold": _score_int(score, "threshold"),
        "reasons": _score_reasons(score),
        "summary": summary,
    })
    if len(suppressions) > 200:
        bot_state["suppressions"] = suppressions[-200:]

def _record_downstream_suppression(
    *,
    bot_state: BotState,
    source: str | None,
    run_id: str | None,
    event_id: str,
    score,
    kill_stage: str,
    kill_reason: str,
    summary: str | None,
) -> None:
    """Append a downstream-kill suppression — a bundle that passed the
    editorial score gate but died in the two-bot pipeline (writer kill,
    fact-check rejection, or pipeline exception). Stage discriminates
    from score-gate near-misses; ``score_total`` is preserved so the
    dashboard can show "passing score 80, killed in writer".
    """
    suppressions = bot_state.setdefault("suppressions", [])
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    suppressions.append({
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": run_id,
        "source": source,
        "stage": kill_stage,  # "writer" | "safety" | "fact_check" | "critic" | "pipeline_error" | "unknown"
        "event_id": event_id or None,
        "category": _score_field(score, "category"),
        "score_total": _score_int(score, "total"),
        "threshold": _score_int(score, "threshold"),
        "reasons": [kill_reason] if kill_reason else [],
        "summary": summary,
    })
    if len(suppressions) > 200:
        bot_state["suppressions"] = suppressions[-200:]

def _record_save_rejection(
    *,
    bot_state: BotState,
    event_id: str,
    score,
    kill_stage: str,
    kill_reason: str,
    summary: str | None,
) -> None:
    """Record a post-score draft-save gate as a suppression row."""
    if score is None:
        return
    ctx = _CURRENT_SUPPRESSION_CTX
    if ctx is None:
        return
    _record_downstream_suppression(
        bot_state=bot_state,
        source=ctx.get("source"),
        run_id=ctx.get("run_id"),
        event_id=event_id,
        score=score,
        kill_stage=kill_stage,
        kill_reason=kill_reason,
        summary=summary,
    )

def _should_draft(
    score: EditorialScore,
    event_id: str = "",
    *,
    summary: str | None = None,
) -> bool:
    """Decide whether an event is strong enough to enter the draft queue."""
    if score.passes:
        return True
    event_desc = f" {event_id}" if event_id else ""
    print(
        f"[score] Suppressed{event_desc}: {score.category} "
        f"{score.total} < {score.threshold} ({', '.join(score.reasons)})"
    )
    ctx = _CURRENT_SUPPRESSION_CTX
    if ctx is not None:
        gap = int(getattr(score, "threshold", 0) or 0) - int(getattr(score, "total", 0) or 0)
        if gap <= _near_miss_gap():
            _record_suppression(
                bot_state=ctx["bot_state"],
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=event_id,
                score=score,
                summary=summary,
            )
    return False

def _unwrap_generated_result(
    generated: str | CandidateBundle | object | None,
) -> tuple[str, list[dict] | None, dict | None, dict | None]:
    if generated is None:
        return "", None, None, None

    if isinstance(generated, str):
        return generated, None, None, None

    if isinstance(generated, CandidateBundle):
        candidates = [candidate.as_dict() for candidate in generated.candidates]
        selected_score = generated.selected_score.as_dict() if generated.selected_score else None
        evaluator_metadata = _evaluator_metadata_from_bundle(generated)
        return generated.text, candidates, selected_score, evaluator_metadata

    text = getattr(generated, "text", "") if isinstance(getattr(generated, "text", ""), str) else ""
    raw_candidates: Any = getattr(generated, "candidates", None)
    raw_selected_score: Any = getattr(generated, "selected_score", None)
    evaluator_metadata = _evaluator_metadata_from_bundle(generated)

    candidate_payload: list[dict] | None = None
    if raw_candidates:
        candidate_payload = []
        for candidate in raw_candidates:
            if hasattr(candidate, "as_dict"):
                candidate_payload.append(candidate.as_dict())
            elif isinstance(candidate, dict):
                candidate_payload.append(candidate)

    selected_payload = (
        raw_selected_score.as_dict() if hasattr(raw_selected_score, "as_dict") else raw_selected_score
    )
    return text, candidate_payload, selected_payload, evaluator_metadata

def _evaluator_metadata_from_bundle(generated: object) -> dict | None:
    verdict = getattr(generated, "evaluator_verdict", None)
    if not isinstance(verdict, dict):
        return None

    scores = verdict.get("scores") if isinstance(verdict.get("scores"), dict) else {}
    failures_raw = verdict.get("failures")
    failures = [str(item) for item in failures_raw] if isinstance(failures_raw, list) else []
    skipped = verdict.get("reasoning") == "evaluator skipped"
    # Null means the evaluator did not actually run; True/False means it returned a verdict.
    evaluator_pass = None if skipped else bool(verdict.get("passed"))

    return {
        "evaluator_pass": evaluator_pass,
        "evaluator_total": int(verdict.get("total") or 0),
        "evaluator_scores": scores,
        "evaluator_failures": failures,
        "evaluator_used_rewrite": bool(getattr(generated, "evaluator_used_rewrite", False)),
    }

def _fact(label: str, value: str | int | float | None) -> dict | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return {"label": label, "value": text}

def _fetch_strict(fetch_fn, *args, **kwargs):
    """Call a source fetch helper in strict mode, with old test-double fallback."""
    try:
        return fetch_fn(*args, strict=True, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument 'strict'" not in str(exc):
            raise
        return fetch_fn(*args, **kwargs)

def _check_city_extreme_signals(cities: list[dict], metrics_out: dict):
    """Call Open-Meteo city signal scan with metrics, tolerating old test doubles."""
    try:
        return open_meteo.check_extreme_signals_for_cities(
            cities,
            metrics_out=metrics_out,
        )
    except TypeError as exc:
        if "unexpected keyword argument 'metrics_out'" not in str(exc):
            raise
        return open_meteo.check_extreme_signals_for_cities(cities)

def _classify_ghcn_source_status(
    pipeline_metrics: dict,
    *,
    today: date | None = None,
) -> str:
    """Classify GHCN source health while tolerating normal newest-diff lag."""
    diff_missing = int(pipeline_metrics.get("diff_dates_missing", 0) or 0)
    if diff_missing <= 0:
        return "success"

    diff_fetched = int(pipeline_metrics.get("diff_dates_fetched", 0) or 0)
    if diff_fetched <= 0:
        return "degraded"

    missing_dates = pipeline_metrics.get("diff_missing_dates")
    if not isinstance(missing_dates, list) or len(missing_dates) != diff_missing:
        return "degraded"

    current_date = today or date.today()
    tolerated_missing_dates = {current_date - timedelta(days=1)}
    try:
        parsed_missing = {date.fromisoformat(str(raw)) for raw in missing_dates}
    except ValueError:
        return "degraded"

    if parsed_missing.issubset(tolerated_missing_dates):
        return "success"
    return "degraded"

def _temp_pair_c(temp_c: float) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    return f"{temp_c:.1f}C / {temp_f:.1f}F"

def _review_context(
    *,
    source: str,
    source_key: str,
    headline: str,
    facts: list[dict | None],
    current_run: dict | None = None,
) -> dict:
    return {
        "source": source,
        "source_key": source_key,
        "headline": headline,
        "facts": [fact for fact in facts if fact],
        "run_id": current_run.get("id") if current_run else None,
        "run_mode": current_run.get("mode") if current_run else None,
        "run_started_at": current_run.get("started_at") if current_run else None,
    }

def _touch_draft(draft: dict) -> None:
    draft["updated_at"] = _utc_now_iso()

def _co2_annual_cap_reached(bot_state: BotState, cap: int = CO2_ANNUAL_CAP) -> bool:
    """True if we've already drafted CO2_ANNUAL_CAP CO2 tweets this calendar year."""
    year_key = str(date.today().year)
    count = bot_state.get("co2_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[co2] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False

def _increment_co2_annual_count(bot_state: BotState) -> None:
    year_key = str(date.today().year)
    counts = bot_state.setdefault("co2_annual_count", {})
    counts[year_key] = counts.get(year_key, 0) + 1

def _ch4_annual_cap_reached(bot_state: BotState, cap: int = CH4_ANNUAL_CAP) -> bool:
    year_key = str(date.today().year)
    count = bot_state.get("ch4_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[ch4] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False

def _coral_dhw_annual_cap_reached(
    bot_state: BotState,
    cap: int = CORAL_DHW_ANNUAL_CAP,
) -> bool:
    year_key = str(date.today().year)
    count = bot_state.get("coral_dhw_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[coral_dhw] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False

def _ice_annual_cap_reached(bot_state: BotState, cap: int = ICE_ANNUAL_CAP) -> bool:
    """True if we've already drafted ICE_ANNUAL_CAP ice-mass tweets this year."""
    year_key = str(date.today().year)
    count = bot_state.get("ice_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[ice_mass] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False

def _increment_ice_annual_count(bot_state: BotState) -> None:
    year_key = str(date.today().year)
    counts = bot_state.setdefault("ice_annual_count", {})
    counts[year_key] = counts.get(year_key, 0) + 1


def _snow_annual_cap_reached(bot_state: BotState, cap: int = SNOW_ANNUAL_CAP) -> bool:
    year_key = str(date.today().year)
    count = bot_state.get("snow_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[snow] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False


def _increment_snow_annual_count(bot_state: BotState) -> None:
    year_key = str(date.today().year)
    counts = bot_state.setdefault("snow_annual_count", {})
    counts[year_key] = counts.get(year_key, 0) + 1

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
    event: RapidIntensificationEvent | TierCrossingEvent | LandfallEvent | BasinRecordEvent,
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
) -> int:
    """Fetch, detect, and draft NHC/JTWC cyclone events."""

    print(f"[alerts] Checking {source_label} tropical cyclones...")
    source_start = time.perf_counter()
    source_promoted = 0
    source_drafted = 0
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
            if _try_two_bot_draft(
                bundle,
                bot_state,
                score,
                legacy_type=event.kind,
                event_id=event.event_id,
                review_context=review_context,
                cooldown_exempt=True,
            ):
                state.record_event(bot_state, event.event_id)
                if isinstance(event, TierCrossingEvent):
                    state.update_cyclone_tier(bot_state, f"{event.source}:{event.storm_id}".lower(), event.to_category)
                state.increment_cyclone_annual_count(bot_state)
                source_drafted += 1

        for advisory in advisories:
            state.record_cyclone_wind_observation(
                bot_state,
                advisory.tracking_key,
                advisory.issued_at,
                advisory.wind_kt,
            )
            if advisory.category >= 1:
                state.update_cyclone_tier(bot_state, advisory.tracking_key, advisory.category)

        _record_source_run(
            current_run, bot_state, source_key, source_start,
            status="success",
            observed=len(advisories),
            promoted=source_promoted,
            drafted=source_drafted,
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
    return source_drafted

def _same_day_already_posted(drafts: list[dict], city: str, tweet_date: str) -> bool:
    """True if a posted draft exists for this (city, tweet_date) tuple."""
    if not city or not tweet_date:
        return False
    for d in drafts:
        if (
            d.get("city") == city
            and d.get("tweet_date") == tweet_date
            and d.get("status") == "posted"
        ):
            return True
    return False

def _same_day_pending_collision(
    drafts: list[dict], city: str, tweet_date: str
) -> tuple[int, dict] | None:
    """Return (index, draft) of a pending draft matching (city, tweet_date), if any."""
    if not city or not tweet_date:
        return None
    for i, d in enumerate(drafts):
        if (
            d.get("city") == city
            and d.get("tweet_date") == tweet_date
            and d.get("status") == "pending"
        ):
            return i, d
    return None

def _posted_city_within_days(drafts: list[dict], city: str, days: int) -> bool:
    """True if any posted draft for this city exists within the last N days."""
    if not city:
        return False
    cutoff = _utc_now() - timedelta(days=days)
    for d in drafts:
        if d.get("city") != city:
            continue
        if d.get("status") != "posted":
            continue
        ts = _parse_iso_utc(
            d.get("posted_at") or d.get("updated_at") or d.get("created_at")
        )
        if ts and ts >= cutoff:
            return True
    return False

def save_draft(
    tweet_text: str,
    bot_state: BotState,
    tweet_type: str,
    event_id: str = "",
    score: EditorialScore | None = None,
    candidates: list[dict] | None = None,
    candidate_score: dict | None = None,
    review_context: dict | None = None,
    evaluator_metadata: dict | None = None,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    """Save a generated tweet as a draft for review.

    When ``city`` and ``tweet_date`` are provided, two extra gates apply:

    * **Same (city, date) dedup.** Only the highest-scoring draft per city
      per day survives. A stronger signal arriving later supersedes a still-
      pending weaker draft; a weaker signal is dropped. If a draft for that
      (city, date) has already been posted, the new one is skipped.

    * **City cooldown.** If the city had a tweet posted within the last
      ``CITY_COOLDOWN_DAYS`` days, new drafts for that city are dropped
      unless ``cooldown_exempt=True`` (elite signals — all-time records,
      extreme anomalies, streaks, NOAA confirmations) OR the copy itself
      is exceptional (``candidate_score.total >= ELITE_COPY_SCORE``).

    These gates are scoped to city-based extreme-temperature signals; other
    event types (fires, disasters, CO2, sea ice, etc.) omit ``city`` and
    pass through unchanged.
    """
    drafts = bot_state.setdefault("drafts", [])

    # Don't duplicate drafts for the same event
    if event_id and any(d.get("event_id") == event_id for d in drafts):
        print(f"[draft] Already drafted: {event_id}")
        _record_save_rejection(
            bot_state=bot_state,
            event_id=event_id,
            score=score,
            kill_stage="duplicate_draft",
            kill_reason="Event already has a draft",
            summary=tweet_text[:120] or event_id,
        )
        return False

    # (city, date) dedup — highest signal wins
    if city and tweet_date:
        if _same_day_already_posted(drafts, city, tweet_date):
            print(f"[draft] Already posted for {city} on {tweet_date}, skipping")
            _record_save_rejection(
                bot_state=bot_state,
                event_id=event_id,
                score=score,
                kill_stage="same_day_posted",
                kill_reason=f"Already posted for {city} on {tweet_date}",
                summary=city,
            )
            return False

        collision = _same_day_pending_collision(drafts, city, tweet_date)
        if collision:
            idx, other = collision
            other_total = (other.get("score") or {}).get("total", 0)
            new_total = score.total if score else 0
            if new_total <= other_total:
                print(
                    f"[draft] Weaker signal for {city} on {tweet_date} "
                    f"({new_total} ≤ {other_total}), skipping"
                )
                _record_save_rejection(
                    bot_state=bot_state,
                    event_id=event_id,
                    score=score,
                    kill_stage="same_day_dedup",
                    kill_reason=(
                        f"Weaker same-day signal for {city} "
                        f"({new_total} <= {other_total})"
                    ),
                    summary=city,
                )
                return False
            _record_save_rejection(
                bot_state=bot_state,
                event_id=other.get("event_id", ""),
                score=other.get("score"),
                kill_stage="same_day_superseded",
                kill_reason=(
                    f"Superseded by stronger same-day signal "
                    f"({new_total} > {other_total})"
                ),
                summary=city,
            )
            drafts.pop(idx)
            print(
                f"[draft] Superseded pending {city} draft "
                f"({other_total} → {new_total})"
            )

    # City cooldown — skip if we posted about this city in the last N days.
    # Exceptional copy (candidate_score.total >= ELITE_COPY_SCORE) bypasses,
    # even if the underlying signal wasn't flagged elite by the caller.
    copy_is_elite = bool(
        candidate_score
        and isinstance(candidate_score, dict)
        and candidate_score.get("total", 0) >= ELITE_COPY_SCORE
    )
    if (
        city
        and not cooldown_exempt
        and not copy_is_elite
        and _posted_city_within_days(drafts, city, CITY_COOLDOWN_DAYS)
    ):
        print(f"[draft] {city} in {CITY_COOLDOWN_DAYS}-day cooldown, skipping")
        _record_save_rejection(
            bot_state=bot_state,
            event_id=event_id,
            score=score,
            kill_stage="city_cooldown",
            kill_reason=f"{city} in {CITY_COOLDOWN_DAYS}-day cooldown",
            summary=city,
        )
        return False

    # Prune oldest non-pending drafts to prevent unbounded growth
    if len(drafts) >= MAX_DRAFTS:
        before = len(drafts)
        bot_state["drafts"] = [
            d for d in drafts if d.get("status") == "pending"
        ][-MAX_DRAFTS:]
        drafts = bot_state["drafts"]
        print(f"[draft] Pruned {before - len(drafts)} old drafts")

    draft: dict[str, Any] = {
        "id": f"draft_{_utc_now().strftime('%Y%m%d_%H%M%S')}_{len(drafts)}",
        "text": tweet_text,
        "type": tweet_type,
        "event_id": event_id,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "status": "pending",
    }
    if city:
        draft["city"] = city
    if tweet_date:
        draft["tweet_date"] = tweet_date
    if score is not None:
        draft["score"] = score.as_dict()
    if candidates:
        draft["candidates"] = candidates
    if candidate_score:
        draft["candidate_score"] = candidate_score
    if review_context:
        draft["review_context"] = review_context
    if evaluator_metadata is not None:
        draft.update(evaluator_metadata)

    policy = recommend_approval_policy(
        tweet_type,
        signal_total=score.total if score is not None else 0,
        candidate_score=candidate_score,
    )
    draft["approval_policy"] = policy.as_dict()
    draft.setdefault("approval_mode", "manual")

    if policy.mode == "armed_auto" and policy.recommended_delay_minutes:
        draft["auto_approve_at"] = _utc_after_minutes_iso(policy.recommended_delay_minutes)
        draft["auto_approve_requested_at"] = _utc_now_iso()
        draft["approval_mode"] = "policy_auto"

    drafts.append(draft)
    print(f"[draft] Saved: {tweet_text[:60]}...")
    return True

def _save_generated_draft(
    generated: str | CandidateBundle | object | None,
    bot_state: BotState,
    tweet_type: str,
    event_id: str,
    score: EditorialScore,
    review_context: dict | None = None,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    tweet_text, candidates, candidate_score, evaluator_metadata = _unwrap_generated_result(generated)
    if not tweet_text:
        return False
    return save_draft(
        tweet_text,
        bot_state,
        tweet_type,
        event_id,
        score=score,
        candidates=candidates,
        candidate_score=candidate_score,
        review_context=review_context,
        evaluator_metadata=evaluator_metadata,
        city=city,
        tweet_date=tweet_date,
        cooldown_exempt=cooldown_exempt,
    )

def _two_bot_bundle_for_extreme_signal(
    strongest_type: str,
    strongest_signal,
    *,
    result_out: dict | None = None,
):
    """Return a StoryBundle for the extreme_signals dispatch loop.

    All extreme_signals types now have bundle builders (full port,
    2026-05-04). Voice generator is no longer reachable from this loop.
    Returns None only if a build raises — in which case the signal is
    silently dropped rather than falling through to voice gen.
    """
    try:
        from src.two_bot import intern

        if strongest_type in ("record", "record_low"):
            return intern.build_record_bundle(strongest_signal)
        if strongest_type in ("monthly_high", "monthly_low"):
            return intern.build_monthly_high_bundle(strongest_signal)
        if strongest_type in ("all_time_high", "all_time_low"):
            return intern.build_all_time_record_bundle(strongest_signal)
        if strongest_type in ("anomaly_hot", "anomaly_cold"):
            return intern.build_anomaly_bundle(strongest_signal)
    except Exception as exc:
        print(f"[two_bot.dispatch] Bundle build failed for {strongest_type}: {exc}")
        if result_out is not None:
            result_out["kill_stage"] = "bundle_build"
            result_out["kill_reason"] = f"{type(exc).__name__}: {exc}"
        return None
    if result_out is not None:
        result_out["kill_stage"] = "bundle_build"
        result_out["kill_reason"] = f"No bundle builder for {strongest_type!r}"
    return None

def _try_two_bot_draft(
    bundle,
    bot_state: BotState,
    score,
    *,
    legacy_type: str,
    event_id: str,
    review_context: dict,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    """Run the live two-bot pipeline (writer → claim extract → fact-check
    → memory) and save the draft. Returns True iff a draft was saved.

    Bypasses the voice generator entirely. The cheap-model directive
    (2026-05-03): no Gemini Flash writes the audience-facing text. If
    two-bot returns None, no draft ships for this signal — we do NOT
    fall through to the voice generator.

    ``legacy_type`` is the pre-port signal-type label (e.g. "record",
    "monthly_high", "country_high") used by the dashboard and editorial
    state. The bundle.signal_kind may differ slightly (e.g.
    "calendar_record" vs "record") to give the writer better semantic
    cues, but the saved draft uses the legacy label for compatibility.

    On a None return from the pipeline (writer kill, fact-check rejection,
    or pipeline exception), records a downstream suppression so the
    dashboard surfaces it. These are *post-score* kills, distinct from
    the editorial-gate near-misses captured by ``_should_draft``.
    """
    from src.two_bot.pipeline import generate_draft

    pipeline_result: dict = {}
    draft = generate_draft(bundle, bot_state, result_out=pipeline_result)
    if draft is None:
        ctx = _CURRENT_SUPPRESSION_CTX
        if ctx is not None:
            _record_downstream_suppression(
                bot_state=ctx["bot_state"],
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=event_id,
                score=score,
                kill_stage=pipeline_result.get("kill_stage", "unknown"),
                kill_reason=pipeline_result.get("kill_reason", "unknown"),
                summary=getattr(bundle, "where", None) or city or None,
            )
        return False
    review_context["two_bot"] = draft["two_bot_metadata"]
    return save_draft(
        draft["text"],
        bot_state,
        legacy_type,
        event_id,
        score=score,
        review_context=review_context,
        city=city,
        tweet_date=tweet_date,
        cooldown_exempt=cooldown_exempt,
    )

def _maybe_shadow_two_bot(bundle, bot_state: BotState, review_context: dict) -> None:
    """Run the shadow two-bot pipeline if enabled, attaching results in place.

    Gated by ``THEHEAT_SHADOW_AB_ENABLED=1``. The shadow's tweet text and
    metadata are stored on ``review_context["shadow_two_bot"]``; the live
    voice-generator tweet is unaffected. Never raises.
    """
    if os.environ.get("THEHEAT_SHADOW_AB_ENABLED") != "1":
        return
    if review_context is None:
        return
    try:
        from src.two_bot.pipeline import generate_shadow_draft

        shadow = generate_shadow_draft(bundle, bot_state)
        if shadow:
            review_context["shadow_two_bot"] = {
                "text": shadow["text"],
                **shadow["two_bot_metadata"],
            }
    except Exception as exc:
        print(f"[shadow_ab] Skipped due to error: {exc}")





def _current_suppression_ctx() -> dict | None:

    return _CURRENT_SUPPRESSION_CTX





__all__ = [
    "Any",
    "AllTimeRecord",
    "AnomalyEvent",
    "BasinRecordEvent",
    "BotState",
    "CH4_ANNUAL_CAP",
    "CO2_ANNUAL_CAP",
    "CORAL_DHW_ANNUAL_CAP",
    "CITY_COOLDOWN_DAYS",
    "CandidateBundle",
    "CycloneAdvisory",
    "ELITE_COPY_SCORE",
    "EditorialScore",
    "ICE_ANNUAL_CAP",
    "LandfallEvent",
    "MAX_DRAFTS",
    "MonthlyRecord",
    "RapidIntensificationEvent",
    "RecordEvent",
    "SNOW_ANNUAL_CAP",
    "SourceSkipped",
    "TierCrossingEvent",
    "_CURRENT_SUPPRESSION_CTX",
    "_activate_suppression_ctx",
    "_bundle_for_cyclone_event",
    "_ch4_annual_cap_reached",
    "_check_city_extreme_signals",
    "_classify_ghcn_source_status",
    "_clear_suppression_ctx",
    "_co2_annual_cap_reached",
    "_coral_dhw_annual_cap_reached",
    "_current_suppression_ctx",
    "_cyclone_history_advisories",
    "_cyclone_review_context",
    "_evaluator_metadata_from_bundle",
    "_fact",
    "_fetch_strict",
    "_find_draft",
    "_ice_annual_cap_reached",
    "_increment_co2_annual_count",
    "_increment_ice_annual_count",
    "_increment_snow_annual_count",
    "_maybe_shadow_two_bot",
    "_near_miss_gap",
    "_parse_iso_utc",
    "_posted_city_within_days",
    "_previous_drafts_for_event",
    "_process_cyclone_source",
    "_record_downstream_suppression",
    "_record_save_rejection",
    "_record_source_run",
    "_record_suppression",
    "_review_context",
    "_same_day_already_posted",
    "_same_day_pending_collision",
    "_save_generated_draft",
    "_score_cyclone_event",
    "_score_field",
    "_score_int",
    "_score_reasons",
    "_should_draft",
    "_snow_annual_cap_reached",
    "_suppression_context",
    "_temp_pair_c",
    "_touch_draft",
    "_try_two_bot_draft",
    "_two_bot_bundle_for_extreme_signal",
    "_unwrap_generated_result",
    "_utc_after_minutes_iso",
    "_utc_now",
    "_utc_now_iso",
    "argparse",
    "cast",
    "cities_to_state_map",
    "co2",
    "climate_indices",
    "contextlib",
    "copernicus_ems",
    "coral_dhw",
    "date",
    "datetime",
    "drought",
    "enso",
    "firms",
    "fire_footprint",
    "gdacs",
    "generator",
    "ghcn",
    "gpm_imerg",
    "ice_mass",
    "jtwc",
    "latest_advisories_by_storm",
    "lat_lon_to_state",
    "methane",
    "nhc",
    "nsidc_snow",
    "nws_alerts",
    "ocean",
    "ocean_sst",
    "open_meteo",
    "ozone_hole",
    "os",
    "post_to_bluesky",
    "post_tweet",
    "recommend_approval_policy",
    "river_gauges",
    "run_safety_pipeline",
    "save_draft",
    "score_all_time_record",
    "score_anomaly",
    "score_ch4_milestone",
    "score_co2_milestone",
    "score_coral_bleaching",
    "score_country_record",
    "score_cyclone_basin_record",
    "score_cyclone_landfall",
    "score_cyclone_rapid_intensification",
    "score_cyclone_tier_crossing",
    "score_drought",
    "score_enso_transition",
    "score_oscillation_transition",
    "score_oscillation_extreme",
    "score_ozone_hole_peak",
    "score_extreme_wave",
    "score_fire_event",
    "score_fire_footprint",
    "score_global_disaster",
    "score_global_flood",
    "score_hot10",
    "score_ice_mass_event",
    "score_marine_heatwave",
    "score_monthly_record",
    "score_precipitation_extreme",
    "score_record_event",
    "score_record_low_event",
    "score_record_streak",
    "score_river_flood",
    "score_sea_ice_record",
    "score_seasonal_snow_record",
    "score_severe_weather",
    "score_simultaneous_records",
    "score_snow_extreme",
    "score_storm_surge",
    "score_synthesis_fire_drought_heat",
    "sea_ice",
    "secrets",
    "select_roll_call_subset",
    "state",
    "synthesis",
    "sys",
    "time",
    "timedelta",
    "water_levels",
]
