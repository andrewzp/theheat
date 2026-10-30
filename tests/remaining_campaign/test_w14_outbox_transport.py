"""W14.3: X outbox stage classification through the real publisher and adapter.

Fake tweepy-shaped objects only; DNS and every socket connect are trapped. The
invented draft names a fictional place. No real X call is possible.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
import tweepy

from src.editorial.revisions import has_unresolved_publish
from src.orchestrator import posting
from src.posting import outbox_outcome, twitter
from src.state import DEFAULT_STATE
from tests.live_content_harness import trap_network
from tests.revision_helpers import bind_reviewed_draft

pytestmark = pytest.mark.usefixtures("automatic_publication_release")

PNG = b"\x89PNG\r\n\x1a\ninvented-w14-graphic"
ALT = "Invented chart: Fenwick Hollow daily highs."


class Reply:
    def __init__(self, status):
        self.status_code, self.reason = status, "invented"

    def json(self):
        return {}


class FakeX:
    """Records each SDK phase; raises the configured failure at one phase."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def _maybe(self, stage):
        if stage in self.fail:
            raise self.fail[stage]

    def media_upload(self, filename, file):
        self.calls.append(("upload", hashlib.sha256(file.read()).hexdigest()))
        self._maybe("upload")
        return SimpleNamespace(media_id=4242)

    def create_media_metadata(self, media_id, alt_text):
        self.calls.append(("alt", alt_text))
        self._maybe("alt")

    def create_tweet(self, text, **options):
        self.calls.append(("create", text, options))
        self._maybe("create")
        return SimpleNamespace(data={"id": "990001"})


def _draft():
    draft = {"id": "w14-outbox", "event_id": "w14-outbox-event", "type": "monthly_high",
             "text": "Invented Fenwick Hollow reached 41 C, a monthly high.",
             "created_at": posting._utc_now_iso(), "updated_at": posting._utc_now_iso(),
             "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
             "review_context": {"two_bot": {"bundle": {"event_id": "w14-outbox-event", "signal_kind": "monthly_high",
                                                       "current_facts": [{"label": "temperature", "value": 41}]}}}}
    return bind_reviewed_draft(draft, "manual", "w14-intent")


@pytest.fixture
def world(monkeypatch):
    importlib.reload(posting)
    trap_network(monkeypatch.setattr)
    storage = MagicMock()
    storage.check_daily_cap.return_value = True
    storage.write_state.return_value = True
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setattr(posting, "post_tweet", twitter.post_tweet)  # the real adapter, not a facade mock
    monkeypatch.setattr(posting, "_hot10_media_for_draft", lambda _draft: (PNG, ALT))
    fake = SimpleNamespace(x=FakeX())
    monkeypatch.setattr(twitter, "_get_client", lambda: fake.x)
    monkeypatch.setattr(twitter, "_get_upload_api", lambda: fake.x)
    draft = _draft()
    bot_state = deepcopy(DEFAULT_STATE)
    bot_state["drafts"] = [draft]
    return SimpleNamespace(fake=fake, draft=draft, state=bot_state, storage=storage)


@pytest.mark.parametrize("report,result,status,reason", [
    ({"stages": [], "refused_before_egress": "credentials_unavailable"}, None, "not_sent", "credentials_unavailable"),
    ({"stages": [{"stage": "upload", "result": "rejected", "http_status": 429, "complete": True}], "refused_before_egress": None},
     {"error": "rate_limited"}, "not_sent", "upload_rejected"),
    ({"stages": [{"stage": "upload", "result": "no_response", "http_status": None, "complete": False}], "refused_before_egress": None},
     None, "unknown", "upload_response_missing"),
    ({"stages": [{"stage": "upload", "result": "returned", "http_status": None, "complete": True},
                 {"stage": "alt", "result": "no_response", "http_status": None, "complete": False}], "refused_before_egress": None},
     None, "unknown", "alt_response_missing"),
    ({"stages": [{"stage": "create", "result": "rejected", "http_status": 429, "complete": True}], "refused_before_egress": None},
     {"error": "rate_limited"}, "not_sent", "create_rate_limited"),
    ({"stages": [{"stage": "create", "result": "rejected", "http_status": 403, "complete": True}], "refused_before_egress": None},
     None, "unknown", "create_rejected_unproven"),
    ({"stages": [{"stage": "create", "result": "no_response", "http_status": None, "complete": False}], "refused_before_egress": None},
     None, "unknown", "create_response_missing"),
    ({"stages": [{"stage": "create", "result": "returned", "http_status": None, "complete": True}], "refused_before_egress": None},
     {"id": "77"}, "confirmed", "post_id_returned"),
    (None, {"error": "rate_limited"}, "not_sent", "rate_limited"),
    (None, None, "unknown", "no_stage_evidence"),
    (None, {"id": "77"}, "confirmed", "post_id_returned"),
])
def test_stage_classifier_never_proves_absence_from_silence(report, result, status, reason):
    outcome = outbox_outcome.classify(report, result)
    assert (outcome["status"], outcome["reason"]) == (status, reason)
    assert outcome["retry_permitted"] is (status == "not_sent")
    assert (outcome["proof"] is not None) is (status == "not_sent")


