"""Offline regression contract for revision/attempt persistence in both runtimes."""

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.editorial.revisions import draft_identity, has_unresolved_publish
from src.state import _merge_drafts, _merge_publish_ledger, read_state, trim_drafts, write_state


CASES = json.loads((Path(__file__).parent / "fixtures/draft_merge_contract.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_draft_merge_contract(case):
    for current, incoming in [(case["current"], case["incoming"]), (case["incoming"], case["current"])]:
        before = deepcopy([current, incoming])
        row = _merge_drafts([current], [incoming])[0]
        for key, value in case["expected"].items():
            assert row.get(key) == value
        for key in case["absent"]:
            assert key not in row
        assert bool(row.get("revision_history")) == case["history"]
        assert bool(row.get("revision_conflicts")) == case["conflict"]
        assert [current, incoming] == before


def test_equal_timestamp_divergent_revision_has_deterministic_display():
    first = {"id": "d1", "text": "A", "content_revision": 2, "status": "pending"}
    second = {**first, "text": "B"}
    a = _merge_drafts([first], [second])[0]
    b = _merge_drafts([second], [first])[0]
    assert a["text"] == b["text"]
    assert len(a["revision_conflicts"]) == 2


def test_higher_revision_resolves_active_conflict_but_retains_history():
    first, second = {"id": "d1", "text": "A", "content_revision": 2}, {"id": "d1", "text": "B", "content_revision": 2}
    conflict = _merge_drafts([first], [second])[0]
    edited = {"id": "d1", "text": "C", "content_revision": 3, "status": "pending", "revision_history": [conflict]}
    row = _merge_drafts([conflict], [edited])[0]
    assert row["text"] == "C"
    assert not row.get("revision_conflicts")
    assert row["revision_history"]


def test_same_attempt_receipt_cannot_be_replaced_by_stale_submission():
    submitted = {"intent_id": "i1", "at": "2026-09-08T12:00:00Z", "phase": "submitted", "tweet_id": None}
    confirmed = {**submitted, "phase": "confirmed", "tweet_id": "t1"}
    for a, b in [(submitted, confirmed), (confirmed, submitted)]:
        row = _merge_publish_ledger({"e1": a}, {"e1": b})["e1"]
        assert row == confirmed


def test_reconciled_receipt_preserves_attempt_start_and_resolves_submission():
    submitted = {"id": "d1", "text": "40°C", "content_revision": 1, "status": "pending", "publish_outcome": "submitted", "last_publish_attempt_at": "2026-09-08T12:00:00Z", "updated_at": "2026-09-08T12:00:00Z"}
    confirmed = {**submitted, "status": "posted", "publish_outcome": "confirmed", "tweet_id": "t1", "posted_at": "2026-09-08T12:01:00Z", "updated_at": "2026-09-08T13:00:00Z"}
    row = _merge_drafts([submitted], [confirmed])[0]
    assert row["publish_outcome"] == "confirmed"
    assert row["last_publish_attempt_at"] == submitted["last_publish_attempt_at"]


def test_distinct_attempt_and_older_receipt_both_survive():
    draft = {"id": "d1", "event_id": "e1", "text": "B", "content_revision": 2}
    confirmed = {"intent_id": "i1", "at": "2026-09-08T12:00:00Z", "phase": "confirmed", "tweet_id": "t1", "text": "A"}
    unknown = {"intent_id": "i2", "at": "2026-09-08T13:00:00Z", "phase": "unknown", "text": "B"}
    ledger = _merge_publish_ledger({"e1": confirmed}, {"e1": unknown})
    assert ledger["e1"]["tweet_id"] == "t1"
    assert ledger["e1"]["attempt_conflicts"] == [unknown]
    assert has_unresolved_publish(draft, {"publish_ledger": ledger})
    assert _merge_publish_ledger(ledger, {"e1": confirmed}) == ledger


def test_unresolved_rejected_draft_is_not_trimmed():
    unknown = {"id": "unknown", "status": "rejected", "created_at": "2000-01-01T00:00:00Z", "publish_outcome": "unknown", "last_publish_attempt_at": "2000-01-01T00:00:00Z"}
    state = {"drafts": [unknown, *[{"id": str(i), "status": "pending"} for i in range(201)]]}
    trim_drafts(state)
    assert unknown in state["drafts"]


@pytest.mark.parametrize("change", ["text", "approval", "attempt"])
def test_gist_expected_draft_rejects_observed_concurrent_change(change):
    draft = {"id": "d1", "event_id": "e1", "text": "40°C", "content_revision": 1, "status": "approved", "approval_binding": {"mode": "manual"}}
    current = {"drafts": [deepcopy(draft)], "publish_ledger": {}}
    if change == "text":
        current["drafts"][0].update(text="50°C", content_revision=2)
    elif change == "approval":
        current["drafts"][0].pop("approval_binding")
    else:
        current["publish_ledger"]["e1"] = {"intent_id": "other", "phase": "submitted"}
    with patch("src.state._configured_backend", return_value="gist"), patch("src.state._read_gist_state", return_value=current), patch("src.state._write_gist_state") as write:
        assert not write_state({"drafts": [draft]}, expected_draft=draft)
    write.assert_not_called()


def test_sqlite_round_trip_keeps_nested_revision_and_attempt_evidence(tmp_path):
    draft = {"id": "d1", "event_id": "e1", "text": "40°C", "content_revision": 2, "status": "pending", "revision_history": [{"content_revision": 1, "text": "30°C"}], "revision_conflicts": [{"content_revision": 2, "text": "41°C"}], "publish_outcome": "unknown"}
    draft["review_binding"] = {**draft_identity(draft), "kind": "human"}
    state = {"drafts": [draft], "publish_ledger": {"e1": {"intent_id": "i1", "phase": "unknown", **draft_identity(draft), "text": draft["text"], "attempt_conflicts": [{"intent_id": "old", "tweet_id": "receipt"}]}}}
    with patch.multiple("src.state", STATE_BACKEND="sqlite", DB_PATH=str(tmp_path / "state.sqlite"), GIST_ID="", GITHUB_TOKEN=""):
        assert write_state(state)
        loaded = read_state()
    assert loaded["drafts"] == [draft]
    assert loaded["publish_ledger"]["e1"]["tweet_id"] == "receipt"
    assert loaded["publish_ledger"]["e1"]["attempt_conflicts"][0]["phase"] == "unknown"
