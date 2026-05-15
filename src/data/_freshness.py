"""Freshness guardrails for source parsers."""

from __future__ import annotations

from datetime import date, datetime

from src.data.source_status import SourceFetchError


def _coerce_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise SourceFetchError(f"freshness check failed: invalid date {value!r}") from exc
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
