"""Synthetic qualified evidence and structural PNG headers, not rendered chart proof."""

from copy import deepcopy
import binascii
import hashlib
import json
import struct

import pytest

from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media.evidence_graphic import HEIGHT, WIDTH, template_version, build_alt_text
from src.media.review_packet import (
    MAX_PNG_BYTES,
    MediaReviewError,
    build_media_review_packet,
    media_review_packet_is_current,
)
from src.media.temperature_graphic_adapter import story_bundle_snapshot, temperature_graphic_spec
from tests.ghcn_graphic_helpers import graphic_bundles


def digest(data):
    return hashlib.sha256(data).hexdigest()


def structural_png(width=WIDTH, height=HEIGHT):
    chunk = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + chunk
        + struct.pack(">I", binascii.crc32(chunk))
    )


def manifest_for(spec, png):
    renderer = {
        name: digest(name.encode())
        for name in (
            "rasterizer_sha256",
            "implementation_sha256",
            "contract_sha256",
            "font_sha256",
            "adapter_sha256",
        )
    }
    renderer.update(library="ReportLab", version="synthetic-fixture", width=WIDTH, height=HEIGHT)
    binding = {
        "template": spec["template"],
        "template_version": template_version(spec["template"]),
        "source_evidence_sha256": spec["expected_evidence_sha256"],
        "renderer": renderer,
    }
    alt = build_alt_text(spec["template"], spec["evidence"])
    return {
        "schema_version": 1,
        "cache_key": fingerprint(binding),
        "binding": binding,
        "files": {
            "input.json": digest(
                (json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            ),
            "alt.txt": digest((alt + "\n").encode()),
            "preview.png": digest(png),
            "preview.svg": digest(b"synthetic svg"),
            "preview.pdf": digest(b"synthetic pdf"),
        },
        "synthetic": True,
        "alt_text": alt,
        "publication_approved": False,
        "scope": spec["evidence"]["scope"],
    }


@pytest.fixture(scope="module")
def seed():
    bundle = graphic_bundles()[-1]
    snapshot = story_bundle_snapshot(bundle)
    spec = temperature_graphic_spec(
        "temperature_comparator",
        [bundle],
        expected_bundle_sha256=[fingerprint(snapshot)],
        synthetic=True,
    )
    draft = {
        "id": "synthetic-draft",
        "event_id": snapshot["event_id"],
        "type": bundle.signal_kind,
        "text": "A synthetic station reading for a local graphics fixture.",
        "content_revision": 1,
        "status": "pending",
        "review_context": {"two_bot": {"bundle": snapshot}},
    }
    png = structural_png()
    return {
        "draft": draft,
        "expected_draft_identity": draft_identity(draft),
        "editorial_policy": current_editorial_policy(),
        "graphic_spec": spec,
        "renderer_manifest": manifest_for(spec, png),
        "png_bytes": png,
    }


@pytest.fixture
def inputs(seed):
    return deepcopy(seed)


def test_current_packet_is_stable_detached_and_never_semantic_or_posting_approval(inputs):
    before = deepcopy(inputs)
    packet = build_media_review_packet(**inputs)
    assert packet == build_media_review_packet(**inputs)
    assert inputs == before and media_review_packet_is_current(packet, **inputs)
    assert (
        packet["claim_agreement_status"] == "unreviewed" and packet["publication_approved"] is False
    )
    assert packet["synthetic"] is True and "SYNTHETIC" in packet["media"]["alt_text"]
    packet["media"]["alt_text"] = "Changed"
    assert inputs == before


@pytest.mark.parametrize(
    "change", ["text", "round_trip", "draft_id", "event_id", "evidence", "policy"]
)
def test_original_packet_does_not_follow_a_new_current_revision(inputs, change):
    packet = build_media_review_packet(**inputs)
    draft = inputs["draft"]
    if change == "text":
        invalidate_text(draft, "Changed synthetic draft.")
    elif change == "round_trip":
        original = draft["text"]
        invalidate_text(draft, "Changed synthetic draft.")
        invalidate_text(draft, original)
    elif change == "draft_id":
        draft["id"] += "-other"
    elif change == "event_id":
        draft["event_id"] += "-other"
    elif change == "evidence":
        draft["review_context"]["source_note"] = "A new evidence revision"
    else:
        inputs["editorial_policy"]["execution_sha256"] = "a" * 64
    inputs["expected_draft_identity"] = draft_identity(draft)
    assert not media_review_packet_is_current(packet, **inputs)


def test_obsolete_request_identity_cannot_follow_an_edit(inputs):
    invalidate_text(inputs["draft"], "Changed synthetic draft.")
    with pytest.raises(MediaReviewError, match="independent requested identity"):
        build_media_review_packet(**inputs)


@pytest.mark.parametrize("change", ["png", "renderer", "svg", "pdf"])
def test_coherent_new_rendering_requires_new_packet(inputs, change):
    first = build_media_review_packet(**inputs)
    manifest = inputs["renderer_manifest"]
    if change == "png":
        inputs["png_bytes"] += b"different encoded content"
        manifest["files"]["preview.png"] = digest(inputs["png_bytes"])
    elif change == "renderer":
        manifest["binding"]["renderer"]["implementation_sha256"] = "a" * 64
        manifest["cache_key"] = fingerprint(manifest["binding"])
    else:
        manifest["files"]["preview." + change] = "b" * 64
    second = build_media_review_packet(**inputs)
    assert first["packet_sha256"] != second["packet_sha256"]
    assert not media_review_packet_is_current(first, **inputs)
    assert second["claim_agreement_status"] == "unreviewed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("publication_approved", True),
        ("claim_agreement_status", "approved"),
        ("synthetic", False),
        ("schema_version", True),
        ("unknown", "injected"),
    ],
)
def test_rehashing_an_edited_packet_cannot_make_it_current(inputs, field, value):
    packet = build_media_review_packet(**inputs)
    packet[field] = value
    packet["packet_sha256"] = fingerprint({k: v for k, v in packet.items() if k != "packet_sha256"})
    assert not media_review_packet_is_current(packet, **inputs)


