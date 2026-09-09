"""P02: exact revision authorization at the Python publication boundary."""

from copy import deepcopy
import importlib
from unittest.mock import MagicMock

import pytest

from src.editorial.revisions import (
    authorize_draft,
    draft_identity,
    initialize_revision,
    has_unresolved_publish,
    invalidate_text,
    record_human_review,
    review_is_current,
)
from src.orchestrator import posting
from src.state import DEFAULT_STATE
from tests.revision_helpers import bind_reviewed_draft, model_review_context


def _draft(mode="manual"):
    draft = {
        "id": "draft_revision", "event_id": "event_revision", "type": "monthly_high",
        "text": "A measured temperature was 40 C.",
        "created_at": posting._utc_now_iso(), "updated_at": posting._utc_now_iso(),
        "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
        "review_context": {"two_bot": {"bundle": {
            "event_id": "event_revision", "signal_kind": "monthly_high",
            "current_facts": [{"label": "temperature", "value": 40}],
        }}},
    }
    if mode == "auto":
        draft["auto_approve_at"] = "2000-01-01T00:00:00Z"
        draft["autoship_on_critic_pass"] = True
    return bind_reviewed_draft(draft, mode, "intent_current" if mode == "manual" else None)


@pytest.fixture
def external(monkeypatch):
    # The legacy main facade copies patched public wrappers into split modules.
    # Restore the real sender before boundary tests so a mock left by another
    # test cannot make them pass or fail without exercising production code.
    importlib.reload(posting)
    storage = MagicMock()
    storage.check_daily_cap.return_value = True
    storage.write_state.return_value = True
    send = MagicMock(return_value={"id": "tweet_current"})
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "post_to_bluesky", MagicMock())
    monkeypatch.setattr(posting, "run_safety_pipeline", MagicMock(return_value=(True, None)))
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
    return storage, send


def _state(draft):
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    return state


@pytest.mark.parametrize("change", ["text", "evidence", "fact_check", "approval", "conflict", "revision"])
def test_final_send_rejects_stale_or_conflicting_binding(external, change):
    draft = _draft()
    if change == "text":
        draft["text"] = "A measured temperature was 50 C."
    elif change == "evidence":
        draft["review_context"]["two_bot"]["bundle"]["current_facts"][0]["value"] = 50
    elif change == "fact_check":
        draft["review_context"]["two_bot"]["fact_check"]["passed"] = False
    elif change == "approval":
        draft["approval_binding"]["text_sha256"] = "stale"
    elif change == "conflict":
        draft["revision_conflicts"] = [{"text": "another revision"}]
    else:
        draft["content_revision"] += 1
    state = _state(draft)

    assert posting.post_approved(draft, state) == "failed"
    external[1].assert_not_called()
    external[0].write_state.assert_not_called()
    assert not state["publish_ledger"]


def test_legacy_approved_status_does_not_authorize_tracked_send(external):
    draft = {"id": "legacy", "text": "Legacy approved text", "status": "approved"}
    assert posting.post_approved(draft, _state(draft)) == "failed"
    external[1].assert_not_called()


@pytest.mark.parametrize("remove", ["review_binding", "approval_binding", "review_context"])
def test_premarked_autoship_cannot_skip_current_checks(external, remove):
    draft = _draft("auto")
    draft.pop(remove)
    posting.process_due_drafts(_state(draft))
    external[1].assert_not_called()
    assert draft["approval_mode"] == "manual"
    assert "auto_approve_at" not in draft
    assert "autoship_attempted" not in draft


def test_current_auto_revision_is_marked_before_durable_write_and_network(external):
    draft = _draft("auto")
    original = deepcopy(draft)
    state = _state(draft)

    def write(submitted_state, *, expected_draft, expected_publish_ledger):
        assert expected_draft == original
        assert expected_publish_ledger is None
        assert draft["autoship_attempted"] is True
        assert draft["publish_outcome"] == "submitted"
        row = submitted_state["publish_ledger"][draft["event_id"]]
        assert row["phase"] == "submitted"
        assert row["text"] == original["text"]
        assert all(row[k] == v for k, v in draft_identity(original).items())
        external[1].assert_not_called()
        return True

    external[0].write_state.side_effect = write
    assert posting.post_approved(draft, state) == "posted"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert draft["publish_outcome"] == "confirmed"
    external[1].assert_called_once_with(original["text"], media_png=None, alt_text=None)


def test_observed_stale_storage_write_aborts_without_network(external):
    draft = _draft()
    external[0].write_state.return_value = False
    state = _state(draft)
    assert posting.post_approved(draft, state) == "failed"
    external[1].assert_not_called()
    assert draft["publish_outcome"] == "not_sent"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "not_sent"


