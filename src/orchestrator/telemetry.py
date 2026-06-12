"""Source-run telemetry helpers for orchestrator flows."""

from __future__ import annotations

import time

from src import state
from src.data.error_class import classify_error_class
from src.state_schema import BotState


def _record_source_run(
    current_run: dict | None,
    bot_state: BotState | None,
    source: str,
    started_at: float,
    *,
    status: str,
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
) -> None:
    """Track a source result when run telemetry is enabled."""
    duration_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
    if bot_state is not None:
        health_error = error
        if not health_error and status in {"failed", "degraded", "partial_failure"}:
            health_error = note
        state.record_source_health(
            bot_state,
            source,
            status,
            health_error,
            error_class=error_class or classify_error_class(error),
            metrics={
                "duration_ms": duration_ms,
                "observed": observed,
                "promoted": promoted,
                "triaged_in": triaged_in,
                "triaged_out": triaged_out,
                "writer_attempted": writer_attempted,
                "drafted": drafted,
            },
        )

    if current_run is None:
        return

    state.add_source_run(
        current_run,
        source=source,
        status=status,
        duration_ms=duration_ms,
        observed=observed,
        promoted=promoted,
        triaged_in=triaged_in,
        triaged_out=triaged_out,
        writer_attempted=writer_attempted,
        drafted=drafted,
        error=error,
        note=note,
        details=details,
        error_class=error_class,
        breaker=breaker,
    )


def _bump_source_field_in_run(
    current_run: dict | None,
    source: str,
    field: str,
    amount: int = 1,
) -> None:
    """Increment a numeric counter on an existing source run entry.

    Source runners write their telemetry entry (via ``_record_source_run``)
    with ``drafted=0`` because at that point their candidates are still in
    the triage queue — the writer hasn't run yet. When the drain step
    successfully calls ``_try_two_bot_draft()`` for a survivor, it calls
    this helper to credit the originating source.

    Finds the *last* entry whose ``source`` key matches (the most recent
    record for that source in this cycle). If no matching entry is found,
    no-ops silently — the spec § 9 says the per-source counter is a
    best-effort telemetry enhancement, not a hard correctness gate.
    """
    if current_run is None:
        return
    sources_list: list[dict] = current_run.get("sources") or []
    # Walk in reverse to find the most recent entry for this source
    for entry in reversed(sources_list):
        if entry.get("source") == source:
            entry[field] = entry.get(field, 0) + amount
            return


def _bump_run_drafted(current_run: dict | None, source: str, amount: int = 1) -> None:
    """Increment the ``drafted`` counter on an existing source run entry."""
    _bump_source_field_in_run(current_run, source, "drafted", amount)


__all__ = [
    "_bump_run_drafted",
    "_bump_source_field_in_run",
    "_record_source_run",
]
