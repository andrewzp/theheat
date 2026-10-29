"""Real generated warning -> actual Gist edit/review -> actual sender/fake X."""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from src.editorial import revisions
from src.editorial.warning_runtime import WarningSource, warning_source_scope
from tests.gist_media_helpers import install_fake_x
from tests.warning_helpers import NOW
from tests.warning_journey_helpers import generated_state, source
from tests.two_bot.conftest import configured_pipeline_providers as configured_pipeline_providers

pytestmark = pytest.mark.usefixtures("configured_pipeline_providers")


def reviewed(state):
    draft = state["drafts"][0]
    revisions.record_human_review(draft)
    revisions.authorize_draft(draft, "manual", "invented-warning-intent")
    draft.update(status="approved", publish_intent_id="invented-warning-intent")
    return draft


def fake_x(monkeypatch):
    from src import state as real_state
    fake = install_fake_x(monkeypatch)
    fake.storage.record_event.side_effect = real_state.record_event
    monkeypatch.setattr(fake.posting, "_hot10_media_for_draft", lambda draft: (None, None))
    return fake


def test_actual_generated_handler_edit_review_then_sender_delivers_exact_text_and_no_resend(monkeypatch):
    from tests.warning_journey_helpers import generated_state
    root = Path(__file__).resolve().parents[1]
    state, policy = generated_state()
    node = shutil.which("node")
    assert node is not None
    # The handler fixture generates only an invented runtime report, while its
    # saved policy is the actual Python policy used by this pipeline result.
    report = {"started_at": "2026-10-29T11:59:00.000Z", "runtime_inventory": {
        "schema_version": 1, "captured_at": "2026-10-29T11:59:00.000Z", "editorial_policy": policy}}
    state["run_history"] = [report]
    done = subprocess.run([node, "tests/helpers/warning-review-driver.mjs"], cwd=root/"dashboard",
        input=json.dumps({"raw_state": json.dumps(state, ensure_ascii=False), "policy": policy}),
        text=True, capture_output=True, timeout=30, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/private/tmp", "LC_ALL": "C", "LANG": "C", "NO_PROXY": "*", "no_proxy": "*",
        "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stderr[-3500:]
    result = json.loads(done.stdout)
    assert result["patches"] == 3 and result["source_preserved"]
    state = json.loads(result["raw_state"])
    draft = state["drafts"][0]
    assert revisions.approval_is_current(draft, "manual")
    fake = fake_x(monkeypatch)
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]),
                        ("PUBLISH_INTENT_ID", draft["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    with warning_source_scope(source()):
        fake.posting.run_manual_tweet(state)
        assert fake.posting.post_approved(draft, state) == "failed"
    assert draft["status"] == "posted"
    assert fake.calls == [("create", result["text"], {})]
    assert fake.safety.call_count == 1
    assert state["publish_ledger"][draft["event_id"]]["tweet_id"] == "invented-x-receipt"
    assert draft["event_id"] in state["posted_events"]


def test_missing_current_source_stops_before_paid_final_safety_or_intent(monkeypatch):
    state, _ = generated_state()
    draft = reviewed(state)
    fake = fake_x(monkeypatch)
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]),
                        ("PUBLISH_INTENT_ID", draft["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    fake.posting.run_manual_tweet(state)
    assert fake.calls == [] and fake.safety.call_count == 0 and fake.persisted == []
    assert draft["status"] == "pending" and "approval_binding" not in draft
    assert "warning_current_source_unavailable" in draft["post_error"]


def test_expiry_during_final_safety_cannot_create_an_intent_or_send(monkeypatch):
    state, _ = generated_state()
    draft = reviewed(state)
    fake = fake_x(monkeypatch)
    clock = {"now": NOW}
    fixed = source()
    current = WarningSource(fixed.resolve, clock=lambda: clock["now"])
    def expire(text):
        clock["now"] += timedelta(days=1)
        return True, None
    fake.safety.side_effect = expire
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]),
                        ("PUBLISH_INTENT_ID", draft["publish_intent_id"])):
        monkeypatch.setenv(name, value)
    with warning_source_scope(current):
        fake.posting.run_manual_tweet(state)
    assert fake.safety.call_count == 1 and fake.calls == [] and fake.persisted == []
    assert draft["status"] == "pending"


def test_lost_create_response_stays_unknown_and_is_never_resent(monkeypatch):
    state, _ = generated_state()
    draft = reviewed(state)
    fake = fake_x(monkeypatch)
    fake.failure = "create"
    with warning_source_scope(source()):
        assert fake.posting.post_approved(draft, state) == "failed"
        assert fake.posting.post_approved(draft, state) == "failed"
    assert len(fake.calls) == 1 and fake.calls[0][0] == "create"
    assert draft["publish_outcome"] == "unknown"
    assert len(fake.persisted) == 1


def test_expiry_after_durable_write_is_not_an_unknown_send(monkeypatch):
    state, _ = generated_state()
    draft = reviewed(state)
    fake = fake_x(monkeypatch)
    clock = {"now": NOW}
    current = WarningSource(source().resolve, clock=lambda: clock["now"])
    original = fake.storage.write_state.side_effect
    def persist(*args, **kwargs):
        result = original(*args, **kwargs)
        clock["now"] += timedelta(days=1)
        return result
    fake.storage.write_state.side_effect = persist
    with warning_source_scope(current):
        assert fake.posting.post_approved(draft, state) == "failed"
    assert len(fake.persisted) == 1 and fake.calls == []
    assert draft["publish_outcome"] == "not_sent"
