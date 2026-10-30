#!/usr/bin/env python3
"""Owner-run qualified point normals: plan, bounded acquisition, admission, install plan.

The installed ``data/normals.csv`` is never written by this tool. The legacy
name-only CSV (``city,month,avg_high_c``) is refused by the loader and is
reported as such; its values are never relabelled.

  plan          deterministic universe/missing inputs/dependency; no network
  acquire       finite, resumable Meteostat fetch into a new candidate directory
                (every limit is explicit; requires the isolated dependency)
  admit         candidate manifest + loader acceptance
  install-plan  comparison with the installed file and a retained rollback copy
  check-deps    isolated dependency compatibility (requirements-acquisition.txt)

Each command prints one ``theheat.acquisition-result/v1`` JSON document. Exit 0
for ``planned``/``ready``, 1 for any other result status, 2 for a refused input.
Root performs the actual acquisition and installation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import acquisition_dependencies as deps  # noqa: E402
from src.data import normals_acquisition as normals  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CITIES_PATH = REPO / "data" / "cities.csv"
NORMALS_PATH = REPO / "data" / "normals.csv"


def _emit(document: dict, result_path: str | None) -> int:
    body = json.dumps(document, sort_keys=True, indent=2)
    if result_path:
        normals._atomic_write(Path(result_path), body.encode() + b"\n")
    print(body)
    return 0 if document.get("status") in {"planned", "ready"} else 1


def main(argv: list[str] | None = None, *, provider_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--cities", type=Path, default=CITIES_PATH)
    plan.add_argument("--installed", type=Path, default=NORMALS_PATH)
    plan.add_argument("--months", default="1-12", help="e.g. 1-12 or 6,7,8")
    plan.add_argument("--output", type=Path, required=True, help="plan JSON to write (new file or same plan)")
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--plan", type=Path, required=True)
    acquire.add_argument("--out-dir", type=Path, required=True)
    acquire.add_argument("--installed", type=Path, default=NORMALS_PATH)
    for name, kind in (("--max-requests", int), ("--max-bytes", int), ("--deadline-seconds", float),
                       ("--max-retries", int)):
        acquire.add_argument(name, type=kind, required=True)
    admit = sub.add_parser("admit")
    admit.add_argument("--candidate", type=Path, required=True)
    install = sub.add_parser("install-plan")
    install.add_argument("--candidate", type=Path, required=True)
    install.add_argument("--installed", type=Path, default=NORMALS_PATH)
    sub.add_parser("check-deps")
    for command in sub.choices.values():
        command.add_argument("--result", help="also write the result JSON here")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-deps":
            check = deps.check("normals")
            return _emit(deps.result("normals", deps.dependency_status(check) or "planned", dependency=check),
                         args.result)
        if args.command == "plan":
            months = _months(args.months)
            document = normals.build_plan(args.cities, args.installed, months=months,
                                          dependency=deps.check("normals"), plan_path=str(args.output))
            if args.output.exists():
                existing = json.loads(args.output.read_text(encoding="utf-8"))
                if existing.get("plan_sha256") != document["plan_sha256"]:
                    raise normals.NormalsError("normals_plan_output_exists")
            normals._atomic_write(args.output, json.dumps(document, sort_keys=True, indent=2).encode() + b"\n")
            return _emit(normals.plan_result(document), args.result)
        if args.command == "acquire":
            document = normals.validate_plan(json.loads(args.plan.read_text(encoding="utf-8")))
            limits = normals.Limits(args.max_requests, args.max_bytes, args.deadline_seconds, args.max_retries)
            check = deps.check("normals")
            forced = deps.dependency_status(check)
            if provider_factory is None and forced:
                return _emit(deps.result("normals", forced, dependency=check,
                                         source={"plan_sha256": document["plan_sha256"]}), args.result)
            provider = (provider_factory or normals.MeteostatProvider)()
            try:
                outcome = normals.acquire(document, args.out_dir, provider, limits, installed_path=args.installed)
            except KeyboardInterrupt:
                print(json.dumps({"status": "incomplete", "reasons": ["interrupted"]}))
                return 130
            outcome["dependency"] = check
            return _emit(outcome, args.result)
        if args.command == "admit":
            return _emit(normals.admit(args.candidate, partitions_dir=args.candidate.parent / "partitions"),
                         args.result)
        plan_document = normals.install_plan(args.candidate, args.installed)
        print(json.dumps(plan_document, sort_keys=True, indent=2))
        return 0
    except (deps.AcquisitionError, OSError, ValueError) as error:
        label = str(error) if isinstance(error, deps.AcquisitionError) else "normals_input_unavailable"
        print(json.dumps({"status": "refused", "error": label}))
        return 2


def _months(text: str) -> list[int]:
    out: set[int] = set()
    for part in text.split(","):
        low, _, high = part.partition("-")
        out.update(range(int(low), int(high or low) + 1))
    return sorted(out)


if __name__ == "__main__":
    sys.exit(main())
