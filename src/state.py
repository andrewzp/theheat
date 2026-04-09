"""State management via pluggable durable backends."""

from copy import deepcopy
import json
import os
from datetime import UTC, date, datetime

import requests

from src.storage import sqlite_store

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
    "pending_confirmations": [],
    "drafts": [],
    "run_history": [],
    "errors": [],
}


class StateReadError(RuntimeError):
    """Raised when a configured durable backend cannot be read safely."""


def _fresh_state() -> dict:
    """Return an isolated copy of the default state."""
    return deepcopy(DEFAULT_STATE)


def _normalize_state(state: dict | None) -> dict:
    """Ensure all expected top-level keys exist in the state payload."""
    normalized = _fresh_state()
    if isinstance(state, dict):
        normalized.update(state)
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
    merged["pending_confirmations"] = deepcopy(next_state.get("pending_confirmations", []))
    merged["drafts"] = _merge_drafts(base.get("drafts", []), next_state.get("drafts", []))
    merged["run_history"] = _merge_run_history(base.get("run_history", []), next_state.get("run_history", []))
    merged["errors"] = _merge_errors(base.get("errors", []), next_state.get("errors", []))
    return merged


def _read_gist_state() -> dict:
    if not GIST_ID or not GITHUB_TOKEN:
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
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        return _fresh_state()


def _write_gist_state(state: dict) -> bool:
    if not GIST_ID or not GITHUB_TOKEN:
        return False

    try:
        normalized = _normalize_state(state)
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            json={"files": {STATE_FILENAME: {"content": json.dumps(normalized, indent=2)}}},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException:
        return False


def read_state() -> dict:
    backend = _configured_backend()
    if backend == "sqlite":
        if not DB_PATH:
            raise StateReadError("SQLite backend selected but THEHEAT_DB_PATH is not set")
        try:
            if sqlite_store.is_empty(DB_PATH) and GIST_ID and GITHUB_TOKEN:
                gist_state = _read_gist_state()
                sqlite_store.write_state(DB_PATH, gist_state)
            return _normalize_state(sqlite_store.read_state(DB_PATH, DEFAULT_STATE))
        except Exception as exc:
            raise StateReadError(f"Failed to read SQLite state store: {exc}") from exc
    return _read_gist_state()


def write_state(state: dict) -> bool:
    normalized = _normalize_state(state)
    if _configured_backend() == "sqlite":
        if not DB_PATH:
            return False
        try:
            current = sqlite_store.read_state(DB_PATH, DEFAULT_STATE)
        except Exception:
            return False
        return sqlite_store.write_state(DB_PATH, _merge_state(current, normalized))
    return _write_gist_state(_merge_state(_read_gist_state(), normalized))


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


def add_pending_confirmation(state: dict, event: dict) -> dict:
    """Add a record detection to *pending_confirmations* for later NOAA check.

    *event* should contain at minimum ``event_id``, ``detected``, ``city``,
    and ``country``.  Duplicate ``event_id`` values are silently ignored.
    """
    pending = state.setdefault("pending_confirmations", [])
    if any(p.get("event_id") == event.get("event_id") for p in pending):
        return state
    pending.append(event)
    return state


def get_expired_confirmations(state: dict, min_hours: int = 24) -> list[dict]:
    """Return pending confirmations whose ``detected`` date is at least
    *min_hours* ago.

    Because Open-Meteo records are detected once per daily run the smallest
    resolution we track is full days (``detected`` stores an ISO date, not a
    timestamp).  We treat each confirmation as ready once at least
    ``min_hours // 24`` full calendar days have elapsed since detection.
    """
    min_days = max(min_hours // 24, 1)
    today = date.today()
    expired = []
    for pending in state.get("pending_confirmations", []):
        detected_str = pending.get("detected")
        if not detected_str:
            continue
        try:
            detected_date = date.fromisoformat(detected_str)
        except (ValueError, TypeError):
            continue
        if (today - detected_date).days >= min_days:
            expired.append(pending)
    return expired


def remove_pending_confirmation(state: dict, event_id: str) -> dict:
    """Remove a confirmation from *pending_confirmations* by ``event_id``."""
    state["pending_confirmations"] = [
        p for p in state.get("pending_confirmations", [])
        if p.get("event_id") != event_id
    ]
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
) -> dict:
    """Append a source-level result to an in-progress run record."""
    run.setdefault("sources", []).append({
        "source": source,
        "status": status,
        "duration_ms": duration_ms,
        "observed": observed,
        "promoted": promoted,
        "drafted": drafted,
        "error": error,
        "note": note,
    })
    return run


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
