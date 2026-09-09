#!/usr/bin/env python3
"""Inspect a local world-cache export and optionally write a migrated LOCAL copy.

Never reads/writes production. Original input is not overwritten. All unattributed
baselines are quarantined; the normal warm budget performs later recomputation.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data.place_migration import migrate_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.resolve() == args.input.resolve():
        parser.error("output must differ from input")
    try:
        original = json.loads(args.input.read_text())
        if not isinstance(original, dict):
            parser.error("input must be a JSON cache object")
        result = migrate_cache(original)
    except (OSError, ValueError) as exc:
        parser.error(f"cannot read cache: {exc}")
    print(
        json.dumps(
            {
                key: result["_meta"][key]
                for key in ("identity_version", "cached_count", "quarantined_count")
            }
        )
    )
    if args.output:
        with args.output.open("x") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


if __name__ == "__main__":
    main()
