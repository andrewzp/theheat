"""Source-day fire cell IDs and conservative, read-only legacy history guards.

A daily rounded coordinate cell is not a physical incident or unique overpass.
The legacy window holds possible duplicates; it does not adjudicate old records.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
import math
import re
from typing import Any

from src.data.fire_source_contract import parse_minute

_NEW_ID = re.compile(r"fire_(-?[0-9]+\.[0-9]{2})_(-?[0-9]+\.[0-9]{2})_([0-9]{4}-[0-9]{2}-[0-9]{2})_utc1")


def source_event_id(lat: float, lon: float, acquired_at: str) -> str:
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or not math.isfinite(lat) or not math.isfinite(lon)):
        raise ValueError("Invalid fire identity coordinates")
    day = parse_minute(acquired_at).date().isoformat()
    return f"fire_{lat:.2f}_{lon:.2f}_{day}_utc1"


def legacy_aliases(event_id: Any) -> frozenset[str]:
    """Return old processing-day IDs for source day D-1 through D+3 inclusive."""
    if type(event_id) is not str or len(event_id) > 100:
        raise ValueError("Invalid source-day fire identity")
    match = _NEW_ID.fullmatch(event_id)
    if match is None:
        raise ValueError("Invalid source-day fire identity")
    lat, lon = float(match[1]), float(match[2])
    day = date.fromisoformat(match[3])
    if source_event_id(lat, lon, day.isoformat() + "T00:00:00Z") != event_id:
        raise ValueError("Noncanonical source-day fire identity")
    try:
        return frozenset(f"fire_{match[1]}_{match[2]}_{(day + timedelta(days=offset)).isoformat()}"
                         for offset in range(-1, 4))
    except OverflowError:
        raise ValueError("Fire history window outside supported calendar") from None


def _explicitly_not_sent(row: Any) -> bool:
    # Any confirmed, unknown, conflicting, malformed or excessive retained
    # attempt holds. A literal not_sent result alone is not a publication.
    pending = [row]
    seen: set[int] = set()
    while pending:
        item = pending.pop()
        if type(item) is not dict or id(item) in seen or len(seen) >= 256:
            return False
        seen.add(id(item))
        if item.get("phase") != "not_sent" or item.get("preserved_evidence_only"):
            return False
        if item.get("tweet_id") is not None and item.get("tweet_id") != "":
            return False
        conflicts = item.get("attempt_conflicts", [])
        if type(conflicts) is not list or len(conflicts) > 256:
            return False
        pending.extend(conflicts)
    return True


def legacy_history_reason(state: Mapping[str, Any], event_id: Any) -> str | None:
    """Read all retained legacy statuses before writing, saving or sending.

    New namespace IDs never become aliases of each other. Existing exact-ID
    checks remain the caller's responsibility. No history is rewritten here.
    """
    if type(event_id) is not str or not event_id.startswith("fire_") or not event_id.endswith("_utc1"):
        return None
    try:
        aliases = legacy_aliases(event_id)
    except (ValueError, OverflowError):
        return "fire_identity_invalid"
    if not isinstance(state, Mapping):
        return "legacy_fire_history_unresolved"
    posted = state.get("posted_events", [])
    drafts = state.get("drafts", [])
    ledger = state.get("publish_ledger", {})
    if type(posted) is not list or type(drafts) is not list or type(ledger) is not dict:
        return "legacy_fire_history_unresolved"
    for recorded in posted:
        if type(recorded) is not str:
            return "legacy_fire_history_unresolved"
        if recorded in aliases:
            return "legacy_fire_already_posted"
    for draft in drafts:
        if type(draft) is not dict:
            return "legacy_fire_history_unresolved"
        identity = draft.get("event_id")
        if identity is not None and type(identity) is not str:
            return "legacy_fire_history_unresolved"
        if identity in aliases:
            # Rejected/expired/unknown drafts hold too. Changing the day must
            # not re-purchase a prior attempt merely because it was never posted.
            return "legacy_fire_retained_draft"
    for alias in aliases:
        if alias in ledger and not _explicitly_not_sent(ledger[alias]):
            return "legacy_fire_history_unresolved"
    return None
