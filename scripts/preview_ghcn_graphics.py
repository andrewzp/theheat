#!/usr/bin/env python3
"""Render synthetic GHCN source-to-graphic specimens locally; never actual weather."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.editorial.revisions import fingerprint
from src.media.evidence_graphic_render import render_preview
from src.media.temperature_graphic_adapter import story_bundle_snapshot, temperature_graphic_spec
from tests.ghcn_graphic_helpers import graphic_bundles, source_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=".gstack/p31-adapter-previews")
    parser.add_argument("--pdftoppm", required=True, help="Explicit existing local rasterizer; optional prototype backend")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = source_archive()
    digest = hashlib.sha256(source).hexdigest()
    source_path = output / f"synthetic-source-{digest}.dly"
    if source_path.exists():
        if source_path.is_symlink() or source_path.read_bytes() != source:
            raise ValueError("Existing source fixture changed")
    else:
        source_path.write_bytes(source)
        source_path.chmod(0o600)
    stories = graphic_bundles()
    for template, selected in (("temperature_comparator", stories[-1:]), ("temperature_trajectory", stories)):
        spec = temperature_graphic_spec(template, selected,
            expected_bundle_sha256=[fingerprint(story_bundle_snapshot(bundle)) for bundle in selected], synthetic=True)
        assert all(point["source"]["revision_sha256"] == digest for point in spec["evidence"]["points"])
        manifest = render_preview(**spec, output_dir=output, pdftoppm=args.pdftoppm)
        print(json.dumps({"template": template, "preview": str(manifest.with_name("preview.png")),
                          "manifest": str(manifest), "source_fixture": str(source_path)}))


if __name__ == "__main__":
    main()
