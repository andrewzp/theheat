"""Source-redundancy witness helpers (SOURCE-REDUNDANCY LANE, R-00).

A *witness* is a fallback feed that fires only when a primary source fetch
fails — covering the outage subset of no-draft days. The mechanics here are
deliberately tiny and shared by every per-source chain (R-02..R-09):

- :func:`with_witness` orchestrates the fallback: it returns the primary's
  result untouched on success, and only on provider-outage/transport failures
  (timeouts, connection errors, 5xx, rate limits, WAF-style 403s — never
  ``SourceSkipped`` or our-side auth/schema failures) does it call the witness.
  The public fetch function keeps its return shape; provenance rides on the
  returned event objects.
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

from src.data.error_class import classify_error_class
from src.data.source_status import SourceFetchError, SourceSkipped

T = TypeVar("T")

_NON_WITNESSABLE_TEXT = (
    "schema drift",
    "missing required field",
    "expected json object",
    "could not parse",
    "freshness check failed",
    "invalid literal",
    "invalid map_key",
    "bad request",
    "earthdata_token",
    "unauthorized",
    "invalid token",
    "token expired",
    "credential",
)
_WITNESSABLE_CLASSES = {"http403", "http429", "http5xx", "timeout", "dns", "connection"}
_NON_WITNESSABLE_CLASSES = {"auth", "parse"}
_WITNESSABLE_TEXT = (
    " down",
    "unavailable",
    "timed out",
    "connection reset",
    "connection aborted",
    "stale data:",
)


def with_witness(
    primary: Callable[[], list[T]],
    witness: Callable[[], list[T]],
    *,
    source_key: str,
    leg_label: str,
) -> list[T]:
    """Return ``primary()`` unchanged on success; fall back to ``witness()``.

    The witness fires only when the primary raises a provider-outage-style
    ``SourceFetchError`` or ``requests.RequestException``. Auth/config/schema
    errors propagate untouched so a backup cannot hide our bugs. A
    ``SourceSkipped`` also propagates untouched — a deliberately-disabled source
    is never substituted by a backup. If the witness ALSO fails, a
    ``SourceFetchError`` chaining both error strings is raised (``gdacs.py``
    GeoRSS-fallback style), so telemetry sees both failures.

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
        if not is_witness_eligible_failure(primary_exc):
            raise
        print(f"[{source_key}] served by {leg_label}")
        try:
            return witness()
        except (SourceFetchError, requests.RequestException) as witness_exc:
            raise SourceFetchError(
                f"{source_key} primary failed: {primary_exc}; "
                f"{leg_label} witness failed: {witness_exc}"
            ) from witness_exc


def is_witness_eligible_failure(exc: Exception) -> bool:
    """True when a primary failure is the outage class witnesses are meant to
    cover. False for credential, configuration, and schema/parser defects."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        if status in {400, 401, 404, 410}:
            return False
        if status == 403:
            return not _looks_credential_related(str(exc))
        return status == 429 or status >= 500
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.RequestException):
        return True

    text = str(exc)
    lowered = text.lower()
    if any(token in lowered for token in _NON_WITNESSABLE_TEXT):
        return False
    error_class = classify_error_class(text)
    if error_class in _NON_WITNESSABLE_CLASSES:
        return False
    if error_class == "http403":
        return not _looks_credential_related(text)
    if any(token in lowered for token in _WITNESSABLE_TEXT):
        return True
    return error_class in _WITNESSABLE_CLASSES


def _looks_credential_related(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in ("earthdata", "urs.earthdata", "edl", "podaac", "credential")
    )


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
