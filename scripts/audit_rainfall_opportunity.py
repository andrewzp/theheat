#!/usr/bin/env python3
"""Audit exported rainfall-opportunity traces offline; prints one JSON document.

Reads only the named files (bounded, no symlinks). No source, database, model,
platform or network access. Exit 0 with an audit, 2 for unusable input files.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src.evaluation import rainfall_opportunity as opportunity  # noqa: E402

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


def _pairs(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_json_key")
    return dict(pairs)


def _nonfinite(value):
    raise ValueError("nonfinite_json_number")


def read_json(path: str):
    """Strict bounded read of one regular, non-symlinked file."""
    target = Path(path)
    if target.is_symlink() or any(parent.is_symlink() for parent in target.absolute().parents):
        raise ValueError("input_symlink")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input_too_large")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="append", default=[], help="one exported trace JSON file")
    parser.add_argument("--population", action="append", default=[], help="one canonical population JSON file")
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    args = parser.parse_args(argv)
    try:
        traces = [read_json(path) for path in args.trace]
        populations = [read_json(path) for path in args.population]
        report = opportunity.evaluate(traces, populations, start=args.start, end=args.end)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).isidentifier() else type(exc).__name__
        print(json.dumps({"error": code}))
        return 2
    rendered = json.dumps(report, sort_keys=True, ensure_ascii=True, indent=1)
    if len(rendered.encode()) > MAX_OUTPUT_BYTES:
        print(json.dumps({"error": "output_too_large"}))
        return 2
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
