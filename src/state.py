"""State management via pluggable durable backends."""

from copy import deepcopy
import json
import os
from datetime import UTC, date, datetime, timedelta

import requests

from src.storage import sqlite_store
from src.two_bot.json_utils import json_default

GIST_ID = os.environ.get("GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
STATE_FILENAME = "state.json"
STATE_BACKEND = os.environ.get("THEHEAT_STATE_BACKEND", "").lower()
DB_PATH = os.environ.get("THEHEAT_DB_PATH", "")

DEFAULT_STATE = {
    "last_hot10": {"date": None, "cities": []},
    "streaks": {},
    "posted_events": [],
    "daily_tweet_count": {},
    # Running count of CO2 tweets per calendar year, keyed by "YYYY".
    # Enforced by _co2_annual_cap_reached() in main.py (cap: 12/year).
    "co2_annual_count": {},
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
    # Per-complex tier dedup for fire footprint (GWIS). Integer index into
    # TIERS_HECTARES. Prevents re-tweeting the same fire at every update;
    # only tier upgrades trigger a new draft.
    "fire_complex_tiers": {},
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


def _fresh_state() -> dict:
    """Return an isolated copy of the default state."""
    return deepcopy(DEFAULT_STATE)


def get_memory(state: dict) -> dict:
    """Return state memory, backfilled with the current first-build schema."""

    default_memory = deepcopy(DEFAULT_STATE["memory"])
    current = state.setdefault("memory", {})
    if not isinstance(current, dict):
        current = {}
        state["memory"] = current
    for key, value in default_memory.items():
        current.setdefault(key, value)
    return current


def set_memory(state: dict, memory: dict) -> dict:
    """Replace state memory after backfilling the first-build schema."""

    state["memory"] = deepcopy(memory) if isinstance(memory, dict) else {}
    get_memory(state)
    return state


def _normalize_state(state: dict | None) -> dict:
    """Ensure all expected top-level keys exist in the state payload."""
    normalized = _fresh_state()
    if isinstance(state, dict):
        normalized.update(state)
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
    parsed = datetime.fromtimestamp(0, UTC)
    if not value:
        return parsed
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return parsed


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
    }.get(draft.get("status"), 0)


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


def _merge_drafts(current: list[dict], incoming: list[dict], max_items: int = 200) -> list[dict]:
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
    if len(ordered) > max_items:
        ordered = ordered[-max_items:]
    return ordered


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


def _merge_memory(current: dict | None, incoming: dict | None) -> dict:
    base = deepcopy(DEFAULT_STATE["memory"])
    if isinstance(current, dict):
        base.update(deepcopy(current))
    next_memory = deepcopy(DEFAULT_STATE["memory"])
    if isinstance(incoming, dict):
        next_memory.update(deepcopy(incoming))

    merged = deepcopy(DEFAULT_STATE["memory"])
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


def _merge_state(current: dict | None, incoming: dict | None) -> dict:
    base = _normalize_state(current)
    next_state = _normalize_state(incoming)
    merged = _fresh_state()
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
        a = base.get("ice_mass_max_loss", {}).get(region)
        b = next_state.get("ice_mass_max_loss", {}).get(region)
        if a is None:
            merged["ice_mass_max_loss"][region] = deepcopy(b)
        elif b is None:
            merged["ice_mass_max_loss"][region] = deepcopy(a)
        else:
            merged["ice_mass_max_loss"][region] = deepcopy(
                a if a.get("gt", 0.0) <= b.get("gt", 0.0) else b
            )
    merged["ice_mass_last_milestone"] = {}
    for region in set(
        list(base.get("ice_mass_last_milestone", {}).keys())
        + list(next_state.get("ice_mass_last_milestone", {}).keys())
    ):
        a = base.get("ice_mass_last_milestone", {}).get(region)
        b = next_state.get("ice_mass_last_milestone", {}).get(region)
        if a is None:
            merged["ice_mass_last_milestone"][region] = b
        elif b is None:
            merged["ice_mass_last_milestone"][region] = a
        else:
            merged["ice_mass_last_milestone"][region] = min(a, b)
    merged["ice_mass_last_seen"] = {}
    for region in set(
        list(base.get("ice_mass_last_seen", {}).keys())
        + list(next_state.get("ice_mass_last_seen", {}).keys())
    ):
        a = base.get("ice_mass_last_seen", {}).get(region, "")
        b = next_state.get("ice_mass_last_seen", {}).get(region, "")
        merged["ice_mass_last_seen"][region] = a if a >= b else b
    merged["ice_annual_count"] = {}
    for year in set(
        list(base.get("ice_annual_count", {}).keys())
        + list(next_state.get("ice_annual_count", {}).keys())
    ):
        merged["ice_annual_count"][year] = max(
            base.get("ice_annual_count", {}).get(year, 0),
            next_state.get("ice_annual_count", {}).get(year, 0),
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
    base: dict | None, incoming: dict | None
) -> dict:
    """Merge synthesis_components preserving cross-run evidence.

    - ``fires`` and ``heats`` are per-state lists of events. Dedup by
      event_id and union; keep the later ``at`` on collision so a stale
      concurrent run doesn't clobber a newer one.
    - ``drought_snapshot`` is a single dict refreshed on each USDM poll.
      Take the one with the later ``updated_at``.
    """
    b = base or {}
    n = incoming or {}
    merged: dict = {"fires": {}, "heats": {}, "drought_snapshot": None}

    for bucket in ("fires", "heats"):
        b_bucket = b.get(bucket) or {}
        n_bucket = n.get(bucket) or {}
        merged_bucket: dict[str, list[dict]] = {}
        for key in set(list(b_bucket.keys()) + list(n_bucket.keys())):
            merged_bucket[key] = _merge_synthesis_event_list(
                b_bucket.get(key), n_bucket.get(key)
            )
        merged[bucket] = merged_bucket

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


def _merge_synthesis_cooldown(
    base: dict | None, incoming: dict | None
) -> dict:
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
            rule_merged[region] = a_ts if a_ts >= c_ts else c_ts
        merged[rule] = rule_merged
    return merged


def _read_gist_state(*, strict: bool = False) -> dict:
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
        content = gist["files"][STATE_FILENAME]["content"]
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


def _write_gist_state(state: dict) -> bool:
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


def read_state() -> dict:
    backend = _configured_backend()
    if backend == "sqlite":
        if not DB_PATH:
            raise StateReadError("SQLite backend selected but THEHEAT_DB_PATH is not set")
        try:
            if sqlite_store.is_empty(DB_PATH) and GIST_ID and GITHUB_TOKEN:
                gist_state = _read_gist_state(strict=True)
                sqlite_store.write_state(DB_PATH, gist_state)
            return _normalize_state(sqlite_store.read_state(DB_PATH, DEFAULT_STATE))
        except Exception as exc:
            raise StateReadError(f"Failed to read SQLite state store: {exc}") from exc
    return _read_gist_state(strict=True)


def write_state(state: dict) -> bool:
    normalized = _normalize_state(state)
    if _configured_backend() == "sqlite":
        if not DB_PATH:
            return False
        try:
            current = sqlite_store.read_state(DB_PATH, DEFAULT_STATE)
        except Exception:
            return False
        try:
            return sqlite_store.write_state(DB_PATH, _merge_state(current, normalized))
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


def is_duplicate(state: dict, event_id: str) -> bool:
    return event_id in state.get("posted_events", [])


def record_event(state: dict, event_id: str) -> dict:
    state.setdefault("posted_events", []).append(event_id)
    # Keep only last 500 events to prevent unbounded growth
    if len(state["posted_events"]) > 500:
        state["posted_events"] = state["posted_events"][-500:]
    return state


def get_daily_count(state: dict) -> int:
    today = date.today().isoformat()
    return state.get("daily_tweet_count", {}).get(today, 0)


def increment_daily_count(state: dict) -> dict:
    today = date.today().isoformat()
    counts = state.setdefault("daily_tweet_count", {})
    counts[today] = counts.get(today, 0) + 1
    # Clean up old days
    for d in list(counts.keys()):
        if d != today:
            del counts[d]
    return state


def check_daily_cap(state: dict, cap: int = 10) -> bool:
    return get_daily_count(state) < cap


def update_record_streak(
    state: dict,
    city: str,
    today_temp_c: float,
    event_date: date | None = None,
) -> dict:
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


def get_record_streak(state: dict, city: str) -> dict | None:
    """Return current streak info for a city, or None if no active streak."""
    streaks = state.get("record_streaks", {})
    return streaks.get(city)


def prune_stale_record_streaks(state: dict, max_gap_days: int = 2) -> dict:
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


def update_ocean_sst_streak(state: dict, streak: dict) -> dict:
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


def update_streaks(state: dict, hot10_cities: list[str]) -> dict:
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


def log_error(state: dict, source: str, msg: str) -> dict:
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
        "drafted": drafted,
        "error": error,
        "note": note,
    }
    if details:
        entry["details"] = details
    run.setdefault("sources", []).append(entry)
    return run


