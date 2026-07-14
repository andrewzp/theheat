"""Shared orchestration helpers for @theheat run modes."""



from __future__ import annotations



# ruff: noqa: F401,F405

import argparse
import contextlib
import os
import secrets
import sys
import time
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.two_bot.types import TriageCandidateBundle
from datetime import UTC, date, datetime, timedelta

from src import state
from src.data import open_meteo, ghcn, firms, fire_footprint, co2, coral_dhw, copernicus_ems, methane, nws_alerts, gdacs, usgs_quakes, nhc, jtwc, sea_ice, drought, enso, ocean, ocean_sst, ocean_sst_anomaly, water_levels, river_gauges, ice_mass, climate_indices, ozone_hole, gpm_imerg, nsidc_snow, air_quality
from src.data.cyclones import (
    BasinRecordEvent,
    CycloneAdvisory,
    LandfallEvent,
    RapidIntensificationEvent,
    TierCrossingEvent,
    latest_advisories_by_storm,
)
from src.data.open_meteo import (
    AbsoluteExtremeEvent,
    AllTimeRecord,
    AnomalyEvent,
    MonthlyRecord,
    RecordEvent,
    WetBulbEvent,
)
from src.state_schema import BotState
from src.data.error_class import classify_error_class
from src.data.source_status import SourceSkipped
from src.editorial import synthesis
from src.editorial.approval import recommend_approval_policy
from src.editorial.candidates import CandidateBundle
from src.editorial._regions import cities_to_state_map, lat_lon_to_state
from src.editorial.simultaneous_format import select_roll_call_subset
from src.editorial.scoring import (
    EditorialScore,
    score_absolute_extreme,
    score_all_time_record,
    score_anomaly,
    score_ch4_milestone,
    score_co2_milestone,
    score_coral_bleaching,
    score_cyclone_basin_record,
    score_cyclone_landfall,
    score_cyclone_rapid_intensification,
    score_cyclone_tier_crossing,
    score_dust_event,
    score_drought,
    score_enso_transition,
    score_oscillation_transition,
    score_oscillation_extreme,
    score_ozone_hole_peak,
    score_pm25_hazard,
    score_extreme_wave,
    score_marine_heatwave,
    score_regional_sst_anomaly,
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
    score_heat_records_cluster,
    score_regional_anomaly,
    score_severe_weather,
    score_simultaneous_records,
    score_snow_extreme,
    score_storm_surge,
    score_synthesis_fire_drought_heat,
    score_synthesis_marine_compound,
    score_usgs_earthquake,
    score_wet_bulb_extreme,
)
from src.voice.safety import run_safety_pipeline
from src.posting.bluesky import post_to_bluesky
from src.posting.twitter import post_tweet
import src.orchestrator.caps as _caps
from src.orchestrator.caps import *  # noqa: F403
import src.orchestrator.telemetry as _telemetry
from src.orchestrator.telemetry import *  # noqa: F403



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
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


from src.orchestrator.suppression import *  # noqa: E402,F403
import src.orchestrator.suppression as _suppression  # noqa: E402

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


from src.orchestrator.draft_save import *  # noqa: E402,F403
import src.orchestrator.draft_save as _draft_save  # noqa: E402

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


from src.orchestrator.cyclones import *  # noqa: E402,F403
import src.orchestrator.cyclones as _cyclones  # noqa: E402

from src.orchestrator.dedup import *  # noqa: E402,F403
import src.orchestrator.dedup as _dedup  # noqa: E402
from src.orchestrator.two_bot_dispatch import *  # noqa: E402,F403
import src.orchestrator.two_bot_dispatch as _two_bot_dispatch  # noqa: E402
from src.orchestrator.triage_queue import *  # noqa: E402,F403
import src.orchestrator.triage_queue as _triage_queue  # noqa: E402

__all__ = [
    "Any",
    "AbsoluteExtremeEvent",
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
    "SST_ANOM_ANNUAL_CAP",
    "SourceSkipped",
    "TierCrossingEvent",
    "WetBulbEvent",
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
    "_record_triage_error_suppression",
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
    "_sst_anom_annual_cap_reached",
    "_suppression_context",
    "_temp_pair_c",
    "_touch_draft",
    "_triage_enabled",
    "_enqueue_candidate",
    "_enqueue_story_candidate",
    "_bump_source_field_in_run",
    "_bump_run_drafted",
    "_drain_and_write_triage_queue",
    "_try_two_bot_draft",
    "_two_bot_bundle_for_extreme_signal",
    "_unwrap_generated_result",
    "_utc_after_minutes_iso",
    "_utc_now",
    "_utc_now_iso",
    "air_quality",
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
    "ocean_sst_anomaly",
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
    "score_absolute_extreme",
    "score_ch4_milestone",
    "score_co2_milestone",
    "score_coral_bleaching",
    "score_country_record",
    "score_cyclone_basin_record",
    "score_cyclone_landfall",
    "score_cyclone_rapid_intensification",
    "score_cyclone_tier_crossing",
    "score_dust_event",
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
    "score_regional_sst_anomaly",
    "score_monthly_record",
    "score_pm25_hazard",
    "score_precipitation_extreme",
    "score_record_event",
    "score_record_low_event",
    "score_record_streak",
    "score_river_flood",
    "score_sea_ice_record",
    "score_seasonal_snow_record",
    "score_heat_records_cluster",
    "score_regional_anomaly",
    "score_severe_weather",
    "score_simultaneous_records",
    "score_snow_extreme",
    "score_storm_surge",
    "score_synthesis_fire_drought_heat",
    "score_synthesis_marine_compound",
    "score_usgs_earthquake",
    "score_wet_bulb_extreme",
    "sea_ice",
    "secrets",
    "select_roll_call_subset",
    "state",
    "synthesis",
    "sys",
    "time",
    "timedelta",
    "usgs_quakes",
    "water_levels",
    "annual_cap_reached",
    "increment_annual_count",
]