@pytest.mark.parametrize("change", ["text", "intent", "identity", "missing_intent", "wrong_draft"])
def test_queued_manual_request_rejects_superseded_request(external, monkeypatch, change):
    draft = _draft()
    monkeypatch.setenv("DRAFT_ID", draft["id"])
    monkeypatch.setenv("TWEET_TEXT", draft["text"])
    monkeypatch.setenv("PUBLISH_INTENT_ID", draft["publish_intent_id"])
    if change == "text":
        monkeypatch.setenv("TWEET_TEXT", "different text that passes safety")
    elif change == "intent":
        monkeypatch.setenv("PUBLISH_INTENT_ID", "intent_old")
    elif change == "identity":
        # Same text after A -> B -> A still requires a new authorization.
        original_text = draft["text"]
        invalidate_text(draft, "A different draft.")
        invalidate_text(draft, original_text)
        record_human_review(draft)
        authorize_draft(draft, "manual", "intent_new")
        draft["status"] = "approved"
    elif change == "missing_intent":
        monkeypatch.delenv("PUBLISH_INTENT_ID")
    else:
        monkeypatch.setenv("DRAFT_ID", "nonexistent")
    posting.run_manual_tweet(_state(draft))
    external[1].assert_not_called()
    posting.run_safety_pipeline.assert_not_called()


def test_queued_manual_request_uses_exact_current_text(external, monkeypatch):
    draft = _draft()
    monkeypatch.setenv("DRAFT_ID", draft["id"])
    monkeypatch.setenv("TWEET_TEXT", draft["text"])
    monkeypatch.setenv("PUBLISH_INTENT_ID", draft["publish_intent_id"])
    posting.run_manual_tweet(_state(draft))
    external[1].assert_called_once_with(draft["text"], media_png=None, alt_text=None)
    assert draft["status"] == "posted"


@pytest.mark.parametrize("phase", [None, "submitted", "unknown"])
def test_old_unresolved_attempt_never_expires_or_retries(external, phase):
    draft = _draft("auto")
    row = {"intent_id": "old_attempt", "tweet_id": None, "at": "2000-01-01T00:00:00Z"}
    if phase:
        row["phase"] = phase
    state = _state(draft)
    state["publish_ledger"][draft["event_id"]] = deepcopy(row)
    posting.process_due_drafts(state)
    assert state["publish_ledger"][draft["event_id"]] == row
    external[1].assert_not_called()


def test_attempt_conflict_blocks_even_when_top_receipt_matches(external):
    draft = _draft()
    state = _state(draft)
    state["publish_ledger"][draft["event_id"]] = {
        **draft_identity(draft), "tweet_id": "known", "phase": "confirmed",
        "attempt_conflicts": [{"intent_id": "other", "phase": "unknown"}],
    }
    assert posting.post_approved(draft, state) == "failed"
    external[1].assert_not_called()


def test_lost_response_retains_attempt_and_blocks_reapproval_retry(external):
    draft = _draft()
    state = _state(draft)
    external[1].side_effect = TimeoutError("response lost")
    assert posting.post_approved(draft, state) == "failed"
    row = deepcopy(state["publish_ledger"][draft["event_id"]])
    assert row["phase"] == "unknown"
    assert draft["publish_outcome"] == "unknown"
    authorize_draft(draft, "manual", "new_queue_intent")
    assert posting.post_approved(draft, state) == "failed"
    assert state["publish_ledger"][draft["event_id"]] == row
    assert external[1].call_count == 1


def test_known_rate_limit_remains_retryable_for_unchanged_revision(external):
    draft = _draft("auto")
    state = _state(draft)
    external[1].side_effect = [{"error": "rate_limited"}, {"id": "second_attempt"}]
    assert posting.post_approved(draft, state) == "rate_limited"
    assert draft["publish_outcome"] == "not_sent"
    assert "autoship_attempted" not in draft
    assert posting.post_approved(draft, state) == "posted"
    assert external[1].call_count == 2


def test_receipt_for_older_revision_does_not_label_current_text_posted(external):
    draft = _draft("auto")
    receipt = {**draft_identity(draft), "text": draft["text"], "tweet_id": "older", "phase": "confirmed"}
    invalidate_text(draft, "A revised temperature statement.")
    state = _state(draft)
    state["publish_ledger"][draft["event_id"]] = deepcopy(receipt)
    posting.process_due_drafts(state)
    assert draft["status"] == "pending"
    assert not draft.get("tweet_id")
    assert state["publish_ledger"][draft["event_id"]] == receipt
    assert "another or unverified revision" in draft["post_error"]
    external[1].assert_not_called()


