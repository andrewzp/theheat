"""Prospective revisions with qualified synthetic evidence; no paid or human rating."""

from copy import deepcopy
import json
import socket
import subprocess

import pytest

from src.editorial.revisions import (
    approval_is_current,
    bind_reviewed_revision,
    decision_revision,
    draft_identity,
    fingerprint,
    invalidate_text,
    record_human_review,
    record_model_review,
    review_is_current,
    text_hash,
)
from src.media.attachment import build_media_attachment_proposal, build_media_removal_proposal
from src.media.review_packet import MediaReviewError, build_media_review_packet
from tests.test_joint_media_review import make, status
from tests.test_media_review_packet import seed as seed, digest

AT = "2026-10-01T18:00:00Z"


def revision(draft):
    return {
        "draft_id": draft["id"],
        **draft_identity(draft),
        "decision_revision": decision_revision(draft),
    }


@pytest.fixture
def inputs(seed):
    return deepcopy(seed)


def proposal(inputs, *, state=None, expected=None, **overrides):
    draft = inputs["draft"]
    args = {
        k: inputs[k] for k in ("editorial_policy", "graphic_spec", "renderer_manifest", "png_bytes")
    }
    args.update(expected_revision=expected if expected is not None else revision(draft), at=AT)
    return build_media_attachment_proposal(
        state if state is not None else {"drafts": [draft], "publish_ledger": {}},
        draft["id"],
        **(args | overrides),
    )


def removal(draft, **overrides):
    return build_media_removal_proposal(
        {"drafts": [draft], "publish_ledger": {}},
        draft["id"],
        **(dict(expected_revision=revision(draft), at=AT) | overrides),
    )


def with_proposed(inputs, result):
    draft = result["proposed_draft"]
    return inputs | {"draft": draft, "expected_draft_identity": draft_identity(draft)}


