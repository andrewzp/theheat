"""Explicit valid revision fixtures for mocked editorial/publication tests."""

from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import (
    authorize_draft,
    fingerprint,
    initialize_revision,
    text_hash,
)


def model_review_context(text, *, passed=True, verdict="PASS"):
    return {"two_bot": {
        "bundle": {},
        "fact_check": {"passed": True, "extracted_claims": []},
        "critic": {"passed": passed, "verdict": verdict},
        "reviewed_policy_sha256": fingerprint(current_editorial_policy()),
        "reviewed_text_sha256": text_hash(text),
        "reviewed_bundle_sha256": fingerprint({}),
    }}


def bind_reviewed_draft(draft, mode="auto", intent_id=None):
    """Build a deliberately successful mocked model check and authorization."""
    # Establish future scheduling after review, just like the production saver.
    schedule = {key: draft[key] for key in (
        "auto_approve_at", "auto_approve_requested_at", "autoship_on_critic_pass",
    ) if key in draft}
    approval_mode = draft.get("approval_mode")
    review = draft.setdefault("review_context", {})
    two_bot = review.setdefault("two_bot", {})
    two_bot.setdefault("bundle", {})
    two_bot.setdefault("fact_check", {}).update(passed=True)
    two_bot.setdefault("critic", {}).update(passed=True, verdict="PASS")
    two_bot["reviewed_policy_sha256"] = fingerprint(current_editorial_policy())
    two_bot["reviewed_text_sha256"] = text_hash(draft["text"])
    two_bot["reviewed_bundle_sha256"] = fingerprint(two_bot["bundle"])
    initialize_revision(draft)
    authorize_draft(draft, mode, intent_id)
    draft["approval_mode"] = "manual" if mode == "manual" else (approval_mode or "auto")
    if mode == "manual":
        draft["status"] = "approved"
        if intent_id:
            draft["publish_intent_id"] = intent_id
    else:
        draft.setdefault("status", "pending")
        draft.update(schedule)
    return draft
