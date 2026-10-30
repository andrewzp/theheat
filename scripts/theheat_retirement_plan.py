#!/usr/bin/env python3
"""Write an unapplied retirement plan for supplied candidates (paths, flags, branches).

Usage: theheat_retirement_plan.py --candidates FILE.json [--state SAVED_STATE.json]
Prints the plan as JSON. Never deletes, renames, pushes or cleans up anything.
Exit codes: 0 every candidate eligible, 1 some refused, 2 refused input, 64 usage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_INPUT = 4 * 1024 * 1024


def _load(path: Path):
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT:
        raise ValueError("input_too_large")
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    from src.retirement_plan import RetirementPlanError, plan

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        candidates = _load(args.candidates)
        state = _load(args.state) if args.state else None
        result = plan(ROOT, candidates.get("candidates") if isinstance(candidates, dict) else None, state=state)
    except (OSError, ValueError, RetirementPlanError) as exc:
        sys.stdout.write(json.dumps({"status": "refused", "error": str(exc)[:200]}) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return 0 if not result["refused"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