def test_proposal_is_stable_detached_and_invalidates_exact_previous_review(inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Proposal attempted external I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    draft = inputs["draft"]
    # Explicit synthetic check stubs, not actual model/source/human evaluation.
    proof = draft["review_context"]["two_bot"]
    proof.update(
        fact_check={"passed": True},
        critic={"passed": True},
        reviewed_text_sha256=text_hash(draft["text"]),
        reviewed_bundle_sha256=fingerprint(proof["bundle"]),
        reviewed_policy_sha256=fingerprint(inputs["editorial_policy"]),
    )
    record_model_review(draft, policy=inputs["editorial_policy"])
    bind_reviewed_revision(
        draft, "manual", at=AT, intent_id="synthetic-intent", policy=inputs["editorial_policy"]
    )
    draft.update(
        status="approved",
        approved_at=AT,
        auto_approve_at=AT,
        candidate_score={"total": 99},
        selected_candidate_rank=2,
    )
    original = deepcopy(inputs)
    first = proposal(inputs)
    assert first == proposal(inputs) and inputs == original
    proposed = first["proposed_draft"]
    assert first["changed"] and proposed["status"] == "pending"
    assert proposed["content_revision"] == draft["content_revision"] + 1
    assert proposed["decision_revision"] == draft["decision_revision"] + 1
    assert proposed["text"] == draft["text"]
    assert proposed["revision_history"][-1]["approval_binding"] == draft["approval_binding"]
    assert proposed["review_context"]["two_bot"] == {"bundle": proof["bundle"]}
    for name in (
        "review_binding",
        "approval_binding",
        "publish_intent_id",
        "auto_approve_at",
        "approved_at",
        "candidate_score",
        "selected_candidate_rank",
    ):
        assert name not in proposed
    assert not review_is_current(proposed, policy=inputs["editorial_policy"])
    assert not approval_is_current(proposed, policy=inputs["editorial_policy"])
    assert first["publication_approved"] is first["production_attachment_authorized"] is False
    assert first["synthetic"] is True and first["packet"]["draft_binding"]["content_revision"] == 2
    content = proposed["media_attachment"]
    assert set(content) == {"schema_version", "graphic_binding", "media", "synthetic"}
    assert not any(k in content for k in ("packet_sha256", "review_sha256", "draft_binding"))
    proposed["media_attachment"]["media"]["alt_text"] = "mutated output"
    assert inputs == original


@pytest.mark.parametrize("decision", ["accept", "reject", "needs_changes"])
def test_review_must_target_the_exact_future_revision(inputs, decision):
    old = make(inputs)
    result = proposal(inputs)
    current = with_proposed(inputs, result)
    assert status(old, current)["status"] == "obsolete"
    from tests.test_joint_media_review import payload

    record = make(current, payload=payload(decision))
    found = status(record, current)
    assert found["current"] and found["accepted"] == (decision == "accept")
    assert not found["publication_approved"] and not found["production_attachment_authorized"]
    assert status(record, inputs)["status"] == "obsolete"
    changed = deepcopy(current)
    invalidate_text(changed["draft"], "Changed synthetic text.", at=AT)
    changed["expected_draft_identity"] = draft_identity(changed["draft"])
    assert status(record, changed)["status"] == "obsolete"


@pytest.mark.parametrize(
    "field", ["content_revision", "decision_revision", "text_sha256", "evidence_sha256", "draft_id"]
)
def test_stale_predecessor_cannot_follow_current_state(inputs, field):
    expected = revision(inputs["draft"])
    expected[field] = expected[field] + 1 if type(expected[field]) is int else "wrong"
    with pytest.raises(MediaReviewError, match="predecessor"):
        proposal(inputs, expected=expected)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "oversized",
        "nonlist",
        "nonstate",
        "bad_ledger",
        "bad_posted",
        "confirmed",
        "unknown",
        "null_attempt",
        "malformed_conflicts",
        "recorded_event",
    ],
)
def test_bad_or_published_authoritative_state_is_not_editable(inputs, change):
    draft = inputs["draft"]
    state = {"drafts": [draft], "publish_ledger": {}}
    if change == "missing":
        state["drafts"] = []
    elif change == "duplicate":
        state["drafts"].append(deepcopy(draft))
    elif change == "oversized":
        state["drafts"] += [{}] * 1024
    elif change == "nonlist":
        state["drafts"] = {}
    elif change == "nonstate":
        state = []
    elif change == "bad_ledger":
        state["publish_ledger"] = []
    elif change == "bad_posted":
        state["posted_events"] = "bad"
    elif change == "recorded_event":
        state["posted_events"] = [draft["event_id"]]
    else:
        row = {"phase": "unknown"}
        if change == "confirmed":
            row = {"phase": "confirmed", "tweet_id": "synthetic-receipt", **draft_identity(draft)}
        elif change == "null_attempt":
            row = None
        elif change == "malformed_conflicts":
            row = {"phase": "not_sent", "attempt_conflicts": None}
        state["publish_ledger"][draft["event_id"]] = row
    before = deepcopy(state)
    with pytest.raises(MediaReviewError):
        proposal(inputs, state=state)
    assert state == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "posted"),
        ("status", "rejected"),
        ("tweet_id", "receipt"),
        ("publish_outcome", "confirmed"),
        ("publish_outcome", "submitted"),
        ("revision_conflicts", [{"text": "another"}]),
        ("revision_history", None),
        ("content_revision", 0),
        ("content_revision", 9007199254740991),
        ("decision_revision", 9007199254740990),
        ("text", " "),
        ("event_id", ""),
        ("extra", "x" * 1_000_001),
        ("extra", float("nan")),
        ("extra", "\ud800"),
    ],
)
def test_invalid_draft_is_refused_without_mutation(inputs, field, value):
    inputs["draft"][field] = value
    # Supply an independent syntactically valid expectation for malformed drafts.
    expected = {
        "draft_id": inputs["draft"]["id"],
        **inputs["expected_draft_identity"],
        "decision_revision": 0,
    }
    if field not in {"extra"}:
        expected = revision(inputs["draft"])
    with pytest.raises(MediaReviewError):
        proposal(inputs, expected=expected)


@pytest.mark.parametrize("at", ["2026-10-01T18:00:00", "2026-10-01T18:00:00+04:60", "2026-02-30T18:00:00Z", "yesterday", None, True])
def test_naive_or_malformed_clock_is_refused(inputs, at):
    with pytest.raises(MediaReviewError):
        proposal(inputs, at=at)


def test_equivalent_timezone_normalizes_and_false_revision_is_not_zero(inputs):
    assert proposal(inputs, at="2026-10-01T14:00:00-04:00") == proposal(inputs)
    expected = revision(inputs["draft"])
    expected["decision_revision"] = False
    with pytest.raises(MediaReviewError):
        proposal(inputs, expected=expected)


