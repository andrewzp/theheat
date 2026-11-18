"""Current-source agreement at real manual/automatic send boundaries; invented I/O."""
from copy import deepcopy

import pytest

from src.editorial import revisions
from src.orchestrator import posting
from tests.revision_helpers import bind_reviewed_draft
from tests.test_ghcn_publication_currentness import archive_http as archive_http, relabelled_record, variants as variants
from tests.test_gist_temperature_posting import (
    fake_transport as fake_transport,
    invented_clock as invented_clock,
    state_for,
)

pytestmark = pytest.mark.usefixtures("automatic_publication_release", "invented_clock")


@pytest.fixture
def source_at_sender(fake_transport, archive_http):
    # Establish the HTTP fixture after the shared fake-X fixture; no source
    # verdict, parser, review function, sender or state transition is replaced.
    return archive_http


def approved_record(variants, mode):
    draft = deepcopy(variants[("high", "all_time")])
    draft.update(status="pending", created_at="2026-09-09T11:00:00Z", updated_at="2026-09-09T11:00:00Z")
    if mode == "manual":
        revisions.initialize_revision(draft)
        revisions.record_human_review(draft)
        revisions.authorize_draft(draft, mode, "invented-ghcn-manual-intent")
        draft.update(status="approved", approval_mode="manual")
    else:
        # Explicit offline model-review fixture. This proves sender authority
        # and source checks, not real model performance or production arming.
        draft.update(approval_mode="auto", auto_approve_at="2026-09-09T11:50:00Z",
                     approval_policy={"mode": "armed_auto", "can_auto_approve": True})
        bind_reviewed_draft(draft, mode)
    assert revisions.approval_is_current(draft, mode)
    return draft


def run_sender(draft, state, mode, monkeypatch):
    if mode == "manual":
        monkeypatch.setenv("DRAFT_ID", draft["id"])
        monkeypatch.setenv("TWEET_TEXT", draft["text"])
        monkeypatch.setenv("PUBLISH_INTENT_ID", draft["publish_intent_id"])
        return posting.run_manual_tweet(state)
    return posting.process_due_drafts(state)


@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_real_senders_persist_intent_then_return_only_the_invented_exact_x_receipt(
    variants, fake_transport, source_at_sender, monkeypatch, mode,
):
    draft = approved_record(variants, mode)
    original = deepcopy(draft)
    identity = revisions.draft_identity(draft)
    state = state_for(draft)
    run_sender(draft, state, mode, monkeypatch)
    assert len(source_at_sender["calls"]) == 2  # entry before safety, then after durable intent
    fake_transport.safety.assert_called_once_with(original["text"])
    assert fake_transport.calls == [("create", original["text"], {})]
    assert len(fake_transport.persisted) == 1
    saved, expectations = fake_transport.persisted[0]
    assert expectations["expected_draft"] == original
    assert saved["publish_ledger"][draft["event_id"]]["phase"] == "submitted"
    row = state["publish_ledger"][draft["event_id"]]
    assert row["phase"] == "confirmed" and row["tweet_id"] == draft["tweet_id"] == "invented-x-receipt"
    assert draft["status"] == "posted"
    assert all(row[key] == value for key, value in identity.items())
    assert draft["review_context"]["two_bot"]["bundle"] == original["review_context"]["two_bot"]["bundle"]
    assert posting.post_approved(draft, state) == "failed"
    assert len(fake_transport.calls) == 1 and len(fake_transport.persisted) == 1
    posting.post_to_bluesky.assert_not_called()


@pytest.mark.parametrize("mode", ["manual", "auto"])
@pytest.mark.parametrize("boundary", ["before_safety", "after_safety", "after_intent"])
def test_current_archive_drift_never_sends_and_leaves_the_next_edit_free(
    variants, fake_transport, source_at_sender, monkeypatch, mode, boundary,
):
    draft = approved_record(variants, mode)
    state = state_for(draft)
    old_bundle = deepcopy(draft["review_context"]["two_bot"]["bundle"])
    if boundary == "before_safety":
        source_at_sender["bytes"] += b"\n"
    elif boundary == "after_safety":
        def safety(_text):
            source_at_sender["bytes"] += b"\n"
            return True, None
        fake_transport.safety.side_effect = safety
    else:
        original_write = fake_transport.storage.write_state.side_effect
        def write(*args, **kwargs):
            result = original_write(*args, **kwargs)
            source_at_sender["bytes"] += b"\n"
            return result
        fake_transport.storage.write_state.side_effect = write
    run_sender(draft, state, mode, monkeypatch)
    assert not fake_transport.calls and not draft.get("tweet_id")
    assert "ghcn_current_archive_changed" in draft["post_error"]
    assert "GHCN station record" in draft["post_error"]
    assert draft["status"] == "pending" and draft["approval_mode"] == "manual"
    assert not draft.get("approval_binding") and not draft.get("auto_approve_at")
    assert draft["review_context"]["two_bot"]["bundle"] == old_bundle
    if boundary == "before_safety":
        fake_transport.safety.assert_not_called()
        assert not state["publish_ledger"] and not fake_transport.persisted
        assert "last_publish_attempt_at" not in draft
    else:
        fake_transport.safety.assert_called_once()
        assert len(fake_transport.persisted) == 1
        assert state["publish_ledger"][draft["event_id"]]["phase"] == draft["publish_outcome"] == "not_sent"
    assert not revisions.has_unresolved_publish(draft, state)
    revisions.invalidate_text(draft, "Another invented station comparison for review.")
    revisions.record_human_review(draft)
    revisions.authorize_draft(draft, "manual", "invented-next-edit")
    assert revisions.approval_is_current(draft, "manual")
    assert not revisions.has_unresolved_publish(draft, state)


@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_full_source_guard_does_not_erase_or_resend_an_unknown_transport_outcome(
    variants, fake_transport, source_at_sender, monkeypatch, mode,
):
    draft = approved_record(variants, mode)
    state = state_for(draft)
    fake_transport.failure = "empty_receipt"
    run_sender(draft, state, mode, monkeypatch)
    row = deepcopy(state["publish_ledger"][draft["event_id"]])
    assert row["phase"] == "unknown" and draft["publish_outcome"] == "unknown"
    assert len(fake_transport.calls) == 1
    assert posting.post_approved(draft, state) == "failed"
    assert state["publish_ledger"][draft["event_id"]] == row
    assert len(fake_transport.calls) == 1


@pytest.mark.parametrize("kind", ["station_only", "station_and_facts"])
def test_human_review_cannot_make_relabelled_station_evidence_bypass_current_source(
    variants, fake_transport, source_at_sender, monkeypatch, kind,
):
    changed = relabelled_record(variants[("high", "all_time")], kind)
    draft = approved_record({("high", "all_time"): changed}, "manual")
    state = state_for(draft)
    run_sender(draft, state, "manual", monkeypatch)
    assert not fake_transport.calls and not state["publish_ledger"]
    assert not source_at_sender["calls"]
    fake_transport.safety.assert_not_called()
    assert draft["publish_outcome"] == "not_sent" and not draft.get("approval_binding")
