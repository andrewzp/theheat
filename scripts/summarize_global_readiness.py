#!/usr/bin/env python3
"""Summarize detached component exports into a bounded global-readiness packet.

Reads exactly one named envelope file (bounded, no symlinks). Writes either JSON
to stdout or, with --output-dir, a new private directory holding readiness.json
and review.txt (never overwriting). No source, database, model or network access.
Exit 0 with a packet; 2 when the envelope or a file boundary is refused.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src.evaluation import global_readiness as readiness  # noqa: E402


def _no_symlink_path(path: Path) -> None:
    target = path.absolute()
    for item in (target, *target.parents):
        if item.is_symlink():
            raise readiness.ReadinessError("symlinked_path")


def read_envelope(path: str):
    target = Path(path)
    _no_symlink_path(target)
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(readiness.MAX_INPUT_BYTES + 1)
    return readiness.strict_loads(raw)


def write_outputs(directory: str, result: dict) -> None:
    target = Path(directory)
    _no_symlink_path(target.parent)
    target.mkdir(mode=0o700)  # FileExistsError: never reuse or overwrite an output
    for name, body in (("readiness.json", json.dumps(result, sort_keys=True, ensure_ascii=True, indent=1) + "\n"),
                       ("review.txt", readiness.render_text(result))):
        fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(body)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="schema-1 readiness envelope JSON file")
    parser.add_argument("--output-dir", help="new private directory for readiness.json and review.txt")
    args = parser.parse_args(argv)
    try:
        result = readiness.assess(read_envelope(args.input))
        if args.output_dir:
            write_outputs(args.output_dir, result)
        else:
            print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=1))
    except readiness.ReadinessError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except OSError as exc:
        print(json.dumps({"error": type(exc).__name__}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
