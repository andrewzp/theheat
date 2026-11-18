"""Expired private airport copy is not competing publishable inventory.

Invented retained source bytes; actual request builders, no model/source calls.
Delivery uncertainty stays visible, and no draft/decision/history is changed.
"""
from copy import deepcopy
from datetime import timedelta
import json

from freezegun import freeze_time
import pytest

from src.data import awc_observed as awc
from src.state import DEFAULT_STATE
from src.two_bot import critic
from tests.test_awc_observed import NOW, install


@pytest.fixture
def case(monkeypatch):
    install(monkeypatch)
    bundle = awc.build_bundle(awc.nominate(now=NOW), now=NOW)
    monkeypatch.setattr(awc, "_read", lambda *a, **k: pytest.fail("No source read"))
    draft = {"id": "invented-expired-private", "event_id": bundle.event_id,
             "type": awc.KIND, "status": "pending", "created_at": NOW.isoformat(),
             "text": "Invented old private draft.", "publish_outcome": "not_sent",
             "last_publish_attempt_at": NOW.isoformat(), "tweet_id": None,
             "review_context": {"two_bot": {"bundle": bundle.to_dict()}}}
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    # A different event prevents the existing exact-event exclusion doing the work.
    current = deepcopy(bundle)
    current.event_id = "invented-distinct-current"
    return state, draft, current


@pytest.mark.parametrize("slate", [False, True])
def test_actual_critic_request_omits_expired_never_sent_copy_without_mutation(case, monkeypatch, slate):
    state, draft, current = case
    # Keep uncertainty about a separate delivery and a normal non-airport sibling.
    unknown = {**deepcopy(draft), "id": "unknown", "event_id": "unknown",
               "text": "Invented uncertain delivery.", "publish_outcome": "unknown"}
    sibling = {"id": "other", "event_id": "other", "status": "pending", "type": "other",
               "created_at": NOW.isoformat(), "text": "Invented current sibling."}
    state["drafts"].extend([unknown, sibling])
    before = deepcopy(state)
    requests = []

    def capture(text, bundle, pending, shipped, **kwargs):
        request = critic.prepare_request(text, bundle, pending, shipped, **kwargs)
        requests.append(request)
        return json.dumps({"verdict": "KILL", "kill_reason": "weak_signal"})

    monkeypatch.setattr(critic, "_call_gemini", capture)
    with freeze_time(NOW + timedelta(hours=3)):
        result = (critic.critic_select_slate(["Invented new copy."], current, state, shipped_recent=[])
                  if slate else critic.critic_review("Invented new copy.", current, state, shipped_recent=[]))
    assert not result.passed and result.kill_reason == "weak_signal"
    assert len(requests) == 1
    contents = requests[0]["contents"]
    assert draft["text"] not in contents
    assert unknown["text"] in contents and sibling["text"] in contents
    assert "OTHER PENDING DRAFT EXCERPTS (2 supplied" in contents
    assert state == before


@pytest.mark.parametrize("seconds,excluded", [(0, False), (6599, False), (6600, False), (6601, True)])
def test_strict_observation_deadline_not_creation_age(case, seconds, excluded):
    state, _, _ = case
    before = deepcopy(state)
    with freeze_time(NOW + timedelta(seconds=seconds)):
        rows = critic._collect_pending_today(state)
    assert (rows == []) is excluded
    assert state == before


