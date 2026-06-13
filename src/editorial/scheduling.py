"""Editorial scheduling helpers."""

from __future__ import annotations

from datetime import UTC, datetime, time


_DEAD_ZONE_START = time(5, 0)
_DEAD_ZONE_END = time(11, 0)
_DEFERRED_HOUR = 12
_DEFERRED_MINUTE = 30


def defer_to_engagement_window(ts: datetime) -> datetime:
    """Move dead-zone UTC timestamps to the same-day engagement window."""
    if ts.tzinfo is None:
        ts_utc = ts.replace(tzinfo=UTC)
    else:
        ts_utc = ts.astimezone(UTC)
    if _DEAD_ZONE_START <= ts_utc.time() < _DEAD_ZONE_END:
        return ts_utc.replace(
            hour=_DEFERRED_HOUR,
            minute=_DEFERRED_MINUTE,
            second=0,
            microsecond=0,
        )
    return ts_utc
