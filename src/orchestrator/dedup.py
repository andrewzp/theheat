"""Draft deduplication helpers."""

from __future__ import annotations

from datetime import timedelta

from src.orchestrator.common import _parse_iso_utc, _utc_now


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


__all__ = [
    "_posted_city_within_days",
    "_same_day_already_posted",
    "_same_day_pending_collision",
]
