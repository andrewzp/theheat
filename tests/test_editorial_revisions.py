"""Decision bindings must fail closed when the reviewed object changes."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.editorial.revisions import (
    approval_is_current, authorize_draft, binding_matches, draft_identity, fingerprint,
    has_unresolved_publish, initialize_revision, invalidate_text, project_draft,
    record_human_review, record_model_review, review_is_current, revoke_approval, text_hash,
)


def reviewed_draft():
    draft = {
        "id": "d1", "event_id": "heat_test", "type": "monthly_high", "status": "pending",
        "text": "A forecast high of 40°C.",
        "review_context": {"source": "example model", "facts": [{"label": "Forecast", "value": "40°C"}],
                           "two_bot": {"bundle": {"temperature": 40.0, "is_forecast": True},
                                       "fact_check": {"passed": True, "extracted_claims": [{"text": "40°C"}]},
                                       "critic": {"passed": True}}},
    }
    proof = draft["review_context"]["two_bot"]
    proof["reviewed_text_sha256"] = text_hash(draft["text"])
    proof["reviewed_bundle_sha256"] = fingerprint(proof["bundle"])
    return initialize_revision(draft)


def test_python_javascript_identity_contract():
    fixture = Path(__file__).parent / "fixtures" / "draft_revision_identity.json"
    for case in json.loads(fixture.read_text()):
        assert draft_identity(case["draft"]) == case["identity"], case["name"]


def test_edited_armed_text_loses_claims_review_approval_and_due_time():
    draft = reviewed_draft()
    authorize_draft(draft, "auto")
    draft.update(auto_approve_at="2026-09-08T00:00:00Z", autoship_on_critic_pass=True, approved_at="old")
    old_identity = draft_identity(draft)
    invalidate_text(draft, "A forecast high of 50°C.")
    assert not binding_matches(draft, old_identity)
    assert not review_is_current(draft)
    assert not approval_is_current(draft)
    for key in ("auto_approve_at", "autoship_on_critic_pass", "approved_at", "approval_binding", "review_binding"):
        assert key not in draft
    assert draft["status"] == "pending"
    assert draft["review_context"]["two_bot"]["bundle"]["temperature"] == 40
    assert "fact_check" not in draft["review_context"]["two_bot"]
    assert draft["revision_history"][0]["review_context"]["two_bot"]["fact_check"]["extracted_claims"]


def test_returning_to_old_text_does_not_restore_its_approval():
    draft = reviewed_draft()
    authorize_draft(draft, "manual", "old-intent")
    original = deepcopy(draft)
    invalidate_text(draft, "Changed text")
    invalidate_text(draft, original["text"])
    draft["review_binding"] = original["review_binding"]
    draft["approval_binding"] = original["approval_binding"]
    assert draft["content_revision"] == 3
    assert not review_is_current(draft)
    assert not approval_is_current(draft)


@pytest.mark.parametrize("change", ["bundle", "display_facts", "date", "model_verdict", "verdict_details"])
def test_changed_evidence_or_model_result_cannot_reuse_review(change):
    draft = reviewed_draft()
    authorize_draft(draft, "manual")
    if change == "bundle":
        draft["review_context"]["two_bot"]["bundle"]["temperature"] = 50
    elif change == "display_facts":
        draft["review_context"]["facts"][0]["value"] = "50°C"
    elif change == "date":
        draft["tweet_date"] = "2026-09-09"
    elif change == "model_verdict":
        draft["review_context"]["two_bot"]["critic"]["passed"] = False
    else:
        draft["review_context"]["two_bot"]["fact_check"]["extracted_claims"] = []
    assert not review_is_current(draft)
    assert not approval_is_current(draft)


def test_save_cannot_stamp_proof_for_text_changed_after_model_review():
    draft = reviewed_draft()
    draft["text"] += " https://example.com/bulletin"
    record_model_review(draft)
    assert not review_is_current(draft)


def test_model_pass_without_actual_reviewed_text_and_bundle_proof_is_unbound():
    draft = reviewed_draft()
    del draft["review_context"]["two_bot"]["reviewed_text_sha256"]
    initialize_revision(draft)
    assert not review_is_current(draft)


def test_explicit_human_review_of_legacy_text_allows_only_new_manual_approval():
    draft = {"text": "Reviewed text", "status": "pending", "auto_approve_at": "old"}
    assert project_draft(draft)["review_status"] == "needs_revalidation"
    record_human_review(draft)
    assert draft["content_revision"] == 1
    assert review_is_current(draft)
    assert "auto_approve_at" not in draft
    assert not approval_is_current(draft)
    with pytest.raises(ValueError, match="model review"):
        authorize_draft(draft, "auto")
    authorize_draft(draft, "manual", "new-intent")
    assert approval_is_current(draft, "manual")
    draft["publish_intent_id"] = "superseding-intent"
    assert not approval_is_current(draft)


def test_noop_edit_preserves_valid_review_and_authorization():
    draft = reviewed_draft()
    authorize_draft(draft, "auto")
    before = deepcopy(draft)
    invalidate_text(draft, draft["text"])
    assert draft == before
    assert approval_is_current(draft, "auto")


def test_cancelled_same_text_cannot_reuse_old_decision_binding():
    draft = reviewed_draft()
    authorize_draft(draft, "manual", "intent")
    old_approval = deepcopy(draft["approval_binding"])
    snapshot = project_draft(draft)["revision_identity"]
    revoke_approval(draft)
    assert review_is_current(draft)
    assert project_draft(draft)["revision_identity"] != snapshot
    draft["approval_binding"] = old_approval
    draft["publish_intent_id"] = "intent"
    assert not approval_is_current(draft)
    authorize_draft(draft, "manual", "new-intent")
    assert approval_is_current(draft)


def test_repeated_model_review_requires_fresh_authorization():
    draft = reviewed_draft()
    authorize_draft(draft, "auto")
    record_model_review(draft)
    assert review_is_current(draft)
    assert not approval_is_current(draft)


def test_malformed_unicode_edit_is_rejected_without_mutating_draft():
    draft = reviewed_draft()
    authorize_draft(draft, "auto")
    original = deepcopy(draft)
    with pytest.raises(UnicodeError):
        invalidate_text(draft, "\ud800")
    assert draft == original


def test_conflicting_revisions_need_explicit_resolution_then_review():
    draft = reviewed_draft()
    draft["revision_conflicts"] = [{"text": "Another editor's text"}]
    assert not review_is_current(draft)
    with pytest.raises(ValueError, match="conflicting"):
        record_human_review(draft)
    invalidate_text(draft, draft["text"])
    assert draft["content_revision"] == 2
    assert not draft.get("revision_conflicts")
    assert draft["revision_history"][0]["revision_conflicts"]
    assert not review_is_current(draft)


@pytest.mark.parametrize("phase", [None, "submitted", "unknown"])
def test_old_unknown_publication_is_not_an_expiring_approval(phase):
    draft = reviewed_draft()
    row = {"at": "2020-01-01T00:00:00Z", "intent_id": "attempt", "tweet_id": None}
    if phase:
        row["phase"] = phase
    assert has_unresolved_publish(draft, {"publish_ledger": {draft["event_id"]: row}})


def test_not_sent_is_retryable_but_prior_unknown_conflict_is_preserved():
    draft = reviewed_draft()
    row = {"phase": "not_sent", "intent_id": "b"}
    state = {"publish_ledger": {draft["event_id"]: row}}
    assert not has_unresolved_publish(draft, state)
    row["attempt_conflicts"] = [{"phase": "unknown", "intent_id": "a"}]
    assert has_unresolved_publish(draft, state)


def test_revocation_and_edit_helpers_do_not_erase_unknown_attempt_markers():
    draft = reviewed_draft()
    draft.update(autoship_attempted=True, last_publish_attempt_at="old", publish_outcome="unknown")
    revoke_approval(draft)
    invalidate_text(draft, "New text")
    assert draft["autoship_attempted"]
    assert draft["last_publish_attempt_at"] == "old"
    assert has_unresolved_publish(draft, {})


def test_receipt_for_old_revision_does_not_validate_edited_text():
    draft = reviewed_draft()
    row = {**draft_identity(draft), "tweet_id": "123", "text": draft["text"], "phase": "confirmed"}
    invalidate_text(draft, "Other text")
    assert has_unresolved_publish(draft, {"publish_ledger": {draft["event_id"]: row}})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {"x": float("-inf")}])
def test_unhashable_evidence_cannot_receive_authorization(value):
    draft = reviewed_draft()
    draft["review_context"]["invalid"] = value
    assert not review_is_current(draft)
    with pytest.raises(ValueError):
        record_human_review(draft)