@pytest.mark.parametrize("change", ["png", "renderer", "svg", "pdf"])
def test_replacement_creates_another_revision_even_when_text_did_not_change(inputs, change):
    first = proposal(inputs)
    current = with_proposed(inputs, first)
    old = deepcopy(current["draft"])
    manifest = current["renderer_manifest"]
    if change == "png":
        current["png_bytes"] += b"another synthetic encoding"
        manifest["files"]["preview.png"] = digest(current["png_bytes"])
    elif change == "renderer":
        manifest["binding"]["renderer"]["implementation_sha256"] = "e" * 64
        manifest["cache_key"] = fingerprint(manifest["binding"])
    else:
        manifest["files"]["preview." + change] = "f" * 64
    second = proposal(current)
    assert second["changed"] and second["proposed_draft"]["content_revision"] == 3
    assert current["draft"] == old
    assert (
        second["proposed_draft"]["revision_history"][-1]["media_attachment"]
        == old["media_attachment"]
    )
    assert second["proposal_sha256"] != first["proposal_sha256"]
    with pytest.raises(MediaReviewError):
        build_media_review_packet(**current)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 1.0),
        ("synthetic", False),
        ("media", {}),
        ("graphic_binding", {}),
        ("extra", True),
    ],
)
def test_packet_cannot_review_a_different_or_coherently_rehashed_attachment(inputs, field, value):
    current = with_proposed(inputs, proposal(inputs))
    current["draft"]["media_attachment"][field] = value
    current["expected_draft_identity"] = draft_identity(current["draft"])
    with pytest.raises(MediaReviewError):
        build_media_review_packet(**current)


def test_identical_media_noop_and_attach_remove_attach_do_not_restore_old_review(inputs):
    first = proposal(inputs)
    current = with_proposed(inputs, first)
    second = proposal(current)
    assert not second["changed"] and second["proposed_draft"] == current["draft"]
    assert not removal(inputs["draft"])["changed"]
    removed = removal(current["draft"])
    plain = removed["proposed_draft"]
    assert removed["changed"] and removed["packet"] is None and removed["synthetic"] is None
    assert "media_attachment" not in plain and plain["content_revision"] == 3
    assert "review_binding" not in plain and "approval_binding" not in plain
    again = proposal(with_proposed(inputs, removed))
    assert again["proposed_draft"]["content_revision"] == 4
    assert (
        again["proposed_draft"]["media_attachment"] == first["proposed_draft"]["media_attachment"]
    )
    assert again["packet"]["packet_sha256"] != first["packet"]["packet_sha256"]
    with pytest.raises(MediaReviewError):
        proposal(current, expected=first["predecessor"])


@pytest.mark.parametrize("value", [None, False, {}, [], "invalid"])
def test_even_malformed_present_content_can_only_be_removed_as_a_new_revision(inputs, value):
    draft = inputs["draft"]
    draft["media_attachment"] = value
    result = removal(draft)
    assert result["changed"] and result["proposed_draft"]["content_revision"] == 2
    assert "media_attachment" not in result["proposed_draft"]
    assert result["proposed_draft"]["revision_history"][-1]["media_attachment"] == value


def test_text_edit_keeps_exact_media_in_current_and_historical_revision(inputs):
    current = with_proposed(inputs, proposal(inputs))["draft"]
    previous = deepcopy(current)
    current["media_review_binding"] = {"review_sha256": "a" * 64}
    invalidate_text(current, "Changed synthetic copy.", at=AT)
    assert current["media_attachment"] == previous["media_attachment"]
    assert current["revision_history"][-1]["media_attachment"] == previous["media_attachment"]
    assert "media_review_binding" not in current


def test_not_sent_evidence_and_unrelated_unknown_outcomes_are_preserved(inputs):
    draft = inputs["draft"]
    draft.update(publish_outcome="not_sent", last_publish_attempt_at="2026-09-30T12:00:00Z")
    state = {
        "drafts": [draft],
        "publish_ledger": {draft["event_id"]: {"phase": "not_sent"}, "other": {"phase": "unknown"}},
    }
    before = deepcopy(state)
    result = proposal(inputs, state=state)
    assert state == before
    assert result["proposed_draft"]["publish_outcome"] == "not_sent"
    assert result["proposed_draft"]["last_publish_attempt_at"] == draft["last_publish_attempt_at"]


def test_replacing_float_schema_with_qualified_integer_is_a_real_revision(inputs):
    current = with_proposed(inputs, proposal(inputs))
    current["draft"]["media_attachment"]["schema_version"] = 1.0
    result = proposal(current)
    assert result["changed"] and result["proposed_draft"]["content_revision"] == 3
    assert type(result["proposed_draft"]["media_attachment"]["schema_version"]) is int
    assert type(result["proposed_draft"]["revision_history"][-1]["media_attachment"]["schema_version"]) is float
