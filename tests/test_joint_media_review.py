"""Synthetic supplied decisions and structural PNGs; no human or visual rating."""

from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from src.commands.schema import Principal
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media.joint_review import (
    CONFIRMATIONS, MAX_REVIEW_BYTES, joint_media_review_status, record_joint_media_review,
)
from src.media.review_packet import MediaReviewError, build_media_review_packet
from tests.test_media_review_packet import digest, seed as seed

ACTOR = Principal("synthetic-reviewer", "editor", "offline-fixture-session")
WHEN = "2026-09-30T12:00:00Z"


@pytest.fixture
def inputs(seed):
    return deepcopy(seed)


def payload(decision="accept"):
    return {
        "decision": decision,
        "confirmations": dict.fromkeys(CONFIRMATIONS, True),
        "reason": "Synthetic test decision, not a human evaluation.",
    }


def make(inputs, **overrides):
    args = dict(
        payload=payload(), principal=ACTOR, reviewed_at=WHEN,
        expected_packet_sha256=build_media_review_packet(**inputs)["packet_sha256"],
    )
    return record_joint_media_review(**inputs, **(args | overrides))


def status(record, inputs, **overrides):
    args = dict(expected_review_sha256=record["review_sha256"], current_principal=ACTOR)
    return joint_media_review_status(record, **inputs, **(args | overrides))


def rehash(record):
    record["review_sha256"] = fingerprint({k: v for k, v in record.items() if k != "review_sha256"})


@pytest.mark.parametrize("decision,expected", [
    ("accept", "accepted"), ("reject", "rejected"), ("needs_changes", "needs_changes"),
])
def test_explicit_decision_round_trip_is_detached_and_never_publishing_approval(inputs, decision, expected):
    before = deepcopy(inputs)
    supplied = payload(decision)
    record = make(inputs, payload=supplied)
    assert record == make(inputs, payload=supplied)
    assert inputs == before
    assert status(record, inputs) == dict(
        status=expected, current=True, accepted=decision == "accept", synthetic=True,
        publication_approved=False, production_attachment_authorized=False,
    )
    assert record["synthetic"] is True and record["publication_approved"] is False
    assert record["production_attachment_authorized"] is False
    assert record["packet"]["claim_agreement_status"] == "unreviewed"
    assert record["packet"]["draft_binding"]["policy_sha256"] == fingerprint(inputs["editorial_policy"])
    supplied["confirmations"]["text_matches_data"] = False
    record["packet"]["media"]["alt_text"] = "changed output"
    assert inputs == before and record["confirmations"]["text_matches_data"] is True


@pytest.mark.parametrize("field", sorted(CONFIRMATIONS))
@pytest.mark.parametrize("value", [False, None, "true", 1, 1.0, "missing"])
def test_acceptance_requires_each_exact_confirmation(inputs, field, value):
    supplied = payload()
    if value == "missing":
        del supplied["confirmations"][field]
    else:
        supplied["confirmations"][field] = value
    with pytest.raises(MediaReviewError):
        make(inputs, payload=supplied)


@pytest.mark.parametrize("decision", ["reject", "needs_changes"])
def test_negative_decision_retains_incomplete_or_negative_confirmations(inputs, decision):
    supplied = payload(decision)
    supplied["confirmations"]["text_matches_data"] = None
    supplied["confirmations"]["alt_text_agrees"] = False
    record = make(inputs, payload=supplied)
    assert record["confirmations"] == supplied["confirmations"]
    result = status(record, inputs)
    assert result["current"] and not result["accepted"]


@pytest.mark.parametrize("role", ["editor", "publisher"])
def test_allowed_current_role_with_refreshed_session_keeps_original_provenance(inputs, role):
    record = make(inputs, principal=Principal(ACTOR.subject, role, "original-session"))
    before = deepcopy(record)
    refreshed = Principal(ACTOR.subject, "publisher", "new-authentication-context")
    assert status(record, inputs, current_principal=refreshed)["accepted"]
    assert record == before