def test_complete_upload_rate_limit_is_proven_not_sent_then_explicit_retry_delivers_original(world):
    world.fake.x.fail = {"upload": tweepy.TooManyRequests(Reply(429))}
    assert posting.post_approved(world.draft, world.state) == "rate_limited"
    row = world.state["publish_ledger"]["w14-outbox-event"]
    assert world.fake.x.calls == [("upload", hashlib.sha256(PNG).hexdigest())]
    assert row["phase"] == "not_sent" and row["delivery_outcome"]["proof"] == "complete_pre_create_rejection"
    assert row["delivery_identity"] == {"text_sha256": hashlib.sha256(world.draft["text"].encode()).hexdigest(),
                                        "png_sha256": hashlib.sha256(PNG).hexdigest(),
                                        "alt_sha256": hashlib.sha256(ALT.encode()).hexdigest()}
    assert outbox_outcome.retry_permitted(row) and not has_unresolved_publish(world.draft, world.state)
    world.fake.x = FakeX()
    original_text = world.draft["text"]
    assert posting.post_approved(world.draft, world.state) == "posted"
    delivered = world.state["publish_ledger"]["w14-outbox-event"]
    assert [call[0] for call in world.fake.x.calls] == ["upload", "alt", "create"]
    assert delivered["phase"] == "confirmed" and delivered["tweet_id"] == "990001" and delivered["text"] == original_text
    assert delivered["delivery_outcome"]["reason"] == "post_id_returned" and not outbox_outcome.retry_permitted(delivered)
    # A later edit never rewrites the delivered original on the receipt row.
    world.draft["text"] = "Invented edit after delivery."
    assert world.state["publish_ledger"]["w14-outbox-event"]["text"] == original_text


@pytest.mark.parametrize("stage,error,expected,calls", [
    ("create", tweepy.TooManyRequests(Reply(429)), "rate_limited", 3),
    ("alt", tweepy.BadRequest(Reply(400)), "failed", 2),
])
def test_complete_platform_rejections_before_a_post_exists_are_not_sent(world, stage, error, expected, calls):
    world.fake.x.fail = {stage: error}
    assert posting.post_approved(world.draft, world.state) == expected
    row = world.state["publish_ledger"]["w14-outbox-event"]
    assert row["phase"] == "not_sent" and world.draft["publish_outcome"] == "not_sent"
    assert row["delivery_outcome"]["stage"] == stage and len(world.fake.x.calls) == calls


@pytest.mark.parametrize("stage,error,reason", [
    ("create", tweepy.Forbidden(Reply(403)), "create_rejected_unproven"),
    ("create", tweepy.TwitterServerError(Reply(503)), "create_rejected_unproven"),
    ("create", requests.exceptions.ConnectionError("invented lost response"), "create_response_missing"),
    ("upload", requests.exceptions.ReadTimeout("invented lost upload"), "upload_response_missing"),
])
def test_ambiguous_phases_stay_unknown_and_are_never_resent(world, stage, error, reason):
    world.fake.x.fail = {stage: error}
    assert posting.post_approved(world.draft, world.state) == "failed"
    row = deepcopy(world.state["publish_ledger"]["w14-outbox-event"])
    assert row["phase"] == "unknown" and row["delivery_outcome"]["reason"] == reason
    sent = len(world.fake.x.calls)
    assert not outbox_outcome.retry_permitted(row)
    assert posting.post_approved(world.draft, world.state) == "failed"
    assert len(world.fake.x.calls) == sent and world.state["publish_ledger"]["w14-outbox-event"] == row


def test_missing_credentials_refuse_before_any_egress(world, monkeypatch):
    monkeypatch.setattr(twitter, "_get_client", lambda: None)
    assert posting.post_approved(world.draft, world.state) == "failed"
    row = world.state["publish_ledger"]["w14-outbox-event"]
    assert world.fake.x.calls == [] and row["phase"] == "not_sent"
    assert row["delivery_outcome"] == {"status": "not_sent", "stage": None, "reason": "credentials_unavailable",
                                       "media_state": None, "proof": "no_egress"}


@pytest.mark.parametrize("old", [
    {"phase": "unknown", "tweet_id": None, "text": "Invented old copy one."},
    {"tweet_id": None, "text": "Invented old copy two."},  # legacy row without a phase
    {"phase": "submitted", "tweet_id": None},
    {"phase": "not_sent", "tweet_id": None, "attempt_conflicts": [{"phase": "unknown"}]},
    {"phase": "not_sent", "tweet_id": None, "operator_cancellation": {"reconciliation_id": "w14-c"}},
    None,
    "malformed",
])
def test_old_unknown_deliveries_are_never_retried(world, old):
    world.state["publish_ledger"] = {"w14-outbox-event": old}
    assert not outbox_outcome.retry_permitted(old)
    before = deepcopy(world.state["publish_ledger"])
    if old is None or not (isinstance(old, dict) and old.get("operator_cancellation")):
        assert posting.post_approved(world.draft, world.state) == "failed"
        assert world.fake.x.calls == [] and world.state["publish_ledger"] == before
