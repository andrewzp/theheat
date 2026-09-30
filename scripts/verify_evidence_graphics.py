#!/usr/bin/env python3
"""Actual optional-backend verification, run with bundled ReportLab/Pillow runtime."""
from pathlib import Path
from copy import deepcopy
import base64
import hashlib
import argparse
import json
import re
import sys
import tempfile
from xml.dom import minidom
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import point_label, validate_graphic
from src.media.evidence_graphic_render import render_preview


def node_text(node):
    child = node.firstChild
    assert child is not None and isinstance(child.nodeValue, str), "Missing SVG text"
    return child.nodeValue


def verify_material_text(svg, template, evidence):
    """Check actual emitted labels, including wrapped qualifications, at phone scale."""
    elements = svg.getElementsByTagName("text")
    assert elements
    for element in elements:
        match = re.search(r"font-size:\s*([\d.]+)px", element.getAttribute("style"))
        assert match and float(match[1]) >= 40, "Material text falls below 13px at 390px width"
    visible = " ".join(" ".join(node_text(element).split()) for element in elements)
    required = [evidence["location"], evidence["scope"]]
    required += [point["source"]["product"] for point in evidence["points"]]
    if template == "temperature_comparator":
        prior = evidence["baseline"]["point"]
        required += [evidence["baseline"]["scope"], evidence["baseline"]["start"],
                     evidence["baseline"]["cutoff"], prior["source"]["product"],
                     point_label(prior, evidence), point_label(evidence["points"][0], evidence)]
        assert "no official record" in visible.lower()
    else:
        required += [point_label(evidence["points"][0], evidence), point_label(evidence["points"][-1], evidence)]
    if evidence.get("time_basis") == "source_calendar_date":
        required.append("Dates are source-calendar labels; reporting interval and timezone unknown.")
    if evidence["synthetic"]:
        required += ["SYNTHETIC DATA", "Illustrative values; not actual weather."]
    for value in required:
        assert " ".join(value.split()) in visible, f"Material qualifier missing: {value}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdftoppm", required=True)
    parser.add_argument("--include-ghcn-adapter", action="store_true", help="Also verify synthetic qualified source-to-chart specimens; requires existing bot dependencies")
    args = parser.parse_args()
    examples = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/evidence_graphics_synthetic.json").read_text())
    specimens = list(examples.items())
    if args.include_ghcn_adapter:
        from src.media.temperature_graphic_adapter import story_bundle_snapshot, temperature_graphic_spec
        from tests.ghcn_graphic_helpers import graphic_bundles
        stories = graphic_bundles()
        for template, selected in (("temperature_comparator", stories[-1:]), ("temperature_trajectory", stories)):
            spec = temperature_graphic_spec(template, selected,
                expected_bundle_sha256=[fingerprint(story_bundle_snapshot(bundle)) for bundle in selected], synthetic=True)
            specimens.append((template, spec["evidence"]))
    for template, evidence in specimens:
        with tempfile.TemporaryDirectory(prefix="theheat-graphics-check-") as root:
            left = render_preview(template, evidence, expected_evidence_sha256=fingerprint(evidence), output_dir=Path(root) / "left", pdftoppm=args.pdftoppm)
            right = render_preview(template, evidence, expected_evidence_sha256=fingerprint(evidence), output_dir=Path(root) / "right", pdftoppm=args.pdftoppm)
            manifest = json.loads(left.read_text())
            assert manifest == json.loads(right.read_text()), "Independent render must be deterministic"
            with Image.open(left.with_name("preview.png")) as preview:
                assert preview.size == (1200, 1500) and preview.format == "PNG"
            svg = minidom.parseString(left.with_name("preview.svg").read_text())
            verify_material_text(svg, template, evidence)
            style = node_text(svg.getElementsByTagName("style")[0])
            encoded_font = style.split("data:font/ttf;base64,", 1)[1].split("'", 1)[0]
            assert hashlib.sha256(base64.b64decode(encoded_font, validate=True)).hexdigest() == manifest["binding"]["renderer"]["font_sha256"]
            assert node_text(svg.getElementsByTagName("desc")[0]) == manifest["alt_text"]
            with patch("src.media.evidence_graphic_render.subprocess.run", side_effect=AssertionError("Cache hit rasterized again")):
                assert render_preview(template, evidence, expected_evidence_sha256=fingerprint(evidence), output_dir=Path(root) / "left", pdftoppm=args.pdftoppm) == left
            changed_manifest = dict(manifest, publication_approved=True)
            left.write_text(json.dumps(changed_manifest))
            try:
                render_preview(template, evidence, expected_evidence_sha256=fingerprint(evidence), output_dir=Path(root) / "left", pdftoppm=args.pdftoppm)
            except ValueError as exc:
                assert "metadata changed" in str(exc)
            else:
                raise AssertionError("Changed cached approval metadata was accepted")
            left.write_text(json.dumps(manifest))
            left.with_name("alt.txt").write_text("Changed after review")
            try:
                render_preview(template, evidence, expected_evidence_sha256=fingerprint(evidence), output_dir=Path(root) / "left", pdftoppm=args.pdftoppm)
            except ValueError as exc:
                assert "content changed" in str(exc)
            else:
                raise AssertionError("Changed cached asset was accepted")
            assert manifest["publication_approved"] is False
            if "input_binding" in evidence:
                assert manifest["binding"]["renderer"]["adapter_sha256"] == hashlib.sha256(
                    (Path(__file__).resolve().parents[1] / "src/media/temperature_graphic_adapter.py").read_bytes()).hexdigest()
                altered = deepcopy(evidence)
                altered["points"][0]["value"] += 1
                with patch("src.media.evidence_graphic_render.subprocess.run", side_effect=AssertionError("Changed projection reached rasterizer")):
                    try:
                        render_preview(template, altered, expected_evidence_sha256=fingerprint(altered), output_dir=Path(root) / "changed", pdftoppm=args.pdftoppm)
                    except ValueError as exc:
                        assert "projection differs" in str(exc)
                    else:
                        raise AssertionError("Adapter projection change survived a refreshed graphic hash")
            print(f"PASS {template}: independent deterministic render, dimensions, reuse, asset/metadata tamper refusal, approval absent")
    dense = deepcopy(examples["temperature_trajectory"])
    for point, valid in zip(dense["points"], ("2026-09-09T00:00:00Z", "2026-09-09T00:01:00Z", "2026-09-10T00:00:00Z", "2026-09-11T00:00:00Z", "2026-09-12T00:00:00Z", "2026-09-13T00:00:00Z")):
        point.update(valid_time=valid, evidence_type="forecast")
    with tempfile.TemporaryDirectory(prefix="theheat-graphics-dense-") as root:
        try:
            render_preview("temperature_trajectory", dense, expected_evidence_sha256=fingerprint(dense), output_dir=root, pdftoppm=args.pdftoppm)
        except ValueError as exc:
            assert "labels would overlap" in str(exc)
        else:
            raise AssertionError("Unreadable dense trajectory was rendered")
    print("PASS unreadable trajectory labels refused before rasterization")
    crowded = deepcopy(examples["temperature_comparator"])
    crowded["scope"] = "Limited station observations with explicitly qualified and unverified reporting times " + "scope " * 3
    crowded["baseline"]["scope"] = "Complete sample comparison with limited archive coverage and no official record certification"
    crowded["points"][0]["source"]["product"] = "Synthetic experimental forecast system with limited temporal coverage"
    crowded["baseline"]["point"]["source"]["product"] = "Synthetic station archive with independent reporting interval metadata"
    # Valid evidence can still exceed the readable canvas; it must not be clipped.
    validate_graphic("temperature_comparator", crowded, expected_evidence_sha256=fingerprint(crowded))
    with tempfile.TemporaryDirectory(prefix="theheat-graphics-overflow-") as root:
        with patch("src.media.evidence_graphic_render.subprocess.run", side_effect=AssertionError("Overflow reached rasterizer")):
            try:
                render_preview("temperature_comparator", crowded, expected_evidence_sha256=fingerprint(crowded), output_dir=root, pdftoppm=args.pdftoppm)
            except ValueError as exc:
                assert "qualifications exceed" in str(exc)
            else:
                raise AssertionError("Oversized qualifications were silently fitted")
    print("PASS valid crowded qualifications refused before rasterization")


if __name__ == "__main__":
    main()
