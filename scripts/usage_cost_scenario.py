#!/usr/bin/env python3
"""Print a dated token-price scenario from one local file; no fetches or writes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.two_bot.usage_cost_scenario import SCENARIO, project_usage_cost

MAX_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite_json")


def main(argv=None) -> int:
    try:
        parser = _Parser(description=__doc__)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--state", type=Path)
        group.add_argument("--window", type=Path)
        parser.add_argument("--scenario", required=True, choices=[SCENARIO])
        args = parser.parse_args(argv)
        with (args.state or args.window).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("input_too_large")
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        # json also accepts huge exponent literals as infinity; reject anywhere,
        # including unrelated state, before projecting any purported valid rows.
        json.dumps(value, allow_nan=False)
        if args.state:
            if not isinstance(value, dict):
                raise ValueError("invalid_state")
            value = value.get("llm_usage_observations")
        report = project_usage_cost(value, scenario=args.scenario)
        encoded = json.dumps(report, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > MAX_OUTPUT_BYTES:
            raise ValueError("output_too_large")
        print(encoded)
        return 0
    except (OSError, ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "report": "unavailable",
                    "reason": "invalid_or_unavailable_input",
                    "actual_cost_known": False,
                    "complete_account_coverage": False,
                    "eligible_token_subtotal_usd": None,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