def test_matching_receipt_repairs_interrupted_submitted_state(external):
    draft = _draft("auto")
    attempt_at = "2026-06-12T12:00:00Z"
    confirmed_at = "2026-06-12T12:01:00Z"
    draft.update(publish_outcome="submitted", autoship_attempted=True, last_publish_attempt_at=attempt_at)
    state = _state(draft)
    state["publish_ledger"][draft["event_id"]] = {
        **draft_identity(draft), "text": draft["text"], "tweet_id": "already_sent", "phase": "confirmed",
        "at": attempt_at, "confirmed_at": confirmed_at,
    }
    posting.process_due_drafts(state)
    assert draft["status"] == "posted"
    assert draft["publish_outcome"] == "confirmed"
    assert draft["last_publish_attempt_at"] == attempt_at
    assert draft["posted_at"] == confirmed_at
    external[1].assert_not_called()


def test_sender_memory_uses_frozen_submitted_text_even_if_object_changes(external):
    draft = _draft()
    original = deepcopy(draft)
    state = _state(draft)

    def send(text, **kwargs):
        draft["text"] = "An unrelated edit during the network call."
        return {"id": "sent_original"}

    external[1].side_effect = send
    assert posting.post_approved(draft, state) == "posted"
    row = state["publish_ledger"][draft["event_id"]]
    assert row["text"] == original["text"]
    assert row["text_sha256"] == draft_identity(original)["text_sha256"]
    assert state["memory"]["shipped_tweets"][0]["tweet_text"] == original["text"]
    assert draft["status"] != "posted"


def test_appended_url_does_not_inherit_checks_for_original_text():
    original = "Bavi is forecast to approach the coast."
    draft = {
        "id": "url_append", "text": original + "\nhttps://example.test/advisory",
        "review_context": model_review_context(original),
    }
    initialize_revision(draft)
    assert not review_is_current(draft)


def test_explicit_ad_hoc_text_path_remains_separate(external, monkeypatch):
    monkeypatch.delenv("DRAFT_ID", raising=False)
    monkeypatch.delenv("PUBLISH_INTENT_ID", raising=False)
    monkeypatch.setenv("TWEET_TEXT", "  Ad hoc manual text.  ")
    posting.run_manual_tweet(deepcopy(DEFAULT_STATE))
    external[1].assert_called_once_with("Ad hoc manual text.", media_png=None, alt_text=None)


def test_success_receipt_merges_with_submitted_state_as_one_attempt(external):
    from src.state import _merge_publish_ledger

    draft = _draft()
    state = _state(draft)
    submitted = {}

    def write(incoming, **kwargs):
        submitted.update(deepcopy(incoming["publish_ledger"]))
        return True

    external[0].write_state.side_effect = write
    assert posting.post_approved(draft, state) == "posted"
    merged = _merge_publish_ledger(submitted, state["publish_ledger"])
    row = merged[draft["event_id"]]
    assert row["at"] == submitted[draft["event_id"]]["at"]
    assert row["confirmed_at"] == draft["posted_at"]
    assert row["phase"] == "confirmed"
    assert not row.get("attempt_conflicts")
    assert not has_unresolved_publish(draft, {"publish_ledger": merged})


def test_manual_daily_cap_refusal_does_not_create_unknown_attempt(external, monkeypatch):
    draft = _draft()
    monkeypatch.setenv("DRAFT_ID", draft["id"])
    monkeypatch.setenv("TWEET_TEXT", draft["text"])
    monkeypatch.setenv("PUBLISH_INTENT_ID", draft["publish_intent_id"])
    external[0].check_daily_cap.return_value = False
    state = _state(draft)
    posting.run_manual_tweet(state)
    assert not draft.get("last_publish_attempt_at")
    assert not has_unresolved_publish(draft, state)
    external[1].assert_not_called()


def test_human_reviewed_revision_records_text_without_old_model_claims():
    from src.two_bot.memory import record_published_draft

    draft = _draft()
    two_bot = draft["review_context"]["two_bot"]
    two_bot["angle_chosen"] = "old model interpretation"
    two_bot["fact_check"]["extracted_claims"] = [{"kind": "peer_comparison", "text": "old comparison"}]
    record_human_review(draft)
    draft.update(status="posted", tweet_id="human_text")
    state = _state(draft)
    assert record_published_draft(state, draft)
    assert state["memory"]["shipped_tweets"][0]["tweet_text"] == draft["text"]
    assert state["memory"]["used_peer_comparisons"] == []
    assert state["memory"]["used_framings"] == []
