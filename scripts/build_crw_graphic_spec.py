#!/usr/bin/env python3
"""Build a CRW graphic specification from explicit retained local inputs, offline."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.media.crw_graphic_adapter import crw_graphic_spec
from src.media.review_package import MAX_JSON_BYTES, _json
from src.media.temperature_graphic_adapter import _StoredBundle


def _load(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("Selected input exceeds its byte bound")
    return _json(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source-packet", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--expected-packet-sha256", required=True)
    parser.add_argument("--synthetic", choices=("true", "false"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        spec = crw_graphic_spec(
            _StoredBundle(_load(args.bundle)),
            _load(args.source_packet),
            expected_bundle_sha256=args.expected_bundle_sha256,
            expected_packet_sha256=args.expected_packet_sha256,
            synthetic=args.synthetic == "true",
        )
        # Explicit output, exclusive creation: never replace an earlier review.
        with args.output.open("x", encoding="utf-8") as stream:
            args.output.chmod(0o600)
            stream.write(json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    except (ValueError, OSError) as exc:
        print("Graphic specification refused: " + str(exc), file=sys.stderr)
        return 2
    print("Created local graphic specification; no approval or publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
