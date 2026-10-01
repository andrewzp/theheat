"""Pure prospective media revisions, not authority writes or posting permission.

Resolve the predecessor from a supplied current state snapshot. A future authority
must rebuild this proposal under its lock, resolve current roles and retain exact
assets, decision and revision atomically. Neither this hash nor a caller's snapshot
provides authentication. No filesystem, provider, clock or transport I/O here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import re
from typing import Any

from src.commands.schema import utc_datetime, utc_text
from src.editorial.revisions import (
    decision_revision, draft_identity, fingerprint, has_unresolved_publish,
    invalidate_media_attachment,
)
from src.media.review_packet import (
    MAX_JSON_BYTES, MediaReviewError, build_media_review_packet, media_attachment_content,
)

MAX_DRAFTS = 1024


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MediaReviewError(message)


def _copy(value: Any) -> dict:
    _require(isinstance(value, dict), "Media proposal requires JSON objects")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    _require(len(encoded) <= MAX_JSON_BYTES, "Media proposal input exceeds the byte bound")
    fingerprint(value)
    return deepcopy(value)


def _revision(draft: dict) -> dict:
    return {"draft_id": draft["id"], **draft_identity(draft), "decision_revision": decision_revision(draft)}


def _receipt(attempt: dict) -> bool:
    return bool(attempt.get("tweet_id")) or any(
        _receipt(item) for item in attempt.get("attempt_conflicts", []) if isinstance(item, dict)
    )


def _target(state, draft_id, expected_revision, at):
    _require(isinstance(at, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", at) is not None,
             "An aware ISO timestamp is required")
    at = utc_text(datetime.fromisoformat(at))
    utc_datetime(at)  # Reuse the authority's canonical UTC representation.
    _require(isinstance(state, dict), "Current state is unavailable")
    drafts = state.get("drafts")
    _require(isinstance(drafts, list) and len(drafts) <= MAX_DRAFTS, "Current drafts are unavailable or oversized")
    _require(isinstance(draft_id, str) and 0 < len(draft_id.strip()) <= len(draft_id) <= 200 and all(ord(c) >= 32 for c in draft_id), "Invalid draft identity")
    matches = [d for d in drafts if isinstance(d, dict) and d.get("id") == draft_id]
    _require(len(matches) == 1, "Draft is missing or ambiguous")
    draft, expected = _copy(matches[0]), _copy(expected_revision)
    _require(
        type(expected.get("content_revision")) is type(expected.get("decision_revision")) is int
        and expected == _revision(draft) and set(expected) == set(_revision(draft)),
        "Draft differs from the expected predecessor revision",
    )
    _require(
        draft.get("status") in {"pending", "approved"} and not draft.get("revision_conflicts"),
        "Draft is not an unambiguous editable revision",
    )
    _require(decision_revision(draft) < 9007199254740990, "Decision revision is exhausted")
    _require(type(draft.get("content_revision")) is int and 1 <= draft["content_revision"] < 9007199254740991,
             "An unexhausted established revision is required")
    _require(isinstance(draft.get("text"), str) and 0 < len(draft["text"].strip()) <= len(draft["text"]) <= 280,
             "Draft text is invalid")
    event = draft.get("event_id")
    _require(isinstance(event, str) and 0 < len(event.strip()) <= len(event) <= 200 and all(ord(c) >= 32 for c in event), "Event identity is required")
    ledger = state.get("publish_ledger", {})
    posted = state.get("posted_events", [])
    _require(isinstance(ledger, dict) and isinstance(posted, list), "Publication evidence is malformed")
    attempt = _copy(ledger[event]) if event in ledger else {}
    _require(not has_unresolved_publish(draft, {"publish_ledger": {event: attempt} if event in ledger else {}}),
             "Publication outcome is unresolved")
    _require(not (draft.get("tweet_id") or draft.get("publish_outcome") == "confirmed" or event in posted or _receipt(attempt)),
             "Publication already has a receipt")
    history = draft.get("revision_history", [])
    _require(isinstance(history, list) and all(isinstance(item, dict) for item in history), "Revision history is malformed")
    return draft, expected, at


def _result(operation, predecessor, proposed, changed, packet):
    # An output too large for the existing media packet contract cannot become a
    # later authority request. This also bounds accumulated revision history.
    proposed = _copy(proposed)
    body = {
        "schema_version": 1, "operation": operation, "predecessor": predecessor,
        "changed": changed, "proposed_draft": proposed, "packet": packet,
        "synthetic": packet["synthetic"] if packet else None,
        "publication_approved": False, "production_attachment_authorized": False,
    }
    return {**body, "proposal_sha256": fingerprint(body)}


def build_media_attachment_proposal(
    state: dict, draft_id: str, *, expected_revision: dict, editorial_policy: dict,
    graphic_spec: dict, renderer_manifest: dict, png_bytes: bytes, at: str,
) -> dict:
    """Build the actual future revision before any supplied joint review of it.

    Only PNG bytes are validated here; immutable retention must still verify all
    five asset byte streams. A structural PNG header is not visual/scientific QA.
    """
    try:
        original, predecessor, at = _target(state, draft_id, expected_revision, at)
        # The predecessor was independently checked above. Detaching only on this
        # private validation copy permits a new render to replace the old one.
        source = deepcopy(original)
        source.pop("media_attachment", None)
        inputs: dict[str, Any] = dict(editorial_policy=editorial_policy, graphic_spec=graphic_spec,
                      renderer_manifest=renderer_manifest, png_bytes=png_bytes)
        source_packet = build_media_review_packet(source, expected_draft_identity=draft_identity(source), **inputs)
        proposed = deepcopy(original)
        invalidate_media_attachment(proposed, media_attachment_content(source_packet), at=at)
        changed = draft_identity(proposed) != draft_identity(original)
        if changed:
            proposed["updated_at"] = at
        packet = build_media_review_packet(proposed, expected_draft_identity=draft_identity(proposed), **inputs)
        return _result("attach", predecessor, proposed, changed, packet)
    except MediaReviewError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MediaReviewError("Malformed media attachment proposal") from None


def build_media_removal_proposal(
    state: dict, draft_id: str, *, expected_revision: dict, at: str,
) -> dict:
    """Remove media only through a new, unreviewed revision; never restore checks."""
    try:
        original, predecessor, at = _target(state, draft_id, expected_revision, at)
        proposed = deepcopy(original)
        changed = "media_attachment" in proposed
        invalidate_media_attachment(proposed, None, at=at)
        if changed:
            proposed["updated_at"] = at
        return _result("remove", predecessor, proposed, changed, None)
    except MediaReviewError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MediaReviewError("Malformed media removal proposal") from None
