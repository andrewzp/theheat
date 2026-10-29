"""Offline full-source sender regressions; Gist, safety and X are explicit fakes.

The render interruption is a pure Python exception, not a process-death test.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from freezegun import freeze_time
import pytest

from src.media import gist_media, gist_temperature_media as media
from src.orchestrator import posting
from tests.test_gist_temperature_posting import state_for

pytest_plugins = ["tests.test_gist_temperature_posting"]


def test_render_interruption_creates_no_attempt_or_storage_write(draft_factory, fake_transport, monkeypatch):
    class InventedRenderInterruption(BaseException):
        pass

    def interrupt(_bundle):
        raise InventedRenderInterruption()

    draft = draft_factory()
    state = state_for(draft)
    original = deepcopy(state)
    monkeypatch.setattr(media, "prepare_media", interrupt)
    with pytest.raises(InventedRenderInterruption):
        posting.post_approved(draft, state)
    assert state == original
    assert fake_transport.calls == [] and fake_transport.persisted == []
    fake_transport.storage.write_state.assert_not_called()


def test_render_refusal_creates_no_attempt_or_storage_write(draft_factory, fake_transport, monkeypatch):
    def refuse(_bundle):
        raise OSError("invented missing embedded font")

    draft = draft_factory()
    state = state_for(draft)
    monkeypatch.setattr(media, "prepare_media", refuse)
    assert posting.post_approved(draft, state) == "failed"
    assert state["publish_ledger"] == {}
    assert "last_publish_attempt_at" not in draft
    assert fake_transport.calls == [] and fake_transport.persisted == []
    fake_transport.storage.write_state.assert_not_called()


@pytest.mark.parametrize("boundary", ["render", "intent_write"])
def test_temperature_expiry_is_rechecked_after_each_boundary(draft_factory, fake_transport, monkeypatch, boundary):
    draft = draft_factory()
    state = state_for(draft)
    render, write = media.prepare_media, fake_transport.storage.write_state.side_effect
    completed = []
    with freeze_time("2026-09-12T23:59:59Z") as clock:
        def slow_render(bundle):
            value = render(bundle)
            completed.append("render")
            if boundary == "render":
                clock.move_to("2026-09-13T00:00:01Z")
            return value

        def slow_write(bot_state, **expected):
            assert completed == ["render"], "render must finish before durable intent"
            value = write(bot_state, **expected)
            clock.move_to("2026-09-13T00:00:01Z")
            return value

        monkeypatch.setattr(media, "prepare_media", slow_render)
        if boundary == "intent_write":
            fake_transport.storage.write_state.side_effect = slow_write
        assert posting.post_approved(draft, state) == "failed"
    assert fake_transport.calls == []
    assert draft["publish_outcome"] == "not_sent"
    assert len(fake_transport.persisted) == (0 if boundary == "render" else 1)
    if boundary == "render":
        assert state["publish_ledger"] == {} and "last_publish_attempt_at" not in draft
    else:
        saved, _expected = fake_transport.persisted[0]
        assert saved["publish_ledger"][draft["event_id"]]["phase"] == "submitted"
        assert state["publish_ledger"][draft["event_id"]]["phase"] == "not_sent"


def test_preflight_preserves_original_conditional_write_snapshots(draft_factory, fake_transport, monkeypatch):
    draft = draft_factory()
    state = state_for(draft)
    old = {"intent_id": "invented-proven-not-sent", "phase": "not_sent", "tweet_id": None}
    state["publish_ledger"][draft["event_id"]] = deepcopy(old)
    original = deepcopy(draft)
    render = media.prepare_media

    def concurrent_edit(bundle):
        value = render(bundle)
        draft["text"] = "Invented concurrent edit while the saved snapshot renders."
        return value

    def reject_stale_write(bot_state, **expected):
        assert expected == {"expected_draft": original, "expected_publish_ledger": old}
        assert fake_transport.calls == []
        return False  # Explicit offline Gist stale-write refusal.

    monkeypatch.setattr(media, "prepare_media", concurrent_edit)
    fake_transport.storage.write_state.side_effect = reject_stale_write
    assert posting.post_approved(draft, state) == "failed"
    fake_transport.storage.write_state.assert_called_once()
    assert fake_transport.calls == [] and fake_transport.persisted == []
    assert "expected revision" in draft["post_error"]


def test_temperature_final_dispatch_check_requires_aware_utc_clock(draft_factory):
    draft = draft_factory()
    gist_media.recheck_before_upload(draft, now=datetime(2026, 9, 12, 23, 59, tzinfo=timezone.utc))
    gist_media.recheck_before_upload(draft, now=datetime(2026, 9, 13, 1, tzinfo=timezone(timedelta(hours=2))))
    with pytest.raises(ValueError, match="future or stale"):
        gist_media.recheck_before_upload(draft, now=datetime(2026, 9, 13, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="future or stale"):
        gist_media.recheck_before_upload(draft, now=datetime(2026, 9, 12, 23, tzinfo=timezone(timedelta(hours=-2))))
    with pytest.raises(ValueError, match="timezone-aware"):
        gist_media.recheck_before_upload(draft, now=datetime(2026, 9, 12))