def update_fire_complex_tier(state: dict, complex_id: str, tier: int) -> dict:
    """Record the highest tier we've tweeted for a fire complex.

    Takes max so concurrent cron runs don't lose a tier bump.
    """
    tiers = state.setdefault("fire_complex_tiers", {})
    current = int(tiers.get(complex_id, -1))
    if tier > current:
        tiers[complex_id] = int(tier)
    return state


def finalize_run(state: dict, run: dict, status: str = "success", max_runs: int = 20) -> dict:
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
    state: dict,
    *,
    kind: str,
    region: str,
    event_id: str,
    metadata: dict | None = None,
    timestamp: str | None = None,
) -> dict:
    bucket_key = "fires" if kind == "fire" else "heats"
    components = state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
    bucket = components.setdefault(bucket_key, {}).setdefault(region, [])
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
    state: dict, *, kind: str, region: str, since: str | None = None,
) -> list[dict]:
    bucket_key = "fires" if kind == "fire" else "heats"
    components = state.get("synthesis_components") or {}
    entries = (components.get(bucket_key) or {}).get(region) or []
    if since is None:
        return list(entries)
    return [e for e in entries if e.get("at", "") >= since]


def record_synthesis_drought_snapshot(state: dict, updates) -> dict:
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


def get_synthesis_drought_snapshot(state: dict) -> dict | None:
    components = state.get("synthesis_components") or {}
    return components.get("drought_snapshot")


