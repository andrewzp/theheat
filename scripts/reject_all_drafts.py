#!/usr/bin/env python
"""Operator tool: reject EVERY pending draft (clear the review queue).

Marks all `status == "pending"` drafts as `rejected` via the bot's own conflict-safe
`read_state`/`write_state`, so it merges cleanly against a concurrent bot run instead of
clobbering the Gist. Only touches pending drafts — posted / already-rejected drafts are
left alone. Rejecting is low-harm and reversible in spirit: a still-live event will simply
re-draft next cycle; stale ones stay gone (the point).

Run in GitHub Actions (where GIST_ID + GITHUB_TOKEN live) via the reject-all-drafts
workflow. Locally it needs GIST_ID + GITHUB_TOKEN in the environment.
"""

from __future__ import annotations

import os
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


if __name__ == "__main__":
    reject_all_pending()
