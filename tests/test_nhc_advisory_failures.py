"""Remaining consumer-failure cases for the ordinary manual sender (invented data only).

Source, import, dashboard and fresh-process cases live beside their deliverables; this
file covers the sender cases they do not: final-check failure, changed policy, labels
or roles that grant nothing, issue/advisory mismatch, clock regression and replay.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.editorial import revisions
from tests import nhc_advisory_helpers as h
from tests.nhc_advisory_pipeline_helpers import Transport, generate
from tests.test_nhc_advisory_sender import approved, fake_sender, send
from tests.two_bot.conftest import configured_pipeline_providers as configured_pipeline_providers

pytestmark = pytest.mark.usefixtures("configured_pipeline_providers")
LATER = h.NOW + timedelta(minutes=5)


def test_final_safety_rejection_creates_no_intent_or_send(monkeypatch):
    state, draft = approved(monkeypatch)
    fake = fake_sender(monkeypatch, draft, Transport())
    fake.safety.side_effect = lambda text: (False, "Explicit invented offline safety rejection")
    send(fake, state, lambda: LATER)
    assert fake.calls == [] and fake.persisted == [] and draft["status"] != "posted"
    assert draft["event_id"] not in state.get("publish_ledger", {})


def test_unavailable_final_safety_is_not_a_pass(monkeypatch):
    from src.voice import safety
    state, draft = approved(monkeypatch)
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)

    class Outage:
        """Invented Gemini client whose one attempt is lost; the real safety path runs."""

        def __init__(self, *args, **kwargs):
            self.models = SimpleNamespace(generate_content=self.lost)

        def lost(self, **request):
            raise TimeoutError("invented safety outage")

        def close(self):
            return None
    monkeypatch.setattr("google.genai.Client", Outage)
    fake.safety.side_effect = safety.run_safety_pipeline
    send(fake, state, lambda: LATER)
    assert fake.calls == [] and fake.persisted == [] and draft["status"] != "posted"
    assert len(transport.calls) == 4  # Entry read, then the live read at the safety attempt.


def test_a_policy_change_after_approval_sends_nothing_and_reads_nothing(monkeypatch):
    state, draft = approved(monkeypatch)
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)
    monkeypatch.setattr("src.voice.safety.GEMINI_SAFETY_MODEL", "invented-changed-safety-model")
    send(fake, state, lambda: LATER)
    assert fake.calls == [] and fake.safety.call_count == 0 and transport.calls == []
    assert not revisions.approval_is_current(draft, "manual")


@pytest.mark.parametrize("label", [{"human_reviewed": True}, {"review_kind": "human", "review_status": "passed"},
                                   {"approved": True, "status": "approved"}], ids=["human-reviewed", "kind", "approved"])
def test_labels_without_bindings_grant_nothing(monkeypatch, label):
    state, _ = generate(monkeypatch, Transport())
    draft = state["drafts"][0]
    draft.pop("review_binding", None)  # Only labels remain; no review or approval binding.
    draft.update(label, publish_intent_id="invented-nhc-intent")
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)
    send(fake, state, lambda: LATER)
    assert fake.calls == [] and fake.safety.call_count == 0 and transport.calls == []


def test_a_model_only_review_cannot_be_promoted_to_manual_approval_without_a_binding(monkeypatch):
    state, _ = generate(monkeypatch, Transport())
    draft = state["drafts"][0]
    assert draft["review_binding"]["kind"] == "model"  # The pipeline's checks, not a human review or approval.
    draft.update(status="approved", publish_intent_id="invented-nhc-intent")
    fake = fake_sender(monkeypatch, draft, Transport())
    send(fake, state, lambda: LATER)
    assert fake.calls == [] and not revisions.approval_is_current(draft, "manual")


@pytest.mark.parametrize("change,code", [
    ({h.URL: (200, {}, h.page(h.bulletin(advisory="35")))}, "nhc_advisory_issue_mismatch"),
    ({h.URL: (200, {}, h.page(h.bulletin(office="NWS National Hurricane Center Miami FL       EP482026")))},
     "nhc_advisory_contradictory"),
    ({h.URL: (200, {"content-encoding": "gzip"}, h.page())}, "nhc_advisory_encoding_invalid"),
    ({h.URL: (200, {"content-length": "9"}, h.page())}, "nhc_advisory_partial_response"),
    ({h.URL: (500, {}, b"")}, "nhc_advisory_source_unavailable"),
    ({h.URL: (200, {}, h.page() + h.page())}, "nhc_advisory_format_drift"),
], ids=["advisory-mismatch", "storm-mismatch", "encoded", "short", "unavailable", "two-bulletins"])
def test_issue_advisory_mismatch_or_malformed_reads_hold_at_entry(monkeypatch, change, code):
    state, draft = approved(monkeypatch)
    fake = fake_sender(monkeypatch, draft, Transport(change))
    send(fake, state, lambda: LATER)
    assert fake.calls == [] and fake.safety.call_count == 0 and fake.persisted == []
    assert code in draft["post_error"]


def test_a_clock_before_the_capture_holds(monkeypatch):
    state, draft = approved(monkeypatch)
    transport = Transport()
    fake = fake_sender(monkeypatch, draft, transport)
    send(fake, state, lambda: h.CAPTURED - timedelta(minutes=1))
    assert fake.calls == [] and transport.calls == [] and "nhc_advisory_time_incoherent" in draft["post_error"]


def test_replaying_a_posted_event_under_a_new_draft_id_never_resends(monkeypatch):
    state, draft = approved(monkeypatch)
    fake = fake_sender(monkeypatch, draft, Transport())
    send(fake, state, lambda: LATER)
    assert len(fake.calls) == 1 and draft["status"] == "posted"
    copy = {k: v for k, v in draft.items() if k not in ("status", "tweet_id", "posted_at", "publish_outcome")}
    copy.update(id="replayed-nhc-draft", status="approved")
    state["drafts"].append(copy)
    monkeypatch.setenv("DRAFT_ID", copy["id"])
    send(fake, state, lambda: LATER + timedelta(minutes=1))
    assert len(fake.calls) == 1  # The event's publish history refuses a second delivery.
