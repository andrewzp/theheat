"""Final current automatic authority; all storage, source and X replies invented."""
from copy import deepcopy
import socket

import pytest

from src.editorial import observed_scope
from src.orchestrator import posting
from tests.test_revision_posting import _draft, _state, external as external
from tests.test_ghcn_publication_currentness import archive_http as archive_http, variants as variants
from tests.test_ghcn_publication_posting import approved_record, source_at_sender as source_at_sender
from tests.test_gist_temperature_posting import (
    fake_transport as fake_transport,
    invented_clock as invented_clock,
    state_for,
)

pytestmark = pytest.mark.usefixtures("automatic_publication_release")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Final-authority fixtures forbid real network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def withdraw(monkeypatch, state, draft, change):
    if change == "pause":
        monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    elif change == "epoch":
        monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "invented-new-final-epoch")
    elif change == "retired":
        state["publication_control"] = {
            "retired_epochs": [draft["approval_binding"]["publication_epoch"]]}
    else:
        state["publication_control"] = {"invalid_control": True, "retired_epochs": []}


def after_boundary(monkeypatch, storage, boundary, callback):
    if boundary == "intent":
        def persist(*args, **kwargs):
            callback()
            return True
        storage.write_state.side_effect = persist
    elif boundary == "source":
        original = posting._current_nws_source
        def source(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs["live"]:
                callback()
            return result
        monkeypatch.setattr(posting, "_current_nws_source", source)
    elif boundary == "policy":
        original = posting.approval_is_current
        def policy(*args, **kwargs):
            result = original(*args, **kwargs)
            if storage.write_state.called:
                callback()
            return result
        monkeypatch.setattr(posting, "approval_is_current", policy)
    else:
        original = observed_scope.story_hold
        def scope(*args, **kwargs):
            result = original(*args, **kwargs)
            if storage.write_state.called:
                callback()
            return result
        monkeypatch.setattr(observed_scope, "story_hold", scope)


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("boundary", ["intent", "source", "policy", "scope"])
@pytest.mark.parametrize("change", ["pause", "epoch", "retired", "invalid"])
def test_withdrawal_after_intent_never_reaches_the_platform(
    external, monkeypatch, marked, boundary, change,
):
    storage, send = external
    draft = _draft("auto")
    if not marked:
        draft.pop("autoship_on_critic_pass")
    state = _state(draft)
    original = deepcopy(draft)
    after_boundary(monkeypatch, storage, boundary,
                   lambda: withdraw(monkeypatch, state, draft, change))
    assert posting.post_approved(draft, state) == "failed"
    send.assert_not_called()
    storage.write_state.assert_called_once()
    assert storage.write_state.call_args.kwargs["expected_draft"] == original
    row = state["publish_ledger"][draft["event_id"]]
    assert row["phase"] == draft["publish_outcome"] == "not_sent"
    assert row["text"] == original["text"] and not row.get("tweet_id")
    assert not draft.get("autoship_attempted") and not draft.get("approval_binding")
    storage.increment_daily_count.assert_not_called()
    posting.post_to_bluesky.assert_not_called()


@pytest.mark.parametrize("marked", [False, True])
def test_current_automatic_authority_keeps_one_exact_receipt(external, marked):
    storage, send = external
    draft = _draft("auto")
    if not marked:
        draft.pop("autoship_on_critic_pass")
    state = _state(draft)
    assert posting.post_approved(draft, state) == "posted"
    send.assert_called_once_with(draft["text"], media_png=None, alt_text=None)
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert draft["tweet_id"] == "tweet_current"
    storage.increment_daily_count.assert_called_once_with(state)
    assert posting.post_approved(draft, state) == "failed"
    assert send.call_count == 1 and storage.write_state.call_count == 1


@pytest.mark.parametrize("change", ["pause", "epoch", "retired", "invalid"])
def test_manual_approval_stays_independent_of_the_automatic_switch(external, monkeypatch, change):
    storage, send = external
    draft = _draft("manual")
    state = _state(draft)
    automatic_identity = {"approval_binding": {
        "publication_epoch": "invented-manual-independent-epoch"}}
    after_boundary(monkeypatch, storage, "intent",
                   lambda: withdraw(monkeypatch, state, automatic_identity, change))
    assert posting.post_approved(draft, state) == "posted"
    assert draft["tweet_id"] == "tweet_current" and send.call_count == 1
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"


@pytest.mark.parametrize("outcome", ["unknown", "confirmed"])
@pytest.mark.parametrize("change", ["pause", "epoch", "retired", "invalid"])
def test_withdrawal_preserves_a_previous_outcome_and_never_resends(
    external, monkeypatch, outcome, change,
):
    storage, send = external
    draft = _draft("auto")
    state = _state(draft)
    if outcome == "unknown":
        send.return_value = None
    assert posting.post_approved(draft, state) == ("posted" if outcome == "confirmed" else "failed")
    retained = deepcopy(state["publish_ledger"])
    original_outcome = draft["publish_outcome"]
    withdraw(monkeypatch, state, draft, change)
    assert posting.post_approved(draft, state) == "failed"
    assert state["publish_ledger"] == retained and draft["publish_outcome"] == original_outcome
    assert send.call_count == 1 and storage.write_state.call_count == 1


@pytest.mark.usefixtures("invented_clock")
def test_full_ghcn_source_cannot_override_a_pause_after_its_saved_intent(
    variants, fake_transport, source_at_sender, monkeypatch,
):
    draft = approved_record(variants, "auto")
    state = state_for(draft)
    original_write = fake_transport.storage.write_state.side_effect
    def write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
        return result
    fake_transport.storage.write_state.side_effect = write
    assert posting.post_approved(draft, state) == "failed"
    assert len(source_at_sender["calls"]) == 1
    assert not fake_transport.calls and not draft.get("tweet_id")
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "not_sent"
