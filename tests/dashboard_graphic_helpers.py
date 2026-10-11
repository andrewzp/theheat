"""Invented saved source fixture; never read credentials or production state."""
from src.editorial.revisions import draft_identity, decision_revision
from tests.fire_graphic_helpers import graphic_bundle

POLICY = "a" * 64
RUNTIME = "b" * 64


def saved_preview():
    draft = {"id": "invented-fire", "status": "pending", "type": "fire",
             "text": "Invented thermal detections for a graphic test.",
             "review_context": {"two_bot": {"bundle": graphic_bundle().to_dict()}},
             "checks": {"retained": "unchanged"}, "approval": {"retained": "unchanged"}}
    request = {"draft_id": draft["id"],
               "expected_revision": {**draft_identity(draft), "decision_revision": decision_revision(draft)},
               "expected_policy_source_sha256": POLICY, "expected_preview_runtime_sha256": RUNTIME}
    return {"drafts": [draft], "publication_ledger": [], "unrelated": {"preserve": True}}, request
