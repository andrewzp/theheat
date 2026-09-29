#!/usr/bin/env python3
"""Assemble explicit local inputs into a private review package; no model or publishing call."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.media.review_packet import MediaReviewError
from src.media.review_package import prepare_media_review


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag, help_text in (
        ("repository", "Absolute repository root, without symlink ancestors"),
        ("output-root", "That repository's ignored .gstack/media-review directory"),
        ("draft", "Explicit private draft JSON snapshot"),
        ("expected-identity", "Independent retained requested draft identity JSON"),
        ("spec", "Qualified graphic specification JSON"),
        ("policy", "Trusted current editorial policy JSON, supplied independently"),
        ("manifest", "Existing preview's manifest.json; all five assets required"),
        ("pdftoppm", "Absolute real rasterizer path for byte fingerprinting only; never executed"),
    ):
        parser.add_argument("--" + flag, required=True, type=Path, help=help_text)
    args = parser.parse_args(argv)
    try:
        result = prepare_media_review(
            repository=args.repository,
            output_root=args.output_root,
            draft_path=args.draft,
            expected_identity_path=args.expected_identity,
            spec_path=args.spec,
            policy_path=args.policy,
            manifest_path=args.manifest,
            pdftoppm=args.pdftoppm,
        )
    except MediaReviewError as exc:
        print("Review package refused: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
