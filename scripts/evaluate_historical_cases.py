#!/usr/bin/env python3
"""Offline P07a evaluation: verified private package in, private reports out."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.evaluation.historical import evaluate, unexpected_observations, write_private_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True,
                        help="Original checkout whose ignored .gstack/benchmarks receives private results")
    args = parser.parse_args()
    report, private = evaluate(args.package, args.manifest_sha256)
    result = write_private_results(args.output, report, private, repository=args.repository)
    result["unexpected_observations"] = unexpected_observations(report)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["unexpected_observations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
