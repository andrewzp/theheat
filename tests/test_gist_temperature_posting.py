"""Invented full-GHCN joint review through the real manual sender and fake X SDK.

Only Gist persistence, final safety and the X client factories are replaced. The
renderer, descriptor validation, revision/approval rules, posting intent/receipt
logic and upload/alt/create adapter execute their actual production functions.
"""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from freezegun import freeze_time
import pytest

from src.editorial import revisions
from src.media import gist_temperature_media as media
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.orchestrator import posting
from src.posting import twitter
from src.state import DEFAULT_STATE
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.test_hot10_card import _sample_rows


@pytest.fixture(autouse=True)
def invented_clock():
    # The entire local invented archive is historical. This controls only test time.
    with freeze_time("2026-09-09T12:00:00Z"):
        yield


@pytest.fixture(scope="module")
def retained_media():
    bundle = story_bundle_snapshot(graphic_bundles()[-1])
    prepared = media.prepare_media(bundle)
    return bundle, prepared


def reviewed(draft):
    revisions.record_joint_media_review(draft)
    revisions.authorize_draft(draft, "manual", "invented-joint-intent")
    draft.update(status="approved", approval_mode="manual")
    assert revisions.review_is_current(draft)
    assert revisions.approval_is_current(draft, "manual")
    return draft


@pytest.fixture
def draft_factory(retained_media):
    bundle, prepared = retained_media
    def make(*, attach=True, approve=True):
        draft = dict(id="invented-gist-temperature", event_id=bundle["event_id"], type="all_time_high",
                     text="Invented station comparison for a saved observed reading.", status="pending",
                     created_at="2026-09-09T11:00:00Z", updated_at="2026-09-09T11:00:00Z",
                     review_context=dict(two_bot=dict(bundle=deepcopy(bundle))))
        revisions.initialize_revision(draft)
        if attach:
            revisions.invalidate_media_attachment(draft, deepcopy(prepared["descriptor"]), at="2026-09-09T12:00:00Z")
            if approve:
                reviewed(draft)
        elif approve:
            revisions.record_human_review(draft)
            revisions.authorize_draft(draft, "manual", "invented-text-intent")
            draft.update(status="approved", approval_mode="manual")
        return draft
    return make


def state_for(draft):
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    return state


@pytest.fixture
def fake_transport(monkeypatch):
    # Existing tests can replace the legacy common facade. Restore this module,
    # then explicitly select the real Twitter adapter with fake SDK factories.
    importlib.reload(posting)
    result = SimpleNamespace(calls=[], persisted=[], failure=None)
    storage = MagicMock()
    storage.check_daily_cap.return_value = True
    def write(bot_state, **expected):
        assert not result.calls, "persist the intent before upload/alt/create"
        result.persisted.append((deepcopy(bot_state), deepcopy(expected)))
        return True
    storage.write_state.side_effect = write
    result.storage = storage

    def upload(*, filename, file, **options):
        assert result.persisted
        saved, _expected = result.persisted[-1]
        assert saved["publish_ledger"][saved["drafts"][0]["event_id"]]["phase"] == "submitted"
        result.calls.append(("upload", file.read(), filename))
        if result.failure == "upload":
            raise TimeoutError("invented upload response lost")
        return SimpleNamespace(media_id=98765)
    def alt(media_id, text, **options):
        result.calls.append(("alt", media_id, text))
        if result.failure == "alt":
            raise TimeoutError("invented alt response lost")
    def create(*, text, **options):
        result.calls.append(("create", text, options))
        if result.failure == "create":
            raise TimeoutError("invented create response lost")
        if result.failure == "empty_receipt":
            return SimpleNamespace(data={})
        return SimpleNamespace(data={"id": "invented-x-receipt"})
    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(create_tweet=create))
    monkeypatch.setattr(twitter, "_get_upload_api", lambda: SimpleNamespace(media_upload=upload, create_media_metadata=alt))
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setattr(posting, "post_tweet", twitter.post_tweet)
    result.safety = MagicMock(return_value=(True, None))  # explicit offline check fixture
    monkeypatch.setattr(posting, "run_safety_pipeline", result.safety)
    monkeypatch.setattr(posting, "post_to_bluesky", MagicMock(side_effect=AssertionError("no crosspost")))
    return result


