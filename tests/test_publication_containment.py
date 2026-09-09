"""Offline publication policy tests; every external side effect is replaced."""
from copy import deepcopy
import importlib
from unittest.mock import Mock

import pytest

from src import state
from src.editorial.publication import (
    automatic_approval_allowed, automatic_publication_policy, merge_publication_control,
    observe_publication_policy,
)
from src.editorial.revisions import authorize_draft, record_human_review
from src.orchestrator import posting, draft_save
from src.runtime_inventory import collect_runtime_inventory
from tests.revision_helpers import bind_reviewed_draft, model_review_context


def release(monkeypatch, epoch="release-epoch-one"):
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", epoch)


def draft(monkeypatch, mode="auto"):
    release(monkeypatch)
    return bind_reviewed_draft({
        "id": "draft", "event_id": "event", "text": "Example City reached 40°C.",
        "status": "pending", "auto_approve_at": "2020-01-01T00:00:00Z",
        "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
    }, mode, "manual-intent" if mode == "manual" else None)


@pytest.fixture
def externals(monkeypatch):
    # Restore the real sender after legacy facade tests copy patched wrappers.
    importlib.reload(posting)
    mocks = {}
    for name, result in [("post_tweet", {"id": "receipt"}), ("post_to_bluesky", None),
                         ("run_safety_pipeline", (True, None))]:
        mocks[name] = Mock(return_value=result)
        monkeypatch.setattr(posting, name, mocks[name])
    mocks["write"] = Mock(return_value=True)
    monkeypatch.setattr(posting.state, "write_state", mocks["write"])
    return mocks


@pytest.mark.parametrize("flag,epoch", [(None, None), ("", "release-one"), ("true", "release-one"),
                                          ("0", "release-one"), ("1", None), ("1", "short"),
                                          ("1", "release\ninvalid"), ("1", "x" * 97)])
def test_policy_defaults_paused_or_rejects_invalid_configuration(monkeypatch, flag, epoch):
    for name, value in [("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", flag), ("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", epoch)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert automatic_publication_policy()["enabled"] is False


@pytest.mark.parametrize("ownership", ["auto", "policy_auto", "marked"])
def test_pause_blocks_all_due_lanes_before_checks_or_platform_calls(monkeypatch, externals, ownership):
    item = draft(monkeypatch)
    item["approval_mode"] = "policy_auto" if ownership == "policy_auto" else "auto"
    if ownership == "marked":
        item["autoship_on_critic_pass"] = True
    bot_state = {"drafts": [item], "publish_ledger": {}}
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    posting.process_due_drafts(bot_state)
    assert "auto_approve_at" not in item
    assert "approval_binding" not in item
    assert item["status"] == "pending"
    assert item["review_binding"]["kind"] == "model"
    for mock in externals.values():
        mock.assert_not_called()


def test_final_sender_refuses_auto_call_without_due_processor(monkeypatch, externals):
    item = draft(monkeypatch)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    assert posting.post_approved(item, {"drafts": [item]}) == "failed"
    externals["post_tweet"].assert_not_called()
    externals["write"].assert_not_called()


@pytest.mark.parametrize("value", ["Raw manual text", {"text": "Raw manual text"}, {"event_id": "event", "text": "Raw manual text"}])
def test_final_sender_refuses_all_untracked_text(value, externals):
    assert posting.post_approved(value, {}) == "failed"
    externals["post_tweet"].assert_not_called()
    externals["write"].assert_not_called()


def test_manual_dispatch_without_id_never_calls_safety_or_sender(monkeypatch, externals):
    monkeypatch.setenv("TWEET_TEXT", "Raw manual text")
    monkeypatch.delenv("DRAFT_ID", raising=False)
    posting.run_manual_tweet({})
    for mock in externals.values():
        mock.assert_not_called()


def test_pausing_preserves_unknown_attempts_and_manually_reviewed_approval(monkeypatch):
    item = draft(monkeypatch)
    item.update(publish_outcome="unknown", last_publish_attempt_at="2026-09-08T12:00:00Z", autoship_attempted=True)
    manual = {"id": "manual", "text": "Reviewed sourced text", "status": "pending"}
    record_human_review(manual)
    authorize_draft(manual, "manual", "intent")
    manual["status"] = "approved"
    ledger = {"event": {"phase": "unknown", "intent_id": "attempt", "text": item["text"]}}
    bot_state = {"drafts": [item, manual], "publish_ledger": deepcopy(ledger)}
    expected_manual = deepcopy(manual)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    observe_publication_policy(bot_state)
    assert bot_state["publish_ledger"] == ledger
    assert item["publish_outcome"] == "unknown" and item["autoship_attempted"]
    assert item["last_publish_attempt_at"] == "2026-09-08T12:00:00Z"
    assert manual == expected_manual


def test_pause_release_never_revives_old_epoch_even_after_stale_merge(monkeypatch):
    item = draft(monkeypatch)
    old = deepcopy(item)
    bot_state = {"drafts": [item]}
    observe_publication_policy(bot_state)
    stale = deepcopy(bot_state)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "pause-epoch-two")
    observe_publication_policy(bot_state)
    merged = state._merge_state(bot_state, stale)
    assert "release-epoch-one" in merged["publication_control"]["retired_epochs"]
    release(monkeypatch)
    assert not automatic_publication_policy(merged)["enabled"]
    assert not automatic_approval_allowed(old, merged)
    release(monkeypatch, "release-epoch-three")
    assert automatic_publication_policy(merged)["enabled"]
    assert not automatic_approval_allowed(old, merged)
    authorize_draft(item, "auto")
    assert automatic_approval_allowed(item, merged)


