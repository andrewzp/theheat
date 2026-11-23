"""Calendar admission at the real send boundaries; invented source and X replies."""
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from freezegun import freeze_time

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


@pytest.mark.parametrize("direction,kind", [("high", "record"), ("low", "record_low")])
def test_real_checked_calendar_save_becomes_due_and_sends_once(
    fake_transport, source_at_sender, monkeypatch, direction, kind,
):
    from src.editorial.scoring import score_record_event, score_record_low_event
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
    from src.state import DEFAULT_STATE
    from tests import ghcn_graphic_helpers as sources
    from tests.test_ghcn_calendar_automatic import NOW, copy_for
    from tests.test_observed_copy_guard_journey import _models

    monkeypatch.setattr(sources, "AS_OF", "2026-09-09T08:00:00Z")
    monkeypatch.setattr(sources, "STATION", {**sources.STATION, "name": "CALENDAR FIXTURE",
                                           "country_name": "United States"})
    bundle = sources.graphic_bundles(direction=direction, tier="calendar")[-1]
    text = copy_for(kind)
    models = _models(monkeypatch, copy=text)
    state = deepcopy(DEFAULT_STATE)
    raw = bundle.raw_signal_dump
    scorer = score_record_event if kind == "record" else score_record_low_event
    score = scorer(raw["new_temp_c"], raw["old_record_c"], raw["old_record_year"])
    with freeze_time(NOW, tick=True):
        assert _try_two_bot_draft(bundle, state, score, legacy_type=kind,
            event_id=bundle.event_id, city="Calendar Fixture", tweet_date="2026-09-08", review_context={})
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = state["drafts"]
    assert draft["approval_mode"] == "auto" and revisions.approval_is_current(draft, "auto")
    with freeze_time("2026-09-09T11:35:00Z"):
        posting.process_due_drafts(state)
        posting.process_due_drafts(state)
    assert fake_transport.calls == [("create", text, {})]
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-receipt"
    assert len(source_at_sender["calls"]) == 2
    assert state["publish_ledger"][bundle.event_id]["phase"] == "confirmed"


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


@pytest.mark.parametrize("withdrawal", ["observed", "autoship", "publication", "epoch"])
def test_calendar_send_refuses_withdrawn_authority(calendar, fake_transport, source_at_sender,
                                                 monkeypatch, withdrawal):
    flag = {"observed": "THEHEAT_OBSERVED_WEATHER_ONLY",
            "autoship": "THEHEAT_AUTOSHIP_ON_CRITIC_PASS",
            "publication": "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED",
            "epoch": "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH"}[withdrawal]
    monkeypatch.setenv(flag, "invented-new-epoch" if withdrawal == "epoch" else "0")
    state = state_for(calendar)
    posting.process_due_drafts(state)
    assert not fake_transport.calls and not calendar.get("tweet_id")
    assert not state["publish_ledger"]
    fake_transport.safety.assert_not_called()


@pytest.mark.parametrize("boundary", ["safety", "intent", "archive"])
@pytest.mark.parametrize("change", ["autoship", "publication", "epoch", "freshness"])
def test_calendar_rechecks_authority_and_clock_after_safety_storage_and_source_io(
    calendar, fake_transport, source_at_sender, monkeypatch, boundary, change,
):
    calendar["autoship_on_critic_pass"] = True
    def withdraw():
        if change == "freshness":
            monkeypatch.setattr(posting, "_utc_now", lambda: datetime(2026, 9, 9, 12, 1, tzinfo=UTC))
        else:
            key = {"autoship": "THEHEAT_AUTOSHIP_ON_CRITIC_PASS",
                   "publication": "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED",
                   "epoch": "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH"}[change]
            monkeypatch.setenv(key, "invented-new-epoch" if change == "epoch" else "0")
    if boundary == "safety":
        def safety(_text):
            withdraw()
            return True, None
        fake_transport.safety.side_effect = safety
    elif boundary == "intent":
        write = fake_transport.storage.write_state.side_effect
        def persist(*args, **kwargs):
            result = write(*args, **kwargs)
            withdraw()
            return result
        fake_transport.storage.write_state.side_effect = persist
    else:
        from src.data import _http
        fetch = _http.fetch_with_retry
        def response(*args, **kwargs):
            result = fetch(*args, **kwargs)
            if len(source_at_sender["calls"]) == 2:
                withdraw()
            return result
        monkeypatch.setattr(_http, "fetch_with_retry", response)
    state = state_for(calendar)
    posting.process_due_drafts(state)
    assert not fake_transport.calls and not calendar.get("tweet_id")
    assert calendar["publish_outcome"] == "not_sent"
    assert not revisions.has_unresolved_publish(calendar, state)
    assert all(row["phase"] == "not_sent" for row in state["publish_ledger"].values())


@pytest.mark.parametrize("timer", ["future", "shortened", "missing", "missing_request"])
def test_direct_calendar_sender_preserves_the_due_time_and_minimum_review_window(
    calendar, fake_transport, source_at_sender, timer,
):
    if timer == "future":
        calendar["auto_approve_at"] = "2026-09-09T13:30:00Z"
    elif timer == "shortened":
        calendar["created_at"] = "2026-09-09T11:00:00Z"
        calendar["auto_approve_at"] = "2026-09-09T11:50:00Z"
    elif timer == "missing":
        calendar.pop("auto_approve_at")
    else:
        calendar.pop("auto_approve_requested_at")
    state = state_for(calendar)
    assert posting.post_approved(calendar, state) == "failed"
    assert not fake_transport.calls and not source_at_sender["calls"]
    assert not state["publish_ledger"] and not calendar.get("tweet_id")


def test_unknown_calendar_delivery_is_not_resent(calendar, fake_transport, source_at_sender):
    state = state_for(calendar)
    fake_transport.failure = "empty_receipt"
    posting.process_due_drafts(state)
    row = deepcopy(state["publish_ledger"][calendar["event_id"]])
    assert row["phase"] == "unknown" and len(fake_transport.calls) == 1
    posting.process_due_drafts(state)
    assert len(fake_transport.calls) == 1 and state["publish_ledger"][calendar["event_id"]] == row
