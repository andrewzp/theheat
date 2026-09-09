"""Bind editorial decisions to exact draft text and evidence.

The equivalent JavaScript contract lives in dashboard/lib/draft-revisions.js.
These fingerprints detect stale decisions; they are not a storage lock.
"""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import math
import struct
from typing import Any

from src.editorial.publication import automatic_publication_policy, valid_epoch


def _canonical(value: Any) -> Any:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Revision evidence must contain finite numbers")
        # JSON numbers share one IEEE-754 representation across Python and JS.
        return ["number", struct.pack(">d", 0.0 if number == 0 else number).hex()]
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, list):
        return ["array", [_canonical(item) for item in value]]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return ["object", [
            [key, _canonical(value[key])]
            for key in sorted(value, key=lambda key: key.encode("utf-8"))
        ]]
    raise ValueError("Revision evidence must be JSON data")


def fingerprint(value: Any) -> str:
    payload = json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Draft text must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evidence_payload(draft: dict) -> dict:
    review = deepcopy(draft.get("review_context"))
    if isinstance(review, dict):
        two_bot = review.pop("two_bot", None)
        if isinstance(two_bot, dict) and "bundle" in two_bot:
            review["two_bot"] = {"bundle": two_bot["bundle"]}
    return {
        "event_id": draft.get("event_id"),
        "type": draft.get("type"),
        "tweet_date": draft.get("tweet_date"),
        "review_context": review,
        "hot10_rows": draft.get("hot10_rows"),
    }


def draft_identity(draft: dict) -> dict:
    revision = draft.get("content_revision", 0)
    if type(revision) is not int or not 0 <= revision <= 9007199254740991:
        raise ValueError("Invalid content revision")
    return {
        "content_revision": revision,
        "text_sha256": text_hash(draft.get("text", "")),
        "evidence_sha256": fingerprint(_evidence_payload(draft)),
    }


def decision_revision(draft: dict) -> int:
    revision = draft.get("decision_revision", 0)
    if type(revision) is not int or not 0 <= revision < 9007199254740991:
        raise ValueError("Invalid decision revision")
    return revision


def _advance_decision(draft: dict) -> None:
    draft["decision_revision"] = decision_revision(draft) + 1


def binding_matches(draft: dict, binding: Any) -> bool:
    if not isinstance(binding, dict):
        return False
    if type(binding.get("content_revision")) is not int:
        return False
    try:
        return all(binding.get(key) == value for key, value in draft_identity(draft).items())
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False


def _two_bot(draft: dict) -> dict:
    review = draft.get("review_context")
    value = review.get("two_bot") if isinstance(review, dict) else None
    return value if isinstance(value, dict) else {}


def _checks(two_bot: dict) -> dict:
    return {"fact_check": two_bot.get("fact_check"), "critic": two_bot.get("critic")}


def _checks_pass(two_bot: dict) -> bool:
    return all(
        isinstance(two_bot.get(key), dict) and two_bot[key].get("passed") is True
        for key in ("fact_check", "critic")
    )


def review_is_current(draft: dict) -> bool:
    binding = draft.get("review_binding")
    if draft.get("revision_conflicts") or not isinstance(binding, dict) or not binding_matches(draft, binding):
        return False
    if binding.get("kind") == "human":
        return True
    if binding.get("kind") != "model" or not _checks_pass(_two_bot(draft)):
        return False
    try:
        return binding.get("checks_sha256") == fingerprint(_checks(_two_bot(draft)))
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False


def approval_is_current(draft: dict, mode: str | None = None) -> bool:
    binding = draft.get("approval_binding")
    if not isinstance(binding, dict) or not review_is_current(draft) or not binding_matches(draft, binding):
        return False
    if binding.get("mode") not in ("manual", "auto"):
        return False
    if mode and binding.get("mode") != mode:
        return False
    try:
        if type(binding.get("decision_revision")) is not int or binding["decision_revision"] != decision_revision(draft):
            return False
    except ValueError:
        return False
    if binding.get("publish_intent_id") != draft.get("publish_intent_id"):
        return False
    if binding["mode"] == "auto" and draft["review_binding"].get("kind") != "model":
        return False
    return True