def is_synthesis_on_cooldown(
    state: dict, rule_name: str, region: str, days: int = 14,
) -> bool:
    cooldowns = (state.get("synthesis_cooldown") or {}).get(rule_name) or {}
    last_fired = cooldowns.get(region)
    if not last_fired:
        return False
    try:
        last_dt = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return (datetime.now(UTC) - last_dt) < timedelta(days=days)


def record_synthesis_fired(
    state: dict, rule_name: str, region: str, timestamp: str | None = None,
) -> dict:
    cooldowns = state.setdefault("synthesis_cooldown", {})
    per_rule = cooldowns.setdefault(rule_name, {})
    per_rule[region] = (
        timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    return state


def prune_stale_synthesis_components(state: dict, ttl_days: int = 14) -> dict:
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat().replace("+00:00", "Z")
    components = state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
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


def increment_data_source_failure(state: dict, source: str) -> int:
    """Increment and return the consecutive failure count for ``source``."""
    failures = state.setdefault("data_source_failures", {})
    failures[source] = failures.get(source, 0) + 1
    return failures[source]


def reset_data_source_failure(state: dict, source: str) -> None:
    """Reset the consecutive failure count for ``source`` to 0 on success."""
    state.setdefault("data_source_failures", {})[source] = 0


def get_data_source_failure_count(state: dict, source: str) -> int:
    """Return current consecutive failure count for ``source`` (0 if unknown)."""
    return state.get("data_source_failures", {}).get(source, 0)
