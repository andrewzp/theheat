"""Live-content owner bytes revoke checks, never delivered-content identity.

All drafts, model passes, cache verdicts and receipts are invented offline fixtures.
Only a private copy of the actual complete policy input set is mutated.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

import pytest

from src.editorial import policy
from src.editorial.revisions import (
    approval_is_current, binding_matches, draft_identity, fingerprint,
    record_model_review, review_is_current,
)
from src.two_bot import negative_cache as cache
from src.two_bot.types import StoryBundle
from tests.revision_helpers import bind_reviewed_draft


OWNERS = (
    "src/editorial/hot10_contract.py",
    "src/two_bot/hot10_claims.py",
    "src/editorial/automatic_text.py",
    "dashboard/lib/automatic-text.js",
    "src/orchestrator/hot10.py",
    "src/data/air_quality_current.py",
    "src/editorial/delegated_media_review.py",
    "src/commands/delivery_reconciliation.py",
    "dashboard/lib/delivery-reconciliation.js",
    "dashboard/app/api/delivery-reconciliation/route.js",
    "src/commands/job_authority.py",
    "src/commands/writer_fencing.py",
    "src/commands/recovery_provenance.py",
    "src/commands/import_plan.py",
    "src/evaluation/file_boundary.py",
)


@pytest.mark.parametrize("owner", OWNERS)
def test_live_content_owner_bytes_revoke_policy_and_reopen_the_exact_cached_decision(monkeypatch, tmp_path, owner):
    manifest = policy.source_manifest()
    # Copy every real policy input plus the named owner even if omitted: red must
    # demonstrate the unchanged policy after an actual owner-byte mutation.
    for name in set(manifest["files"]) | set(OWNERS):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((policy.ROOT / name).read_bytes())
    monkeypatch.setattr(policy, "ROOT", tmp_path)
    assert policy.source_manifest() == manifest
    before_policy = policy.current_editorial_policy()
    assert before_policy is not None
    before_epoch = cache.decision_epoch()
    assert len(before_epoch) == 64

    draft = bind_reviewed_draft(
        {"id": "invented-policy-draft", "event_id": "invented-policy-event",
         "type": "monthly_high", "text": "Port Example's forecast high is 40°C."},
        "manual", "invented-intent",
    )
    identity = draft_identity(draft)
    receipt = {**identity, "tweet_id": "invented-retained-receipt", "phase": "confirmed"}
    assert draft["review_binding"]["kind"] == "model"
    assert review_is_current(draft) and approval_is_current(draft)
    state = {"drafts": [draft], "publish_ledger": {draft["event_id"]: receipt}}
    packet = StoryBundle(
        "coral_bleaching", "Invented Reef", "2026-10-30", draft["event_id"],
        {"label": "dhw", "value": 8}, [],
    )
    now = datetime(2026, 10, 30, 3, tzinfo=UTC)
    facts_sha = cache.bundle_fingerprint(packet, state, now=now)
    assert facts_sha
    for offset in (2, 1):
        cache.record_kill(
            state, packet.event_id, facts_sha, "writer", "invented missing evidence",
            scope="evidence", code="insufficient_evidence", now=now - timedelta(minutes=offset),
        )
    assert cache.should_skip(state, packet.event_id, packet, now=now)
    retained = json.dumps(state, sort_keys=True, ensure_ascii=False)

    target = tmp_path / owner
    comment = b"\n// Invented owner-byte mutation.\n" if target.suffix == ".js" else b"\n# Invented owner-byte mutation.\n"
    target.write_bytes(target.read_bytes() + comment)
    changed = policy.source_manifest()
    assert changed["source_sha256"] != manifest["source_sha256"]
    assert {name for name, digest in changed["files"].items() if digest != manifest["files"][name]} == {owner}
    assert policy.current_editorial_policy() != before_policy
    assert not review_is_current(draft) and not approval_is_current(draft)
    assert draft_identity(draft) == identity and binding_matches(draft, receipt)

    assert cache.decision_epoch() != before_epoch
    assert cache.bundle_fingerprint(packet, state, now=now) == facts_sha
    assert cache.should_skip(state, packet.event_id, packet, now=now) is None
    # All other epoch inputs are unchanged: restoring only the policy value for
    # this read restores the old epoch/cache decision; no record is restamped.
    with monkeypatch.context() as scoped:
        scoped.setattr(policy, "current_editorial_policy", lambda: before_policy)
        assert cache.decision_epoch() == before_epoch
        assert cache.should_skip(state, packet.event_id, packet, now=now)
    assert json.dumps(state, sort_keys=True, ensure_ascii=False) == retained

    retry = deepcopy(draft)
    old_check_policy = retry["review_context"]["two_bot"]["reviewed_policy_sha256"]
    assert old_check_policy == fingerprint(before_policy)
    record_model_review(retry)
    assert "review_binding" not in retry
    assert not review_is_current(retry) and not approval_is_current(retry)
    assert retry["review_context"]["two_bot"]["reviewed_policy_sha256"] == old_check_policy
    assert draft_identity(retry) == identity and binding_matches(retry, receipt)
    assert json.dumps(state, sort_keys=True, ensure_ascii=False) == retained
