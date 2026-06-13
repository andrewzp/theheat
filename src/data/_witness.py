"""Source-redundancy witness helpers (SOURCE-REDUNDANCY LANE, R-00).

A *witness* is a fallback feed that fires only when a primary source fetch
fails — covering the outage subset of no-draft days. The mechanics here are
deliberately tiny and shared by every per-source chain (R-02..R-09):

- :func:`with_witness` orchestrates the fallback: it returns the primary's
  result untouched on success, and only on a *transport/parse* failure
  (``SourceFetchError`` / ``requests.RequestException`` — never
  ``SourceSkipped``, which means a credential was intentionally absent) does it
  call the witness. The public fetch function keeps its return shape; provenance
  rides on the returned event objects.
- :func:`tag_source_leg` stamps each returned event's ``source_leg`` with the
  leg that served (works for frozen and mutable dataclasses).
- :func:`source_leg_of` / :func:`degraded_via` turn that provenance into the
  runner's degraded-telemetry note, so the sentinel and dashboard report a
  backup-served primary honestly instead of as fully healthy.

The ``evidence_grade`` is NOT recorded here. Per the §L0 grading ladder, the
bundle builder maps a non-null ``source_leg`` to the correct grade fact
(``observed_alt_host`` / ``model_fallback``) when it assembles ``current_facts``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any, TypeVar, cast

import requests

from src.data.source_status import SourceFetchError, SourceSkipped

T = TypeVar("T")


def with_witness(
    primary: Callable[[], list[T]],
    witness: Callable[[], list[T]],
    *,
    source_key: str,
    leg_label: str,
) -> list[T]:
    """Return ``primary()`` unchanged on success; fall back to ``witness()``.

    The witness fires only when the primary raises ``SourceFetchError`` or a
    ``requests.RequestException`` (transport, timeout, connection, parse). A
    ``SourceSkipped`` propagates untouched — a deliberately-disabled source is
    never substituted by a backup. If the witness ALSO fails, a
    ``SourceFetchError`` chaining both error strings is raised
    (``gdacs.py`` GeoRSS-fallback style), so telemetry sees both failures.

    ``witness()`` MUST return the same object type/shape as ``primary()`` with
    each event's ``source_leg`` set to ``leg_label`` (use :func:`tag_source_leg`).
    The return value is the result list only — never a tuple.
    """
    try:
        return primary()
    except SourceSkipped:
        # A credential/config is intentionally absent — do not substitute.
        raise
    except (SourceFetchError, requests.RequestException) as primary_exc:
        print(f"[{source_key}] served by {leg_label}")
        try:
            return witness()
        except (SourceFetchError, requests.RequestException) as witness_exc:
            raise SourceFetchError(
                f"{source_key} primary failed: {primary_exc}; "
                f"{leg_label} witness failed: {witness_exc}"
            ) from witness_exc


def tag_source_leg(events: Sequence[T], leg_label: str) -> list[T]:
    """Return ``events`` with each event's ``source_leg`` set to ``leg_label``.

    Uses :func:`dataclasses.replace` so it works for frozen dataclasses too.
    Witness implementations call this on the events they build so provenance is
    carried back through the unchanged public return shape.
    """
    # Events are always dataclass instances with a `source_leg` field; the cast
    # narrows for `dataclasses.replace`, whose result we restore to T.
    return [
        cast(T, dataclasses.replace(cast(Any, event), source_leg=leg_label))
        for event in events
    ]


def source_leg_of(events: Sequence[T]) -> str | None:
    """Return the witness leg that served this batch, or ``None`` if the
    primary served. Assumes a homogeneous batch (a chain serves one leg)."""
    for event in events:
        leg = getattr(event, "source_leg", None)
        if leg:
            return str(leg)
    return None


def degraded_via(events: Sequence[T]) -> str | None:
    """Runner telemetry helper: the error text to record alongside
    ``status="degraded"`` when a witness served (``"served via <leg>"``), or
    ``None`` when the primary served and the run should record ``success``."""
    leg = source_leg_of(events)
    return f"served via {leg}" if leg else None
