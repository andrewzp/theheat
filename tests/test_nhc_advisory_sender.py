"""Sender ownership: the ordinary manual sender re-reads the fixed NHC products itself."""
from datetime import timedelta
import sys

import pytest

from src.data import nhc_advisory as source
from src.editorial import revisions
from src.editorial.nhc_advisory_runtime import AdvisoryOwner, advisory_owner_scope, current_owner
from src.two_bot import trial_budget
from tests import nhc_advisory_helpers as h
from tests.gist_media_helpers import install_fake_x
from tests.nhc_advisory_pipeline_helpers import Transport, generate
from tests.two_bot.conftest import configured_pipeline_providers as configured_pipeline_providers

pytestmark = pytest.mark.usefixtures("configured_pipeline_providers")
PAIR = [source.INDEX_URL, h.URL]


def approved(monkeypatch):
    """A genuinely generated pending draft plus EXPLICIT fixture human actions."""
    state, _ = generate(monkeypatch, Transport())
    draft = state["drafts"][0]
    revisions.record_human_review(draft)  # Explicit invented review action; never a real review record.
    revisions.authorize_draft(draft, "manual", "invented-nhc-intent")
    draft.update(status="approved", publish_intent_id="invented-nhc-intent")
    return state, draft


def fake_sender(monkeypatch, draft, transport, *, on_safety=None):
    from src import state as real_state
    fake = install_fake_x(monkeypatch)
    fake.storage.record_event.side_effect = real_state.record_event
    monkeypatch.setattr(fake.posting, "_hot10_media_for_draft", lambda draft: (None, None))
    monkeypatch.setattr(source, "_http_get", transport)

    def safety(text):
        if on_safety is not None:
            on_safety()
        # The final safety purchase goes through the real provider boundary.
        trial_budget.provider_call("safety", "google", {"model": "invented-safety"}, lambda **r: object())
        return True, None
    fake.safety.side_effect = safety
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]),
                        ("PUBLISH_INTENT_ID", draft["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    return fake


def send(fake, state, clock):
    with advisory_owner_scope(AdvisoryOwner(clock=clock)):
        fake.posting.run_manual_tweet(state)
        return source.current_budget().used


def test_owner_rereads_at_entry_final_safety_and_after_intent_then_never_resends(monkeypatch):
    state, draft = approved(monkeypatch)
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)
    used = send(fake, state, lambda: h.NOW + timedelta(minutes=5))
    assert draft["status"] == "posted" and fake.calls == [("create", draft["text"], {})]
    assert used == 6 and transport.calls == PAIR * 3  # Entry, final-safety attempt, after the durable intent.
    assert state["publish_ledger"][draft["event_id"]]["tweet_id"] == "invented-x-receipt"
    assert draft["event_id"] in state["posted_events"] and fake.safety.call_count == 1
    with advisory_owner_scope(AdvisoryOwner(clock=lambda: h.NOW + timedelta(minutes=6))):
        assert fake.posting.post_approved(draft, state) == "failed"
    assert len(fake.calls) == 1  # No resend.


def test_missing_owner_holds_before_paid_final_safety_or_intent(monkeypatch):
    state, draft = approved(monkeypatch)
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)
    fake.posting.run_manual_tweet(state)  # No owner installed in this (library) call.
    assert fake.calls == [] and fake.safety.call_count == 0 and fake.persisted == [] and transport.calls == []
    assert draft["status"] == "pending" and "approval_binding" not in draft
    assert draft["post_error"] == "NHC advisory needs fresh source review: nhc_advisory_current_source_unavailable"


