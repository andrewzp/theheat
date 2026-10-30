#!/usr/bin/env python3
"""Offline rainfall/sparse-hazard supply tools (W06). No fetch, no activation.

reconcile   compare supplied product granule cells with supplied gauge packets
pilots      select bounded reference-gap pilots from retained coverage rows
readiness   per source/region readiness from retained scan details in a state snapshot
scan-plan   the next bounded regional scan (cursor and revisit ages) from a state snapshot

Exit codes: 0 complete, 1 holds/gaps present, 2 refused input, 64 usage.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_INPUT_BYTES = 16 * 1024 * 1024


def _load(path: str):
    data = Path(path).read_bytes()
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("input_too_large")
    return json.loads(data)


def main(argv: list[str] | None = None) -> int:
    from src.data import rainfall_supply as rs

    parser = argparse.ArgumentParser(prog="rainfall_supply")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("reconcile")
    rec.add_argument("--granules", required=True)
    rec.add_argument("--gauges", required=True)
    pil = sub.add_parser("pilots")
    pil.add_argument("--coverage", required=True)
    pil.add_argument("--max", type=int, required=True)
    pil.add_argument("--plan", action="append", default=[])
    rdy = sub.add_parser("readiness")
    rdy.add_argument("--state", required=True)
    scn = sub.add_parser("scan-plan")
    scn.add_argument("--state", required=True)
    scn.add_argument("--regions", required=True)
    scn.add_argument("--source", required=True)
    scn.add_argument("--today", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 64
    try:
        if args.command == "reconcile":
            result = rs.reconcile(_load(args.granules), _load(args.gauges))
            code = 1 if result["holds"] else 0
        elif args.command == "pilots":
            result = rs.select_pilots(_load(args.coverage), max_pilots=args.max, supplied_plan=args.plan)
            code = 1 if result["gaps"] else 0
        elif args.command == "readiness":
            rows = rs.readiness(_load(args.state).get("run_history"))
            result = {"rows": rows}
            code = 1 if any(row["outcome"] != "qualified" for row in rows) else 0
        else:
            regions = _load(args.regions)
            history = _load(args.state).get("run_history")
            result = {"cursor": rs.cursor_from_history(history, args.source, regions),
                      "revisit_age_days": rs.revisit_ages(history, args.source, regions,
                                                          today=date.fromisoformat(args.today)),
                      "region_set_sha256": rs.region_set_sha(regions)}
            code = 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        sys.stdout.write(json.dumps({"refused": type(exc).__name__}) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=1) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
