"""Freshness guardrails for source parsers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime

from src.data.source_status import SourceFetchError


def parse_freshness_date(value: date | datetime | int | float | str | None) -> date | None:
    """Best-effort parse for upstream payload timestamps."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        try:
            seconds = float(value) / 1000 if abs(float(value)) > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds, tz=UTC).date()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            pass
        try:
            return parsedate_to_datetime(raw).date()
        except (TypeError, ValueError, IndexError, AttributeError):
            return None
    return None


def newest_freshness_date(
    values: list[date | datetime | int | float | str | None],
) -> date | None:
    dates = [parsed for value in values if (parsed := parse_freshness_date(value))]
    return max(dates) if dates else None


def _coerce_date(value: date | datetime | str) -> date:
    parsed = parse_freshness_date(value)
    if parsed is not None:
        return parsed
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raise SourceFetchError(f"freshness check failed: invalid date {value!r}")
    raise SourceFetchError(
        f"freshness check failed: unsupported date type {type(value).__name__}"
    )


def assert_freshness(
    data_date: date | datetime | str,
    source_name: str,
    max_age_days: int,
    *,
    today: date | None = None,
) -> None:
    """Raise when a source's latest data point is older than expected."""
    observed_date = _coerce_date(data_date)
    current_date = today or date.today()
    age_days = (current_date - observed_date).days
    if age_days > max_age_days:
        raise SourceFetchError(
            f"{source_name} stale data: latest data point is {observed_date.isoformat()} "
            f"({age_days} days old; max {max_age_days})"
        )
