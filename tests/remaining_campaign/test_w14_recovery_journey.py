"""W14.6: one fixture journey through real consumers; invariants checked in Python.

dashboard/tests/remaining-campaign-w14-recovery.test.js spawns the same child as a fresh
process and projects its output across the editor, Published and Operations surfaces.
"""
from __future__ import annotations

import pytest

from tests.remaining_campaign import w14_journey_child

pytestmark = pytest.mark.usefixtures("automatic_publication_release")


def test_source_job_outbox_receipt_history_import_journey(tmp_path):
    result = w14_journey_child.run(str(tmp_path))
    steps = {row["step"]: row for row in result["journey"] if row["step"] not in {"outbox"}}
    outbox = [row for row in result["journey"] if row["step"] == "outbox"]
    assert [(row["result"], row["phase"]) for row in outbox] == [("failed", "unknown"), ("failed", "unknown")]
    assert steps["no_resend"] == {"step": "no_resend", "result": "failed", "create_calls": 2}
    assert steps["receipt"]["status"] == "applied" and steps["cancel_unknown"]["status"] == "applied"
    assert steps["cancel_delivered"] == {"step": "cancel_delivered", "result": "refused", "code": "delivered_content_retained"}
    assert steps["import"]["statuses"] == ["imported"]
    state = result["state"]
    delivered = next(d for d in state["drafts"] if d["id"] == "w14j-delivered")
    cancelled = next(d for d in state["drafts"] if d["id"] == "w14j-cancelled")
    row = state["publish_ledger"]["w14j-ev-delivered"]
    assert delivered["status"] == "posted" and delivered["tweet_id"] == row["tweet_id"] == "1900000000000004242"
    assert row["text"] == delivered["text"] and row["reconciliation"]["evidence"] == "operator_supplied_receipt"
    kept = state["publish_ledger"]["w14j-ev-cancelled"]
    assert cancelled["status"] == "rejected" and kept["phase"] == "unknown" and kept["tweet_id"] is None
    assert kept["delivery_outcome"]["reason"] == "create_response_missing" and kept["operator_cancellation"]["actor"] == "w14j-publisher"
