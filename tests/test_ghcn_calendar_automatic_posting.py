"""Calendar admission at the real send boundaries; invented source and X replies."""
from copy import deepcopy

import pytest

from src.editorial import revisions
from src.orchestrator import posting
from tests.revision_helpers import bind_reviewed_draft
from tests.test_ghcn_publication_currentness import archive_http as archive_http, variants as variants
from tests.test_ghcn_publication_posting import approved_record, source_at_sender as source_at_sender
from tests.test_gist_temperature_posting import (
    fake_transport as fake_transport,
    invented_clock as invented_clock,
    state_for,
)

pytestmark = pytest.mark.usefixtures("automatic_publication_release", "invented_clock")


@pytest.fixture(autouse=True)
def observed_route(monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")


@pytest.fixture(params=["high", "low"])
def calendar(variants, request):
    return approved_record({("high", "all_time"): variants[(request.param, "calendar")]}, "auto")


def test_calendar_source_reread_and_one_fake_x_receipt(calendar, fake_transport, source_at_sender):
    state = state_for(calendar)
    before = deepcopy(calendar)
    posting.process_due_drafts(state)
    assert len(source_at_sender["calls"]) == 2
    assert fake_transport.calls == [("create", before["text"], {})]
    assert calendar["status"] == "posted" and calendar["tweet_id"] == "invented-x-receipt"
    assert state["publish_ledger"][calendar["event_id"]]["phase"] == "confirmed"
    posting.process_due_drafts(state)
    assert len(fake_transport.calls) == 1


@pytest.mark.parametrize("boundary", ["before_safety", "after_safety", "after_intent"])
def test_changed_calendar_archive_never_sends(calendar, fake_transport, source_at_sender, boundary):
    state = state_for(calendar)
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
    posting.process_due_drafts(state)
    assert not fake_transport.calls and not calendar.get("tweet_id")
    assert "ghcn_current_archive_changed" in calendar["post_error"]
    assert calendar["approval_mode"] == "manual" and not calendar.get("approval_binding")
    assert not revisions.has_unresolved_publish(calendar, state)


def test_auto_label_without_ghcn_evidence_stops_before_source_or_safety(calendar, fake_transport, source_at_sender):
    calendar["event_id"] = "invented-foreign-record"
    calendar["review_context"]["two_bot"]["bundle"] = {}
    bind_reviewed_draft(calendar, "auto")  # Mocked checks are not source evidence.
    state = state_for(calendar)
    posting.process_due_drafts(state)
    assert not source_at_sender["calls"] and not fake_transport.calls
    fake_transport.safety.assert_not_called()
    assert not state["publish_ledger"] and not calendar.get("approval_binding")
    assert "ghcn_calendar_source_required" in calendar["post_error"]


def test_calendar_edit_revokes_old_checks_and_approval(calendar, fake_transport, source_at_sender):
    state = state_for(calendar)
    revisions.invalidate_text(calendar, "An invented calendar comparison needing fresh checks.")
    assert not revisions.review_is_current(calendar) and not revisions.approval_is_current(calendar, "auto")
    posting.process_due_drafts(state)
    assert not fake_transport.calls and not calendar.get("tweet_id")


def test_unknown_calendar_delivery_is_not_resent(calendar, fake_transport, source_at_sender):
    state = state_for(calendar)
    fake_transport.failure = "empty_receipt"
    posting.process_due_drafts(state)
    row = deepcopy(state["publish_ledger"][calendar["event_id"]])
    assert row["phase"] == "unknown" and len(fake_transport.calls) == 1
    posting.process_due_drafts(state)
    assert len(fake_transport.calls) == 1 and state["publish_ledger"][calendar["event_id"]] == row
