#!/usr/bin/env python
"""Operator tool: reject pending drafts.

With no arguments, the existing Gist workflow rereads and retries false writes
up to five times. Its GET/PATCH merge is not an atomic compare-and-swap and may
race concurrent writers. Each retry selects the then-current pending drafts.

Explicit --command-endpoint, --command-origin, --operators, --subject and
--request-file options select the local authenticated authority instead. This
mode retains one fixed revision-bound request for recovery; it never falls back
to Gist. Acceptance is pending until the separate consumer finishes. Publishing
and the legacy workflow's default backend are unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.state import read_state, write_state  # noqa: E402

REASON = "operator_bulk_reject"
_MAX_ATTEMPTS = 5


def reject_all_pending() -> int:
    """Reject every pending draft. Returns the number rejected. Retries on a
    write conflict (re-reading the merged state each time)."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        state = read_state()
        drafts = state.get("drafts") or []
        pending = [d for d in drafts if isinstance(d, dict) and d.get("status") == "pending"]
        if not pending:
            print("No pending drafts to reject.")
            return 0
        for d in pending:
            d["status"] = "rejected"
            d["rejected_reason"] = REASON
            d["post_error"] = None
            for key in ("auto_approve_at", "auto_approve_requested_at", "publish_intent_id"):
                d.pop(key, None)
        if write_state(state):
            print(f"Rejected {len(pending)} pending draft(s).")
            return len(pending)
        print(f"write_state conflict (attempt {attempt}/{_MAX_ATTEMPTS}); re-reading and retrying...")
    print("ERROR: could not persist rejections after retries.", file=sys.stderr)
    raise SystemExit(1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reject pending drafts; local command mode is explicit and opt-in.")
    for name in ("command-endpoint", "command-origin", "operators", "subject", "request-file"):
        parser.add_argument("--" + name)
    args = parser.parse_args(argv)
    values = vars(args)
    if not any(value is not None for value in values.values()):
        reject_all_pending()
        return 0
    if not all(values.values()):
        parser.error("Command mode requires all five explicit options; legacy fallback is unavailable.")
    from src.commands.bulk_rejection_client import BulkRejectionClient
    result = BulkRejectionClient(args.command_endpoint, args.command_origin,
        Path(args.operators), args.subject, Path(args.request_file)).run()
    print(json.dumps(result, sort_keys=True))
    return {"noop": 0, "applied": 0, "unchanged": 0, "pending": 2, "unknown": 3}.get(result["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