def has_unresolved_publish(draft: dict, state: Mapping[str, Any]) -> bool:
    """Unknown attempts and receipts for other content cannot be cleared by edits."""
    ledger = state.get("publish_ledger") or {}
    event_id = draft.get("event_id") or draft.get("id")

    def unresolved(attempt: Any) -> bool:
        if not isinstance(attempt, dict):
            return True
        conflicts = attempt.get("attempt_conflicts", [])
        if not isinstance(conflicts, list):
            return True
        if any(unresolved(other) for other in conflicts):
            return True
        if attempt.get("tweet_id"):
            if "text_sha256" in attempt:
                return not binding_matches(draft, attempt)
            return isinstance(attempt.get("text"), str) and attempt["text"] != draft.get("text")
        # A missing phase is legacy evidence of a possible send, not proof of expiry.
        return attempt.get("phase") != "not_sent"

    # Missing evidence and an explicitly malformed retained row are different.
    # Never treat null/scalar conflict members as proof that nothing was sent.
    if isinstance(ledger, dict) and event_id in ledger and unresolved(ledger[event_id]):
        return True
    if draft.get("publish_outcome") in ("submitted", "unknown"):
        return True
    if draft.get("status") == "posted" or draft.get("publish_outcome") in ("not_sent", "confirmed"):
        return False
    return bool(draft.get("autoship_attempted") or draft.get("last_publish_attempt_at"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_model_review(draft: dict) -> dict:
    revoke_approval(draft)
    two_bot = _two_bot(draft)
    try:
        proven = (
            _checks_pass(two_bot)
            and two_bot.get("reviewed_text_sha256") == text_hash(draft.get("text", ""))
            and "bundle" in two_bot
            and two_bot.get("reviewed_bundle_sha256") == fingerprint(two_bot["bundle"])
        )
    except (ValueError, TypeError, UnicodeError, OverflowError):
        proven = False
    if proven and not draft.get("revision_conflicts"):
        draft["review_binding"] = {
            **draft_identity(draft), "kind": "model", "reviewed_at": _now(),
            "checks_sha256": fingerprint(_checks(two_bot)),
        }
    else:
        draft.pop("review_binding", None)
    return draft


def initialize_revision(draft: dict) -> dict:
    draft.setdefault("content_revision", 1)
    return record_model_review(draft)


def record_human_review(draft: dict, *, at: str | None = None) -> dict:
    if draft.get("revision_conflicts"):
        raise ValueError("Resolve the conflicting revision before reviewing")
    text = draft.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 280:
        raise ValueError("Invalid draft text")
    draft["content_revision"] = max(1, draft_identity(draft)["content_revision"])
    revoke_approval(draft)
    draft["review_binding"] = {**draft_identity(draft), "kind": "human", "reviewed_at": at if at is not None else _now()}
    return draft


def authorize_draft(draft: dict, mode: str, intent_id: str | None = None, *, publication_epoch: str | None = None) -> dict:
    if not review_is_current(draft):
        raise ValueError("This revision needs revalidation")
    if mode not in ("manual", "auto"):
        raise ValueError("Invalid approval mode")
    if mode == "auto" and draft["review_binding"].get("kind") != "model":
        raise ValueError("Scheduling requires a current model review")
    if mode == "auto":
        policy = automatic_publication_policy()
        if not policy["enabled"] or (publication_epoch is not None and publication_epoch != policy["epoch"]):
            raise ValueError(policy["reason"])
        publication_epoch = policy["epoch"]
    return bind_reviewed_revision(draft, mode, at=_now(), intent_id=intent_id, publication_epoch=publication_epoch)


def bind_reviewed_revision(draft: dict, mode: str, *, at: str,
                           intent_id: str | None = None, publication_epoch: str | None = None) -> dict:
    """Record a binding deterministically after the caller's authorization check.

    This is a domain transition, not permission to send a post. Runtime callers
    must use authorize_draft; a command authority supplies its verified policy
    and clock explicitly. Final publication still requires the sender's checks.
    """
    if not review_is_current(draft):
        raise ValueError("This revision needs revalidation")
    if mode not in ("manual", "auto"):
        raise ValueError("Invalid approval mode")
    if mode == "auto" and draft["review_binding"].get("kind") != "model":
        raise ValueError("Scheduling requires a current model review")
    if mode == "auto" and not valid_epoch(publication_epoch):
        raise ValueError("A valid publication epoch is required")
    _advance_decision(draft)
    draft["approval_binding"] = {
        **draft_identity(draft), "decision_revision": draft["decision_revision"],
        "mode": mode, "authorized_at": at,
    }
    if mode == "auto":
        draft["approval_binding"]["publication_epoch"] = publication_epoch
    if intent_id:
        draft["approval_binding"]["publish_intent_id"] = intent_id
        draft["publish_intent_id"] = intent_id
    return draft


def revoke_approval(draft: dict) -> dict:
    _advance_decision(draft)
    for key in (
        "approval_binding", "approved_at", "auto_approve_at", "auto_approve_requested_at",
        "publish_requested_at", "publish_intent_id", "autoship_on_critic_pass",
    ):
        draft.pop(key, None)
    draft["approval_mode"] = "manual"
    return draft


def invalidate_text(draft: dict, new_text: str, *, at: str | None = None) -> dict:
    if not isinstance(new_text, str) or not new_text.strip() or len(new_text) > 280:
        raise ValueError("Invalid draft text")
    text_hash(new_text)  # Reject malformed Unicode before changing durable fields.
    if new_text == draft.get("text") and not draft.get("revision_conflicts"):
        return draft
    previous = {key: deepcopy(draft[key]) for key in (
        "text", "review_context", "review_binding", "approval_binding", "revision_conflicts", "decision_revision",
    ) if key in draft}
    previous.update(draft_identity(draft))
    previous["invalidated_at"] = at if at is not None else _now()
    draft.setdefault("revision_history", []).append(previous)
    draft["content_revision"] = previous["content_revision"] + 1
    draft["text"] = new_text
    draft["status"] = "pending"
    revoke_approval(draft)
    for key in ("review_binding", "revision_conflicts", "candidate_score", "selected_candidate_rank"):
        draft.pop(key, None)
    review = draft.get("review_context")
    if isinstance(review, dict) and isinstance(review.get("two_bot"), dict):
        review["two_bot"] = {key: value for key, value in review["two_bot"].items() if key in ("bundle", "signal_kind")}
    return draft


def project_draft(draft: dict) -> dict:
    current = review_is_current(draft)
    return {
        **draft, "revision_identity": {**draft_identity(draft), "decision_revision": decision_revision(draft)},
        "review_status": "conflict" if draft.get("revision_conflicts") else "passed" if current else "needs_revalidation",
        "review_kind": draft.get("review_binding", {}).get("kind") if current else None,
    }
