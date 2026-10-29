"""Closed dispatch for explicitly selected Gist post images; never a plugin registry.

Every kind names one reviewed, versioned renderer. The deployed temperature kind
delegates unchanged to gist_temperature_media. A kind joins KINDS only together
with its complete preview, joint-review, approval and sender path; anything else,
including an experimental or PG attachment, stays refused for approval and send.
Callers look the family functions up on their modules at call time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.media import gist_hazard_media as hazard, gist_temperature_media as temperature

TEMPERATURE = temperature.KIND
KINDS = frozenset({TEMPERATURE, *hazard.KINDS})


def kind_of(value):
    """The allowlisted kind of an attachment object, else a refusal."""
    kind = value.get("kind") if type(value) is dict else None
    if type(kind) is not str or kind not in KINDS:
        raise ValueError("Image withheld: unsupported attachment")
    return kind


def validate_descriptor(value, bundle):
    if kind_of(value) == TEMPERATURE:
        return temperature.validate_descriptor(value, bundle)
    return hazard.validate_descriptor(value, bundle)


def prepare_media(bundle, *, synthetic=False):
    """Select the family from the retained source shape, never from a caller's kind."""
    if hazard.claims(bundle):
        return hazard.prepare_media(bundle, synthetic=synthetic)
    return temperature.prepare_media(bundle, synthetic=synthetic)


def posting_window(bundle, *, now=None):
    """Preview disclosure only; approval and the sender recheck independently."""
    current = datetime.now(timezone.utc) if now is None else now
    reason = hazard.currentness(hazard.family_for(bundle), bundle, current)
    checked = current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"status": "unavailable" if reason else "current", "code": reason[0] if reason else None,
            "reason": reason[1] if reason else None, "checked_at": checked}


def media_for_draft(draft, *, now=None):
    """Exact reviewed recipe only; any mismatch refuses before upload."""
    if kind_of(draft["media_attachment"]) == TEMPERATURE:
        return temperature.media_for_draft(draft)
    return hazard.media_for_draft(draft, now=now)


def recheck_before_upload(draft, *, now=None):
    """Every family rechecks its unchanged source-time rule immediately before upload."""
    if kind_of(draft["media_attachment"]) == TEMPERATURE:
        return temperature.recheck_before_upload(draft, now=now)
    return hazard.recheck_before_upload(draft, now=now)
