"""Editorial-policy revisions never change the identity of delivered content."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from src.editorial import policy
from src.editorial.revisions import (
    approval_is_current, binding_matches, draft_identity, fingerprint, has_unresolved_publish,
    initialize_revision, project_draft, record_human_review, record_model_review, review_is_current,
)
from tests.revision_helpers import bind_reviewed_draft, model_review_context

ROOT = Path(__file__).resolve().parents[1]


def approved():
    return bind_reviewed_draft({"id": "draft", "event_id": "event", "type": "monthly_high", "text": "40°C forecast"}, "manual", "intent")


def node(script, data):
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(data),
                            cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_generated_source_manifest_is_current_and_version_is_not_an_input():
    subprocess.run([__import__('sys').executable, "scripts/gen_editorial_policy.py", "--check"], cwd=ROOT, check=True)
    manifest = policy.source_manifest()
    assert "VERSION" not in manifest["files"]
    for name in ("src/two_bot/prompts/writer_prompt.py", "src/two_bot/strict_contract.py", "src/data/temperature_evidence.py"):
        assert name in manifest["files"]


def test_missing_legacy_policy_cannot_be_stamped_onto_old_model_checks():
    draft = approved()
    draft["review_binding"].pop("editorial_policy")
    assert not review_is_current(draft) and not approval_is_current(draft)
    old = {"text": "40°C forecast", "review_context": model_review_context("40°C forecast")}
    old["review_context"]["two_bot"].pop("reviewed_policy_sha256")
    initialize_revision(old)
    assert "review_binding" not in old


@pytest.mark.parametrize("change", ["source", "model", "prompt", "checking_flag"])
def test_policy_change_revokes_eligibility_without_changing_content_or_receipts(monkeypatch, change):
    from src.two_bot import writer
    draft = approved()
    identity = draft_identity(draft)
    receipt = {**identity, "tweet_id": "receipt", "phase": "confirmed"}
    state = {"publish_ledger": {"event": deepcopy(receipt)}}
    if change == "source":
        monkeypatch.setattr(policy, "source_manifest", lambda: {"source_sha256": "f" * 64})
    elif change == "model":
        monkeypatch.setattr(writer, "WRITER_MODEL", "claude-different-policy")
    elif change == "prompt":
        monkeypatch.setattr(writer, "WRITER_SYSTEM_PROMPT", writer.WRITER_SYSTEM_PROMPT + " Updated policy.")
    else:
        monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    assert not review_is_current(draft) and not approval_is_current(draft)
    assert draft_identity(draft) == identity and binding_matches(draft, receipt)
    assert not has_unresolved_publish(draft, state)
    assert state["publish_ledger"]["event"] == receipt
    record_model_review(draft)
    assert not review_is_current(draft)  # Old model proof cannot acquire new policy.
    record_human_review(draft)
    assert review_is_current(draft) and draft["review_binding"]["kind"] == "human"
    assert not approval_is_current(draft)


def test_python_javascript_bindings_match_and_require_explicit_current_policy():
    draft = approved()
    expected = policy.current_editorial_policy()
    result = node('''
      import { readFileSync } from "node:fs";
      import { approvalIsCurrent, reviewIsCurrent, recordHumanReview, fingerprint, draftIdentity } from "./dashboard/lib/draft-revisions.js";
      const {draft, policy} = JSON.parse(readFileSync(0, "utf8"));
      const missing = reviewIsCurrent(draft);
      const accepted = approvalIsCurrent(draft, "manual", policy);
      const other = structuredClone(policy); other.models.writer = "another-model";
      const changed = reviewIsCurrent(draft, other);
      const human = {text: draft.text}; recordHumanReview(human, policy);
      console.log(JSON.stringify({missing, accepted, changed, human, identity: draftIdentity(draft), hash: fingerprint(policy)}));
    ''', {"draft": draft, "policy": expected})
    assert result["accepted"] and not result["missing"] and not result["changed"]
    assert result["hash"] == fingerprint(expected) and result["identity"] == draft_identity(draft)
    assert review_is_current(result["human"])


def test_dashboard_expired_missing_newer_or_mismatched_inventory_is_unverified():
    now = "2026-09-09T12:00:00Z"
    snapshot = {"schema_version": 1, "captured_at": now, "editorial_policy": policy.current_editorial_policy()}
    result = node('''
      import { readFileSync } from "node:fs";
      import { dashboardEditorialPolicy } from "./dashboard/lib/editorial-policy.js";
      const {snapshot, now} = JSON.parse(readFileSync(0, "utf8")); const clock = Date.parse(now);
      const run = {started_at: now, runtime_inventory: snapshot};
      const check = (runs, time=clock) => dashboardEditorialPolicy({run_history: runs}, {now:time}).status;
      const valid = check([run]); const stale = check([run], clock+7*3600000);
      const missing = check([{started_at:now}]);
      const mismatch = structuredClone(run); mismatch.runtime_inventory.editorial_policy.source_sha256 = "a".repeat(64);
      console.log(JSON.stringify({valid, stale, missing, mismatch:check([mismatch]), newer:check([run,{started_at:"2026-09-09T13:00:00Z"}],clock+3600000)}));
    ''', {"snapshot": snapshot, "now": now})
    assert result == {"valid": "recorded", "stale": "unverified", "missing": "unverified", "mismatch": "unverified", "newer": "unverified"}


@pytest.mark.parametrize("field", ["schema_version", "writer_samples"])
def test_boolean_policy_corruption_is_rejected_in_both_runtimes(field):
    draft = approved()
    stored = draft["review_binding"]["editorial_policy"]
    if field == "schema_version":
        stored[field] = True
    else:
        stored["flags"][field] = True
    assert not review_is_current(draft) and not approval_is_current(draft)
    assert node('''
      import { readFileSync } from "node:fs";
      import { reviewIsCurrent } from "./dashboard/lib/draft-revisions.js";
      const {draft, policy} = JSON.parse(readFileSync(0,"utf8"));
      console.log(JSON.stringify(reviewIsCurrent(draft, policy)));
    ''', {"draft": draft, "policy": policy.current_editorial_policy()}) is False


@pytest.mark.parametrize("phase", ["confirmed", "submitted", "unknown"])
def test_policy_drift_preserves_retained_draft_and_receipt_bytes(monkeypatch, phase):
    from src.orchestrator.posting import _reconcile_publish_ledger
    from src.two_bot import writer

    draft = approved()
    draft["publish_outcome"] = phase
    receipt = {**draft_identity(draft), "phase": phase, "at": "2026-09-09T10:00:00Z"}
    if phase == "confirmed":
        draft.update(status="posted", tweet_id="receipt")
        receipt["tweet_id"] = "receipt"
    state = {"drafts": [draft], "publish_ledger": {draft["event_id"]: receipt}}
    before = json.dumps(state, sort_keys=True, ensure_ascii=False)
    monkeypatch.setattr(writer, "WRITER_MODEL", writer.WRITER_MODEL + "-changed")
    assert not review_is_current(draft) and not approval_is_current(draft)
    project_draft(draft)
    _reconcile_publish_ledger(state)
    assert json.dumps(state, sort_keys=True, ensure_ascii=False) == before
    assert has_unresolved_publish(draft, state) is (phase != "confirmed")


@pytest.mark.parametrize("field", ["source_sha256", "execution_sha256"])
def test_policy_hashes_require_strings_in_both_runtimes(field):
    descriptor = policy.current_editorial_policy()
    descriptor[field] = [descriptor[field]]
    assert not policy.valid_policy(descriptor)
    assert node('''
      import { readFileSync } from "node:fs";
      import { validEditorialPolicy } from "./dashboard/lib/editorial-policy.js";
      console.log(JSON.stringify(validEditorialPolicy(JSON.parse(readFileSync(0,"utf8")))));
    ''', descriptor) is False
