#!/usr/bin/env python3
"""Offline onboarding: preflight a checkout, or inspect one draft in a supplied saved state.

preflight      report repository inputs, pinned dependencies in this interpreter, the
               dashboard lock/cache match, generator --check state and which optional
               features are unavailable (JSON to stdout)
inspect-draft  project one draft from a supplied state file: review/approval currency,
               automatic holds, attachment and publication outcome

Never installs packages, reads environment values or credentials, contacts a service or
writes state. Exit codes: 0 ready, 1 completed with unavailable/stale items, 2 refused, 64 usage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from src import operator_onboarding as onboarding

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--skip-generators", action="store_true", help="report generator scripts without running --check")
    inspect = commands.add_parser("inspect-draft")
    inspect.add_argument("--state", required=True, type=Path)
    inspect.add_argument("--draft-id", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        if args.command == "preflight":
            report = onboarding.preflight(ROOT, run_generators=not args.skip_generators)
            ready = all(value in ("available", "available_offline_code_only", "current", "inputs present")
                        for value in report["features"].values())
        else:
            report = onboarding.inspect_draft(args.state, args.draft_id)
            ready = True
    except (OSError, ValueError, KeyError) as exc:
        sys.stdout.write(json.dumps({"status": "refused", "error": type(exc).__name__, "detail": str(exc)[:200]}) + "\n")
        return 2
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
