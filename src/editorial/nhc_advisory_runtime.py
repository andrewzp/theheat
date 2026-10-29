"""Independently refreshed current-source owner for the nhc_advisory kind.

Each process that can spend, admit, approve-preflight or send installs its own
owner (a clock plus a finite request budget). A retained bundle supplies only
the validated nomination; the owner re-reads the fixed NHC products itself. No
proof is cached across callbacks or processes: every live boundary re-reads.
Static boundaries re-check the retained record, deadline, issue age and copy.
Missing owner, changed, superseded, removed, contradictory or unavailable
evidence holds before further paid work, admission, approval and send.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
import re

from src.editorial.nhc_advisory import SOURCE_NAME, AdvisoryHold, utc
from src.two_bot.intern.nhc_advisory import SIGNAL_KIND, RetainedAdvisory, is_nhc_advisory
from src.two_bot.types import StoryBundle


@dataclass(frozen=True)
class AdvisoryOwner:
    """Trusted process-local owner; it holds no source, URL or retained proof."""

    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


_OWNER: ContextVar[AdvisoryOwner | None] = ContextVar("nhc_advisory_owner", default=None)


@contextmanager
def advisory_owner_scope(owner: AdvisoryOwner | None = None, *, request_limit: int | None = None) -> Iterator[AdvisoryOwner]:
    """Install the owner and a fresh finite request budget for one command/phase."""
    from src.data.nhc_advisory import MAX_REQUESTS_PER_PHASE, request_budget_scope
    owner = AdvisoryOwner() if owner is None else owner
    if type(owner) is not AdvisoryOwner or not callable(owner.clock):
        raise AdvisoryHold("nhc_advisory_owner_invalid")
    with request_budget_scope(MAX_REQUESTS_PER_PHASE if request_limit is None else request_limit):
        token = _OWNER.set(owner)
        try:
            yield owner
        finally:
            _OWNER.reset(token)


def current_owner() -> AdvisoryOwner:
    owner = _OWNER.get()
    if owner is None:
        raise AdvisoryHold("nhc_advisory_current_source_unavailable")
    return owner


def _now(owner: AdvisoryOwner) -> datetime:
    try:
        value = owner.clock()
    except Exception:
        raise AdvisoryHold("nhc_advisory_clock_invalid") from None
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AdvisoryHold("nhc_advisory_clock_invalid")
    return value.astimezone(UTC)


def _named(text: str, name: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None


_ATTRIBUTION = re.compile(r"(?<![A-Za-z0-9_])(?:NHC|National Hurricane Center)(?![A-Za-z0-9_])", re.IGNORECASE)
_MODALITY = re.compile(r"\b(?:forecasts?|forecast to|expected|could|may|might|possible|possibly|likely|risk|"
                       r"warns?|advisory)\b", re.IGNORECASE)
_OBSERVED_FLOODING = re.compile(r"\b(?:flooded|(?:has|have|had) (?:caused )?flood(?:ed|ing)|flooding (?:has|have))\b",
                                re.IGNORECASE)


def check_copy(candidate: object, retained: RetainedAdvisory) -> None:
    """Necessary bindings only; entailment remains the ordinary required checks' job."""
    if type(candidate) is not str or not candidate.strip():
        raise AdvisoryHold("nhc_advisory_copy_invalid")
    if _ATTRIBUTION.search(candidate) is None:
        raise AdvisoryHold("nhc_advisory_copy_attribution_missing")
    if not _named(candidate, retained.nomination.place):
        raise AdvisoryHold("nhc_advisory_copy_place_missing")
    rest = _ATTRIBUTION.sub("", candidate)
    rest = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(retained.nomination.place) + r"(?![A-Za-z0-9_])", "", rest,
                  flags=re.IGNORECASE)
    if _MODALITY.search(rest) is None:
        raise AdvisoryHold("nhc_advisory_copy_modality_missing")
    source = " ".join([retained.record["hazard"]["text"], *(row["text"] for row in retained.record["context"])])
    for word in ("landfall", "record", "population"):
        if re.search(rf"\b{word}\b", candidate, re.IGNORECASE) and not re.search(rf"\b{word}\b", source, re.IGNORECASE):
            raise AdvisoryHold("nhc_advisory_copy_unsupported_claim")
    if _OBSERVED_FLOODING.search(candidate):
        raise AdvisoryHold("nhc_advisory_copy_unsupported_claim")


