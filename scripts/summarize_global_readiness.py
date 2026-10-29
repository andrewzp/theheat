#!/usr/bin/env python3
"""Summarize detached component exports into a bounded global-readiness packet.

Reads exactly one named regular envelope file (bounded, nonblocking, no symlink
in any path component). Writes either JSON to stdout or, with --output-dir, a new
private directory holding readiness.json and review.txt, created through held
directory descriptors and never overwriting. Both bodies are bounded before
anything is written. No source, database, model or network access.
Exit 0 with a packet; 2 when the envelope or a file boundary is refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src.evaluation import file_boundary  # noqa: E402
from src.evaluation import global_readiness as readiness  # noqa: E402


def read_envelope(path: str):
    """One regular file reached through held no-follow directory descriptors."""
    return readiness.strict_loads(file_boundary.read_regular(path, readiness.MAX_INPUT_BYTES))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="schema-1 readiness envelope JSON file")
    parser.add_argument("--output-dir", help="new private directory for readiness.json and review.txt")
    args = parser.parse_args(argv)
    try:
        result = readiness.assess(read_envelope(args.input))
        # Both bodies are encoded and bounded before any directory or file exists.
        body, text = readiness.encode_outputs(result)
        if args.output_dir:
            file_boundary.write_private_directory(args.output_dir, {"readiness.json": body, "review.txt": text})
        else:
            sys.stdout.write(body.decode("ascii"))
    except (readiness.ReadinessError, file_boundary.FileBoundaryError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except OSError as exc:
        print(json.dumps({"error": type(exc).__name__}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