@pytest.mark.parametrize("change", [
    "missing_outcome", "unknown", "submitted", "confirmed", "malformed_outcome", "receipt",
    "posted_time", "published_revision", "publication_observations", "attempt_conflicts",
    "revision_conflicts", "posted_event", "malformed_posted_events", "malformed_ledger",
    "event_ledger_null", "event_ledger_unknown", "event_ledger_receipt", "event_ledger_conflict",
    "draft_ledger_unknown", "draft_ledger_receipt", "malformed_ledger_conflicts", "ledger_confirmation",
    "wrong_event", "wrong_type", "changed_bundle", "missing_capture", "bad_capture",
    "future_capture", "missing_bundle", "malformed_context",
])
def test_uncertain_delivery_or_unqualified_source_stays_visible(case, change):
    state, draft, _ = case
    bundle = draft["review_context"]["two_bot"]["bundle"]
    if change == "missing_outcome":
        draft.pop("publish_outcome")
    elif change in ("unknown", "submitted", "confirmed", "malformed_outcome"):
        draft["publish_outcome"] = {} if change == "malformed_outcome" else change
    elif change == "receipt":
        draft["tweet_id"] = "invented receipt"
    elif change in ("posted_time", "published_revision", "publication_observations", "attempt_conflicts", "revision_conflicts"):
        key = "posted_at" if change == "posted_time" else change
        draft[key] = {"fixture": "uncertain"}
    elif change == "posted_event":
        state["posted_events"] = [draft["event_id"]]
    elif change == "malformed_posted_events":
        state["posted_events"] = {}
    elif change == "malformed_ledger":
        state["publish_ledger"] = []
    elif "ledger" in change:
        row: dict | None = {"phase": "unknown"}
        if change == "event_ledger_null":
            row = None
        elif change in ("event_ledger_receipt", "draft_ledger_receipt"):
            row = {"phase": "not_sent", "tweet_id": "invented receipt"}
        elif change == "event_ledger_conflict":
            row = {"phase": "not_sent", "attempt_conflicts": [{"phase": "unknown"}]}
        elif change == "malformed_ledger_conflicts":
            row = {"phase": "not_sent", "attempt_conflicts": None}
        elif change == "ledger_confirmation":
            row = {"phase": "not_sent", "confirmed_at": NOW.isoformat()}
        key = draft["id"] if change.startswith("draft_") else draft["event_id"]
        state["publish_ledger"] = {key: row}
    elif change == "wrong_event":
        draft["event_id"] = "different retained event"
    elif change == "wrong_type":
        draft["type"] = "other"
    elif change == "changed_bundle":
        bundle["raw_signal_dump"]["evidence"]["points"][0]["temperature_c"] = 100
    elif change == "missing_capture":
        bundle["raw_signal_dump"]["evidence"].pop("retrieved_at")
    elif change == "bad_capture":
        bundle["raw_signal_dump"]["evidence"]["retrieved_at"] = "invalid"
    elif change == "future_capture":
        bundle["raw_signal_dump"]["evidence"]["retrieved_at"] = (NOW + timedelta(hours=4)).isoformat()
    elif change == "missing_bundle":
        draft["review_context"]["two_bot"].pop("bundle")
    elif change == "malformed_context":
        draft["review_context"] = []
    before = deepcopy(state)
    with freeze_time(NOW + timedelta(hours=3)):
        assert critic._collect_pending_today(state) == [draft]
    assert state == before


@pytest.mark.parametrize("key_kind", ["event", "draft"])
def test_matching_never_sent_ledger_does_not_make_expired_copy_compete(case, key_kind):
    state, draft, _ = case
    key = draft["event_id"] if key_kind == "event" else draft["id"]
    state["publish_ledger"] = {key: {"phase": "not_sent", "tweet_id": None, "attempt_conflicts": []}}
    before = deepcopy(state)
    with freeze_time(NOW + timedelta(hours=3)):
        assert critic._collect_pending_today(state) == []
    assert state == before


@pytest.mark.parametrize("slate", [False, True])
def test_overflowing_retained_source_stays_context_and_does_not_abort_current_check(case, monkeypatch, slate):
    state, draft, current = case
    draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["points"][0]["temperature_c"] = 10 ** 400
    state = json.loads(json.dumps(state))
    before = deepcopy(state)
    requests = []

    def capture(text, bundle, pending, shipped, **kwargs):
        requests.append(critic.prepare_request(text, bundle, pending, shipped, **kwargs))
        return json.dumps({"verdict": "KILL", "kill_reason": "weak_signal"})

    monkeypatch.setattr(critic, "_call_gemini", capture)
    with freeze_time(NOW + timedelta(hours=3)):
        result = (critic.critic_select_slate(["Invented new copy."], current, state, shipped_recent=[])
                  if slate else critic.critic_review("Invented new copy.", current, state, shipped_recent=[]))
    assert not result.passed and result.kill_reason == "weak_signal"
    assert len(requests) == 1 and draft["text"] in requests[0]["contents"]
    assert state == before
