#!/usr/bin/env python3
"""Render the explicitly synthetic P31 specimen; no network or publishing code."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.editorial.revisions import fingerprint
from src.media.evidence_graphic_render import render_preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=".gstack/p31-previews")
    parser.add_argument("--pdftoppm", required=True, help="Explicit local PDF rasterizer; not a production dependency")
    args = parser.parse_args()
    examples = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/evidence_graphics_synthetic.json").read_text())
    for template, evidence in examples.items():
        manifest = render_preview(template, evidence, expected_evidence_sha256=fingerprint(evidence),
                                  output_dir=args.output_dir, pdftoppm=args.pdftoppm)
        print(json.dumps({"template": template, "preview": str(manifest.with_name("preview.png")), "manifest": str(manifest)}))


if __name__ == "__main__":
    main()
