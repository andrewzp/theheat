#!/usr/bin/env python3
"""Owner-run GHCN-Daily threshold rebuild from explicit local inputs.

Replaces the old one-shot bootstrap that silently downloaded the whole archive.
Every step is explicit, bounded and restartable; nothing uploads.

  fetch-archive  bounded resumable download of ghcnd_all.tar.gz with a receipt
                 (--max-bytes/--deadline-seconds/--max-retries are required)
  plan           exact inputs (stations/inventory/countries files + archive),
                 snapshot cutoff, QC policy, active universe and partitions
  build          one archive pass over the selected pending partitions; each
                 partition is published only when complete
  assemble       SQLite artifact + gzip asset + V2 manifest + build manifest

Station/inventory/country text files are the NOAA ghcnd-stations.txt,
ghcnd-inventory.txt and ghcnd-countries.txt files, saved by the owner.
Then verify and plan the upload with ``scripts/threshold_package.py``.
Each command prints JSON. Exit 0 ready/planned, 1 other status, 2 refused input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import acquisition_dependencies as deps  # noqa: E402
from src.data import threshold_rebuild as rebuild  # noqa: E402


def _paths(args) -> dict[str, Path]:
    return {"stations": args.stations, "inventory": args.inventory, "countries": args.countries,
            "archive": args.archive}


def _emit(document: dict) -> int:
    print(json.dumps(document, sort_keys=True, indent=2))
    return 0 if document.get("status") in {"planned", "ready"} else 1


def main(argv: list[str] | None = None, *, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch-archive")
    fetch.add_argument("--dest", type=Path, required=True)
    fetch.add_argument("--max-bytes", type=int, required=True)
    fetch.add_argument("--deadline-seconds", type=float, required=True)
    fetch.add_argument("--max-retries", type=int, required=True)
    for name in ("plan", "build", "assemble"):
        command = sub.add_parser(name)
        for flag in ("--stations", "--inventory", "--countries", "--archive"):
            command.add_argument(flag, type=Path, required=True)
        if name == "plan":
            command.add_argument("--snapshot-date", required=True)
            command.add_argument("--partitions", type=int, required=True)
            command.add_argument("--active-year-cutoff", type=int)
            command.add_argument("--archive-receipt", type=Path)
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--plan", type=Path, required=True)
            command.add_argument("--work-dir", type=Path, required=True)
        if name == "build":
            command.add_argument("--partition", type=int, action="append", help="repeat; default all pending")
            command.add_argument("--deadline-seconds", type=float, required=True)
        if name == "assemble":
            command.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch-archive":
            if session_factory is None:
                import requests

                session_factory = requests.Session
            return _emit(rebuild.fetch_archive(args.dest, session=session_factory(), max_bytes=args.max_bytes,
                                               deadline_seconds=args.deadline_seconds, max_retries=args.max_retries))
        if args.command == "plan":
            plan = rebuild.build_plan(stations=args.stations, inventory=args.inventory, countries=args.countries,
                                      archive=args.archive, snapshot_date=args.snapshot_date,
                                      partitions=args.partitions, active_year_cutoff=args.active_year_cutoff,
                                      archive_receipt=args.archive_receipt)
            if args.output.exists() and json.loads(args.output.read_text()).get("plan_sha256") != plan["plan_sha256"]:
                raise rebuild.RebuildError("threshold_plan_output_exists")
            rebuild._atomic_bytes(args.output, json.dumps(plan, sort_keys=True, indent=2).encode() + b"\n")
            status = "source_absent" if plan["missing_inputs"] else "planned"
            return _emit(deps.result("thresholds", status, reasons=[f"{name}_missing" for name in plan["missing_inputs"]],
                                     source={"plan_sha256": plan["plan_sha256"], "inputs": plan["inputs"]},
                                     product={"active_stations": plan["active_stations"],
                                              "partitions": len(plan["partitions"])},
                                     observed=plan["active_stations"]))
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if args.command == "build":
            return _emit(rebuild.build_partitions(plan, paths=_paths(args), work_dir=args.work_dir,
                                                  select=args.partition, deadline_seconds=args.deadline_seconds))
        build = rebuild.assemble(plan, paths=_paths(args), work_dir=args.work_dir, out_dir=args.out_dir)
        return _emit(deps.result("thresholds", "ready", source={"plan_sha256": plan["plan_sha256"]},
                                 product={"database": build["database"], "asset": build["asset"],
                                          "coverage": build["coverage"]},
                                 observed=build["coverage"]["active_stations"],
                                 promoted=build["coverage"]["active_with_thresholds"]))
    except (deps.AcquisitionError, OSError, ValueError, KeyError) as error:
        label = str(error) if isinstance(error, deps.AcquisitionError) else "threshold_input_unavailable"
        print(json.dumps({"status": "refused", "error": label}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
