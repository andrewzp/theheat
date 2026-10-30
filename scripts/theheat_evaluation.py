#!/usr/bin/env python3
"""Offline coverage, metrics and evaluation tools over supplied files (W15).

reference-intake       supplied reference events/quiet periods -> intake record
match-coverage         intake record + saved state -> coverage assessment with match evidence
metrics-intake         saved state + supplied X API lookup response -> new state copy + report
route-evaluation       saved state -> per-route factual/editorial evaluation columns
correction-candidates  saved state + supplied discrepancies -> review-only candidates
experiment-plan        weekly review's selected improvement + arm spec -> frozen default-off plan
experiment-accept      frozen plan + supplied bound result -> HOLD / PROMOTE_RECOMMENDED decision

Reads only the named files and writes only the named new output file. No
network, model, Gist, platform or database access; nothing is published,
corrected or deleted. Exit codes: 0 written, 2 refused, 64 usage.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_INPUT = 16 * 1024 * 1024


def _read(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) > MAX_INPUT:
        raise ValueError("input_too_large")
    return data


def _json(path: Path):
    return json.loads(_read(path))


def _time(value: str) -> datetime:
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ValueError("timezone_required")
    return at.astimezone(UTC)


def _write(path: Path, value) -> None:
    if path.exists():
        raise ValueError("output_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("reference-intake")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--retained-at", required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("match-coverage")
    p.add_argument("--record", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--cutoff", required=True)
    p.add_argument("--evaluated-at", required=True)
    p.add_argument("--policy-sha256", required=True)
    p.add_argument("--state-version", type=int, default=0)
    p.add_argument("--invented-fixture", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("metrics-intake")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--response", type=Path, required=True)
    p.add_argument("--captured-at", required=True)
    p.add_argument("--ids", required=True, help="comma-separated post IDs requested in the saved response")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("route-evaluation")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--human-comparisons", type=Path)
    p.add_argument("--counterexamples", type=Path, help="JSON list of known bad published text sha256 values")
    p.add_argument("--invented-fixture", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("correction-candidates")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--discrepancies", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("experiment-plan")
    p.add_argument("--weekly-review", type=Path, required=True)
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("experiment-accept")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        if args.command == "reference-intake":
            from src.evaluation import reference_intake
            result = reference_intake.intake(_json(args.input), retained_at=args.retained_at)
        elif args.command == "match-coverage":
            from src.evaluation import production_match
            result = production_match.assess(_json(args.record), _json(args.state), cutoff=args.cutoff,
                                             evaluated_at=args.evaluated_at, state_version=args.state_version,
                                             policy_sha256=args.policy_sha256,
                                             execution_class="invented_fixture" if args.invented_fixture else "retained_runtime")
        elif args.command == "metrics-intake":
            from src.data import metric_intake
            state = _json(args.state)
            metrics, report = metric_intake.ingest(state, _read(args.response), captured_at=_time(args.captured_at),
                                                   requested_ids=args.ids.split(","))
            result = {"state": {**state, "tweet_metrics": metrics}, "report": report}
        elif args.command == "route-evaluation":
            from src.evaluation import reconciled_cost, route_evaluation
            state = _json(args.state)
            result = route_evaluation.evaluate(
                state, window_start=_time(args.since), window_end=_time(args.until),
                cost_observations=reconciled_cost.operation_observations(state),
                human_comparisons=_json(args.human_comparisons) if args.human_comparisons else None,
                counterexample_text_sha256s=set(_json(args.counterexamples)) if args.counterexamples else None,
                execution="invented_fixture" if args.invented_fixture else "retained_runtime")
        elif args.command == "experiment-plan":
            from src.evaluation import experiment_plan
            result = experiment_plan.plan_from_weekly_review(_json(args.weekly_review), _json(args.spec))
        elif args.command == "experiment-accept":
            from src.evaluation import experiment_plan
            result = experiment_plan.accept(_json(args.plan), _json(args.result))
        else:
            from src.evaluation import correction_candidates
            result = correction_candidates.prepare(_json(args.state), _json(args.discrepancies))
        _write(args.output, result)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.stdout.write(json.dumps({"status": "refused", "error": type(exc).__name__, "detail": str(exc)[:200]}) + "\n")
        return 2
    sys.stdout.write(json.dumps({"status": "written", "output": str(args.output)}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