@pytest.mark.parametrize("principal", [
    Principal(ACTOR.subject, "viewer", "current"),
    Principal("someone-else", "publisher", "current"),
    {"subject": ACTOR.subject, "role": "publisher", "authentication_context": "untrusted"},
    None,
])
def test_revoked_mismatched_or_untrusted_current_principal_cannot_reuse_review(inputs, principal):
    record = make(inputs)
    result = status(record, inputs, current_principal=principal)
    assert result["status"] == "reviewer_unavailable"
    assert not result["accepted"] and not result["current"] and result["synthetic"] is True


@pytest.mark.parametrize("principal", [Principal("viewer", "viewer", "test"), {}, None])
def test_recording_requires_trusted_allowed_principal(inputs, principal):
    with pytest.raises(MediaReviewError):
        make(inputs, principal=principal)


@pytest.mark.parametrize("change", [
    "text", "alternate", "round_trip", "revision", "draft_id", "event_id",
    "evidence", "bundle", "policy", "png", "renderer", "svg", "pdf", "alt", "template",
])
def test_current_inputs_cannot_reuse_a_previous_decision(inputs, change):
    record = make(inputs)
    old_packet = record["packet"]["packet_sha256"]
    draft = inputs["draft"]
    manifest = inputs["renderer_manifest"]
    if change in {"text", "alternate", "round_trip"}:
        original = draft["text"]
        invalidate_text(draft, "A different supplied synthetic candidate.")
        if change == "round_trip":
            invalidate_text(draft, original)
    elif change == "revision":
        draft["content_revision"] += 1
    elif change in {"draft_id", "event_id"}:
        draft["id" if change == "draft_id" else "event_id"] += "-changed"
    elif change == "evidence":
        draft["review_context"]["source_note"] = "New retained evidence"
    elif change == "bundle":
        draft["review_context"]["two_bot"]["bundle"]["where"] = "Changed location"
    elif change == "policy":
        inputs["editorial_policy"]["execution_sha256"] = "a" * 64
    elif change == "png":
        inputs["png_bytes"] += b"another structural fixture"
        manifest["files"]["preview.png"] = digest(inputs["png_bytes"])
    elif change == "renderer":
        manifest["binding"]["renderer"]["implementation_sha256"] = "b" * 64
        manifest["cache_key"] = fingerprint(manifest["binding"])
    elif change in {"svg", "pdf"}:
        manifest["files"]["preview." + change] = "c" * 64
    elif change == "alt":
        manifest["alt_text"] = "Different qualification"
        manifest["files"]["alt.txt"] = digest((manifest["alt_text"] + "\n").encode())
    else:
        manifest["binding"]["template_version"] = "changed"
        manifest["cache_key"] = fingerprint(manifest["binding"])
    inputs["expected_draft_identity"] = draft_identity(draft)
    result = status(record, inputs)
    assert result["status"] == "obsolete" and not result["accepted"]
    assert result["synthetic"] is True
    # Even a fresh independent draft identity cannot bless the old preview.
    with pytest.raises(MediaReviewError):
        record_joint_media_review(
            **inputs, payload=payload(), principal=ACTOR, reviewed_at=WHEN,
            expected_packet_sha256=old_packet,
        )


def test_new_render_requires_new_supplied_review(inputs):
    old = make(inputs)
    inputs["png_bytes"] += b"new image bytes"
    inputs["renderer_manifest"]["files"]["preview.png"] = digest(inputs["png_bytes"])
    assert status(old, inputs)["status"] == "obsolete"
    new = make(inputs)
    assert new["review_sha256"] != old["review_sha256"] and status(new, inputs)["accepted"]


