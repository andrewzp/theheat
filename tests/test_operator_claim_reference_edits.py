"""Real edit/reducer/journal consumers over invented retained facts."""
from copy import deepcopy

import pytest

from src.commands.reducer import reduce_command
from src.commands.schema import CommandError
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.operator_claim_references import build_operator_claim_references
from src.editorial.revisions import draft_identity, initialize_revision, invalidate_text, project_draft
from tests.test_command_authority import EDITOR, NOW, command, resolver
from tests.test_operator_claim_references import FIXTURE


def reference_draft():
    return initialize_revision({"id": "invented-reference", "event_id": FIXTURE["bundle"]["event_id"],
        "type": FIXTURE["bundle"]["signal_kind"], "text": FIXTURE["text"], "status": "pending",
        "review_context": {"source": "Invented fixture", "two_bot": {"bundle": deepcopy(FIXTURE["bundle"])}}})


def test_reference_only_edit_invalidates_every_decision_but_preserves_media_and_source_history():
    draft = reference_draft()
    draft.update(status="approved", review_binding={"old": "text review"}, approval_binding={"old": "approval"},
                 publish_intent_id="invented-old-intent", media_attachment={"invented": "retained recipe"},
                 media_review_binding={"old": "joint decision"}, auto_approve_at="2032-01-01T00:00:00Z")
    draft["review_context"]["two_bot"]["fact_check"] = {"passed": None, "unknown": True}
    before = deepcopy(draft)
    invalidate_text(draft, draft["text"], operator_claim_references=FIXTURE["items"])
    assert draft["content_revision"] == before["content_revision"] + 1
    assert draft["decision_revision"] == before["decision_revision"] + 1
    assert draft["status"] == "pending"
    for key in ("review_binding", "approval_binding", "publish_intent_id", "media_review_binding", "auto_approve_at"):
        assert key not in draft
    assert draft["media_attachment"] == before["media_attachment"]
    assert draft["review_context"]["two_bot"] == {"bundle": FIXTURE["bundle"]}
    assert draft["revision_history"][0]["review_context"] == before["review_context"]
    assert draft_identity(draft)["evidence_sha256"] != draft_identity(before)["evidence_sha256"]
    assert project_draft(draft)["operator_claim_reference_view"]["status"] == "saved"


def test_omission_empty_noop_text_change_and_revert_have_distinct_history_semantics():
    draft = reference_draft()
    invalidate_text(draft, draft["text"], operator_claim_references=FIXTURE["items"])
    before = deepcopy(draft)
    invalidate_text(draft, draft["text"])
    assert draft == before
    invalidate_text(draft, draft["text"], operator_claim_references=FIXTURE["items"])
    assert draft == before
    invalidate_text(draft, draft["text"], operator_claim_references=[])
    assert "operator_claim_references" not in draft["review_context"]
    assert draft["content_revision"] == before["content_revision"] + 1
    assert project_draft(draft)["operator_claim_reference_history"][-1]["operator_claim_reference_view"]["status"] == "saved"
    invalidate_text(draft, draft["text"], operator_claim_references=FIXTURE["items"])
    invalidate_text(draft, FIXTURE["text"] + ".")
    assert "operator_claim_references" not in draft["review_context"]
    invalidate_text(draft, FIXTURE["text"])
    assert "operator_claim_references" not in draft["review_context"]
    assert project_draft(draft)["operator_claim_reference_view"]["status"] == "missing"


def test_invalid_or_unresolved_references_fail_one_edit_without_mutating_inputs():
    for change in (lambda d, i: i[0]["sources"][0].update(pointer="/current_facts/64"),
                   lambda d, i: d["review_context"]["two_bot"]["bundle"].update(event_id="other-source"),
                   lambda d, i: i[0]["sources"][0].update(value_sha256="a" * 64)):
        draft, items = reference_draft(), deepcopy(FIXTURE["items"])
        change(draft, items)
        before = deepcopy(draft)
        with pytest.raises(ValueError):
            invalidate_text(draft, draft["text"], operator_claim_references=items)
        assert draft == before


def test_real_local_command_envelope_reducer_and_sqlite_journal_round_trip(tmp_path):
    draft = reference_draft()
    state = {"drafts": [draft], "publish_ledger": {}, "unknown": {"retained": True}}
    store = SQLiteAuthority(tmp_path / "invented.sqlite")
    store.initialize(state)
    cmd = command(draft, payload={"text": draft["text"], "operator_claim_references": FIXTURE["items"]})
    reduced = reduce_command(state, cmd, EDITOR, now=NOW)
    assert state["drafts"][0] == draft
    assert reduced.state["drafts"][0]["review_context"]["operator_claim_references"] == FIXTURE["saved"]
    store.accept(cmd, EDITOR)
    assert store.consume(resolver, command_id=cmd.command_id, now=NOW)["status"] == "applied"
    version, saved = store.read()
    assert version == 1
    assert saved == reduced.state
    # Reusing the exact accepted command cannot duplicate its revision history.
    store.accept(cmd, EDITOR)
    assert store.read() == (version, saved)


@pytest.mark.parametrize("change", [
    lambda d, s: d.update(text=d["text"] + "."),
    lambda d, s: d.update(decision_revision=d["decision_revision"] + 1),
    lambda d, s: d.update(id="other-draft"),
    lambda d, s: d["review_context"]["two_bot"]["bundle"]["current_facts"][0].update(value=99),
    lambda d, s: d.update(publish_outcome="unknown"),
    lambda d, s: s["publish_ledger"].update({d["event_id"]: {"phase": "submitted"}}),
])
def test_existing_revision_and_delivery_fences_apply_to_reference_only_edits(change):
    draft = reference_draft()
    cmd = command(draft, payload={"text": draft["text"], "operator_claim_references": FIXTURE["items"]})
    state = {"drafts": [draft], "publish_ledger": {}}
    change(draft, state)
    before = deepcopy(state)
    with pytest.raises(CommandError):
        reduce_command(state, cmd, EDITOR, now=NOW)
    assert state == before


def test_viewer_fence_remains_and_source_refresh_never_guesses_new_references():
    from src.commands.schema import Principal
    draft = reference_draft()
    with pytest.raises(CommandError):
        command(draft, payload={"text": draft["text"], "operator_claim_references": []}, principal=Principal("invented-viewer", "viewer", "fixture"))
    draft["review_context"]["operator_claim_references"] = build_operator_claim_references(draft["text"], FIXTURE["bundle"], FIXTURE["items"])
    draft["review_context"]["two_bot"]["bundle"]["current_facts"][0]["value"] = 99
    assert project_draft(draft)["operator_claim_reference_view"]["status"] == "unavailable"


def test_projection_keeps_explicit_saved_type_scope_and_times_distinct_from_unknowns():
    draft = reference_draft()
    draft["review_context"]["two_bot"]["bundle"]["evidence"] = {
        "evidence_type": "forecast", "spatial_scope": "model_grid_point", "issued_at": None,
        "valid_start": "2032-01-02T00:00:00Z", "valid_end": "2032-01-03T00:00:00Z"}
    invalidate_text(draft, draft["text"], operator_claim_references=FIXTURE["items"])
    view = project_draft(draft)["operator_claim_reference_view"]
    assert view["source_type"] == "forecast"
    assert view["scope"] == "model_grid_point"
    assert view["issued_at"] is None
    assert view["valid_start"] == "2032-01-02T00:00:00Z"