def test_missing_epoch_legacy_approval_does_not_publish(monkeypatch, externals):
    item = draft(monkeypatch)
    del item["approval_binding"]["publication_epoch"]
    assert posting.post_approved(item, {"drafts": [item]}) == "failed"
    externals["post_tweet"].assert_not_called()


def test_latest_read_with_retired_epoch_blocks_intent_write(monkeypatch):
    item = draft(monkeypatch)
    current = {"drafts": [item], "publication_control": {"retired_epochs": ["release-epoch-one"]}}
    assert not state._expected_draft_matches(current, item, None)


@pytest.mark.parametrize("autoship", ["0", "1"])
def test_paused_saver_preserves_drafting_without_arming(monkeypatch, autoship):
    from src.editorial.scoring import EditorialScore
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", autoship)
    bot_state = deepcopy(state.DEFAULT_STATE)
    text = "Atmospheric CO2 reached 430 ppm."
    score = EditorialScore(category="co2_milestone", severity=80, novelty=80, timeliness=80, confidence=80, shareability=80, sensitivity=0, total=80, threshold=60, reasons=[])
    assert draft_save.save_draft(text, bot_state, "co2_milestone", "co2:test", score,
                                 review_context=model_review_context(text))
    saved = bot_state["drafts"][0]
    assert saved["review_binding"]["kind"] == "model"
    assert "auto_approve_at" not in saved and "approval_binding" not in saved


def test_retired_epoch_merge_is_monotonic_and_invalid_control_fails_closed(monkeypatch):
    release(monkeypatch)
    a = {"retired_epochs": ["release-one"]}
    b = {"retired_epochs": ["release-two"]}
    assert merge_publication_control(a, b) == merge_publication_control(b, a)
    merged = merge_publication_control(a, {"retired_epochs": "broken"})
    assert merged["invalid_control"] and "release-one" in merged["retired_epochs"]
    assert not automatic_publication_policy({"publication_control": merged})["enabled"]


def test_runtime_inventory_reports_effective_pause_and_epoch(monkeypatch):
    release(monkeypatch)
    inventory = collect_runtime_inventory("alerts", bot_state={"publication_control": {"retired_epochs": ["release-epoch-one"]}})
    assert inventory["flags"]["automatic_publication_enabled"] is False
    assert inventory["flags"]["automatic_publication_epoch"] == "release-epoch-one"


def test_shared_control_merge_contract():
    import json
    from pathlib import Path
    rows = json.loads((Path(__file__).parent / "fixtures/publication_control_merge.json").read_text())
    for row in rows:
        assert merge_publication_control(row["a"], row["b"]) == row["expected"], row["name"]
