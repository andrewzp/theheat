"""PM2.5 through existing private media/revision boundaries; no actual approval."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media.review_packet import build_media_review_packet, media_review_packet_is_current
from src.media.review_package import prepare_media_review
from tests.air_quality_graphic_helpers import graphic_bundle
from tests.test_air_quality_graphic_adapter import adapt
from tests.test_joint_media_review import make, status
from tests.test_media_review_packet import manifest_for, structural_png
from tests.test_media_review_package import local as local


@pytest.fixture(scope="module")
def seed():
    bundle = graphic_bundle()
    spec = adapt(bundle)
    png = structural_png()
    draft = {
        "id": "synthetic-pm25",
        "event_id": bundle.event_id,
        "type": bundle.signal_kind,
        "text": "An invented PM2.5 forecast for a private graphic fixture.",
        "content_revision": 1,
        "decision_revision": 1,
        "status": "pending",
        "review_context": {"two_bot": {"bundle": bundle.to_dict()}},
    }
    return {
        "draft": draft,
        "expected_draft_identity": draft_identity(draft),
        "editorial_policy": current_editorial_policy(),
        "graphic_spec": spec,
        "renderer_manifest": manifest_for(spec, png),
        "png_bytes": png,
    }


def test_complete_package_reuses_exact_assets_without_approving(local):
    result = prepare_media_review(**local)
    assert result["publication_approved"] is False
    assert result["claim_agreement_status"] == "unreviewed"
    assert prepare_media_review(**local) == {**result, "reused": True}
    packet = json.loads((Path(result["output"]) / "packet.json").read_text())
    assert packet["graphic_binding"]["template_version"] == "p31-pm25-forecast-1"


@pytest.mark.parametrize("changed", ["text", "policy", "window", "template", "asset", "bundle"])
def test_joint_review_becomes_stale_when_bound_inputs_change(seed, changed):
    inputs = deepcopy(seed)
    record = make(inputs)
    assert status(record, inputs)["accepted"]
    packet = build_media_review_packet(**inputs)
    if changed == "text":
        invalidate_text(inputs["draft"], "A different invented claim.")
        inputs["expected_draft_identity"] = draft_identity(inputs["draft"])
    elif changed == "policy":
        inputs["editorial_policy"]["execution_sha256"] = "b" * 64
    elif changed == "window":
        e = inputs["graphic_spec"]["evidence"]
        e["input_binding"]["selected_window_sha256"] = "b" * 64
        inputs["graphic_spec"]["expected_evidence_sha256"] = fingerprint(e)
    elif changed == "template":
        inputs["renderer_manifest"]["binding"]["template_version"] = "p31-crw-anomaly-1"
    elif changed == "asset":
        inputs["png_bytes"] += b"changed"
    else:
        inputs["draft"]["review_context"]["two_bot"]["bundle"]["where"] = "Different City"
    assert not media_review_packet_is_current(packet, **inputs)
    assert not status(record, inputs)["accepted"]


def test_attachment_invalidates_checks_and_previous_approval(seed, monkeypatch):
    from tests.test_media_attachment import (
        test_proposal_is_stable_detached_and_invalidates_exact_previous_review,
    )

    test_proposal_is_stable_detached_and_invalidates_exact_previous_review(
        deepcopy(seed), monkeypatch
    )
