"""The actual save path must preserve the shared protected-history contract."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

import pytest

from src import state as state_store
from src.orchestrator.draft_save import save_draft


PROTECTED = [
    {"status": "pending"}, {"status": "approved"}, {"status": "posted", "tweet_id": "synthetic-receipt"},
    {"status": "rejected", "publish_intent_id": "synthetic-intent"},
    {"status": "rejected", "publish_outcome": "unknown"},
    {"status": "rejected", "publish_outcome": "submitted"},
    {"status": "rejected", "last_publish_attempt_at": "2000-01-01T00:00:00Z"},
    {"status": "rejected", "autoship_attempted": True},
    {"status": "rejected", "revision_conflicts": [{"text": "Synthetic conflicting revision"}]},
]


def row(identity, **fields):
    return {"id": identity, "event_id": identity, "text": "Synthetic retained draft.",
            "created_at": "2000-01-01T00:00:00Z", "status": "pending", **fields}


def append(state):
    return save_draft("A synthetic source-qualified alert.", state, "global_disaster", "synthetic-new")


def round_trip(state, monkeypatch):
    stored = {}
    monkeypatch.setattr(state_store, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(state_store, "_read_gist_state", lambda **kwargs: deepcopy(stored))
    def write(value):
        stored.update(json.loads(json.dumps(value)))
        return True
    monkeypatch.setattr(state_store, "_write_gist_state", write)
    assert state_store.write_state(state)
    return state_store.read_state()


@pytest.mark.parametrize("count", [199, 200, 201])
@pytest.mark.parametrize("protected", PROTECTED, ids=["pending", "approved", "posted", "intent",
    "unknown", "submitted", "attempt", "autoship", "conflict"])
def test_save_preserves_exact_protected_rows_at_and_above_old_cap(count, protected):
    history = row("protected", **protected,
        review_context={"two_bot": {"bundle": {"raw_signal_dump": {"source": "synthetic", "values": [1, 2]}}}},
        revision_history=[{"text": "Synthetic earlier text", "content_revision": 1}],
        approval_binding={"mode": "manual", "evidence_sha256": "synthetic-binding"})
    original = [history, *[row(f"pending-{i}") for i in range(count - 1)]]
    state = {"drafts": deepcopy(original), "publish_ledger": {"protected": {"phase": "unknown", "intent_id": "synthetic"}}}
    ledger = deepcopy(state["publish_ledger"])
    assert append(state)
    assert state["drafts"][:-1] == original
    assert len(state["drafts"]) == count + 1 and state["drafts"][-1]["event_id"] == "synthetic-new"
    assert state["publish_ledger"] == ledger


def test_rejected_expiry_and_cap_wait_until_after_save_and_cycle_selection(monkeypatch):
    now = datetime.now(UTC)
    original = [row("protected", status="approved"), row("expired", status="rejected"),
                *[row(f"recent-{i}", status="rejected", created_at=(now - timedelta(seconds=250-i)).isoformat())
                  for i in range(225)]]
    state = {"drafts": deepcopy(original)}
    assert append(state)
    assert state["drafts"][:-1] == original
    expected = {"drafts": [*deepcopy(original), deepcopy(state["drafts"][-1])]}
    state_store.trim_drafts(expected)
    loaded = round_trip(state, monkeypatch)
    assert {d["id"]: d for d in loaded["drafts"]} == {d["id"]: d for d in expected["drafts"]}
    assert len(loaded["drafts"]) == 200
    assert "protected" in {d["id"] for d in loaded["drafts"]}
    assert [d["id"] for d in loaded["drafts"] if d["id"].startswith("recent-")][0] == "recent-27"


def test_persistence_expires_old_unprotected_rejections_after_save(monkeypatch):
    state = {"drafts": [row("expired", status="rejected")]}
    assert append(state)
    assert len(state["drafts"]) == 2
    loaded = round_trip(state, monkeypatch)
    assert [d["event_id"] for d in loaded["drafts"]] == ["synthetic-new"]


def test_duplicate_save_does_not_trim_existing_history(monkeypatch):
    original = [row("synthetic-new"), row("expired", status="rejected"),
                *[row(f"pending-{i}") for i in range(201)]]
    state = {"drafts": deepcopy(original), "publish_ledger": {"other": {"phase": "unknown"}}}
    def forbidden(*args, **kwargs):
        raise AssertionError("A refused save must not invoke retention")
    monkeypatch.setattr(state_store, "trim_drafts", forbidden)
    assert not append(state)
    assert state["drafts"] == original and state["publish_ledger"] == {"other": {"phase": "unknown"}}


def test_save_does_not_shift_cycle_boundary_before_portfolio_pruning(monkeypatch):
    from src.orchestrator import finalize
    monkeypatch.setattr(finalize, "_effective_cycle_cap", lambda: 3)
    old = [row(f"expired-{i}", status="rejected") for i in range(3)]
    state = {"drafts": deepcopy(old)}
    before = len(state["drafts"])
    for i in range(4):
        assert save_draft(f"Synthetic source alert {i}.", state, "global_disaster", f"new-{i}")
        state["drafts"][-1]["score"] = {"total": 90-i}
    pruned = set()
    assert finalize._prune_weakest_cycle_drafts(state, before, None, 4, pruned_ids_out=pruned) == 3
    assert pruned == {"new-3"}
    assert state["drafts"][:before] == old
    assert [d["event_id"] for d in state["drafts"][before:]] == ["new-0", "new-1", "new-2"]


def test_new_state_write_cannot_depend_on_old_remote_rows_to_restore_history(monkeypatch):
    original = [row(f"protected-{i}", **fields) for i, fields in enumerate(PROTECTED)]
    original += [row(f"pending-{i}") for i in range(201)]
    state = {"drafts": deepcopy(original), "publish_ledger": {"receipt": {"phase": "confirmed", "tweet_id": "synthetic"}}}
    assert append(state)
    loaded = round_trip(state, monkeypatch)
    by_id = {d["id"]: d for d in loaded["drafts"]}
    for before in original:
        assert by_id[before["id"]] == before
    assert len(loaded["drafts"]) == len(original) + 1
    assert loaded["publish_ledger"] == state["publish_ledger"]
