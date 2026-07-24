"""State management via pluggable durable backends."""

from copy import deepcopy
import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, cast

import requests

from src.state_schema import (
    BotState,
    CoverageRecord,  # noqa: F401 — re-exported for callers
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
MAX_SHIPPED_TWEETS = 200
MAX_SUPPRESSIONS = 100
STATE_SIZE_WARNING_BYTES = 800_000
SOURCE_HEALTH_MAX_RUNS = 10
COVERAGE_WINDOW_DAYS = 21
RECENT_RECORD_TTL_DAYS = 90
RECORD_STORE_RETENTION_YEARS = 10
REJECTED_DRAFT_RETENTION_DAYS = 30
REJECTED_DRAFT_GUARDRAIL_COUNT = 10
_DRAFT_CAP_PROTECTED_STATUSES = {"pending", "posted"}
_TIER_TOUCH_SEPARATOR = "::"
_TIER_TTLS_DAYS = {
    "fire_complex_tiers": 90,
    "cyclone_tiers": 30,
    "cyclone_land_threat_pairs": 30,
    "heat_records_cluster_fired": 30,
    "flood_activation_tiers": 60,
}

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
    "coverage_log": [],  # rolling per-surfaced-event geography for the coverage watch
    # Newsworthiness lane (Bet A phase 0, flag-gated): what the world reports.
    "news_events": [],
    # Rolling {event_id, category, type, city, where, date} for every enqueued
    # candidate — the news-gap watch's "what did we detect?" side. There is no
    # other durable candidate registry (suppressions hold near-misses only).
    "candidates_log": [],
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
    # Derived expiry per tracked credential (dashboard counter). Holds only the
    # expiry date, never the token; recomputed each run from the environment.
    "credential_expiry": {},
    # Compact last-good readings for slow-moving sources. Each entry is a
    # derived detector input, never raw fetched rows.
    "last_good_readings": {},
    # Durable publish intent ledger, keyed by event_id. Written before posting
    # so an interrupted publish pass can avoid immediately re-posting a draft.
    "publish_ledger": {},
    # Public engagement metrics for posted X tweets, keyed by tweet_id.
    "tweet_metrics": {},
    # Per-day LLM usage ledger (economics P0.6): day → "stage|model" →
    # {calls, in, cached_in, cache_write, out, usd}. Pruned to
    # usage_ledger.LLM_USAGE_RETENTION_DAYS days — single-digit KB (#390).
    "llm_usage": {},
    # Cross-cycle negative cache for paid-stage writer kills (economics P1.3):
    # event_id → {sha, stage, reason, at, hits}. TTL'd (48h default) + capped
    # at negative_cache.NEGATIVE_CACHE_MAX_ENTRIES — small and self-cleaning.
    "writer_negative_cache": {},
    # Monotonic state revision used to detect and re-merge gist write conflicts.
    "_state_rev": 0,
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
    # One-shot land-threat dedup (#375): tracking_key -> drafted landmass
    # slugs. A (storm, landmass) pair drafts exactly once, ever; recorded
    # only on draft SUCCESS (the fire_complex_tiers callback pattern).
    "cyclone_land_threat_pairs": {},
    # Per-cluster/date dedup for the heat records-cluster class (#414):
    # event_id -> signal_date. Recorded only on draft SUCCESS (a killed draft
    # retries next cycle); TTL-pruned. The generic posted_events guard only
    # sees per-event ids, so this map is consulted explicitly in detection.
    "heat_records_cluster_fired": {},
    # Per-Copernicus EMS activation severity dedup for global flood events.
    "flood_activation_tiers": {},
    # Flat sidecar timestamps for tier TTL pruning. Tier dict values stay bare
    # ints/strings for backwards compatibility; keys are "{tier_dict}::{id}".
    "tier_touch_ts": {},
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
    state_backend = os.environ.get("THEHEAT_STATE_BACKEND", STATE_BACKEND).lower()
    db_path = os.environ.get("THEHEAT_DB_PATH", DB_PATH)
    if state_backend in {"gist", "sqlite"}:
        return state_backend
    return "sqlite" if db_path else "gist"


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


def _utc_iso(moment: datetime | None = None) -> str:
    when = moment or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _coerce_utc_datetime(value: datetime | date | str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return _parse_state_timestamp(str(value))


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


def _merge_coverage_log(current: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge two coverage_log lists, deduplicating on event_id.

    Records without an event_id (anonymous) are appended without dedup.
    The merged list preserves the last-writer value for each event_id.
    """
    by_id: dict[str, dict] = {}
    anonymous: list[dict] = []
    for rec in [*(current or []), *(incoming or [])]:
        rec_id = rec.get("event_id")
        if not rec_id:
            anonymous.append(dict(rec))
        else:
            by_id[rec_id] = dict(rec)
    return [*by_id.values(), *anonymous]


def _news_event_key(ev: dict) -> tuple:
    return (
        str(ev.get("kind") or ""),
        str(ev.get("headline") or ""),
        str(ev.get("window_start") or ""),
    )


def _merge_news_events(current: list[dict], incoming: list[dict]) -> list[dict]:
    """Dedup on (kind, headline, window_start); last writer wins."""
    by_key: dict[tuple, dict] = {}
    for rec in [*(current or []), *(incoming or [])]:
        if isinstance(rec, dict):
            by_key[_news_event_key(rec)] = dict(rec)
    return list(by_key.values())


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


def _merge_suppressions(current: list[dict], incoming: list[dict], max_items: int = MAX_SUPPRESSIONS) -> list[dict]:
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
    merged["shipped_tweets"] = tweets[-MAX_SHIPPED_TWEETS:]

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


def _merge_land_threat_pairs(
    ours: dict[str, list[str]], theirs: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Per-storm union of drafted landmass slugs — a pair recorded by either
    concurrent run stays recorded (one-shot dedup must never regress).

    Known + accepted (codex #388 r1 P2): merging against a STALE backend
    copy can transiently resurrect a TTL-pruned pair. The failure direction
    is suppression (the pair reads as already-drafted), never a duplicate
    draft, and the next prune re-deletes it — the union deliberately favors
    the one-shot guarantee over prune latency.
    """
    merged: dict[str, list[str]] = {}
    for key in set(ours or {}) | set(theirs or {}):
        merged[key] = sorted(
            set((ours or {}).get(key, [])) | set((theirs or {}).get(key, []))
        )
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


def _pick_newer_city_tier(a: dict | None, b: dict | None) -> dict | None:
    """Reconcile two per-city air-quality tier records ``{"tier", "date"}``.

    Keeps the more recent observation (later ``date``); on the same date keeps the
    higher tier. Matches the _should_emit_tier dedup rule (re-emit only on a newer
    date or a higher tier), so a concurrent merge never re-opens a covered tier.
    """
    if not a:
        return b
    if not b:
        return a
    a_date, b_date = str(a.get("date", "")), str(b.get("date", ""))
    if a_date != b_date:
        return a if a_date > b_date else b
    return a if int(a.get("tier", 0)) >= int(b.get("tier", 0)) else b


# ---------------------------------------------------------------------------
# Declarative merge strategies. Each strategy is a callable (base, next) -> merged
# wired to a state key in MERGE_SPEC (defined after the merge helpers, below).
# Replaces the former 314-line imperative _merge_state. See
# docs/superpowers/specs/2026-06-09-merge-spec-design.md for the full key->strategy
# mapping and the equivalence contract (byte-identical on schema-valid state).
# ---------------------------------------------------------------------------


def _strat_take_incoming(base: Any, nxt: Any) -> Any:
    """Replace with the incoming value (detection fns only write on change)."""
    return deepcopy(nxt)


def _strat_dict_overlay(base: Any, nxt: Any) -> dict:
    """Per-key last-writer-wins overlay, deepcopied to avoid aliasing the inputs."""
    return {**deepcopy(base or {}), **deepcopy(nxt or {})}


def _strat_max_int(base: Any, nxt: Any) -> int:
    """Scalar integer max for monotonic revision counters."""
    try:
        base_i = int(base)
    except (TypeError, ValueError):
        base_i = 0
    try:
        nxt_i = int(nxt)
    except (TypeError, ValueError):
        nxt_i = 0
    return max(base_i, nxt_i)


def _strat_ordered_unique(max_items: int) -> Callable[..., Any]:
    """Order-preserving union with a tail cap (e.g. posted_events)."""

    def merge(base: Any, nxt: Any) -> list:
        return _merge_ordered_unique(base or [], nxt or [], max_items=max_items)

    return merge


def _strat_max_by_key(floor: Any) -> Callable[..., Any]:
    """Per-key raw max over the key union; an absent key defaults to ``floor``.

    Raw comparison (no int()/str() coercion) keeps the stored value's type and
    reproduces the current per-key loops exactly on schema-valid state. ``floor``
    is the per-side default for an absent key, applied by membership — never
    ``value or floor`` (which would collapse a legitimate 0 tier to a -1 floor).
    """

    def merge(base: Any, nxt: Any) -> dict:
        base = base or {}
        nxt = nxt or {}
        out: dict = {}
        for key in sorted(set(base) | set(nxt)):  # sorted: deterministic merged-dict bytes
            a = base[key] if key in base else floor
            b = nxt[key] if key in nxt else floor
            out[key] = a if a >= b else b
        return out

    return merge


def _strat_reduce_by_key(reducer: Callable[[Any, Any], Any]) -> Callable[..., Any]:
    """Per-key reduce over the key union via ``reducer(base_v, next_v)``.

    The reducer receives ``None`` for an absent side and may be asymmetric. The
    chosen value is deepcopied so a returned dict never aliases an input snapshot.
    """

    def merge(base: Any, nxt: Any) -> dict:
        base = base or {}
        nxt = nxt or {}
        out: dict = {}
        for key in sorted(set(base) | set(nxt)):  # sorted: deterministic merged-dict bytes
            out[key] = deepcopy(reducer(base.get(key), nxt.get(key)))
        return out

    return merge


def _keep_min_gt(a: dict | None, b: dict | None) -> dict | None:
    """ice_mass_max_loss reducer: keep the more-negative gt (worst loss); ties keep a."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a.get("gt", 0.0) <= b.get("gt", 0.0) else b


def _present_min(a: Any, b: Any) -> Any:
    """ice_mass_last_milestone reducer: take the present side, else the minimum."""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _merge_ch4_last_milestone(base: Any, nxt: Any) -> Any:
    """One-sided: take the present value unchanged. Both present: max of the ints."""
    if base is None:
        return nxt
    if nxt is None:
        return base
    return max(int(base), int(nxt))


def _merge_fire_footprint_last_run(base: Any, nxt: Any) -> str | None:
    """Daily-gate ISO date: keep the later string; an empty result collapses to None."""
    return max(base or "", nxt or "") or None


def _merge_data_source_failures(base: Any, nxt: Any) -> dict:
    """Per-provider consecutive-failure streak. Incoming (this cycle) is authoritative:
    a 0 clears the streak; a non-zero takes the max with the persisted value so a stale
    concurrent run can't shorten a real outage; a source untouched this cycle keeps its
    persisted streak.
    """
    base = base or {}
    nxt = nxt or {}
    out: dict = {}
    for src in sorted(set(base) | set(nxt)):  # sorted: deterministic merged-dict bytes
        if src in nxt:
            n = int(nxt.get(src, 0))
            out[src] = 0 if n == 0 else max(n, int(base.get(src, 0)))
        else:
            out[src] = int(base.get(src, 0))
    return out


def _merge_last_good(base: Any, nxt: Any) -> dict:
    """Per-source last-good cache merge: keep newest captured_at."""

    base = base if isinstance(base, dict) else {}
    nxt = nxt if isinstance(nxt, dict) else {}
    out: dict = {}
    for source in sorted(set(base) | set(nxt)):
        a = base.get(source)
        b = nxt.get(source)
        if not isinstance(a, dict):
            out[source] = deepcopy(b)
            continue
        if not isinstance(b, dict):
            out[source] = deepcopy(a)
            continue
        a_ts = _parse_state_timestamp(str(a.get("captured_at") or ""))
        b_ts = _parse_state_timestamp(str(b.get("captured_at") or ""))
        out[source] = deepcopy(a if a_ts >= b_ts else b)
    return out


def _merge_llm_usage(base: Any, nxt: Any) -> dict:
    """Merge the day-keyed LLM usage ledger (economics P0.6).

    Per (day, "stage|model", counter): element-wise MAX. Counters increase
    monotonically within a day for any single writer lineage, so serialized
    bot cycles merge exactly (max == the newer snapshot), and a STALE overlay
    from a concurrent state writer that recorded no usage (e.g. the
    reject-all-drafts operator tool — its own concurrency group) can no
    longer roll a day bucket backwards (codex P1). Two writers that both
    ADDED usage from one base undercount by the smaller increment — bounded,
    never inflated, fine for a directional ledger. Union of days + newest-N
    prune HERE, not only at drain: a plain overlay merge resurrects
    drain-pruned days on every write (codex P1 — reproduced as 45→46 days).
    """
    from src.two_bot.usage_ledger import (
        LLM_USAGE_RETENTION_DAYS,
        _is_valid_day_key,
        _valid_agg,
    )

    base_d = base if isinstance(base, dict) else {}
    nxt_d = nxt if isinstance(nxt, dict) else {}
    merged: dict = {}
    for day in set(base_d) | set(nxt_d):
        # Corrupt day keys are dropped, not merged — canonical-date validated,
        # since shape-valid junk ("9999-99-00") sorts above real days and a
        # lexicographic prune would evict them (codex r2/r3 P2).
        if not _is_valid_day_key(day):
            continue
        b_day = base_d.get(day)
        n_day = nxt_d.get(day)
        b_day = b_day if isinstance(b_day, dict) else {}
        n_day = n_day if isinstance(n_day, dict) else {}
        day_out: dict = {}
        for key in set(b_day) | set(n_day):
            b_agg = _valid_agg(deepcopy(b_day.get(key, {})))
            n_agg = _valid_agg(deepcopy(n_day.get(key, {})))
            out = {
                field: max(b_agg[field], n_agg[field])
                for field in ("calls", "in", "cached_in", "cache_write", "out")
            }
            out["usd"] = max(b_agg["usd"], n_agg["usd"])
            day_out[key] = out
        merged[day] = day_out
    for day in sorted(merged.keys())[:-LLM_USAGE_RETENTION_DAYS]:
        del merged[day]
    return merged


def _merge_writer_negative_cache(base: Any, nxt: Any) -> dict:
    """Merge the cross-cycle negative cache (economics P1.3).

    Per event_id: structurally VALIDATE both sides (malformed dropped, never
    trusted), keep the entry with the newest PARSED instant (offset-safe —
    string comparison would let a "+02:00" suffix defeat newest-wins), and
    when both sides describe the same (sha, epoch) evidence take the MAX
    kill count (two writers incrementing from one base under-count by the
    smaller increment — bounded, never inflated; mirrors _merge_llm_usage).
    TTL-expiry and the size cap are enforced HERE as well as at drain time:
    a merge without its own prune resurrects drain-pruned entries on every
    write from a stale overlay (codex r1 P2 — reproduced)."""
    from src.two_bot.negative_cache import (
        NEGATIVE_CACHE_MAX_ENTRIES,
        parse_at,
        ttl_hours,
        valid_entry,
    )

    base_d = base if isinstance(base, dict) else {}
    nxt_d = nxt if isinstance(nxt, dict) else {}
    now = datetime.now(UTC)
    ttl = timedelta(hours=ttl_hours())
    merged: dict = {}
    for event_id in set(base_d) | set(nxt_d):
        a = base_d.get(event_id)
        b = nxt_d.get(event_id)
        a = a if valid_entry(a) else None
        b = b if valid_entry(b) else None
        if a is None and b is None:
            continue
        if a is None or b is None:
            chosen = deepcopy(a if b is None else b)
            assert chosen is not None  # both-None handled above
        else:
            a_at, b_at = parse_at(a["at"]), parse_at(b["at"])
            assert a_at is not None and b_at is not None  # valid_entry guarantees
            chosen = deepcopy(a if a_at >= b_at else b)
            if a.get("sha") == b.get("sha") and a.get("epoch") == b.get("epoch"):
                chosen["kills"] = max(int(a["kills"]), int(b["kills"]))
        at = parse_at(chosen["at"])
        assert at is not None
        age = now - at
        if age < timedelta(0) or age > ttl:
            continue  # TTL-expired (or future-stamped) — do not resurrect
        merged[event_id] = chosen
    if len(merged) > NEGATIVE_CACHE_MAX_ENTRIES:
        # Parsed-instant sort (codex r2 P2): raw ISO strings with mixed
        # offsets would evict newer instants over older ones.
        def _instant(key: str) -> datetime:
            at = parse_at(merged[key].get("at"))
            return at if at is not None else datetime.min.replace(tzinfo=UTC)

        oldest_first = sorted(merged.keys(), key=_instant)
        for key in oldest_first[: len(merged) - NEGATIVE_CACHE_MAX_ENTRIES]:
            del merged[key]
    return merged


def _merge_tweet_metrics(base: Any, nxt: Any) -> dict:
    """Per-tweet metrics merge: keep the row sampled at the newest timestamp."""

    base = base if isinstance(base, dict) else {}
    nxt = nxt if isinstance(nxt, dict) else {}
    out: dict = {}
    for tweet_id in sorted(set(base) | set(nxt)):
        a = base.get(tweet_id)
        b = nxt.get(tweet_id)
        if not isinstance(a, dict):
            out[tweet_id] = deepcopy(b)
            continue
        if not isinstance(b, dict):
            out[tweet_id] = deepcopy(a)
            continue
        a_ts = _parse_state_timestamp(str(a.get("at") or ""))
        b_ts = _parse_state_timestamp(str(b.get("at") or ""))
        out[tweet_id] = deepcopy(a if a_ts >= b_ts else b)
    return out


def _merge_state(current: BotState | dict | None, incoming: BotState | dict | None) -> BotState:
    """Reconcile two state snapshots key-by-key via MERGE_SPEC.

    Every DEFAULT_STATE key has exactly one strategy (enforced by
    test_merge_spec_covers_exactly_default_state), so a newly added key can never
    silently reset on write. Strategies are independent (no cross-key reads), so
    MERGE_SPEC iteration order does not affect the result.
    """
    base = _normalize_state(current)
    nxt = _normalize_state(incoming)
    merged: dict = cast(dict, _fresh_state())
    for key, strategy in MERGE_SPEC.items():
        merged[key] = strategy(base.get(key), nxt.get(key))
    return cast(BotState, merged)


def _row_date(row: dict) -> date | None:
    value = row.get("date") if isinstance(row, dict) else None
    if not value:
        return None
    return _parse_state_timestamp(str(value)).date()


def _newest_row_date(rows: Any) -> date | None:
    if not isinstance(rows, list):
        return None
    dates: list[date] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_dt = _row_date(row)
        if row_dt is not None:
            dates.append(row_dt)
    return max(dates) if dates else None


def _record_year_from_payload(record: Any) -> int | None:
    if not isinstance(record, dict):
        return None
    raw_year: Any = record.get("year")
    try:
        return int(raw_year)
    except (TypeError, ValueError):
        record_date = _row_date(record)
        return record_date.year if record_date is not None else None


def _prune_recent_mm_rows(state: BotState, key: str, cutoff: date) -> set[str]:
    state_dict = cast(dict, state)
    recent = cast(dict, state_dict.setdefault(key, {}))
    active: set[str] = set()
    for location_key in sorted(list(recent.keys())):
        newest = _newest_row_date(recent.get(location_key))
        if newest is None or newest < cutoff:
            del recent[location_key]
            continue
        active.add(str(location_key))
    return active


def _prune_daily_mm_records(
    state: BotState,
    *,
    records_key: str,
    recent_key: str,
    now_dt: datetime,
) -> None:
    active_locations = _prune_recent_mm_rows(
        state,
        recent_key,
        (now_dt - timedelta(days=RECENT_RECORD_TTL_DAYS)).date(),
    )
    state_dict = cast(dict, state)
    records = cast(dict, state_dict.setdefault(records_key, {}))
    min_year = now_dt.year - RECORD_STORE_RETENTION_YEARS
    for record_key in sorted(list(records.keys())):
        record = records.get(record_key)
        if not isinstance(record, dict):
            del records[record_key]
            continue
        year = _record_year_from_payload(record)
        if year is not None and year < min_year:
            del records[record_key]
            continue
        location_key = str(record_key).rsplit(":", 1)[0]
        if location_key not in active_locations:
            del records[record_key]


def _cap_shipped_tweets(rows: Any) -> list[dict]:
    tweets = [deepcopy(row) for row in (rows or []) if isinstance(row, dict)]
    tweets.sort(key=lambda row: _parse_state_timestamp(row.get("shipped_at")))
    return tweets[-MAX_SHIPPED_TWEETS:]


def _tier_touch_key(store_key: str, item_key: str) -> str:
    return f"{store_key}{_TIER_TOUCH_SEPARATOR}{item_key}"


def _split_tier_touch_key(touch_key: str) -> tuple[str, str] | None:
    if _TIER_TOUCH_SEPARATOR not in touch_key:
        return None
    store_key, item_key = touch_key.split(_TIER_TOUCH_SEPARATOR, 1)
    return store_key, item_key


def _touch_tier(state: BotState, store_key: str, item_key: str, *, now: datetime | None = None) -> None:
    touches = cast(dict, state.setdefault("tier_touch_ts", {}))
    touches[_tier_touch_key(store_key, item_key)] = _utc_iso(now)


def _prune_tier_store(state: BotState, store_key: str, ttl_days: int, now_dt: datetime) -> None:
    state_dict = cast(dict, state)
    tiers = cast(dict, state_dict.setdefault(store_key, {}))
    touches = cast(dict, state.setdefault("tier_touch_ts", {}))
    cutoff = now_dt - timedelta(days=ttl_days)
    now_iso = _utc_iso(now_dt)

    for item_key in sorted(list(tiers.keys())):
        touch_key = _tier_touch_key(store_key, str(item_key))
        touched_at = touches.get(touch_key)
        if not touched_at:
            touches[touch_key] = now_iso
            continue
        if _parse_state_timestamp(str(touched_at)) < cutoff:
            del tiers[item_key]
            touches.pop(touch_key, None)

    for touch_key in sorted(list(touches.keys())):
        split = _split_tier_touch_key(str(touch_key))
        if split is None:
            continue
        touch_store, item_key = split
        if touch_store == store_key and item_key not in tiers:
            del touches[touch_key]


def _prune_year_keyed_dict(values: Any, min_year: int) -> dict:
    if not isinstance(values, dict):
        return {}
    pruned = {}
    for key, value in sorted(values.items()):
        try:
            year = int(str(key))
        except ValueError:
            pruned[key] = value
            continue
        if year >= min_year:
            pruned[key] = value
    return pruned


def prune_state(bot_state: BotState, now: datetime | date | str) -> BotState:
    """Prune unbounded durable state in place at the end of a run."""

    now_dt = _coerce_utc_datetime(now)
    _prune_daily_mm_records(
        bot_state,
        records_key="snow_daily_swe_gain_records",
        recent_key="snow_recent_by_station",
        now_dt=now_dt,
    )
    _prune_daily_mm_records(
        bot_state,
        records_key="precip_daily_records",
        recent_key="precip_recent_by_city",
        now_dt=now_dt,
    )

    memory = get_memory(bot_state)
    memory["shipped_tweets"] = _cap_shipped_tweets(memory.get("shipped_tweets"))

    for store_key, ttl_days in _TIER_TTLS_DAYS.items():
        _prune_tier_store(bot_state, store_key, ttl_days, now_dt)

    min_year = now_dt.year - 1
    for key in sorted(DEFAULT_STATE):
        if key.endswith("_annual_count"):
            cast(dict, bot_state)[key] = _prune_year_keyed_dict(bot_state.get(key), min_year)
    bot_state["ozone_hole_last_peak"] = _prune_year_keyed_dict(
        bot_state.get("ozone_hole_last_peak"),
        min_year,
    )
    return bot_state


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
    b: dict = cast(dict, base or {})
    n: dict = cast(dict, incoming or {})
    merged: dict = {"fires": {}, "heats": {}, "drought_snapshot": None}

    def _merge_bucket(
        b_bucket: dict[str, list[dict]], n_bucket: dict[str, list[dict]]
    ) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for key in set(list(b_bucket.keys()) + list(n_bucket.keys())):
            result[key] = _merge_synthesis_event_list(b_bucket.get(key), n_bucket.get(key))
        return result

    event_bucket_keys = (
        set(b.keys())
        | set(n.keys())
        | {"fires", "heats"}
    ) - {"drought_snapshot"}
    for bucket_key in sorted(event_bucket_keys):
        b_bucket_raw = b.get(bucket_key)
        n_bucket_raw = n.get(bucket_key)
        b_bucket = (
            cast(dict[str, list[dict]], b_bucket_raw)
            if isinstance(b_bucket_raw, dict)
            else {}
        )
        n_bucket = (
            cast(dict[str, list[dict]], n_bucket_raw)
            if isinstance(n_bucket_raw, dict)
            else {}
        )
        merged[bucket_key] = _merge_bucket(b_bucket, n_bucket)

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
    return cast(SynthesisComponents, merged)


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
        payload = json.dumps(normalized, separators=(",", ":"), default=json_default)
        if len(payload) > STATE_SIZE_WARNING_BYTES:
            warning = (
                f"[state] WARNING size {len(payload)}B approaching gist inline cliff"
            )
            print(warning)
            log_error(normalized, "state_size", warning)
            payload = json.dumps(normalized, separators=(",", ":"), default=json_default)
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            json={
                "files": {
                    STATE_FILENAME: {
                        # Minified, not indent=2: pretty-printing added ~35% size
                        # and pushed prod past the ~928 KB inline-content
                        # truncation cliff on 2026-05-13. Reads handle either form.
                        "content": payload
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


def _state_rev_value(snapshot: BotState | dict | None) -> int:
    if not isinstance(snapshot, dict):
        return 0
    try:
        return int(snapshot.get("_state_rev") or 0)
    except (TypeError, ValueError):
        return 0


def _prepare_merged_write(
    current: BotState | dict,
    normalized: BotState,
    *,
    log_conflict: bool = False,
) -> BotState:
    current_rev = _state_rev_value(current)
    incoming_rev = _state_rev_value(normalized)
    if log_conflict and current_rev != incoming_rev:
        print("[state] write conflict re-merged")
    merged = _merge_state(current, normalized)
    merged["_state_rev"] = max(current_rev, incoming_rev) + 1
    return merged


def write_state(state: BotState) -> bool:
    # Economics P0.6: fold any buffered per-call LLM usage into the state
    # about to be written. Structural (not call-site-dependent): EVERY
    # state-writing process persists its own spend; never raises; a second
    # write in the same run drains an empty buffer. Dryruns and replay
    # suites never call write_state, so their spend deliberately stays out
    # of state (Console + workflow logs cover them).
    from src.two_bot import usage_ledger as _usage_ledger

    _usage_ledger.drain_into_state(state)
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
                DB_PATH, cast(dict, _prepare_merged_write(current, normalized))
            )
        except (TypeError, ValueError):
            return False
    try:
        current = _read_gist_state(strict=True)
    except StateReadError:
        return False
    try:
        return _write_gist_state(_prepare_merged_write(current, normalized, log_conflict=True))
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
    error_class: str | None = None,
    breaker: bool = False,
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
    if error_class:
        entry["error_class"] = error_class
    if breaker:
        entry["breaker"] = True
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
    for run in sorted(runs, key=lambda row: _parse_state_timestamp(row.get("ts"))):
        ts = _format_state_timestamp(run.get("ts"))
        if _parse_state_timestamp(ts) < cutoff:
            continue
        status = _source_health_status(str(run.get("status") or "failed"))
        error = run.get("error")
        error_text = str(error) if error else None
        error_class = run.get("error_class")
        error_class_text = str(error_class) if error_class else None
        key = (ts, status, error_text, error_class_text)
        if key in seen:
            continue
        seen.add(key)
        entry: SourceHealthRun = {"ts": ts, "status": status}
        if error_text:
            entry["error"] = error_text
        if error_class_text:
            entry["error_class"] = error_class_text
        entry_writeable = cast(dict, entry)
        for metric in _SOURCE_HEALTH_METRICS:
            raw_value = run.get(metric)
            value = _nonnegative_int(raw_value)
            if value is None or value == 0:
                continue
            entry_writeable[metric] = value
        ordered.append(entry)

    ordered = ordered[-SOURCE_HEALTH_MAX_RUNS:]
    duration_values: list[int] = []
    for entry in ordered:
        status = str(entry.get("status") or "failed")
        error_text = entry.get("error")
        entry_writeable = cast(dict, entry)
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
            health["last_success_ts"] = entry.get("ts")
        elif status in {"degraded", "failed"} and error_text:
            health["last_error"] = error_text
            health["last_error_ts"] = entry.get("ts")
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
    error_class: str | None = None,
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
    if error_class is not None:
        run["error_class"] = str(error_class)
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


# ---------------------------------------------------------------------------
# MERGE_SPEC: the single source of truth for how each state key is reconciled on
# write. Defined here, after every merge helper it references. The contract test
# test_merge_spec_covers_exactly_default_state asserts set(MERGE_SPEC) ==
# set(DEFAULT_STATE), so coverage is total by construction — a new DEFAULT_STATE
# key with no strategy fails at collection instead of silently resetting on write.
# ---------------------------------------------------------------------------

MERGE_SPEC: dict[str, Callable[..., Any]] = {
    "last_hot10": _strat_take_incoming,
    "streaks": _strat_take_incoming,
    "posted_events": _strat_ordered_unique(500),
    "daily_tweet_count": _strat_dict_overlay,
    "co2_annual_count": _strat_max_by_key(0),
    "ch4_annual_count": _strat_max_by_key(0),
    "ch4_last_milestone": _merge_ch4_last_milestone,
    "nao_annual_count": _strat_max_by_key(0),
    "ao_annual_count": _strat_max_by_key(0),
    "pdo_annual_count": _strat_max_by_key(0),
    "ozone_hole_annual_count": _strat_max_by_key(0),
    "nao_last_phase": _strat_take_incoming,
    "ao_last_phase": _strat_take_incoming,
    "pdo_last_phase": _strat_take_incoming,
    "ozone_hole_last_peak": _merge_ozone_hole_last_peak,
    "drafts": _merge_drafts,
    "run_history": _merge_run_history,
    "errors": _merge_errors,
    "suppressions": _merge_suppressions,
    "memory": _merge_memory,
    "city_all_time_max": _strat_take_incoming,
    "city_all_time_min": _strat_take_incoming,
    "city_monthly_max": _strat_take_incoming,
    "city_monthly_min": _strat_take_incoming,
    "record_streaks": _strat_take_incoming,
    "source_health": _merge_source_health,
    "credential_expiry": _strat_take_incoming,
    "last_good_readings": _merge_last_good,
    "publish_ledger": _strat_dict_overlay,
    "tweet_metrics": _merge_tweet_metrics,
    "llm_usage": _merge_llm_usage,
    "writer_negative_cache": _merge_writer_negative_cache,
    "_state_rev": _strat_max_int,
    "ocean_sst_streak": _strat_take_incoming,
    "ice_mass_max_loss": _strat_reduce_by_key(_keep_min_gt),
    "ice_mass_last_milestone": _strat_reduce_by_key(_present_min),
    "ice_mass_last_seen": _strat_max_by_key(""),
    "ice_annual_count": _strat_max_by_key(0),
    "precip_daily_records": _merge_max_mm_records,
    "precip_recent_by_city": _merge_recent_mm_rows,
    "snow_daily_swe_gain_records": _merge_max_mm_records,
    "snow_recent_by_station": _merge_recent_mm_rows,
    "snow_annual_count": _strat_max_by_key(0),
    "seasonal_snow_records": _merge_max_mm_records,
    "fire_complex_tiers": _strat_max_by_key(-1),
    "coral_dhw_last_tier": _strat_max_by_key(0),
    "coral_dhw_annual_count": _strat_max_by_key(0),
    "air_quality_pm25_tiers": _strat_reduce_by_key(_pick_newer_city_tier),
    "air_quality_dust_tiers": _strat_reduce_by_key(_pick_newer_city_tier),
    "data_source_failures": _merge_data_source_failures,
    "sst_anom_last_tier": _strat_max_by_key(0),
    "sst_anom_annual_count": _strat_max_by_key(0),
    "reganom_last_fired": _strat_max_by_key(""),
    "cyclone_tiers": _strat_max_by_key(-1),
    "cyclone_wind_history": _merge_cyclone_wind_history,
    "cyclone_annual_count": _strat_max_by_key(0),
    "cyclone_land_threat_pairs": _merge_land_threat_pairs,
    # event_id -> date; key-union so a cluster fired by either concurrent run
    # stays deduped (max on the shared date value is a no-op).
    "heat_records_cluster_fired": _strat_max_by_key(""),
    "flood_activation_tiers": _strat_reduce_by_key(_max_flood_severity),
    "tier_touch_ts": _strat_max_by_key(""),
    "flood_annual_count": _strat_max_by_key(0),
    "fire_footprint_last_run": _merge_fire_footprint_last_run,
    "synthesis_components": _merge_synthesis_components,
    "synthesis_cooldown": _merge_synthesis_cooldown,
    "coverage_log": _merge_coverage_log,
    "news_events": _merge_news_events,
    # Same contract as coverage_log: dedup on event_id, last writer wins.
    "candidates_log": _merge_coverage_log,
}


NEWS_WINDOW_DAYS = 7
CANDIDATES_WINDOW_DAYS = 7


def record_news_events(
    state: BotState,
    events: list[dict],
    *,
    now: datetime | None = None,
) -> None:
    """Replace-and-prune the rolling news_events window. Never raises."""
    try:
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(days=NEWS_WINDOW_DAYS)).date().isoformat()
        # A window_end may not sit meaningfully in the future (tomorrow at most,
        # for timezone slack) — a malformed/far-future value would otherwise
        # make an event immortal against the prune (codex P2).
        horizon = (now + timedelta(days=1)).date().isoformat()

        def _in_window(ev: dict) -> bool:
            end = str(ev.get("window_end") or "")
            return cutoff <= end <= horizon

        stamped = [
            {**ev, "retrieved_at": now.isoformat().replace("+00:00", "Z")}
            for ev in events
            if isinstance(ev, dict) and _in_window(ev)
        ]
        existing = [
            e for e in (state.get("news_events") or [])
            if isinstance(e, dict) and _in_window(e)
        ]
        state["news_events"] = _merge_news_events(existing, stamped)
    except Exception as exc:  # noqa: BLE001 — recording must never break a cycle
        print(f"[state] record_news_events failed: {exc}")


def record_candidate_observation(
    state: BotState,
    *,
    event_id: str,
    category: str,
    legacy_type: str,
    city: str,
    where: str,
    now: datetime | None = None,
) -> None:
    """Append one enqueued-candidate record; dedup on event_id; prune window.

    Mirrors record_coverage_observation's contract: never raises.
    """
    try:
        now = now or datetime.now(UTC)
        log = state.setdefault("candidates_log", [])
        log[:] = [r for r in log if r.get("event_id") != event_id]
        log.append({
            "event_id": event_id,
            "category": category or "",
            "type": legacy_type or "",
            "city": city or "",
            "where": where or "",
            "date": now.date().isoformat(),
        })
        cutoff = (now - timedelta(days=CANDIDATES_WINDOW_DAYS)).date().isoformat()
        state["candidates_log"] = [
            r for r in log if str(r.get("date") or "") >= cutoff
        ]
    except Exception as exc:  # noqa: BLE001 — recording must never break a cycle
        print(f"[state] record_candidate_observation failed: {exc}")


def record_coverage_observation(
    state: BotState,
    *,
    cls: str,
    event_id: str,
    country: str | None,
    when: "str | date | None",
    now: datetime | None = None,
) -> None:
    """Append one surfaced-event geography record; dedup on event_id; prune window.

    Never raises — bad inputs (None country, unparseable date) degrade gracefully.
    Consumes src.coverage.resolve_continent to fill the continent field.
    """
    try:
        from src.coverage import resolve_continent

        now = now or datetime.now(UTC)
        if isinstance(when, date) and not isinstance(when, datetime):
            date_str = when.isoformat()
        elif isinstance(when, str) and when:
            date_str = when[:10]
        else:
            date_str = now.date().isoformat()
        log = state.setdefault("coverage_log", [])
        log[:] = [r for r in log if r.get("event_id") != event_id]
        log.append(
            {
                "cls": cls,
                "event_id": event_id,
                "country": country or "",
                "continent": resolve_continent(country),
                "date": date_str,
            }
        )
        cutoff = (now - timedelta(days=COVERAGE_WINDOW_DAYS)).date().isoformat()
        state["coverage_log"] = [r for r in log if str(r.get("date") or "") >= cutoff]
    except Exception:
        pass


def update_fire_complex_tier(state: BotState, complex_id: str, tier: int) -> BotState:
    """Record the highest tier we've tweeted for a fire complex.

    Takes max so concurrent cron runs don't lose a tier bump.
    """
    tiers = state.setdefault("fire_complex_tiers", {})
    current = int(tiers.get(complex_id, -1))
    if tier > current:
        tiers[complex_id] = int(tier)
        _touch_tier(state, "fire_complex_tiers", complex_id)
    return state


def record_heat_records_cluster(state: BotState, event_id: str, when: str) -> BotState:
    """Record that a heat records-cluster (#414) has drafted, for per-cluster/date
    dedup. ``event_id`` is ``heat_records_cluster_{date}_{signature}``; ``when`` is
    the signal date (stored as the value, informational). Called only from
    on_draft_success — a killed draft leaves it unrecorded and retries next cycle.
    TTL-pruned via the tier sidecar (see _TIER_TTLS_DAYS)."""
    fired = state.setdefault("heat_records_cluster_fired", {})
    if event_id not in fired:
        fired[event_id] = when
        _touch_tier(state, "heat_records_cluster_fired", event_id)
    return state


def record_land_threat_pair(state: BotState, tracking_key: str, landmass_slug: str) -> BotState:
    """Record that a (storm, landmass) land-threat pair has drafted (#375).

    Sorted-deduped list per storm so concurrent runs merge losslessly
    (see _merge_land_threat_pairs). Called only from on_draft_success —
    a killed draft leaves the pair unrecorded and retries next advisory.
    """
    pairs = state.setdefault("cyclone_land_threat_pairs", {})
    slugs = set(pairs.get(tracking_key, []))
    if landmass_slug not in slugs:
        slugs.add(landmass_slug)
        pairs[tracking_key] = sorted(slugs)
        _touch_tier(state, "cyclone_land_threat_pairs", tracking_key)
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
        _touch_tier(state, "cyclone_tiers", storm_id)
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
        _touch_tier(state, "flood_activation_tiers", activation_id)
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
    prune_state(state, datetime.now(UTC))
    return state


_SYNTHESIS_COMPONENT_BUCKET_BY_KIND = {
    "fire": "fires",
    "heat": "heats",
    "coral": "corals",
    "sst_anomaly": "sst_anomalies",
}


def _synthesis_bucket_key(kind: str) -> str:
    return _SYNTHESIS_COMPONENT_BUCKET_BY_KIND.get(kind, "heats")


def record_synthesis_component(
    state: BotState,
    *,
    kind: str,
    region: str,
    event_id: str,
    metadata: dict | None = None,
    timestamp: str | None = None,
) -> BotState:
    bucket_key = _synthesis_bucket_key(kind)
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
    bucket_key = _synthesis_bucket_key(kind)
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
    event_bucket_keys = [
        key
        for key, value in components.items()
        if key != "drought_snapshot" and isinstance(value, dict)
    ]
    for bucket_key in event_bucket_keys:
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
