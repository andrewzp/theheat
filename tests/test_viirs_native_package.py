"""Actual invented VIIRS native PNG/review package; required native-media CI lane."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import pytest

from src.dashboard_preview.preview import qualified_spec
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media.evidence_graphic_render import render_preview
from src.media.review_packet import build_media_review_packet, media_review_packet_is_current
from tests.dashboard_graphic_helpers import saved_viirs_preview
from tests.test_joint_media_review import make, status

ROOT = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"
CONFIDENCE_ROW = "A high · B nominal · C low · D high"


def _draft(bundle):
    return {"id": "invented-viirs-media", "event_id": bundle["event_id"], "type": "fire",
            "text": "Invented VIIRS thermal detections for a native package test.",
            "content_revision": 1, "decision_revision": 1, "status": "pending",
            "review_context": {"two_bot": {"bundle": bundle}}}


def test_actual_native_viirs_png_package_binds_the_new_template_and_refuses_altered_content(tmp_path):
    pdftoppm = shutil.which("pdftoppm")
    assert pdftoppm, "The native package test requires the locked profile's pdftoppm; a skip is not a pass"
    state, _ = saved_viirs_preview()
    bundle = state["drafts"][0]["review_context"]["two_bot"]["bundle"]
    spec, _, _ = qualified_spec(deepcopy(bundle), synthetic=True, include_viirs=True)
    manifest_path = render_preview(**spec, output_dir=tmp_path / "media", pdftoppm=pdftoppm)
    manifest = json.loads(manifest_path.read_text())
    folder = manifest_path.parent
    png = (folder / "preview.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    binding = manifest["binding"]
    assert (binding["template"], binding["template_version"]) == ("viirs_thermal_detection_map", "p31-viirs-locator-1")
    media = ROOT / "src/media"
    for key, name in (("adapter_sha256", "viirs_map_graphic_adapter.py"),
                      ("implementation_sha256", "evidence_graphic_render.py"),
                      ("contract_sha256", "evidence_graphic.py")):
        assert binding["renderer"][key] == hashlib.sha256((media / name).read_bytes()).hexdigest()
    assert set(manifest["files"]) == {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}
    assert manifest["publication_approved"] is False and manifest["synthetic"] is True
    svg_texts = ["".join(n.itertext()) for n in ET.parse(folder / "preview.svg").getroot().iter(NS + "text")]
    assert CONFIDENCE_ROW in svg_texts and "NASA FIRMS · NOAA-20 VIIRS" in svg_texts
    # Identical inputs reuse the immutable package; a changed cached asset is refused, never overwritten.
    assert render_preview(**spec, output_dir=tmp_path / "media", pdftoppm=pdftoppm) == manifest_path

    draft = _draft(bundle)
    inputs = dict(draft=draft, expected_draft_identity=draft_identity(draft),
                  editorial_policy=current_editorial_policy(), graphic_spec=spec,
                  renderer_manifest=manifest, png_bytes=png)
    packet = build_media_review_packet(**inputs)
    assert packet["graphic_binding"]["template"] == "viirs_thermal_detection_map"
    assert packet["graphic_binding"]["template_version"] == "p31-viirs-locator-1"
    assert (packet["media"]["width"], packet["media"]["height"], packet["media"]["png_sha256"]) == (
        1200, 1500, hashlib.sha256(png).hexdigest())
    assert packet["publication_approved"] is False and packet["claim_agreement_status"] == "unreviewed"
    current = {k: v for k, v in inputs.items() if k != "draft"}
    assert media_review_packet_is_current(packet, draft, **current)
    record = make(inputs)
    assert status(record, inputs)["accepted"]

    for change in ("png", "text", "receipt", "template", "bundle"):
        altered = deepcopy(inputs)
        if change == "png":
            altered["png_bytes"] = png + b"changed"
        elif change == "text":
            invalidate_text(altered["draft"], "A different invented claim.")
            altered["expected_draft_identity"] = draft_identity(altered["draft"])
        elif change == "receipt":
            e = altered["graphic_spec"]["evidence"]
            e["input_binding"]["selected_receipt_sha256"][1] = "b" * 64
            altered["graphic_spec"]["expected_evidence_sha256"] = fingerprint(e)
        elif change == "template":
            altered["renderer_manifest"]["binding"]["template_version"] = "p31-modis-locator-2-social"
        else:
            altered["draft"]["review_context"]["two_bot"]["bundle"]["where"] = "Different City"
        assert not media_review_packet_is_current(packet, altered["draft"],
                                                  **{k: v for k, v in altered.items() if k != "draft"})
        assert not status(record, altered)["accepted"]

    (folder / "preview.png").write_bytes(png + b"tampered")
    with pytest.raises(ValueError, match="Cached preview content changed"):
        render_preview(**spec, output_dir=tmp_path / "media", pdftoppm=pdftoppm)
