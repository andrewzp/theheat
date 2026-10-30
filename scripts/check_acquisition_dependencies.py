#!/usr/bin/env python3
"""Report isolated acquisition dependency compatibility; installs nothing.

Reads requirements-acquisition.txt and the current interpreter's installed
distributions. Prints one theheat.acquisition-result/v1 document per tool.
Exit 0 when every requested tool's dependencies are usable, else 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import acquisition_dependencies as deps  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", action="append", choices=["normals", "thresholds"])
    args = parser.parse_args(argv)
    documents = []
    for tool in args.tool or ["normals", "thresholds"]:
        check = deps.check(tool)
        documents.append(deps.result(tool, deps.dependency_status(check) or "planned", dependency=check))
    print(json.dumps(documents, sort_keys=True, indent=2))
    return 0 if all(doc["status"] == "planned" for doc in documents) else 1


if __name__ == "__main__":
    sys.exit(main())