def no_network_or_fallback(fake, monkeypatch):
    monkeypatch.setattr(posting, "_hot10_media_for_draft", lambda _draft: pytest.fail("present attachment fell back to text/Hot10"))
    assert not fake.calls


def test_full_joint_review_manual_journey_uploads_exact_reviewed_png_and_alt(draft_factory, retained_media, fake_transport, monkeypatch):
    draft = draft_factory()
    _bundle, prepared = retained_media
    original = deepcopy(draft)
    state = state_for(draft)
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]), ("PUBLISH_INTENT_ID", draft["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    posting.run_manual_tweet(state)
    fake_transport.safety.assert_called_once_with(original["text"])
    assert fake_transport.calls == [
        ("upload", prepared["png"], "hot10.png"),
        ("alt", "98765", prepared["descriptor"]["alt_text"]),
        ("create", original["text"], {"media_ids": ["98765"]}),
    ]
    saved, expected = fake_transport.persisted[0]
    assert expected == {"expected_draft": original, "expected_publish_ledger": None}
    row = state["publish_ledger"][draft["event_id"]]
    assert row["phase"] == "confirmed" and row["tweet_id"] == draft["tweet_id"] == "invented-x-receipt"
    assert draft["status"] == "posted"
    assert all(row[key] == value for key, value in revisions.draft_identity(original).items())
    assert saved["publish_ledger"][draft["event_id"]]["phase"] == "submitted"
    assert hashlib.sha256(fake_transport.calls[0][1]).hexdigest() == original["media_attachment"]["png_sha256"]
    assert hashlib.sha256(fake_transport.calls[1][2].encode()).hexdigest() == original["media_attachment"]["alt_sha256"]
    assert draft["review_context"]["two_bot"]["bundle"] == original["review_context"]["two_bot"]["bundle"]
    assert posting.post_approved(draft, state) == "failed"
    assert len(fake_transport.calls) == 3 and len(fake_transport.persisted) == 1
    posting.post_to_bluesky.assert_not_called()


@pytest.mark.parametrize("stage,expected_calls", [("upload", 1), ("alt", 2), ("create", 3), ("empty_receipt", 3)])
def test_uncertain_transport_phase_never_resends_or_becomes_text_only(draft_factory, fake_transport, monkeypatch, stage, expected_calls):
    draft = draft_factory()
    state = state_for(draft)
    fake_transport.failure = stage
    no_network_or_fallback(fake_transport, monkeypatch)
    assert posting.post_approved(draft, state) == "failed"
    row = deepcopy(state["publish_ledger"][draft["event_id"]])
    assert row["phase"] == "unknown" and draft["publish_outcome"] == "unknown"
    assert len(fake_transport.calls) == expected_calls
    restarted = deepcopy(state)
    revisions.authorize_draft(restarted["drafts"][0], "manual", "invented-new-intent")
    assert posting.post_approved(restarted["drafts"][0], restarted) == "failed"
    assert restarted["publish_ledger"][draft["event_id"]] == row
    assert len(fake_transport.calls) == expected_calls and len(fake_transport.persisted) == 1


@pytest.mark.parametrize("changed", ["png", "alt", "unit", "source", "comparator"])
def test_rehashed_but_invalid_attachment_or_source_refuses_before_upload(draft_factory, fake_transport, monkeypatch, changed):
    draft = draft_factory(approve=False)
    descriptor = draft["media_attachment"]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    if changed == "png":
        descriptor["png_sha256"] = "a" * 64
    elif changed == "alt":
        descriptor["alt_text"] += " Unsupported changed description."
        descriptor["alt_sha256"] = hashlib.sha256(descriptor["alt_text"].encode()).hexdigest()
    elif changed == "unit":
        bundle["raw_signal_dump"]["evidence"]["unit"] = "F"
    elif changed == "source":
        bundle["raw_signal_dump"]["evidence"]["source_product"] = "invented-other-source"
    else:
        bundle["historical_context"]["prior_record_c"] -= 5
    descriptor["bundle_sha256"] = revisions.fingerprint(bundle)
    reviewed(draft)
    no_network_or_fallback(fake_transport, monkeypatch)
    state = state_for(draft)
    assert posting.post_approved(draft, state) == "failed"
    assert fake_transport.calls == []
    assert state["publish_ledger"][draft["event_id"]]["phase"] == draft["publish_outcome"] == "not_sent"
    assert "new preview and joint review" in draft["post_error"]


def test_changed_renderer_profile_refuses_review_and_send_before_intent(draft_factory, fake_transport, monkeypatch):
    draft = draft_factory()
    changed = deepcopy(draft["media_attachment"]["renderer"])
    changed["pillow"] = "invented-other-profile"
    monkeypatch.setattr(media, "renderer_identity", lambda: changed)
    assert not revisions.review_is_current(draft)
    assert not revisions.approval_is_current(draft, "manual")
    with pytest.raises(ValueError, match="render profile changed"):
        revisions.record_joint_media_review(draft)
    no_network_or_fallback(fake_transport, monkeypatch)
    state = state_for(draft)
    assert posting.post_approved(draft, state) == "failed"
    assert fake_transport.calls == [] and not state["publish_ledger"]
    fake_transport.storage.write_state.assert_not_called()


@pytest.mark.parametrize("age,allowed", [(0, True), (4, True), (5, False), (-1, False)])
def test_send_uses_observation_day_age_not_new_retrieval_time(draft_factory, fake_transport, monkeypatch, age, allowed):
    draft = draft_factory()
    no_network_or_fallback(fake_transport, monkeypatch)
    observed = date.fromisoformat(draft["media_attachment"]["valid_date"])
    with freeze_time((observed + timedelta(days=age)).isoformat() + "T12:00:00Z"):
        result = posting.post_approved(draft, state_for(draft))
    assert result == ("posted" if allowed else "failed")
    assert len(fake_transport.calls) == (3 if allowed else 0)
    if not allowed:
        assert draft["publish_outcome"] == "not_sent" and "future or stale" in draft["post_error"]


@pytest.mark.parametrize("change", ["text", "source", "policy", "remove", "decision", "text_only_review"])
def test_stale_review_or_approval_stops_before_persisting_intent(draft_factory, fake_transport, monkeypatch, change):
    draft = draft_factory()
    if change == "text":
        revisions.invalidate_text(draft, "An edited invented comparison.")
    elif change == "source":
        draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["valid_date"] = "2026-09-07"
    elif change == "policy":
        draft["review_binding"]["policy_sha256"] = "a" * 64
    elif change == "remove":
        revisions.invalidate_media_attachment(draft, None, at="2026-09-09T12:01:00Z")
    elif change == "decision":
        draft["decision_revision"] += 1
    else:
        draft["review_binding"]["kind"] = "human"
        draft["review_binding"].pop("media_sha256")
    no_network_or_fallback(fake_transport, monkeypatch)
    state = state_for(draft)
    assert posting.post_approved(draft, state) == "failed"
    assert fake_transport.calls == [] and not state["publish_ledger"]
    fake_transport.storage.write_state.assert_not_called()


def test_render_failure_is_proven_not_sent_without_erasing_old_unknown(draft_factory, fake_transport, monkeypatch):
    draft = draft_factory()
    no_network_or_fallback(fake_transport, monkeypatch)
    monkeypatch.setattr(media, "prepare_media", MagicMock(side_effect=OSError("invented missing font asset")))
    state = state_for(draft)
    assert posting.post_approved(draft, state) == "failed"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "not_sent"
    assert fake_transport.calls == []
    # An older uncertain attempt fences publication before another media attempt.
    state = state_for(draft_factory())
    old = {"intent_id": "invented-old", "phase": "unknown", "tweet_id": None}
    state["publish_ledger"][state["drafts"][0]["event_id"]] = deepcopy(old)
    assert posting.post_approved(state["drafts"][0], state) == "failed"
    assert state["publish_ledger"][state["drafts"][0]["event_id"]] == old
    assert len(fake_transport.persisted) == 1


def test_two_selected_images_refuse_without_hot10_fallback(draft_factory, fake_transport, monkeypatch):
    draft = draft_factory(approve=False)
    draft["hot10_rows"] = _sample_rows()
    reviewed(draft)
    no_network_or_fallback(fake_transport, monkeypatch)
    state = state_for(draft)
    assert posting.post_approved(draft, state) == "failed"
    assert "Only one explicitly selected image" in draft["post_error"]
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "not_sent"
    assert fake_transport.calls == []


@pytest.mark.parametrize("kind", ["text", "hot10"])
def test_absent_temperature_attachment_preserves_text_and_hot10_transport(draft_factory, fake_transport, monkeypatch, kind):
    draft = draft_factory(attach=False, approve=False)
    if kind == "hot10":
        draft["hot10_rows"] = _sample_rows()
        monkeypatch.setenv("THEHEAT_HOT10_CARD_ENABLED", "1")
    revisions.record_human_review(draft)
    revisions.authorize_draft(draft, "manual", "invented-legacy-intent")
    draft["status"] = "approved"
    assert posting.post_approved(draft, state_for(draft)) == "posted"
    if kind == "text":
        assert fake_transport.calls == [("create", draft["text"], {})]
    else:
        from src.media.hot10_card import build_hot10_alt_text, render_hot10_card
        assert fake_transport.calls[0][1] == render_hot10_card(draft["hot10_rows"])
        assert fake_transport.calls[1] == ("alt", "98765", build_hot10_alt_text(draft["hot10_rows"]))
        assert fake_transport.calls[2] == ("create", draft["text"], {"media_ids": ["98765"]})


@pytest.mark.parametrize("reason", ["invented final safety refusal", "invented safety unavailable"])
def test_manual_joint_review_still_requires_final_safety(draft_factory, fake_transport, monkeypatch, reason):
    draft = draft_factory()
    attachment = deepcopy(draft["media_attachment"])
    fake_transport.safety.return_value = (False, reason)
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]), ("PUBLISH_INTENT_ID", draft["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    state = state_for(draft)
    posting.run_manual_tweet(state)
    assert fake_transport.calls == [] and not state["publish_ledger"]
    assert draft["status"] == "pending" and not draft.get("approval_binding")
    assert draft["post_error"] == reason and draft["media_attachment"] == attachment
    fake_transport.storage.write_state.assert_not_called()


def test_joint_review_never_enrolls_automatic_publication(draft_factory):
    draft = draft_factory(approve=False)
    revisions.record_joint_media_review(draft)
    assert draft["review_binding"]["kind"] == "human_media"
    with pytest.raises(ValueError, match="Scheduling requires a current model review"):
        revisions.authorize_draft(draft, "auto")
    assert not draft.get("approval_binding") and not draft.get("auto_approve_at")


def test_attach_remove_idempotency_and_material_changes_revoke_reviews(draft_factory):
    draft = draft_factory()
    before = deepcopy(draft)
    descriptor = deepcopy(draft["media_attachment"])
    revisions.invalidate_media_attachment(draft, deepcopy(descriptor), at="2026-09-09T12:01:00Z")
    assert draft == before  # Identical repeat does not revoke current review/approval.
    descriptor["alt_text"] += " Changed invented description."
    descriptor["alt_sha256"] = hashlib.sha256(descriptor["alt_text"].encode()).hexdigest()
    revisions.invalidate_media_attachment(draft, descriptor, at="2026-09-09T12:02:00Z")
    assert draft["content_revision"] == before["content_revision"] + 1
    assert draft["status"] == "pending" and not draft.get("review_binding") and not draft.get("approval_binding")
    assert draft["revision_history"][-1]["media_attachment"] == before["media_attachment"]
    revisions.invalidate_media_attachment(draft, None, at="2026-09-09T12:03:00Z")
    assert "media_attachment" not in draft and not draft.get("review_binding")
    removed = deepcopy(draft)
    revisions.invalidate_media_attachment(draft, None, at="2026-09-09T12:04:00Z")
    assert draft == removed
