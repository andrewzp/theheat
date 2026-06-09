"""State management via pluggable durable backends."""

from copy import deepcopy
import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import requests

from src.state_schema import (
    BotState,
    CycloneWindObservation,
    DroughtSnapshot,
    MemoryState,
    OceanSSTStreak,
    RecordStreakEntry,
    SourceHealth,
    SourceHealthRun,
    SynthesisComponents,
)
from src.storage import sqlite_store
from src.two_bot.json_utils import json_default

GIST_ID = os.environ.get("GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
STATE_FILENAME = "state.json"
STATE_BACKEND = os.environ.get("THEHEAT_STATE_BACKEND", "").lower()
DB_PATH = os.environ.get("THEHEAT_DB_PATH", "")
MAX_DRAFTS = 200
REJECTED_DRAFT_RETENTION_DAYS = 30
REJECTED_DRAFT_GUARDRAIL_COUNT = 10
_DRAFT_CAP_PROTECTED_STATUSES = {"pending", "posted"}

DEFAULT_STATE: BotState = {
    "last_hot10": {"date": None, "cities": []},
    "streaks": {},
    "posted_events": [],
    "daily_tweet_count": {},
    # Running count of CO2 tweets per calendar year, keyed by "YYYY".
    # Enforced by _co2_annual_cap_reached() in main.py (cap: 12/year).
    "co2_annual_count": {},
    # Atmospheric methane milestone state (Lane 08). Count is keyed by
    # calendar year; last_milestone dedupes the NOAA monthly series.
    "ch4_annual_count": {},
    "ch4_last_milestone": None,
    # Monthly climate-mode indices (Lane 14). Counts are keyed by calendar
    # year; last_phase records the newest observed sign so state/debug views
    # can show the current regime even when no draft fires.
    "nao_annual_count": {},
    "ao_annual_count": {},
    "pdo_annual_count": {},
    "nao_last_phase": None,
    "ao_last_phase": None,
    "pdo_last_phase": None,
    # Antarctic ozone hole annual peak state. Keyed by year string.
    "ozone_hole_last_peak": {},
    "ozone_hole_annual_count": {},
    # Air quality tier dedup. Updated only after a draft succeeds.
    "air_quality_pm25_tiers": {},
    "air_quality_dust_tiers": {},
    "drafts": [],
    "run_history": [],
    "errors": [],
    # Suppressed signals: events the bot observed but the editorial gate killed
    # before they could become drafts. Populated by _record_suppression() in
    # main.py when score.total < score.threshold and the gap is small enough
    # to be interesting (configurable near-miss filter).
    "suppressions": [],
    "memory": {
        "ongoing_events": [],
        "used_era_anchors": [],
        "used_peer_comparisons": [],
        "used_framings": [],
        "shipped_tweets": [],
    },
    # Tracks the hottest/coldest reading we've seen for each city across
    # the full history we have access to (Open-Meteo archive, ~1940 onward).
    # Used for "hottest since X year" detection.
    "city_all_time_max": {},  # {city: {"temp_c": float, "year": int}}
    "city_all_time_min": {},  # {city: {"temp_c": float, "year": int}}
    # Monthly extremes. Structure: {city: {"1": {...}, "2": {...}, ...}}
    "city_monthly_max": {},
    "city_monthly_min": {},
    # Record-breaking streaks: consecutive days a city has broken its daily record.
    "record_streaks": {},  # {city_or_station_id: {"days": int, "last_date": "YYYY-MM-DD", "start_date": "YYYY-MM-DD"}}
    # Consecutive fetch failures per data source (reset on success).
    # Used to fire a structural alert when a source goes silent for 3+ cycles.
    "data_source_failures": {},  # {source_key: consecutive_failure_count}
    # Rolling 7-day source-health counters keyed by run source.
    # Populated from alert run telemetry so every source row gets a durable
    # health observation, not just the last 20-run dashboard window.
    "source_health": {},
    # Global ocean SST archive-high streak. Two-field state:
    # seeded flips True after first observation (enables silent bootstrap);
    # last_milestone_fired tracks which milestone we last tweeted so
    # same-day re-runs don't double-fire.
    "ocean_sst_streak": {
        "seeded": False,
        "last_milestone_fired": None,
    },
    # GRACE-FO ice mass loss (Lane 2). See docs/conductor-lanes/02-ice-events.md.
    # Worst single-month mass-delta per region. `gt` is month-over-month
    # change in gigatons (negative = loss). More-negative = new record.
    "ice_mass_max_loss": {},  # {region: {"gt": float, "month": "YYYY-MM"}}
    # Last fired cumulative-loss milestone per region (negative threshold).
    # Next milestone fires at this value minus MILESTONE_STEP_GT.
    "ice_mass_last_milestone": {},  # {region: float}
    # Latest month we've successfully processed per region. Prevents re-eval
    # of the same month within a publication cycle.
    "ice_mass_last_seen": {},  # {region: "YYYY-MM"}
    # Running count of ice_mass tweets per calendar year (cap: 8/year).
    "ice_annual_count": {},  # {year_str: int}
    # GPM IMERG precipitation state. Daily records are keyed by
    # country:city:MM-DD. Recent rows are keyed by country:city.
    "precip_daily_records": {},
    "precip_recent_by_city": {},
    # NSIDC Snow Today state. Daily gain records are keyed by station:MM-DD.
    # Seasonal records and recent rows are keyed by station.
    "snow_daily_swe_gain_records": {},
    "snow_recent_by_station": {},
    "snow_annual_count": {},
    "seasonal_snow_records": {},
    # Per-complex tier dedup for fire footprint (GWIS). Integer index into
    # TIERS_HECTARES. Prevents re-tweeting the same fire at every update;
    # only tier upgrades trigger a new draft.
    "fire_complex_tiers": {},
    # Per-reef DHW threshold dedup. Values are the highest tweeted
    # threshold in °C-weeks (4, 8, or 12).
    "coral_dhw_last_tier": {},
    # Running count of coral-bleaching DHW tweets per calendar year
    # (cap: 16/year).
    "coral_dhw_annual_count": {},
    # Regional SST anomaly tier dedup. Keyed as "{YYYY}/{slug}" so lagged
    # CRW readings rotate annually by the reading date, not the cron date.
    "sst_anom_last_tier": {},
    # Running count of regional SST anomaly tweets per reading calendar year.
    "sst_anom_annual_count": {},
    # Reanalysis regional-anomaly onset guard. Keyed by region slug; value is the
    # window_start ISO date of the last attempted event, so a sustained spell does
    # not re-enter the writer pipeline every day. Written at attempt time (§D).
    "reganom_last_fired": {},  # {region_slug: "YYYY-MM-DD"}
    # Per-storm NHC/JTWC Saffir-Simpson tier dedup. Keys include source
    # (e.g. "nhc:al012026") so basin identifiers cannot collide.
    "cyclone_tiers": {},
    # Rolling per-storm wind observations retained for rapid-intensification
    # detection across scheduled runs.
    "cyclone_wind_history": {},
    # Visibility counter only; no cap yet.
    "cyclone_annual_count": {},
    # Per-Copernicus EMS activation severity dedup for global flood events.
    "flood_activation_tiers": {},
    # Visibility counter only; no cap yet.
    "flood_annual_count": {},
    # ISO date of last fire-footprint (NIFC) poll. Used as a once-per-day gate.
    "fire_footprint_last_run": None,
    # Cross-source synthesis layer (src/editorial/synthesis.py).
    "synthesis_components": {
        "fires": {},              # {state: [{event_id, frp, region, at}]}
        "heats": {},              # {state: [{event_id, kind, city, value_c, at}]}
        "drought_snapshot": None, # {updated_at, entries: [...]}
    },
    # {rule_name: {region: last_fired_at_iso}}
    "synthesis_cooldown": {},
}


class StateReadError(RuntimeError):
    """Raised when a configured durable backend cannot be read safely."""


def _fresh_state() -> BotState:
    """Return an isolated copy of the default state."""
    return deepcopy(DEFAULT_STATE)


def get_memory(state: BotState) -> MemoryState:
    """Return state memory, backfilled with the current first-build schema."""

    default_memory = deepcopy(DEFAULT_STATE["memory"])
    current = state.setdefault("memory", {})
    if not isinstance(current, dict):
        current = {}
        state["memory"] = current
    # Iteration uses runtime keys; widen to plain dict so TypedDict's
    # literal-key restriction on setdefault doesn't apply during backfill.
    current_writeable: dict = cast(dict, current)
    for key, value in default_memory.items():
        current_writeable.setdefault(key, value)
    return current


def set_memory(state: BotState, memory: MemoryState | dict) -> BotState:
    """Replace state memory after backfilling the first-build schema."""

    state["memory"] = cast(MemoryState, deepcopy(memory) if isinstance(memory, dict) else {})
    get_memory(state)
    return state


def _normalize_state(state: BotState | dict | None) -> BotState:
    """Ensure all expected top-level keys exist in the state payload."""
    normalized: BotState = _fresh_state()
    if isinstance(state, dict):
        normalized.update(cast(BotState, state))
    get_memory(normalized)
    return normalized


def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _configured_backend() -> str:
    if STATE_BACKEND in {"gist", "sqlite"}:
        return STATE_BACKEND
    return "sqlite" if DB_PATH else "gist"


def _parse_state_timestamp(value: str | None) -> datetime:
    fallback = datetime.fromtimestamp(0, UTC)
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _merge_ordered_unique(current: list, incoming: list, max_items: int | None = None) -> list:
    merged = []
    seen = set()
    for item in [*(current or []), *(incoming or [])]:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    if max_items is not None and len(merged) > max_items:
        return merged[-max_items:]
    return merged


def _draft_status_rank(draft: dict) -> int:
    return {
        "posted": 4,
        "approved": 3,
        "rejected": 2,
        "pending": 1,
    }.get(draft.get("status") or "", 0)


def _draft_recency_key(draft: dict) -> tuple[datetime, int]:
    return (
        _parse_state_timestamp(
            draft.get("updated_at")
            or draft.get("posted_at")
            or draft.get("approved_at")
            or draft.get("created_at")
        ),
        _draft_status_rank(draft),
    )


def _draft_retention_timestamp(draft: dict) -> datetime:
    parsed = _parse_state_timestamp(draft.get("created_at"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _enforce_draft_cap(drafts: list[dict], max_items: int) -> list[dict]:
    if len(drafts) <= max_items:
        return drafts

    protected = [
        draft for draft in drafts
        if draft.get("status") in _DRAFT_CAP_PROTECTED_STATUSES
    ]
    if len(protected) >= max_items:
        return protected

    slots = max_items - len(protected)
    cap_candidates = [
        draft for draft in drafts
        if draft.get("status") not in _DRAFT_CAP_PROTECTED_STATUSES
    ]
    capped_candidates = cap_candidates[-slots:] if slots > 0 else []
    keep_ids = {id(draft) for draft in [*protected, *capped_candidates]}
    return [draft for draft in drafts if id(draft) in keep_ids]


def _trim_drafts(state: BotState, max_items: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=REJECTED_DRAFT_RETENTION_DAYS)
    retained = []
    expired_rejected = []
    for draft in state.get("drafts", []):
        if draft.get("status") == "rejected" and _draft_retention_timestamp(draft) < cutoff:
            expired_rejected.append(draft)
            continue
        retained.append(draft)

    if not retained and expired_rejected:
        expired_rejected.sort(key=_draft_retention_timestamp)
        retained = expired_rejected[-REJECTED_DRAFT_GUARDRAIL_COUNT:]

    state["drafts"] = _enforce_draft_cap(retained, max_items)


def trim_drafts(state: BotState) -> None:
    """Trim durable drafts in place.

    Policy:
    - all pending drafts are kept indefinitely for human review
    - all posted drafts are kept indefinitely for audit trail
    - rejected drafts older than 30 days by created_at are dropped
    - if every draft would be dropped, keep the newest 10 rejected drafts
      as a guardrail for state/audit continuity
    - after time-trim, enforce the 200-cap against non-pending/non-posted
      drafts as a backstop
    """

    _trim_drafts(state, MAX_DRAFTS)


def _merge_drafts(current: list[dict], incoming: list[dict], max_items: int = MAX_DRAFTS) -> list[dict]:
    merged: dict[str, dict] = {}
    anonymous: list[dict] = []

    for draft in [*(current or []), *(incoming or [])]:
        draft_copy = deepcopy(draft)
        draft_id = draft_copy.get("id")
        if not draft_id:
            anonymous.append(draft_copy)
            continue
        existing = merged.get(draft_id)
        if existing is None or _draft_recency_key(draft_copy) >= _draft_recency_key(existing):
            merged[draft_id] = draft_copy

    ordered = list(merged.values()) + anonymous
    ordered.sort(
        key=lambda draft: (
            _parse_state_timestamp(draft.get("created_at") or draft.get("updated_at")),
            _parse_state_timestamp(draft.get("updated_at") or draft.get("created_at")),
        )
    )
    state: BotState = {"drafts": ordered}
    _trim_drafts(state, max_items)
    return state["drafts"]


def _merge_run_history(current: list[dict], incoming: list[dict], max_items: int = 20) -> list[dict]:
    merged: dict[str, dict] = {}
    anonymous: list[dict] = []
    for run in [*(current or []), *(incoming or [])]:
        run_copy = deepcopy(run)
        run_id = run_copy.get("id")
        if not run_id:
            anonymous.append(run_copy)
            continue
        existing = merged.get(run_id)
        if existing is None:
            merged[run_id] = run_copy
            continue
        existing_key = (
            _parse_state_timestamp(existing.get("ended_at") or existing.get("started_at")),
            len(existing.get("sources", [])),
        )
        candidate_key = (
            _parse_state_timestamp(run_copy.get("ended_at") or run_copy.get("started_at")),
            len(run_copy.get("sources", [])),
        )
        if candidate_key >= existing_key:
            merged[run_id] = run_copy

    ordered = list(merged.values()) + anonymous
    ordered.sort(
        key=lambda run: _parse_state_timestamp(run.get("started_at") or run.get("ended_at")),
        reverse=True,
    )
    return ordered[:max_items]


def _merge_errors(current: list[dict], incoming: list[dict], max_items: int = 50) -> list[dict]:
    merged = []
    seen = set()
    for error in [*(current or []), *(incoming or [])]:
        key = (error.get("source"), error.get("ts"), error.get("msg"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(deepcopy(error))
    merged.sort(key=lambda error: _parse_state_timestamp(error.get("ts")))
    return merged[-max_items:]


def _merge_suppressions(current: list[dict], incoming: list[dict], max_items: int = 200) -> list[dict]:
    """Merge suppression records. Dedupe by id (latest ts wins), then trim."""
    merged: dict[str, dict] = {}
    anonymous: list[dict] = []
    for supp in [*(current or []), *(incoming or [])]:
        supp_copy = deepcopy(supp)
        supp_id = supp_copy.get("id")
        if not supp_id:
            anonymous.append(supp_copy)
            continue
        existing = merged.get(supp_id)
        if existing is None:
            merged[supp_id] = supp_copy
            continue
        if _parse_state_timestamp(supp_copy.get("ts")) >= _parse_state_timestamp(existing.get("ts")):
            merged[supp_id] = supp_copy

    ordered = list(merged.values()) + anonymous
    ordered.sort(key=lambda supp: _parse_state_timestamp(supp.get("ts")))
    return ordered[-max_items:]


def _merge_memory(current: MemoryState | None, incoming: MemoryState | None) -> MemoryState:
    base: MemoryState = deepcopy(DEFAULT_STATE["memory"])
    if isinstance(current, dict):
        base.update(deepcopy(current))
    next_memory: MemoryState = deepcopy(DEFAULT_STATE["memory"])
    if isinstance(incoming, dict):
        next_memory.update(deepcopy(incoming))

    merged: MemoryState = deepcopy(DEFAULT_STATE["memory"])
    merged["used_era_anchors"] = _merge_ordered_unique(
        base.get("used_era_anchors", []),
        next_memory.get("used_era_anchors", []),
    )
    merged["used_peer_comparisons"] = _merge_ordered_unique(
        base.get("used_peer_comparisons", []),
        next_memory.get("used_peer_comparisons", []),
    )
    merged["used_framings"] = _merge_ordered_unique(
        base.get("used_framings", []),
        next_memory.get("used_framings", []),
    )

    tweets = []
    seen_tweets = set()
    for row in [*(base.get("shipped_tweets", []) or []), *(next_memory.get("shipped_tweets", []) or [])]:
        if not isinstance(row, dict):
            continue
        key = (
            row.get("tweet_text"),
            row.get("signal_kind"),
            row.get("event_id"),
            row.get("shipped_at"),
        )
        if key in seen_tweets:
            continue
        seen_tweets.add(key)
        tweets.append(deepcopy(row))
    tweets.sort(key=lambda row: _parse_state_timestamp(row.get("shipped_at")))
    merged["shipped_tweets"] = tweets

    events: dict[str, dict] = {}
    anonymous: list[dict] = []
    for row in [*(base.get("ongoing_events", []) or []), *(next_memory.get("ongoing_events", []) or [])]:
        if not isinstance(row, dict):
            continue
        event_id = row.get("event_id")
        if not event_id:
            anonymous.append(deepcopy(row))
            continue
        existing = events.get(event_id)
        if existing is None:
            events[event_id] = deepcopy(row)
            continue
        existing["first_seen"] = min(
            existing.get("first_seen") or row.get("first_seen") or "",
            row.get("first_seen") or existing.get("first_seen") or "",
        ) or None
        existing["last_seen"] = max(
            existing.get("last_seen") or row.get("last_seen") or "",
            row.get("last_seen") or existing.get("last_seen") or "",
        ) or None
        existing["days_running"] = max(
            int(existing.get("days_running") or 0),
            int(row.get("days_running") or 0),
        )
        for field in ("region", "country", "signal_kind"):
            existing[field] = row.get(field) or existing.get(field)
    merged["ongoing_events"] = list(events.values()) + anonymous
    return merged


def _merge_cyclone_wind_history(
    current: dict[str, list[CycloneWindObservation]] | None,
    incoming: dict[str, list[CycloneWindObservation]] | None,
    max_items: int = 16,
) -> dict[str, list[CycloneWindObservation]]:
    """Merge retained cyclone wind observations by storm and timestamp."""

    merged: dict[str, list[CycloneWindObservation]] = {}
    for storm_id in set(list((current or {}).keys()) + list((incoming or {}).keys())):
        by_time: dict[str, CycloneWindObservation] = {}
        for row in [*((current or {}).get(storm_id) or []), *((incoming or {}).get(storm_id) or [])]:
            if not isinstance(row, dict):
                continue
            issued_at = str(row.get("issued_at") or "")
            if not issued_at:
                continue
            try:
                wind_kt = int(row.get("wind_kt", 0))
            except (TypeError, ValueError):
                continue
            by_time[issued_at] = {"issued_at": issued_at, "wind_kt": wind_kt}
        rows = list(by_time.values())
        rows.sort(key=lambda row: _parse_state_timestamp(row.get("issued_at")))
        merged[storm_id] = rows[-max_items:]
    return merged


_FLOOD_SEVERITY_ORDER = {
    "Minor": 0,
    "Moderate": 1,
    "Major": 2,
    "Extreme": 3,
}


def _max_flood_severity(a: str | None, b: str | None) -> str:
    a_label = str(a or "")
    b_label = str(b or "")
    return (
        a_label
        if _FLOOD_SEVERITY_ORDER.get(a_label, -1) >= _FLOOD_SEVERITY_ORDER.get(b_label, -1)
        else b_label
    )


def _merge_max_mm_records(a: dict | None, b: dict | None) -> dict:
    """Merge keyed mm records, preserving the highest observed value."""

    merged: dict = {}
    for key in set(list((a or {}).keys()) + list((b or {}).keys())):
        a_record = (a or {}).get(key)
        b_record = (b or {}).get(key)
        if not isinstance(a_record, dict):
            if isinstance(b_record, dict):
                merged[key] = deepcopy(b_record)
            continue
        if not isinstance(b_record, dict):
            merged[key] = deepcopy(a_record)
            continue
        a_mm = _record_mm_value(a_record)
        b_mm = _record_mm_value(b_record)
        merged[key] = deepcopy(a_record if a_mm >= b_mm else b_record)
    return merged


def _record_mm_value(record: dict) -> float:
    try:
        return float(record.get("mm") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _merge_recent_mm_rows(a: dict | None, b: dict | None, *, max_items: int = 10) -> dict:
    """Merge recent measurement rows by date for each keyed location."""

    merged: dict = {}
    for key in set(list((a or {}).keys()) + list((b or {}).keys())):
        by_date: dict[str, dict] = {}
        for row in [*((a or {}).get(key) or []), *((b or {}).get(key) or [])]:
            if not isinstance(row, dict):
                continue
            row_date = str(row.get("date") or "")
            if not row_date:
                continue
            by_date[row_date] = deepcopy(row)
        rows = list(by_date.values())
        rows.sort(key=lambda row: str(row.get("date") or ""))
        merged[key] = rows[-max_items:]
    return merged


def _merge_state(current: BotState | dict | None, incoming: BotState | dict | None) -> BotState:
    base = _normalize_state(current)
    next_state = _normalize_state(incoming)
    merged: BotState = _fresh_state()
    merged["last_hot10"] = deepcopy(next_state.get("last_hot10", base["last_hot10"]))
    merged["streaks"] = deepcopy(next_state.get("streaks", base["streaks"]))
    merged["posted_events"] = _merge_ordered_unique(
        base.get("posted_events", []),
        next_state.get("posted_events", []),
        max_items=500,
    )
    merged["daily_tweet_count"] = {
        **deepcopy(base.get("daily_tweet_count", {})),
        **deepcopy(next_state.get("daily_tweet_count", {})),
    }
    # For co2_annual_count, prefer max per year so concurrent runs don't
    # lose increments (last-writer-wins would drop a concurrent draft).
    merged["co2_annual_count"] = {}
    for year in set(
        list(base.get("co2_annual_count", {}).keys())
        + list(next_state.get("co2_annual_count", {}).keys())
    ):
        merged["co2_annual_count"][year] = max(
            base.get("co2_annual_count", {}).get(year, 0),
            next_state.get("co2_annual_count", {}).get(year, 0),
        )
    merged["ch4_annual_count"] = {}
    for year in set(
        list(base.get("ch4_annual_count", {}).keys())
        + list(next_state.get("ch4_annual_count", {}).keys())
    ):
        merged["ch4_annual_count"][year] = max(
            base.get("ch4_annual_count", {}).get(year, 0),
            next_state.get("ch4_annual_count", {}).get(year, 0),
        )
    base_ch4 = base.get("ch4_last_milestone")
    next_ch4 = next_state.get("ch4_last_milestone")
    if base_ch4 is None:
        merged["ch4_last_milestone"] = next_ch4
    elif next_ch4 is None:
        merged["ch4_last_milestone"] = base_ch4
    else:
        merged["ch4_last_milestone"] = max(int(base_ch4), int(next_ch4))
    merged_writeable: dict = cast(dict, merged)
    for key in ("nao_annual_count", "ao_annual_count", "pdo_annual_count", "ozone_hole_annual_count"):
        base_counts = cast(dict, base.get(key, {}))
        next_counts = cast(dict, next_state.get(key, {}))
        merged_counts: dict[str, int] = {}
        for year in set(
            list(base_counts.keys())
            + list(next_counts.keys())
        ):
            merged_counts[year] = max(
                int(base_counts.get(year, 0) or 0),
                int(next_counts.get(year, 0) or 0),
            )
        merged_writeable[key] = merged_counts
    for key in ("nao_last_phase", "ao_last_phase", "pdo_last_phase"):
        merged_writeable[key] = next_state.get(key, base.get(key))
    merged["ozone_hole_last_peak"] = _merge_ozone_hole_last_peak(
        base.get("ozone_hole_last_peak"),
        next_state.get("ozone_hole_last_peak"),
    )
    merged["drafts"] = _merge_drafts(base.get("drafts", []), next_state.get("drafts", []))
    merged["run_history"] = _merge_run_history(base.get("run_history", []), next_state.get("run_history", []))
    merged["errors"] = _merge_errors(base.get("errors", []), next_state.get("errors", []))
    merged["suppressions"] = _merge_suppressions(
        base.get("suppressions", []), next_state.get("suppressions", [])
    )
    merged["memory"] = _merge_memory(base.get("memory"), next_state.get("memory"))
    # Extreme record tracking — always take the incoming (most recent) dict
    # since detection functions only write when a new record is set.
    merged["city_all_time_max"] = deepcopy(next_state.get("city_all_time_max", base.get("city_all_time_max", {})))
    merged["city_all_time_min"] = deepcopy(next_state.get("city_all_time_min", base.get("city_all_time_min", {})))
    merged["city_monthly_max"] = deepcopy(next_state.get("city_monthly_max", base.get("city_monthly_max", {})))
    merged["city_monthly_min"] = deepcopy(next_state.get("city_monthly_min", base.get("city_monthly_min", {})))
    merged["record_streaks"] = deepcopy(next_state.get("record_streaks", base.get("record_streaks", {})))
    merged["source_health"] = _merge_source_health(
        base.get("source_health"),
        next_state.get("source_health"),
    )
    # ocean_sst_streak — always-take-incoming, same semantics as record_streaks above.
    merged["ocean_sst_streak"] = deepcopy(
        next_state.get("ocean_sst_streak", base.get("ocean_sst_streak", {}))
    )
    # ice_mass: per-region keep the extreme to survive concurrent writers.
    merged["ice_mass_max_loss"] = {}
    for region in set(
        list(base.get("ice_mass_max_loss", {}).keys())
        + list(next_state.get("ice_mass_max_loss", {}).keys())
    ):
        a_loss = base.get("ice_mass_max_loss", {}).get(region)
        b_loss = next_state.get("ice_mass_max_loss", {}).get(region)
        if a_loss is None:
            assert b_loss is not None  # loop invariant: region in at least one
            merged["ice_mass_max_loss"][region] = deepcopy(b_loss)
        elif b_loss is None:
            merged["ice_mass_max_loss"][region] = deepcopy(a_loss)
        else:
            merged["ice_mass_max_loss"][region] = deepcopy(
                a_loss if a_loss.get("gt", 0.0) <= b_loss.get("gt", 0.0) else b_loss
            )
    merged["ice_mass_last_milestone"] = {}
    for region in set(
        list(base.get("ice_mass_last_milestone", {}).keys())
        + list(next_state.get("ice_mass_last_milestone", {}).keys())
    ):
        a_mil = base.get("ice_mass_last_milestone", {}).get(region)
        b_mil = next_state.get("ice_mass_last_milestone", {}).get(region)
        if a_mil is None:
            assert b_mil is not None  # loop invariant: region in at least one
            merged["ice_mass_last_milestone"][region] = b_mil
        elif b_mil is None:
            merged["ice_mass_last_milestone"][region] = a_mil
        else:
            merged["ice_mass_last_milestone"][region] = min(a_mil, b_mil)
    merged["ice_mass_last_seen"] = {}
    for region in set(
        list(base.get("ice_mass_last_seen", {}).keys())
        + list(next_state.get("ice_mass_last_seen", {}).keys())
    ):
        a_seen = base.get("ice_mass_last_seen", {}).get(region, "")
        b_seen = next_state.get("ice_mass_last_seen", {}).get(region, "")
        merged["ice_mass_last_seen"][region] = a_seen if a_seen >= b_seen else b_seen
    merged["ice_annual_count"] = {}
    for year in set(
        list(base.get("ice_annual_count", {}).keys())
        + list(next_state.get("ice_annual_count", {}).keys())
    ):
        merged["ice_annual_count"][year] = max(
            base.get("ice_annual_count", {}).get(year, 0),
            next_state.get("ice_annual_count", {}).get(year, 0),
        )
    merged["precip_daily_records"] = _merge_max_mm_records(
        base.get("precip_daily_records"),
        next_state.get("precip_daily_records"),
    )
    merged["precip_recent_by_city"] = _merge_recent_mm_rows(
        base.get("precip_recent_by_city"),
        next_state.get("precip_recent_by_city"),
    )
    merged["snow_daily_swe_gain_records"] = _merge_max_mm_records(
        base.get("snow_daily_swe_gain_records"),
        next_state.get("snow_daily_swe_gain_records"),
    )
    merged["snow_recent_by_station"] = _merge_recent_mm_rows(
        base.get("snow_recent_by_station"),
        next_state.get("snow_recent_by_station"),
    )
    merged["snow_annual_count"] = {}
    for year in set(
        list(base.get("snow_annual_count", {}).keys())
        + list(next_state.get("snow_annual_count", {}).keys())
    ):
        merged["snow_annual_count"][year] = max(
            base.get("snow_annual_count", {}).get(year, 0),
            next_state.get("snow_annual_count", {}).get(year, 0),
        )
    merged["seasonal_snow_records"] = _merge_max_mm_records(
        base.get("seasonal_snow_records"),
        next_state.get("seasonal_snow_records"),
    )
    # Take max tier per complex across concurrent writes so a tier bump
    # on one cron run isn't lost to a stale concurrent run.
    merged["fire_complex_tiers"] = {}
    for cid in set(
        list(base.get("fire_complex_tiers", {}).keys())
        + list(next_state.get("fire_complex_tiers", {}).keys())
    ):
        merged["fire_complex_tiers"][cid] = max(
            int(base.get("fire_complex_tiers", {}).get(cid, -1)),
            int(next_state.get("fire_complex_tiers", {}).get(cid, -1)),
        )
    merged["coral_dhw_last_tier"] = {}
    for region_id in set(
        list(base.get("coral_dhw_last_tier", {}).keys())
        + list(next_state.get("coral_dhw_last_tier", {}).keys())
    ):
        merged["coral_dhw_last_tier"][region_id] = max(
            int(base.get("coral_dhw_last_tier", {}).get(region_id, 0)),
            int(next_state.get("coral_dhw_last_tier", {}).get(region_id, 0)),
        )
    merged["coral_dhw_annual_count"] = {}
    for year in set(
        list(base.get("coral_dhw_annual_count", {}).keys())
        + list(next_state.get("coral_dhw_annual_count", {}).keys())
    ):
        merged["coral_dhw_annual_count"][year] = max(
            base.get("coral_dhw_annual_count", {}).get(year, 0),
            next_state.get("coral_dhw_annual_count", {}).get(year, 0),
        )
    merged["sst_anom_last_tier"] = {}
    for region_key in set(
        list(base.get("sst_anom_last_tier", {}).keys())
        + list(next_state.get("sst_anom_last_tier", {}).keys())
    ):
        merged["sst_anom_last_tier"][region_key] = max(
            int(base.get("sst_anom_last_tier", {}).get(region_key, 0)),
            int(next_state.get("sst_anom_last_tier", {}).get(region_key, 0)),
        )
    merged["sst_anom_annual_count"] = {}
    for year in set(
        list(base.get("sst_anom_annual_count", {}).keys())
        + list(next_state.get("sst_anom_annual_count", {}).keys())
    ):
        merged["sst_anom_annual_count"][year] = max(
            int(base.get("sst_anom_annual_count", {}).get(year, 0)),
            int(next_state.get("sst_anom_annual_count", {}).get(year, 0)),
        )
    # Reanalysis regional-anomaly onset guard: keep the latest window_start per
    # region (lexical max == chronological for bare YYYY-MM-DD dates), so a
    # concurrent gist/sqlite merge never re-opens a suppressed ongoing event.
    merged["reganom_last_fired"] = {}
    for region in set(
        list(base.get("reganom_last_fired", {}).keys())
        + list(next_state.get("reganom_last_fired", {}).keys())
    ):
        a_fired = base.get("reganom_last_fired", {}).get(region, "")
        b_fired = next_state.get("reganom_last_fired", {}).get(region, "")
        merged["reganom_last_fired"][region] = a_fired if a_fired >= b_fired else b_fired
    # Cyclone tier dedup follows the same monotonic semantics: never lose a
    # higher category already observed by a concurrent run.
    merged["cyclone_tiers"] = {}
    for storm_id in set(
        list(base.get("cyclone_tiers", {}).keys())
        + list(next_state.get("cyclone_tiers", {}).keys())
    ):
        merged["cyclone_tiers"][storm_id] = max(
            int(base.get("cyclone_tiers", {}).get(storm_id, -1)),
            int(next_state.get("cyclone_tiers", {}).get(storm_id, -1)),
        )
    merged["cyclone_wind_history"] = _merge_cyclone_wind_history(
        base.get("cyclone_wind_history"),
        next_state.get("cyclone_wind_history"),
    )
    merged["cyclone_annual_count"] = {}
    for year in set(
        list(base.get("cyclone_annual_count", {}).keys())
        + list(next_state.get("cyclone_annual_count", {}).keys())
    ):
        merged["cyclone_annual_count"][year] = max(
            base.get("cyclone_annual_count", {}).get(year, 0),
            next_state.get("cyclone_annual_count", {}).get(year, 0),
        )
    merged["flood_activation_tiers"] = {}
    for activation_id in set(
        list(base.get("flood_activation_tiers", {}).keys())
        + list(next_state.get("flood_activation_tiers", {}).keys())
    ):
        merged["flood_activation_tiers"][activation_id] = _max_flood_severity(
            base.get("flood_activation_tiers", {}).get(activation_id),
            next_state.get("flood_activation_tiers", {}).get(activation_id),
        )
    merged["flood_annual_count"] = {}
    for year in set(
        list(base.get("flood_annual_count", {}).keys())
        + list(next_state.get("flood_annual_count", {}).keys())
    ):
        merged["flood_annual_count"][year] = max(
            base.get("flood_annual_count", {}).get(year, 0),
            next_state.get("flood_annual_count", {}).get(year, 0),
        )
    # Max-merge the daily gate so concurrent cron runs keep the later date.
    merged["fire_footprint_last_run"] = max(
        base.get("fire_footprint_last_run") or "",
        next_state.get("fire_footprint_last_run") or "",
    ) or None
    merged["synthesis_components"] = _merge_synthesis_components(
        base.get("synthesis_components"),
        next_state.get("synthesis_components"),
    )
    merged["synthesis_cooldown"] = _merge_synthesis_cooldown(
        base.get("synthesis_cooldown"),
        next_state.get("synthesis_cooldown"),
    )
    return merged


def _merge_synthesis_event_list(
    a: list[dict] | None, b: list[dict] | None
) -> list[dict]:
    """Union of two synthesis event lists, deduped by event_id.

    When both sides have the same event_id, keep the one with the later
    ``at`` timestamp so a stale concurrent writer doesn't roll back
    progress. Entries without an event_id are kept as-is (anonymous
    components still contribute evidence to the rule).
    """
    merged: dict[str, dict] = {}
    anonymous: list[dict] = []
    for entry in [*(a or []), *(b or [])]:
        eid = entry.get("event_id") if isinstance(entry, dict) else None
        if not eid:
            anonymous.append(deepcopy(entry))
            continue
        existing = merged.get(eid)
        if existing is None:
            merged[eid] = deepcopy(entry)
            continue
        existing_at = _parse_state_timestamp(existing.get("at"))
        new_at = _parse_state_timestamp(entry.get("at"))
        if new_at >= existing_at:
            merged[eid] = deepcopy(entry)
    return list(merged.values()) + anonymous


def _merge_synthesis_components(
    base: SynthesisComponents | None, incoming: SynthesisComponents | None
) -> SynthesisComponents:
    """Merge synthesis_components preserving cross-run evidence.

    - ``fires`` and ``heats`` are per-state lists of events. Dedup by
      event_id and union; keep the later ``at`` on collision so a stale
      concurrent run doesn't clobber a newer one.
    - ``drought_snapshot`` is a single dict refreshed on each USDM poll.
      Take the one with the later ``updated_at``.
    """
    b: SynthesisComponents = base or {}
    n: SynthesisComponents = incoming or {}
    merged: SynthesisComponents = {"fires": {}, "heats": {}, "drought_snapshot": None}

    def _merge_bucket(
        b_bucket: dict[str, list[dict]], n_bucket: dict[str, list[dict]]
    ) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for key in set(list(b_bucket.keys()) + list(n_bucket.keys())):
            result[key] = _merge_synthesis_event_list(b_bucket.get(key), n_bucket.get(key))
        return result

    merged["fires"] = _merge_bucket(b.get("fires") or {}, n.get("fires") or {})
    merged["heats"] = _merge_bucket(b.get("heats") or {}, n.get("heats") or {})

    b_snap = b.get("drought_snapshot")
    n_snap = n.get("drought_snapshot")
    if b_snap is None and n_snap is None:
        merged["drought_snapshot"] = None
    elif b_snap is None:
        merged["drought_snapshot"] = deepcopy(n_snap)
    elif n_snap is None:
        merged["drought_snapshot"] = deepcopy(b_snap)
    else:
        b_at = _parse_state_timestamp(b_snap.get("updated_at"))
        n_at = _parse_state_timestamp(n_snap.get("updated_at"))
        merged["drought_snapshot"] = deepcopy(
            n_snap if n_at >= b_at else b_snap
        )
    return merged


def _merge_ozone_hole_last_peak(current: dict | None, incoming: dict | None) -> dict:
    merged = deepcopy(current or {})
    for year, payload in (incoming or {}).items():
        if not isinstance(payload, dict):
            continue
        existing = merged.get(year)
        if not isinstance(existing, dict):
            merged[year] = deepcopy(payload)
            continue
        existing_area = _safe_float(existing.get("area_million_km2"))
        incoming_area = _safe_float(payload.get("area_million_km2"))
        if incoming_area >= existing_area:
            merged[year] = deepcopy(payload)
    return merged


def _safe_float(value: object) -> float:
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return float("-inf")


def _merge_synthesis_cooldown(
    base: dict[str, dict[str, str]] | None,
    incoming: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    """Per-rule per-region cooldown. Keep the later fired-at timestamp."""
    b = base or {}
    n = incoming or {}
    merged: dict[str, dict[str, str]] = {}
    for rule in set(list(b.keys()) + list(n.keys())):
        b_rule = b.get(rule) or {}
        n_rule = n.get(rule) or {}
        rule_merged: dict[str, str] = {}
        for region in set(list(b_rule.keys()) + list(n_rule.keys())):
            a_ts = b_rule.get(region, "")
            c_ts = n_rule.get(region, "")
            rule_merged[region] = (
                a_ts
                if _parse_state_timestamp(a_ts) >= _parse_state_timestamp(c_ts)
                else c_ts
            )
        merged[rule] = rule_merged
    return merged


def _read_gist_state(*, strict: bool = False) -> BotState:
    if not GIST_ID and not GITHUB_TOKEN:
        return _fresh_state()
    if not GIST_ID or not GITHUB_TOKEN:
        if strict:
            raise StateReadError("Gist backend requires both GIST_ID and GITHUB_TOKEN")
        return _fresh_state()

    try:
        resp = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        gist = resp.json()
        file_meta = gist["files"][STATE_FILENAME]
        # GitHub Gists REST API truncates the inline ``content`` field at
        # ~900 KB. When that happens the API sets ``truncated: true`` and
        # exposes the full payload at ``raw_url``. Reading ``content``
        # directly would feed a cut-off JSON tail to json.loads and crash
        # every scheduled run until the state shrank back below the
        # threshold. Observed in production 2026-05-13 (three alerts runs
        # failed at 11:03, 13:34, 14:47 UTC with state.json = 928 KB).
        if file_meta.get("truncated"):
            raw_url = file_meta.get("raw_url")
            if not raw_url:
                if strict:
                    raise StateReadError(
                        f"{STATE_FILENAME} is truncated and has no raw_url"
                    )
                return _fresh_state()
            raw_resp = requests.get(raw_url, headers=_headers(), timeout=30)
            raw_resp.raise_for_status()
            content = raw_resp.text
        else:
            content = file_meta["content"]
        return _normalize_state(json.loads(content))
    except requests.RequestException as exc:
        if strict:
            raise StateReadError(f"Failed to read gist state: {exc}") from exc
    except KeyError as exc:
        if strict:
            raise StateReadError(f"Gist is missing {STATE_FILENAME}") from exc
    except json.JSONDecodeError as exc:
        if strict:
            raise StateReadError(f"{STATE_FILENAME} is not valid JSON") from exc
    return _fresh_state()


def _write_gist_state(state: BotState) -> bool:
    if not GIST_ID or not GITHUB_TOKEN:
        return False

    try:
        normalized = _normalize_state(state)
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            json={
                "files": {
                    STATE_FILENAME: {
                        "content": json.dumps(normalized, indent=2, default=json_default)
                    }
                }
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except (requests.RequestException, TypeError, ValueError):
        return False


def read_state() -> BotState:
    backend = _configured_backend()
    if backend == "sqlite":
        if not DB_PATH:
            raise StateReadError("SQLite backend selected but THEHEAT_DB_PATH is not set")
        try:
            if sqlite_store.is_empty(DB_PATH) and GIST_ID and GITHUB_TOKEN:
                gist_state = _read_gist_state(strict=True)
                sqlite_store.write_state(DB_PATH, cast(dict, gist_state))
            return _normalize_state(sqlite_store.read_state(DB_PATH, cast(dict, DEFAULT_STATE)))
        except Exception as exc:
            raise StateReadError(f"Failed to read SQLite state store: {exc}") from exc
    return _read_gist_state(strict=True)


def write_state(state: BotState) -> bool:
    normalized = _normalize_state(state)
    if _configured_backend() == "sqlite":
        if not DB_PATH:
            return False
        try:
            current: BotState | dict = sqlite_store.read_state(DB_PATH, cast(dict, DEFAULT_STATE))
        except Exception:
            return False
        try:
            return sqlite_store.write_state(
                DB_PATH, cast(dict, _merge_state(current, normalized))
            )
        except (TypeError, ValueError):
            return False
    try:
        current = _read_gist_state(strict=True)
    except StateReadError:
        return False
    try:
        return _write_gist_state(_merge_state(current, normalized))
    except (TypeError, ValueError):
        return False


def is_duplicate(state: BotState, event_id: str) -> bool:
    return event_id in state.get("posted_events", [])


def record_event(state: BotState, event_id: str) -> BotState:
    state.setdefault("posted_events", []).append(event_id)
    # Keep only last 500 events to prevent unbounded growth
    if len(state["posted_events"]) > 500:
        state["posted_events"] = state["posted_events"][-500:]
    return state


def get_daily_count(state: BotState) -> int:
    today = date.today().isoformat()
    return state.get("daily_tweet_count", {}).get(today, 0)


def increment_daily_count(state: BotState) -> BotState:
    today = date.today().isoformat()
    counts = state.setdefault("daily_tweet_count", {})
    counts[today] = counts.get(today, 0) + 1
    # Clean up old days
    for d in list(counts.keys()):
        if d != today:
            del counts[d]
    return state


def check_daily_cap(state: BotState, cap: int = 10) -> bool:
    return get_daily_count(state) < cap


def update_record_streak(
    state: BotState,
    city: str,
    today_temp_c: float,
    event_date: date | None = None,
) -> BotState:
    """Update the record-breaking streak for a city.

    Called when a city has broken its daily calendar-date record.
    If the city already has a streak AND yesterday was also a record day,
    extend it. Otherwise start a new streak.
    """
    today = event_date or date.today()
    updated_at = date.today().isoformat()
    streaks = state.setdefault("record_streaks", {})
    entry = streaks.get(city)

    if entry:
        try:
            last = date.fromisoformat(entry.get("last_date", ""))
            gap = (today - last).days
        except (ValueError, TypeError):
            gap = None
        if gap == 1:
            entry["days"] = int(entry.get("days", 0)) + 1
            entry["last_date"] = today.isoformat()
            entry["peak_temp_c"] = max(float(entry.get("peak_temp_c", -273.15)), today_temp_c)
            entry["updated_at"] = updated_at
        elif gap == 0:
            # Same day re-entry (multi-run day) — no change
            entry["peak_temp_c"] = max(float(entry.get("peak_temp_c", -273.15)), today_temp_c)
            entry["updated_at"] = updated_at
        else:
            # Gap > 1 day → streak broken, reset
            entry["days"] = 1
            entry["start_date"] = today.isoformat()
            entry["last_date"] = today.isoformat()
            entry["peak_temp_c"] = today_temp_c
            entry["updated_at"] = updated_at
    else:
        streaks[city] = {
            "days": 1,
            "start_date": today.isoformat(),
            "last_date": today.isoformat(),
            "peak_temp_c": today_temp_c,
            "updated_at": updated_at,
        }

    return state


def get_record_streak(state: BotState, city: str) -> RecordStreakEntry | None:
    """Return current streak info for a city, or None if no active streak."""
    streaks = state.get("record_streaks", {})
    return streaks.get(city)


def prune_stale_record_streaks(state: BotState, max_gap_days: int = 2) -> BotState:
    """Remove streaks that haven't been updated in more than max_gap_days.

    Called at the end of each alert cycle to prevent unbounded growth
    and to reset streaks that have silently lapsed.
    """
    today = date.today()
    streaks = state.setdefault("record_streaks", {})
    stale = []
    for city, entry in streaks.items():
        try:
            prune_anchor = entry.get("updated_at") or entry.get("last_date", "")
            last = date.fromisoformat(prune_anchor)
            if (today - last).days > max_gap_days:
                stale.append(city)
        except (ValueError, TypeError):
            stale.append(city)
    for city in stale:
        del streaks[city]
    return state


def update_ocean_sst_streak(state: BotState, streak: OceanSSTStreak | dict) -> BotState:
    """Replace the stored ocean SST streak state.

    Idempotent: callers always pass the full two-field dict
    ({seeded: bool, last_milestone_fired: int | None}) computed from the
    most recent observation. No incremental mutation.
    """
    state["ocean_sst_streak"] = {
        "seeded": bool(streak.get("seeded", False)),
        "last_milestone_fired": streak.get("last_milestone_fired"),
    }
    return state


def update_streaks(state: BotState, hot10_cities: list[str]) -> BotState:
    today = date.today().isoformat()
    streaks = state.setdefault("streaks", {})

    for city in hot10_cities:
        if city in streaks and streaks[city]["last_seen"] >= today:
            continue
        if city in streaks:
            prev = datetime.fromisoformat(streaks[city]["last_seen"]).date()
            current = date.today()
            gap = (current - prev).days
            if gap <= 1:
                streaks[city]["consecutive_days"] += 1
            else:
                streaks[city]["consecutive_days"] = 1
            streaks[city]["last_seen"] = today
        else:
            streaks[city] = {"consecutive_days": 1, "last_seen": today}

    for city in list(streaks.keys()):
        if city not in hot10_cities:
            prev = datetime.fromisoformat(streaks[city]["last_seen"]).date()
            if (date.today() - prev).days > 1:
                del streaks[city]

    return state


def log_error(state: BotState, source: str, msg: str) -> BotState:
    errors = state.setdefault("errors", [])
    errors.append({
        "source": source,
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "msg": str(msg)[:200],
    })
    # Keep last 50 errors
    if len(errors) > 50:
        state["errors"] = errors[-50:]
    return state


def init_run(mode: str) -> dict:
    """Create an in-memory run record."""
    started_at = datetime.now(UTC)
    run_id = f"run_{mode}_{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    return {
        "id": run_id,
        "mode": mode,
        "status": "running",
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "sources": [],
    }


def add_source_run(
    run: dict,
    *,
    source: str,
    status: str,
    duration_ms: int = 0,
    observed: int = 0,
    promoted: int = 0,
    triaged_in: int = 0,
    triaged_out: int = 0,
    writer_attempted: int = 0,
    drafted: int = 0,
    error: str | None = None,
    note: str | None = None,
    details: dict | None = None,
) -> dict:
    """Append a source-level result to an in-progress run record.

    ``details`` is an optional structured payload for dashboard drill-down.
    Conventional keys (best-effort, source-specific):
      - ``pipeline_metrics``: dict of stage counts (e.g. for the GHCN path:
        stations_active, stations_with_obs, stations_checked, raw_signals,
        bundles_after_dedup, country_records).
      - ``events``: list of per-event decision rows
        ({event_id, kind, decision, score, reason, station_id?, ...}).
      - ``fetch_meta``: dict of input metadata (urls, byte counts, lookback).
    The schema is intentionally loose — sources add what's useful for them.
    """
    entry = {
        "source": source,
        "status": status,
        "duration_ms": duration_ms,
        "observed": observed,
        "promoted": promoted,
        "triaged_in": triaged_in,
        "triaged_out": triaged_out,
        "writer_attempted": writer_attempted,
        "drafted": drafted,
        "error": error,
        "note": note,
    }
    if details:
        entry["details"] = details
    run.setdefault("sources", []).append(entry)
    return run


SOURCE_HEALTH_WINDOW_DAYS = 7
_SOURCE_HEALTH_COUNTERS = ("success", "degraded", "failed", "skipped")
_SOURCE_HEALTH_METRICS = (
    "duration_ms",
    "observed",
    "promoted",
    "triaged_in",
    "triaged_out",
    "writer_attempted",
    "drafted",
)


def _nonnegative_int(value: Any) -> int | None:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def _source_health_status(status: str) -> str:
    if status == "partial_failure":
        return "degraded"
    if status in _SOURCE_HEALTH_COUNTERS:
        return status
    return "failed"


def _format_state_timestamp(value: datetime | str | None = None) -> str:
    if isinstance(value, str):
        parsed = _parse_state_timestamp(value)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _empty_source_health() -> SourceHealth:
    return {
        "success": 0,
        "degraded": 0,
        "failed": 0,
        "skipped": 0,
        "total_duration_ms": 0,
        "avg_duration_ms": None,
        "max_duration_ms": 0,
        "total_observed": 0,
        "total_promoted": 0,
        "total_triaged_in": 0,
        "total_triaged_out": 0,
        "total_writer_attempted": 0,
        "total_drafted": 0,
        "last_success_ts": None,
        "last_error": None,
        "last_error_ts": None,
        "runs": [],
    }


def _source_health_window_cutoff(runs: list[SourceHealthRun]) -> datetime:
    latest: datetime | None = None
    for run in runs:
        parsed = _parse_state_timestamp(run.get("ts"))
        if latest is None or parsed > latest:
            latest = parsed
    if latest is None:
        latest = datetime.now(UTC)
    return latest - timedelta(days=SOURCE_HEALTH_WINDOW_DAYS)


def _rebuild_source_health(runs: list[SourceHealthRun]) -> SourceHealth:
    health = _empty_source_health()
    cutoff = _source_health_window_cutoff(runs)
    seen = set()
    ordered: list[SourceHealthRun] = []
    duration_values: list[int] = []
    for run in sorted(runs, key=lambda row: _parse_state_timestamp(row.get("ts"))):
        ts = _format_state_timestamp(run.get("ts"))
        if _parse_state_timestamp(ts) < cutoff:
            continue
        status = _source_health_status(str(run.get("status") or "failed"))
        error = run.get("error")
        error_text = str(error) if error else None
        key = (ts, status, error_text)
        if key in seen:
            continue
        seen.add(key)
        entry: SourceHealthRun = {"ts": ts, "status": status}
        if error_text:
            entry["error"] = error_text
        entry_writeable = cast(dict, entry)
        for metric in _SOURCE_HEALTH_METRICS:
            raw_value = run.get(metric)
            value = _nonnegative_int(raw_value)
            if value is None:
                continue
            entry_writeable[metric] = value
        ordered.append(entry)
        health_counts = cast(dict, health)
        health_counts[status] = int(health_counts.get(status, 0)) + 1
        for metric in _SOURCE_HEALTH_METRICS:
            if metric not in entry_writeable:
                continue
            value = int(entry_writeable[metric])
            if metric == "duration_ms":
                health["total_duration_ms"] = int(health.get("total_duration_ms") or 0) + value
                health["max_duration_ms"] = max(int(health.get("max_duration_ms") or 0), value)
                duration_values.append(value)
            else:
                health_key = f"total_{metric}"
                health_counts[health_key] = int(health_counts.get(health_key, 0)) + value
        if status == "success":
            health["last_success_ts"] = ts
        elif status in {"degraded", "failed"} and error_text:
            health["last_error"] = error_text
            health["last_error_ts"] = ts
    if duration_values:
        health["avg_duration_ms"] = round(sum(duration_values) / len(duration_values))
    health["runs"] = ordered
    return health


def record_source_health(
    state: BotState,
    source: str,
    status: str,
    error: str | None = None,
    *,
    timestamp: datetime | str | None = None,
    metrics: dict | None = None,
) -> None:
    """Append a source-health observation and keep a rolling 7-day summary."""
    if not source:
        return
    health_map = state.setdefault("source_health", {})
    health_writeable: dict = cast(dict, health_map)
    existing = health_writeable.get(source) or {}
    runs = list(existing.get("runs") or [])
    run: SourceHealthRun = {
        "ts": _format_state_timestamp(timestamp),
        "status": _source_health_status(status),
    }
    if error:
        run["error"] = str(error)
    run_writeable = cast(dict, run)
    for metric in _SOURCE_HEALTH_METRICS:
        if metrics is None or metric not in metrics:
            continue
        value = metrics.get(metric)
        coerced = _nonnegative_int(value)
        if coerced is None:
            continue
        run_writeable[metric] = coerced
    runs.append(run)
    health_writeable[source] = _rebuild_source_health(runs)


def _merge_source_health(
    current: dict[str, SourceHealth] | None,
    incoming: dict[str, SourceHealth] | None,
) -> dict[str, SourceHealth]:
    merged: dict[str, SourceHealth] = {}
    for source in set(list((current or {}).keys()) + list((incoming or {}).keys())):
        runs: list[SourceHealthRun] = []
        for health in ((current or {}).get(source), (incoming or {}).get(source)):
            if not isinstance(health, dict):
                continue
            for run in health.get("runs") or []:
                if isinstance(run, dict):
                    runs.append(run)
        merged[source] = _rebuild_source_health(runs)
    return merged


def update_fire_complex_tier(state: BotState, complex_id: str, tier: int) -> BotState:
    """Record the highest tier we've tweeted for a fire complex.

    Takes max so concurrent cron runs don't lose a tier bump.
    """
    tiers = state.setdefault("fire_complex_tiers", {})
    current = int(tiers.get(complex_id, -1))
    if tier > current:
        tiers[complex_id] = int(tier)
    return state


def update_coral_dhw_tier(state: BotState, region_id: str, tier: int) -> BotState:
    """Record the highest DHW threshold that has produced a draft."""

    tiers = state.setdefault("coral_dhw_last_tier", {})
    current = int(tiers.get(region_id, 0))
    if tier > current:
        tiers[region_id] = int(tier)
    return state


def increment_coral_dhw_annual_count(state: BotState) -> BotState:
    """Track annual coral-bleaching DHW draft volume."""

    year = str(date.today().year)
    counts = state.setdefault("coral_dhw_annual_count", {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state


def update_sst_anom_tier(
    state: BotState,
    region_slug: str,
    tier: int,
    reading_date: str,
) -> BotState:
    """Record the highest regional SST anomaly tier fired in a reading year."""

    year = reading_date[:4]
    key = f"{year}/{region_slug}"
    tiers = state.setdefault("sst_anom_last_tier", {})
    current = int(tiers.get(key, 0))
    if tier > current:
        tiers[key] = int(tier)
    return state


def increment_sst_anom_annual_count(state: BotState, reading_date: str) -> BotState:
    """Track regional SST anomaly draft volume by the CRW reading year."""

    year = reading_date[:4]
    counts = state.setdefault("sst_anom_annual_count", {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state


def set_reganom_last_fired(state: BotState, region_slug: str, window_start: str) -> BotState:
    """Record the onset guard for a reanalysis regional-anomaly region (§D).

    Monotonic max over the ISO window_start, so an older window never clobbers a
    newer one (and a re-attempt of the same ongoing spell is a no-op). Written at
    attempt time in the runner so killed drafts still suppress same-window re-tries.
    """
    fired = state.setdefault("reganom_last_fired", {})
    if window_start > fired.get(region_slug, ""):
        fired[region_slug] = window_start
    return state


def update_ch4_last_milestone(state: BotState, milestone: int) -> BotState:
    """Record the highest methane milestone that has produced a draft."""

    current = state.get("ch4_last_milestone")
    if current is None or milestone > int(current):
        state["ch4_last_milestone"] = int(milestone)
    return state


def increment_ch4_annual_count(state: BotState) -> BotState:
    """Track annual methane milestone draft volume."""

    year = str(date.today().year)
    counts = state.setdefault("ch4_annual_count", {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state


def increment_oscillation_annual_count(state: BotState, index_name: str) -> BotState:
    """Track NAO/AO/PDO draft volume against per-index annual caps."""

    key = f"{index_name.lower()}_annual_count"
    year = str(date.today().year)
    counts = cast(dict, state).setdefault(key, {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state


def update_oscillation_last_phase(
    state: BotState,
    index_name: str,
    phase: str,
) -> BotState:
    """Store the latest observed NAO/AO/PDO phase."""

    cast(dict, state)[f"{index_name.lower()}_last_phase"] = phase
    return state


def record_ozone_hole_peak(state: BotState, event) -> BotState:
    """Persist the latest annual Antarctic ozone hole peak payload."""

    peaks = state.setdefault("ozone_hole_last_peak", {})
    peaks[str(event.year)] = {
        "peak_date": event.peak_date,
        "area_million_km2": event.area_million_km2,
        "previous_year": event.previous_year,
        "previous_area_million_km2": event.previous_area_million_km2,
        "record_year": event.record_year,
        "record_area_million_km2": event.record_area_million_km2,
    }
    return state


def increment_ozone_hole_annual_count(state: BotState) -> BotState:
    """Track annual ozone-hole draft volume."""

    year = str(date.today().year)
    counts = state.setdefault("ozone_hole_annual_count", {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state


def update_cyclone_tier(state: BotState, storm_id: str, tier: int) -> BotState:
    """Record the highest cyclone tier that has produced a draft."""

    tiers = state.setdefault("cyclone_tiers", {})
    current = int(tiers.get(storm_id, -1))
    if tier > current:
        tiers[storm_id] = int(tier)
    return state


def record_cyclone_wind_observation(
    state: BotState,
    storm_id: str,
    issued_at: str,
    wind_kt: int,
    *,
    max_items: int = 16,
) -> BotState:
    """Retain a small wind history for rapid-intensification detection."""

    if not storm_id or not issued_at:
        return state
    history = state.setdefault("cyclone_wind_history", {})
    rows = [
        row for row in history.get(storm_id, [])
        if isinstance(row, dict) and row.get("issued_at") != issued_at
    ]
    rows.append({"issued_at": issued_at, "wind_kt": int(wind_kt)})
    rows.sort(key=lambda row: _parse_state_timestamp(row.get("issued_at")))
    history[storm_id] = rows[-max_items:]
    return state


def increment_cyclone_annual_count(state: BotState) -> BotState:
    """Track cyclone draft volume for visibility without enforcing a cap."""

    year = str(date.today().year)
    counts = state.setdefault("cyclone_annual_count", {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state


def update_flood_activation_tier(state: BotState, activation_id: str, severity: str) -> BotState:
    """Record the highest Copernicus EMS flood severity that produced a draft."""

    tiers = state.setdefault("flood_activation_tiers", {})
    current = str(tiers.get(activation_id, ""))
    if _max_flood_severity(current, severity) == severity:
        tiers[activation_id] = severity
    return state


def increment_flood_annual_count(state: BotState) -> BotState:
    """Track global-flood draft volume for visibility without enforcing a cap."""

    year = str(date.today().year)
    counts = state.setdefault("flood_annual_count", {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state


def finalize_run(state: BotState, run: dict, status: str = "success", max_runs: int = 20) -> BotState:
    """Persist a completed run into state history."""
    completed = deepcopy(run)
    completed["status"] = status
    completed["ended_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    completed["source_count"] = len(completed.get("sources", []))
    completed["failure_count"] = sum(
        1 for source in completed.get("sources", [])
        if source.get("status") == "failed"
    )
    completed["drafted_count"] = sum(
        source.get("drafted", 0) for source in completed.get("sources", [])
    )

    history = state.setdefault("run_history", [])
    history.insert(0, completed)
    if len(history) > max_runs:
        state["run_history"] = history[:max_runs]
    return state


def record_synthesis_component(
    state: BotState,
    *,
    kind: str,
    region: str,
    event_id: str,
    metadata: dict | None = None,
    timestamp: str | None = None,
) -> BotState:
    bucket_key = "fires" if kind == "fire" else "heats"
    state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
    # Cast to plain dict for runtime-keyed setdefault; SynthesisComponents
    # restricts keys to literals which doesn't match the conditional above.
    components_writeable: dict = cast(dict, state["synthesis_components"])
    bucket = components_writeable.setdefault(bucket_key, {}).setdefault(region, [])
    if any(entry.get("event_id") == event_id for entry in bucket):
        return state
    entry = {
        "event_id": event_id,
        "at": timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if metadata:
        for k, v in metadata.items():
            entry[k] = v
    bucket.append(entry)
    return state


def get_synthesis_components(
    state: BotState, *, kind: str, region: str, since: str | None = None,
) -> list[dict]:
    bucket_key = "fires" if kind == "fire" else "heats"
    components: dict = cast(dict, state.get("synthesis_components") or {})
    entries = (components.get(bucket_key) or {}).get(region) or []
    if since is None:
        return list(entries)
    return [e for e in entries if e.get("at", "") >= since]


def record_synthesis_drought_snapshot(state: BotState, updates) -> BotState:
    entries = []
    for u in updates or []:
        if hasattr(u, "state"):
            entries.append({
                "state": u.state,
                "d3_pct": float(getattr(u, "d3_pct", 0) or 0),
                "d4_pct": float(getattr(u, "d4_pct", 0) or 0),
                "total_drought_pct": float(getattr(u, "total_drought_pct", 0) or 0),
            })
        elif isinstance(u, dict):
            entries.append({
                "state": u.get("state", ""),
                "d3_pct": float(u.get("d3_pct", 0) or 0),
                "d4_pct": float(u.get("d4_pct", 0) or 0),
                "total_drought_pct": float(u.get("total_drought_pct", 0) or 0),
            })
    components = state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
    components["drought_snapshot"] = {
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "entries": entries,
    }
    return state


def get_synthesis_drought_snapshot(state: BotState) -> DroughtSnapshot | None:
    components = state.get("synthesis_components") or {}
    return components.get("drought_snapshot")


def is_synthesis_on_cooldown(
    state: BotState, rule_name: str, region: str, days: int = 14,
) -> bool:
    cooldowns = (state.get("synthesis_cooldown") or {}).get(rule_name) or {}
    last_fired = cooldowns.get(region)
    if not last_fired:
        return False
    try:
        last_dt = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    else:
        last_dt = last_dt.astimezone(UTC)
    return (datetime.now(UTC) - last_dt) < timedelta(days=days)


def record_synthesis_fired(
    state: BotState, rule_name: str, region: str, timestamp: str | None = None,
) -> BotState:
    cooldowns = state.setdefault("synthesis_cooldown", {})
    per_rule = cooldowns.setdefault(rule_name, {})
    per_rule[region] = (
        timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    return state


def prune_stale_synthesis_components(state: BotState, ttl_days: int = 14) -> BotState:
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat().replace("+00:00", "Z")
    state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
    components: dict = cast(dict, state["synthesis_components"])
    for bucket_key in ("fires", "heats"):
        bucket = components.setdefault(bucket_key, {})
        for region in list(bucket.keys()):
            fresh = [e for e in bucket[region] if e.get("at", "") >= cutoff]
            if fresh:
                bucket[region] = fresh
            else:
                del bucket[region]
    return state


# ---------------------------------------------------------------------------
# Data-source failure tracking
# ---------------------------------------------------------------------------


def increment_data_source_failure(state: BotState, source: str) -> int:
    """Increment and return the consecutive failure count for ``source``."""
    failures = state.setdefault("data_source_failures", {})
    failures[source] = failures.get(source, 0) + 1
    return failures[source]


def reset_data_source_failure(state: BotState, source: str) -> None:
    """Reset the consecutive failure count for ``source`` to 0 on success."""
    state.setdefault("data_source_failures", {})[source] = 0


def get_data_source_failure_count(state: BotState, source: str) -> int:
    """Return current consecutive failure count for ``source`` (0 if unknown)."""
    return state.get("data_source_failures", {}).get(source, 0)
