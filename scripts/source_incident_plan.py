#!/usr/bin/env python3
"""Offline source-incident diagnosis and repair plan (no probes, no credentials).

inspect          product-level incidents projected from a retained state snapshot
plan             exact next action per open incident, with optional operator inputs
validate-input   check one endpoint confirmation or owner-access attestation document

Every command reads only the files named on the command line (bounded size). No
network, provider probe, credential read/enumeration, configuration change,
self-heal repair or background activation happens here.
Exit codes: 0 no open incident, 1 open incidents/holds, 2 refused input, 64 usage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_INPUT_BYTES = 16 * 1024 * 1024


def _load(path: str) -> object:
    data = Path(path).read_bytes()
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("input_too_large")
    return json.loads(data)


def _emit(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    from src.data import source_incident_plan, source_incidents

    parser = argparse.ArgumentParser(prog="source_incident_plan")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--state", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--state", required=True)
    plan.add_argument("--endpoint-confirmation", action="append", default=[])
    plan.add_argument("--access-attestation", action="append", default=[])
    check = sub.add_parser("validate-input")
    group = check.add_mutually_exclusive_group(required=True)
    group.add_argument("--endpoint-confirmation")
    group.add_argument("--access-attestation")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 64
    try:
        if args.command == "validate-input":
            if args.endpoint_confirmation:
                doc = source_incident_plan.validate_endpoint_confirmation(_load(args.endpoint_confirmation))
                _emit({"valid": True, "kind": "endpoint_confirmation", "product_id": doc["product_id"]})
            else:
                doc = source_incidents.validate_access_attestation(_load(args.access_attestation))
                _emit({"valid": True, "kind": "owner_access_attestation", "provider": doc["provider"]})
            return 0
        state = _load(args.state)
        if not isinstance(state, dict):
            raise ValueError("state_not_object")
        if args.command == "inspect":
            incidents = source_incidents.project_incidents(state.get("run_history"))
            _emit({"incidents": incidents, "recovery": source_incidents.recovery_summary(incidents)})
            return 1 if any(row["state"] not in {"qualified", "recovered"} for row in incidents) else 0
        result = source_incident_plan.build_plan(
            state, confirmations=[_load(p) for p in args.endpoint_confirmation],  # type: ignore[misc]
            attestations=[_load(p) for p in args.access_attestation],  # type: ignore[misc]
        )
        _emit(result)
        return 1 if result["actions"] or result["earthdata_hold"] else 0
    except (OSError, ValueError) as exc:
        reason = str(exc) if str(exc).replace("_", "").isalnum() else type(exc).__name__
        _emit({"refused": reason})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
