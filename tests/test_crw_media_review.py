"""CRW media through existing private review/revision boundaries, not approval."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media.attachment import build_media_attachment_proposal
from src.media.crw_graphic_adapter import crw_graphic_spec
from src.media.review_packet import (
    build_media_review_packet,
    media_review_packet_is_current,
    MediaReviewError,
)
from src.media.review_package import prepare_media_review
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from tests.crw_graphic_helpers import graphic_inputs
from tests.test_joint_media_review import make, status
from tests.test_media_review_packet import manifest_for, structural_png
from tests.test_media_review_package import local as local


@pytest.fixture(scope="module")
def seed():
    bundle, source = graphic_inputs()
    snapshot = story_bundle_snapshot(bundle)
    spec = crw_graphic_spec(
        bundle,
        source,
        expected_bundle_sha256=fingerprint(snapshot),
        expected_packet_sha256=fingerprint(source),
        synthetic=True,
    )
    draft = {
        "id": "synthetic-crw",
        "event_id": bundle.event_id,
        "type": bundle.signal_kind,
        "text": "An invented warm anomaly for a private graphic fixture.",
        "content_revision": 1,
        "decision_revision": 1,
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


def test_complete_crw_package_reuses_exact_assets_and_selected_adapter(local):
    result = prepare_media_review(**local)
    assert (
        result["publication_approved"] is False and result["claim_agreement_status"] == "unreviewed"
    )
    assert prepare_media_review(**local) == {**result, "reused": True}
    packet = json.loads((Path(result["output"]) / "packet.json").read_text())
    assert packet["graphic_binding"]["template_version"] == "p31-crw-anomaly-1"


def test_ghcn_adapter_hash_cannot_certify_crw_render(local):
    import hashlib
    from src.media import temperature_graphic_adapter

    manifest = json.loads(local["manifest_path"].read_text())
    binding = manifest["binding"]
    binding["renderer"]["adapter_sha256"] = hashlib.sha256(
        Path(temperature_graphic_adapter.__file__).read_bytes()
    ).hexdigest()
    manifest["cache_key"] = fingerprint(binding)
    local["manifest_path"].write_text(json.dumps(manifest))
    with pytest.raises(MediaReviewError, match="renderer differs"):
        prepare_media_review(**local)


@pytest.mark.parametrize(
    "changed", ["text", "policy", "source_packet", "template_version", "asset", "bundle"]
)
def test_crw_joint_review_becomes_stale_when_any_bound_input_changes(seed, changed):
    inputs = deepcopy(seed)
    record = make(inputs)
    assert status(record, inputs)["accepted"]
    packet = build_media_review_packet(**inputs)
    if changed == "text":
        invalidate_text(inputs["draft"], "Another invented alternative.")
        inputs["expected_draft_identity"] = draft_identity(inputs["draft"])
    elif changed == "policy":
        inputs["editorial_policy"]["execution_sha256"] = "b" * 64
    elif changed == "source_packet":
        inputs["graphic_spec"]["evidence"]["input_binding"]["source_packet"]["csv_utf8"] += (
            "changed"
        )
    elif changed == "template_version":
        inputs["renderer_manifest"]["binding"]["template_version"] = "p31-preview-3-mobile"
    elif changed == "asset":
        inputs["png_bytes"] += b"changed"
    elif changed == "bundle":
        inputs["draft"]["review_context"]["two_bot"]["bundle"]["where"] = "Another region"
    assert not media_review_packet_is_current(packet, **inputs)
    assert not status(record, inputs)["accepted"]


def test_crw_attachment_proposal_keeps_predecessor_and_invalidates_approval(seed, monkeypatch):
    from tests.test_media_attachment import (
        test_proposal_is_stable_detached_and_invalidates_exact_previous_review,
    )
    # Exercise the full existing revision/approval contract with the new source.
    test_proposal_is_stable_detached_and_invalidates_exact_previous_review(deepcopy(seed), monkeypatch)
