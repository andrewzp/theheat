"""Draft deduplication helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from src.data.places import draft_place_id

from src.orchestrator.common import _parse_iso_utc, _utc_now


def _same_place(draft: dict, city: str, place_id: str, resolved_place_id: str | None) -> bool:
    if not place_id and draft.get("city") != city:
        return False
    existing = resolved_place_id if resolved_place_id is not None else draft_place_id(draft)
    return existing == place_id


def _same_day_already_posted(drafts: list[dict], city: str, tweet_date: str, *, place_id: str = "", resolved_place_ids: tuple[str, ...] | None = None) -> bool:
    """True if a posted draft exists for this (city, tweet_date) tuple."""
    if not city or not tweet_date:
        return False
    for i, d in enumerate(drafts):
        if (
            _same_place(d, city, place_id, resolved_place_ids[i] if resolved_place_ids is not None else None)
            and d.get("tweet_date") == tweet_date
            and d.get("status") == "posted"
        ):
            return True
    return False


def _same_day_pending_collision(
    drafts: list[dict], city: str, tweet_date: str, *, place_id: str = "", resolved_place_ids: tuple[str, ...] | None = None
) -> tuple[int, dict] | None:
    """Return (index, draft) of a pending draft matching (city, tweet_date), if any."""
    if not city or not tweet_date:
        return None
    for i, d in enumerate(drafts):
        if (
            _same_place(d, city, place_id, resolved_place_ids[i] if resolved_place_ids is not None else None)
            and d.get("tweet_date") == tweet_date
            and d.get("status") == "pending"
        ):
            return i, d
    return None


def _posted_city_within_days(drafts: list[dict], city: str, days: int, *, place_id: str = "", at: datetime | None = None, resolved_place_ids: tuple[str, ...] | None = None) -> bool:
    """True if any posted draft for this city exists within the last N days."""
    if not city:
        return False
    if at is not None and (at.tzinfo is None or at.utcoffset() != timedelta(0)):
        raise ValueError("aware_utc_clock_required")
    cutoff = (at if at is not None else _utc_now()) - timedelta(days=days)
    for i, d in enumerate(drafts):
        if not _same_place(d, city, place_id, resolved_place_ids[i] if resolved_place_ids is not None else None):
            continue
        if d.get("status") != "posted":
            continue
        ts = _parse_iso_utc(
            d.get("posted_at") or d.get("updated_at") or d.get("created_at")
        )
        if ts and ts >= cutoff:
            return True
    return False


__all__ = [
    "_posted_city_within_days",
    "_same_day_already_posted",
    "_same_day_pending_collision",
]
