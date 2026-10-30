"""W14.6 fixture journey: source -> outbox job -> lost response -> receipt -> history -> import.

Runs in-process (pytest) or as a fresh process (Node spawns it and projects the result
across editor/Published/Operations). Invented places only; sockets are refused and the
X adapter talks to a fake tweepy-shaped object.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _refuse(*_args, **_kwargs):
    raise AssertionError("network refused in the W14 journey")


def run(workdir: str) -> dict:
    import requests

    from src.commands import import_plan
    from src.commands.schema import Principal, canonical_json
    from src.commands.sqlite_authority import SQLiteAuthority
    from src.commands.delivery_reconciliation import ReconciliationError
    from src.editorial.revisions import decision_revision
    from src.orchestrator import posting
    from src.posting import twitter
    from src.state import DEFAULT_STATE
    from tests.revision_helpers import bind_reviewed_draft

    saved = {name: getattr(owner, name) for owner, name in ((socket, "getaddrinfo"), (socket, "create_connection"))}
    originals = (posting.state, posting.post_tweet, twitter._get_client, twitter._get_upload_api)
    socket.getaddrinfo = socket.create_connection = _refuse
    os.environ.setdefault("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    os.environ.setdefault("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "offline-test-release")
    journey: list[dict] = []

    class LostCreate:
        calls: list = []

        def create_tweet(self, text, **_options):
            LostCreate.calls.append(text)
            raise requests.exceptions.ConnectionError("invented lost create response")

    try:
        storage = MagicMock()
        storage.check_daily_cap.return_value = True
        storage.write_state.return_value = True
        posting.state = storage
        posting.post_tweet = twitter.post_tweet
        twitter._get_client = LostCreate
        twitter._get_upload_api = LostCreate

        def source(key: str, place: str) -> dict:
            draft = {"id": f"w14j-{key}", "event_id": f"w14j-ev-{key}", "type": "monthly_high",
                     "text": f"Invented {place} reached 41 C, a monthly high.",
                     "created_at": "2026-10-30T09:00:00Z", "updated_at": "2026-10-30T09:00:00Z",
                     "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
                     "review_context": {"two_bot": {"bundle": {"event_id": f"w14j-ev-{key}", "signal_kind": "monthly_high",
                                                               "current_facts": [{"label": "place", "value": place}]}}}}
            return bind_reviewed_draft(draft, "manual", f"w14j-intent-{key}")

        state = deepcopy(DEFAULT_STATE)
        state["drafts"] = [source("delivered", "Corran Shelf"), source("cancelled", "Wick Hollow")]
        for draft in state["drafts"]:
            outcome = posting.post_approved(draft, state)
            journey.append({"step": "outbox", "draft": draft["id"], "result": outcome,
                            "phase": state["publish_ledger"][draft["event_id"]]["phase"]})
        journey.append({"step": "no_resend", "result": posting.post_approved(state["drafts"][0], state), "create_calls": len(LostCreate.calls)})
        authority = SQLiteAuthority(Path(workdir) / "authority.sqlite3")
        authority.initialize(json.loads(canonical_json(state)))
        publisher = Principal("w14j-publisher", "publisher", "local-fixture")
        _version, stored = authority.read()

        def request(key: str, action: str, **extra) -> dict:
            row = stored["publish_ledger"][f"w14j-ev-{key}"]
            draft = next(d for d in stored["drafts"] if d["event_id"] == f"w14j-ev-{key}")
            return {"reconciliation_id": f"w14j-{action}-{key}", "action": action, "event_id": f"w14j-ev-{key}",
                    "intent_id": row["intent_id"], "expected_decision_revision": decision_revision(draft),
                    "expected_evidence_sha256": row["evidence_sha256"], "reason": "Invented operator check", **extra}

        delivered_row = stored["publish_ledger"]["w14j-ev-delivered"]
        receipt = {"tweet_id": "1900000000000004242", "text": delivered_row["text"], "created_at": delivered_row["at"]}
        journey.append({"step": "receipt", **authority.delivery_reconciliation(request("delivered", "confirm", receipt=receipt), publisher)})
        journey.append({"step": "cancel_unknown", **authority.delivery_reconciliation(request("cancelled", "cancel"), publisher)})
        _version, stored = authority.read()
        try:
            authority.delivery_reconciliation(request("delivered", "cancel"), publisher)
            journey.append({"step": "cancel_delivered", "result": "applied"})
        except ReconciliationError as exc:
            journey.append({"step": "cancel_delivered", "result": "refused", "code": exc.code})
        _version, final = authority.read()
        posting._reconcile_publish_ledger(final)  # type: ignore[arg-type]  # the real publisher consumer writes history
        raw = canonical_json(final).encode()
        target = SQLiteAuthority(Path(workdir) / "imported.sqlite3")
        target.initialize({"drafts": [], "publish_ledger": {}})
        reviewed = import_plan.plan([("w14j-import", raw)], authority=target)
        imported = import_plan.execute(target, reviewed, [("w14j-import", raw)])
        journey.append({"step": "import", "statuses": [item["status"] for item in imported["items"]]})
        provenance = {draft["id"]: {"origin": "import", "import_id": "w14j-import", "source_sha256": hashlib.sha256(raw).hexdigest()}
                      for draft in final["drafts"]}
        return {"state": final, "provenance": provenance, "journey": journey}
    finally:
        socket.getaddrinfo, socket.create_connection = saved["getaddrinfo"], saved["create_connection"]
        posting.state, posting.post_tweet, twitter._get_client, twitter._get_upload_api = originals


if __name__ == "__main__":
    from contextlib import redirect_stdout
    with tempfile.TemporaryDirectory() as directory:
        with redirect_stdout(sys.stderr):  # sender logs never mix with the JSON result
            result = run(directory)
        print(json.dumps(result, sort_keys=True))