@pytest.mark.parametrize("field,value", [
    ("decision", "reject"), ("reason", "altered"), ("reviewed_at", "2026-10-01T12:00:00Z"),
    ("publication_approved", True), ("production_attachment_authorized", True),
    ("synthetic", False), ("schema_version", True), ("unknown", "injected"),
])
def test_rehashing_changed_review_does_not_replace_trusted_receipt(inputs, field, value):
    record = make(inputs)
    expected = record["review_sha256"]
    record[field] = value
    rehash(record)
    assert status(record, inputs, expected_review_sha256=expected)["status"] == "invalid"


@pytest.mark.parametrize("path,value", [
    (("packet", "draft_binding", "content_revision"), 1.0),
    (("packet", "draft_binding", "policy_sha256"), "a" * 64),
    (("packet", "draft_binding", "text_sha256"), "b" * 64),
    (("packet", "media", "width"), 1200.0),
    (("packet", "media", "png_sha256"), "c" * 64),
    (("packet", "synthetic"), False),
])
def test_current_independent_packet_rejects_recomputed_tampered_bindings(inputs, path, value):
    record = make(inputs)
    obj = record
    for part in path[:-1]:
        obj = obj[part]
    obj[path[-1]] = value
    record["packet"]["packet_sha256"] = fingerprint({
        k: v for k, v in record["packet"].items() if k != "packet_sha256"
    })
    rehash(record)
    # Even an incorrectly replaced trusted receipt cannot make old bindings
    # match current data. This does not claim protection against trusted actors.
    assert not status(record, inputs)["accepted"]


@pytest.mark.parametrize("field,value", [
    ("reason", ""), ("reason", " \n"), ("reason", "x" * 2001),
    ("reason", "\ud800"), ("reason", float("nan")), ("reason", float("inf")),
    ("reason", "x" * (MAX_REVIEW_BYTES + 1)), ("decision", []),
    ("decision", "approve"), ("confirmations", None), ("unknown", "field"),
    ("principal", {"subject": "injected", "role": "publisher"}),
], ids=lambda value: str(value)[:60])
def test_malformed_payloads_are_bounded_and_refused(inputs, field, value):
    supplied = payload()
    supplied[field] = value
    with pytest.raises(MediaReviewError):
        make(inputs, payload=supplied)


@pytest.mark.parametrize("when", [
    "2026-02-30T12:00:00Z", "2026-09-30", "2026-09-30T12:00:00+02:00",
    "2026-09-30T12:00:00", None, 0, "2026-09-30T12:00:60Z",
])
def test_invalid_calendar_or_non_utc_timestamp_refused(inputs, when):
    with pytest.raises(MediaReviewError):
        make(inputs, reviewed_at=when)


@pytest.mark.parametrize("expected", [None, True, "bad", "a" * 64])
def test_wrong_expected_packet_never_records(inputs, expected):
    with pytest.raises(MediaReviewError):
        make(inputs, expected_packet_sha256=expected)


def test_malformed_readback_never_raises_or_becomes_approval(inputs):
    recursive = {}
    recursive["self"] = recursive
    for record in [None, [], {}, recursive, {"bad": "\ud800"}, {1: "nonstring"}]:
        result = joint_media_review_status(
            record, **inputs, expected_review_sha256="a" * 64, current_principal=ACTOR,
        )
        assert result["status"] == "invalid" and not result["publication_approved"]
        assert not result["production_attachment_authorized"]


def test_no_io_or_mutation_of_draft_approval_fields(inputs, monkeypatch):
    packet = build_media_review_packet(**inputs)
    before = deepcopy(inputs)

    def blocked(*args, **kwargs):
        raise AssertionError("joint review must be pure")

    monkeypatch.setattr("builtins.open", blocked)
    monkeypatch.setattr(Path, "read_bytes", blocked)
    monkeypatch.setattr(Path, "write_bytes", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    record = record_joint_media_review(
        **inputs, payload=payload(), principal=ACTOR, reviewed_at=WHEN,
        expected_packet_sha256=packet["packet_sha256"],
    )
    assert status(record, inputs)["accepted"]
    assert inputs == before
    assert not any(k in inputs["draft"] for k in ("review_binding", "approval_binding", "publish_intent"))