@pytest.mark.parametrize(
    "path,value",
    [
        ("draft.content_revision", None),
        ("draft.content_revision", True),
        ("expected_draft_identity.content_revision", True),
        ("draft.text", " "),
        ("draft.text", "a" * 281),
        ("draft.id", ""),
        ("draft.status", "posted"),
        ("draft.revision_conflicts", [{"text": "conflict"}]),
        ("draft.review_context.two_bot.bundle", None),
        ("editorial_policy", {}),
        ("draft.extra", float("nan")),
        ("draft.extra", "x" * 1_000_001),
        ("draft.extra", "\ud800"),
        ("graphic_spec.extra", True),
        ("graphic_spec.template", "temperature_trajectory"),
        ("graphic_spec.evidence.input_binding", None),
        ("graphic_spec.expected_evidence_sha256", "a" * 64),
        ("graphic_spec.evidence.input_binding.adapter_version", "old"),
        ("renderer_manifest.schema_version", True),
        ("renderer_manifest.extra", "unknown"),
        ("renderer_manifest.alt_text", "edited"),
        ("renderer_manifest.publication_approved", True),
        ("renderer_manifest.synthetic", 1),
        ("renderer_manifest.scope", "Global"),
        ("renderer_manifest.cache_key", "bad"),
        ("renderer_manifest.binding.template", "temperature_trajectory"),
        ("renderer_manifest.binding.template_version", "old"),
        ("renderer_manifest.binding.source_evidence_sha256", "a" * 64),
        ("renderer_manifest.files", {}),
        ("renderer_manifest.files.preview.svg", "bad"),
        ("renderer_manifest.files.input.json", "a" * 64),
        ("renderer_manifest.files.alt.txt", "a" * 64),
        ("renderer_manifest.files.preview.png", "a" * 64),
    ],
    ids=lambda value: str(value)[:70],
)
def test_invalid_or_contradictory_inputs_fail(inputs, path, value):
    # File names contain dots; split only the object portion for these paths.
    parts = path.split(".")
    if parts[:2] == ["renderer_manifest", "files"] and len(parts) > 2:
        parts = parts[:2] + [".".join(parts[2:])]
    obj = inputs
    for part in parts[:-1]:
        obj = obj[part]
    obj[parts[-1]] = value
    with pytest.raises(MediaReviewError):
        build_media_review_packet(**inputs)


