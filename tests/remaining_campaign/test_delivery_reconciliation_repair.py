"""Invented late receipts reconcile transport without restoring approval."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.commands import delivery_reconciliation as rec
from src.orchestrator import posting
from src.posting.outbox_outcome import retry_permitted

VECTORS = json.loads((Path(__file__).parents[1] / "fixtures" / "w14_delivery_reconciliation_vectors.json").read_text())
STEPS = VECTORS["cases"][-1]["steps"]
EVENT = STEPS[0]["request"]["event_id"]
AT = "2026-10-30T11:00:00Z"


def decide(state, request):
    return rec.decide(state, request, actor="invented-publisher", at=AT)


@pytest.mark.parametrize("phase", ["unknown", "submitted", None])
def test_withdrawal_reload_late_receipt_and_real_publisher_consumer(phase):
    state = deepcopy(VECTORS["state"])
    row = state["publish_ledger"][EVENT]
    if phase is None:
        row.pop("phase")
    else:
        row["phase"] = phase
    original = deepcopy(state)
    state, result = decide(state, STEPS[0]["request"])
    assert result["status"] == "applied"
    cancellation = deepcopy(state["publish_ledger"][EVENT]["operator_cancellation"])
    view = next(row for row in rec.inspect(state)["rows"] if row["event_id"] == EVENT)
    assert view["actions"] == ["confirm"] and view["cancelled"] and not view["retry_permitted"]
    state = json.loads(json.dumps(state))  # a reload must retain both identities
    state, result = decide(state, STEPS[1]["request"])
    row = state["publish_ledger"][EVENT]
    assert result["status"] == "applied" and row["phase"] == "confirmed"
    assert row["operator_cancellation"] == cancellation and not retry_permitted(row)
    for key, value in original["publish_ledger"][EVENT].items():
        if key not in {"phase", "tweet_id"}:
            assert row[key] == value
    for event_id in original["publish_ledger"]:
        if event_id != EVENT:
            assert state["publish_ledger"][event_id] == original["publish_ledger"][event_id]
    draft = next(d for d in state["drafts"] if d["event_id"] == EVENT)
    assert draft["status"] == "rejected" and draft["decision_revision"] == 3
    assert "approval_binding" not in draft and "publish_intent_id" not in draft
    assert decide(state, STEPS[2]["request"])[1]["status"] == "unchanged"
    with pytest.raises(rec.ReconciliationError, match="delivered_content_retained"):
        decide(state, STEPS[3]["request"])
    posting._reconcile_publish_ledger(state)
    assert draft["status"] == "posted" and draft["publish_outcome"] == "confirmed"
    assert draft["tweet_id"] == row["tweet_id"] == "1900000000000000901"
    assert row["operator_cancellation"] == cancellation and not retry_permitted(row)


@pytest.mark.parametrize("mutation,code", [
    ("text", "receipt_text_mismatch"), ("time", "receipt_predates_attempt"),
    ("intent", "attempt_mismatch"), ("revision", "stale_decision_revision"),
    ("source", "source_snapshot_changed"), ("missing", "receipt_required"),
])
def test_withdrawal_never_weakens_exact_receipt_checks(mutation, code):
    state, _ = decide(deepcopy(VECTORS["state"]), STEPS[0]["request"])
    request = deepcopy(STEPS[1]["request"])
    if mutation == "text":
        request["receipt"]["text"] = "Invented unrelated text."
    elif mutation == "time":
        request["receipt"]["created_at"] = "2026-10-30T09:00:00Z"
    elif mutation == "intent":
        request["intent_id"] = "invented-other-intent"
    elif mutation == "revision":
        request["expected_decision_revision"] = 2
    elif mutation == "source":
        state["drafts"][0]["review_context"]["two_bot"]["bundle"]["current_facts"][0]["value"] = "Invented changed evidence"
    else:
        request.pop("receipt")
    before = deepcopy(state)
    with pytest.raises(rec.ReconciliationError, match=code):
        decide(state, request)
    assert state == before and not retry_permitted(state["publish_ledger"][EVENT])


def test_withdrawn_media_still_requires_the_exact_description_and_preserves_image_limits():
    request = deepcopy(next(c for c in VECTORS["cases"] if c["name"] == "media_alt_match")["steps"][0]["request"])
    cancel = {key: value for key, value in request.items() if key != "receipt"}
    cancel.update(action="cancel", reconciliation_id="invented-media-withdrawal")
    state, _ = decide(deepcopy(VECTORS["state"]), cancel)
    request["expected_decision_revision"] = 3
    bad = deepcopy(request)
    bad["receipt"]["alt_text"] = "Invented unrelated description."
    before = deepcopy(state)
    with pytest.raises(rec.ReconciliationError, match="receipt_media_mismatch"):
        decide(state, bad)
    assert state == before
    state, _ = decide(state, request)
    row = state["publish_ledger"][request["event_id"]]
    assert row["operator_cancellation"] == before["publish_ledger"][request["event_id"]]["operator_cancellation"]
    assert row["delivery_identity"] == before["publish_ledger"][request["event_id"]]["delivery_identity"]
    assert row["reconciliation"]["png_receipt_verification"] == "not_available_from_platform"
    assert not retry_permitted(row)


def test_proven_not_sent_stays_unconfirmable_after_withdrawal():
    request = deepcopy(next(c for c in VECTORS["cases"] if c["name"] == "not_sent_cannot_be_confirmed")["steps"][0]["request"])
    cancel = {key: value for key, value in request.items() if key != "receipt"}
    cancel.update(action="cancel", reconciliation_id="invented-notsent-withdrawal")
    state, _ = decide(deepcopy(VECTORS["state"]), cancel)
    request["expected_decision_revision"] = 3
    before = deepcopy(state)
    with pytest.raises(rec.ReconciliationError, match="attempt_proven_not_sent"):
        decide(state, request)
    assert state == before and not retry_permitted(state["publish_ledger"][request["event_id"]])
    view = next(row for row in rec.inspect(state)["rows"] if row["event_id"] == request["event_id"])
    assert view["actions"] == []