def guard_advisory_story(bundle: StoryBundle, *, candidate: object | None = None, generating: bool = True,
                         live: bool = False) -> None:
    """Static or live current-source check for one nhc_advisory bundle; no approval."""
    if not is_nhc_advisory(bundle):
        return
    if getattr(bundle, "signal_kind", None) != SIGNAL_KIND:
        raise AdvisoryHold("nhc_advisory_identity_changed")
    if generating and os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1":
        raise AdvisoryHold("nhc_advisory_generation_paused")
    owner = current_owner()
    retained = RetainedAdvisory(bundle)
    retained.check_times(_now(owner))
    if live:
        from src.data.nhc_advisory import current_evidence
        try:
            fresh = current_evidence(retained.nomination, clock=lambda: _now(owner))
        except AdvisoryHold:
            raise
        except Exception:
            # Callback/transport text can contain hosts, paths or credentials.
            raise AdvisoryHold("nhc_advisory_current_source_unavailable") from None
        if fresh.identity() != retained.identity():
            raise AdvisoryHold("nhc_advisory_current_source_changed")
        retained.check_times(_now(owner))  # The read can outlive the deadline.
    if candidate is not None:
        check_copy(candidate, retained)


def _draft_bundle(draft: dict) -> tuple[bool, object]:
    context = draft.get("review_context") or {}
    two = context.get("two_bot") if isinstance(context, dict) else None
    raw = two.get("bundle") if isinstance(two, dict) else None
    advisory = (draft.get("type") == SIGNAL_KIND or str(draft.get("event_id", "")).startswith(SIGNAL_KIND + ":")
                or (isinstance(raw, dict) and raw.get("signal_kind") == SIGNAL_KIND))
    return advisory, raw


def is_advisory_draft(draft: object) -> bool:
    return isinstance(draft, dict) and _draft_bundle(draft)[0]


def current_advisory_source(draft: object, *, live: bool) -> str | None:
    """Sender/source-review hold code, or None. A saved bundle is never itself current."""
    if not isinstance(draft, dict):
        return None
    advisory, raw = _draft_bundle(draft)
    if not advisory:
        return None
    try:
        context = draft.get("review_context") or {}
        if isinstance(context, dict) and context.get("nhc_advisory_source_hold"):
            raise AdvisoryHold("nhc_advisory_saved_source_held")
        if (not isinstance(raw, dict) or draft.get("type") != SIGNAL_KIND
                or draft.get("event_id") != raw.get("event_id") or raw.get("signal_kind") != SIGNAL_KIND):
            raise AdvisoryHold("nhc_advisory_draft_identity_changed")
        guard_advisory_story(StoryBundle(**raw), candidate=draft.get("text"), generating=False, live=live)
        return None
    except AdvisoryHold as exc:
        return exc.code
    except (TypeError, ValueError, AttributeError):
        return "nhc_advisory_retained_invalid"


def operator_deadline(bundle: StoryBundle) -> datetime:
    """For display/plans only: the retained operator recheck deadline (never an NHC expiry)."""
    return utc(RetainedAdvisory(bundle).record["times"]["operator_recheck_deadline"])


__all__ = ["SOURCE_NAME", "AdvisoryOwner", "advisory_owner_scope", "check_copy", "current_advisory_source",
           "current_owner", "guard_advisory_story", "is_advisory_draft", "operator_deadline"]
