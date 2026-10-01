#!/usr/bin/env python3
"""Print a private-input-safe operating report. Never fetch or modify state."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.editorial.policy import source_manifest  # noqa: E402
from src.writer_health import summarize_writer_health, timestamp  # noqa: E402

MAX_BYTES = 16 * 1024 * 1024


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_path")
    parser.add_argument("--now", help="Aware ISO timestamp for offline reproduction")
    args = parser.parse_args(argv)
    try:
        now = timestamp(args.now) if args.now is not None else datetime.now(UTC)
        if now is None:
            raise ValueError("invalid_time")
        with Path(args.state_path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("input_too_large")
        state = json.loads(raw)
        report = summarize_writer_health(state, now=now, current_source_sha256=source_manifest()["source_sha256"])
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0  # Report generated; not a pass for product health or publishing.
    except (OSError, ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        print(json.dumps({"schema_version": 1, "report": "unavailable", "reason": "input_or_manifest_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