@pytest.mark.parametrize(
    "change",
    ["missing_revision", "recursive", "nonstr_key", "bundle_date", "bundle_qc", "bundle_place"],
)
def test_new_self_hash_does_not_repair_bad_or_different_source_input(inputs, change):
    draft = inputs["draft"]
    if change == "missing_revision":
        del draft["content_revision"]
    elif change == "recursive":
        draft["recursive"] = draft
    elif change == "nonstr_key":
        draft[1] = "invalid key"
    else:
        bundle = draft["review_context"]["two_bot"]["bundle"]
        if change == "bundle_date":
            bundle["when"] = "2026-09-07"
        elif change == "bundle_qc":
            bundle["raw_signal_dump"]["evidence"]["variables"]["TMAX"]["qflag"] = "S"
        else:
            bundle["where"] = "Another place"
        inputs["expected_draft_identity"] = draft_identity(draft)
    with pytest.raises(MediaReviewError):
        build_media_review_packet(**inputs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("adapter_sha256", None),
        ("font_sha256", "bad"),
        ("width", True),
        ("height", 100),
        ("library", "unknown"),
        ("extra", "unexpected"),
    ],
)
def test_resealed_manifest_requires_valid_renderer_contract(inputs, field, value):
    manifest = inputs["renderer_manifest"]
    manifest["binding"]["renderer"][field] = value
    manifest["cache_key"] = fingerprint(manifest["binding"])
    with pytest.raises(MediaReviewError):
        build_media_review_packet(**inputs)


@pytest.mark.parametrize(
    "kind", ["dimensions", "signature", "crc", "truncated", "oversized", "changed"]
)
def test_invalid_png_or_changed_bytes_cannot_hide_behind_a_manifest(inputs, kind):
    png = inputs["png_bytes"]
    if kind == "dimensions":
        png = structural_png(width=10)
    elif kind == "signature":
        png = b"bad" + png[3:]
    elif kind == "crc":
        png = png[:-1] + bytes([png[-1] ^ 255])
    elif kind == "truncated":
        png = png[:20]
    elif kind == "oversized":
        png += b"x" * MAX_PNG_BYTES
    else:
        png += b"changed"
    inputs["png_bytes"] = png
    if kind != "changed":
        inputs["renderer_manifest"]["files"]["preview.png"] = digest(png)
    with pytest.raises(MediaReviewError):
        build_media_review_packet(**inputs)


def test_shared_bundle_does_not_certify_tweet_claims(inputs):
    inputs["draft"]["text"] = "An intentionally unsupported claim in a synthetic fixture."
    inputs["expected_draft_identity"] = draft_identity(inputs["draft"])
    packet = build_media_review_packet(**inputs)
    assert packet["claim_agreement_status"] == "unreviewed" and not packet["publication_approved"]


@pytest.mark.parametrize(
    "path",
    [
        "schema_version",
        "draft_binding.content_revision",
        "media.byte_count",
        "media.width",
        "media.height",
    ],
)
def test_packet_integer_fields_remain_strict_even_under_numeric_hash_equivalence(inputs, path):
    packet = build_media_review_packet(**inputs)
    parts = path.split(".")
    parent = packet
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = float(parent[parts[-1]])
    packet["packet_sha256"] = fingerprint({k: v for k, v in packet.items() if k != "packet_sha256"})
    assert not media_review_packet_is_current(packet, **inputs)
