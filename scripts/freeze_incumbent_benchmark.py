#!/usr/bin/env python3
"""Create/verify a private local benchmark. Never calls a model or a platform API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.evaluation.incumbent import freeze, verify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("freeze")
    for flag in ("repository", "corpus", "snapshot", "cases", "output"):
        create.add_argument(f"--{flag}", type=Path, required=True)
    create.add_argument("--revision", required=True)
    create.add_argument("--evidence", action="append", default=[], metavar="NAME=PATH")
    check = commands.add_parser("verify")
    check.add_argument("package", type=Path)
    check.add_argument("--manifest-sha256", required=True)
    args = vars(parser.parse_args())
    if args.pop("command") == "verify":
        result = verify(**args)
    else:
        evidence = {}
        for item in args.pop("evidence"):
            name, separator, path = item.partition("=")
            if not separator or not path or name in evidence:
                parser.error("Evidence requires unique NAME=PATH entries")
            evidence[name] = Path(path)
        result = freeze(**args, evidence=evidence)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