@pytest.mark.parametrize("change,code", [
    ({source.INDEX_URL: (200, {}, h.index(advisory="35"))}, "nhc_advisory_superseded"),
    ({source.INDEX_URL: (200, {}, h.index(storms=[]))}, "nhc_advisory_storm_not_current"),
    ({h.URL: (200, {}, h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4"))))},
     "nhc_advisory_current_source_changed"),
    ({h.URL: (302, {"location": "https://evil.example.test/"}, b"")}, "nhc_advisory_redirect_refused"),
    ({h.URL: (200, {}, h.page()[:200])}, "nhc_advisory_format_drift"),
], ids=["superseded", "removed", "corrected", "redirect", "partial"])
def test_changed_or_unavailable_source_at_entry_holds_before_final_safety(monkeypatch, change, code):
    state, draft = approved(monkeypatch)
    fake = fake_sender(monkeypatch, draft, Transport(change))
    send(fake, state, lambda: h.NOW + timedelta(minutes=5))
    assert fake.calls == [] and fake.safety.call_count == 0 and fake.persisted == []
    assert draft["status"] == "pending" and draft["post_error"].endswith(code)


def test_correction_during_final_safety_creates_no_intent_or_send(monkeypatch):
    state, draft = approved(monkeypatch)
    transport = Transport()

    def correct():
        transport.responses[h.URL] = (200, {}, h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4"))))
    fake = fake_sender(monkeypatch, draft, transport, on_safety=correct)
    send(fake, state, lambda: h.NOW + timedelta(minutes=5))
    assert fake.calls == [] and fake.persisted == [] and draft["status"] == "pending"
    assert "nhc_advisory_current_source_changed" in draft["post_error"]


def test_correction_after_the_durable_intent_is_not_sent_and_not_unknown(monkeypatch):
    state, draft = approved(monkeypatch)
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)
    original = fake.storage.write_state.side_effect

    def persist(*args, **kwargs):
        result = original(*args, **kwargs)
        transport.responses[h.URL] = (200, {}, h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4"))))
        return result
    fake.storage.write_state.side_effect = persist
    send(fake, state, lambda: h.NOW + timedelta(minutes=5))
    assert len(fake.persisted) == 1 and fake.calls == []
    assert draft["publish_outcome"] == "not_sent"


def test_operator_deadline_passing_during_final_safety_holds(monkeypatch):
    state, draft = approved(monkeypatch)
    clock = {"now": h.NOW + timedelta(minutes=5)}

    def late():
        clock["now"] = h.NOW + timedelta(minutes=31)  # Past capture + 30 minutes.
    fake = fake_sender(monkeypatch, draft, Transport(), on_safety=late)
    send(fake, state, lambda: clock["now"])
    assert fake.calls == [] and fake.persisted == []
    assert "nhc_advisory_operator_deadline_passed" in draft["post_error"]


def test_text_changed_after_approval_invalidates_it_before_any_read_or_purchase(monkeypatch):
    state, draft = approved(monkeypatch)
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)
    draft["text"] = "Rain could flood Example Province tonight."
    monkeypatch.setenv("TWEET_TEXT", draft["text"])
    send(fake, state, lambda: h.NOW + timedelta(minutes=5))
    assert fake.calls == [] and fake.safety.call_count == 0 and transport.calls == []
    assert not revisions.approval_is_current(draft, "manual")


def test_lost_create_response_stays_unknown_and_is_never_resent(monkeypatch):
    state, draft = approved(monkeypatch)
    fake = fake_sender(monkeypatch, draft, Transport())
    fake.failure = "create"
    with advisory_owner_scope(AdvisoryOwner(clock=lambda: h.NOW + timedelta(minutes=5))):
        assert fake.posting.post_approved(draft, state) == "failed"
        assert fake.posting.post_approved(draft, state) == "failed"
    assert len(fake.calls) == 1 and draft["publish_outcome"] == "unknown" and len(fake.persisted) == 1


def test_the_ordinary_cli_installs_an_owner_for_every_mode(monkeypatch):
    from src.orchestrator import cli
    seen = {}
    monkeypatch.setattr(cli.state, "read_state", lambda: {"drafts": []})
    monkeypatch.setattr(cli.state, "write_state", lambda *a, **k: True)
    monkeypatch.setattr(cli.state, "finalize_run", lambda *a, **k: None)
    monkeypatch.setattr(cli.runtime_inventory, "collect_runtime_inventory", lambda *a, **k: {})

    def record(mode):
        def run(bot_state, current_run=None):
            seen[mode] = (current_owner() is not None, source.current_budget().remaining)
            return bot_state
        return run
    for mode in ("manual_tweet", "alerts", "auto_publish_due"):
        monkeypatch.setattr(sys, "argv", ["src.main", mode])
        cli.main({name: record(name) for name in ("alerts", "leaderboard", "manual_tweet", "auto_publish_due")})
    assert seen == {"manual_tweet": (True, 32), "alerts": (True, 32), "auto_publish_due": (True, 32)}
