"""Invented Gist post-image drafts and a fake X SDK; no captured weather or platform call.

Only Gist persistence, the final safety model and the X client factories are
replaced. Renderers, descriptor validation, revision/approval rules, posting
intent/receipt logic and the upload/alt/create adapter run their production code.
"""
from copy import deepcopy
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.editorial import revisions
from src.state import DEFAULT_STATE


def state_for(*drafts):
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = list(drafts)
    return state


def saved_draft(bundle, *, draft_id, draft_type, text, created_at="2026-06-08T11:00:00Z"):
    draft = dict(id=draft_id, event_id=bundle["event_id"], type=draft_type, text=text, status="pending",
                 created_at=created_at, updated_at=created_at,
                 review_context=dict(two_bot=dict(bundle=deepcopy(bundle))))
    revisions.initialize_revision(draft)
    return draft


def attach(draft, descriptor, *, at="2026-06-08T12:00:00Z"):
    return revisions.invalidate_media_attachment(draft, deepcopy(descriptor), at=at)


def approve(draft, intent="invented-joint-intent"):
    revisions.record_joint_media_review(draft)
    revisions.authorize_draft(draft, "manual", intent)
    draft.update(status="approved", approval_mode="manual", publish_intent_id=intent)
    assert revisions.review_is_current(draft)
    assert revisions.approval_is_current(draft, "manual")
    return draft


def install_fake_x(monkeypatch):
    """Fake SDK factories behind the real twitter.post_tweet adapter."""
    from src.orchestrator import posting
    from src.posting import twitter

    # Other tests can replace the legacy common facade; restore the real module.
    posting = importlib.reload(posting)
    result = SimpleNamespace(calls=[], persisted=[], failure=None, posting=posting)
    storage = MagicMock()
    storage.check_daily_cap.return_value = True

    def write(bot_state, **expected):
        assert not result.calls, "persist the intent before upload/alt/create"
        result.persisted.append((deepcopy(bot_state), deepcopy(expected)))
        return True

    storage.write_state.side_effect = write
    result.storage = storage

    def upload(*, filename, file, **options):
        assert result.persisted, "an intent must be durable before the first upload"
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
    monkeypatch.setattr(twitter, "_get_upload_api",
                        lambda: SimpleNamespace(media_upload=upload, create_media_metadata=alt))
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setattr(posting, "post_tweet", twitter.post_tweet)
    result.safety = MagicMock(return_value=(True, None))  # explicit offline check fixture
    monkeypatch.setattr(posting, "run_safety_pipeline", result.safety)
    monkeypatch.setattr(posting, "post_to_bluesky", MagicMock(side_effect=AssertionError("no crosspost")))
    monkeypatch.setattr(posting, "_hot10_media_for_draft",
                        lambda _draft: pytest.fail("a present attachment fell back to text/Hot10"))
    return result


def run_manual(monkeypatch, fake, state, draft):
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]),
                        ("PUBLISH_INTENT_ID", draft["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    fake.posting.run_manual_tweet(state)
    return state
