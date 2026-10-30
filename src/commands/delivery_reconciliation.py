"""Operator reconciliation of publish-ledger attempts: inspect, confirm, cancel.

A decision joins operator-supplied receipt evidence to one exact attempt
(event, intent, decision revision and source snapshot). It never infers
delivery from timing or from the absence of an error: ``unknown`` stays
``unknown`` until a receipt whose text, time and media description match the
attempt is supplied. Confirming writes the receipt onto the ledger row only;
the existing publisher reconciliation (``posting._reconcile_publish_ledger``)
repairs the draft. Cancelling withdraws the draft's approval and records the
cancellation, keeping every delivery field; delivered content cannot be
cancelled. Withdrawal does not settle transport: an exact later receipt may
still confirm that attempt, retaining the withdrawal and never permitting retry.
Decisions are idempotent by ``reconciliation_id`` on the row itself,
so a reload or a repeated request is ``unchanged`` and a reused identifier with
a different request is refused.

The rules mirror ``dashboard/lib/delivery-reconciliation.js``; both are checked
against ``tests/fixtures/w14_delivery_reconciliation_vectors.json``.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from src.commands.schema import canonical_json
from src.editorial.revisions import decision_revision, draft_identity, fingerprint, revoke_approval
from src.posting.outbox_outcome import retry_permitted

ACTIONS = ("confirm", "cancel")
REQUEST_KEYS = {"reconciliation_id", "action", "event_id", "intent_id", "expected_decision_revision",
                "expected_evidence_sha256", "reason"}
RECEIPT_KEYS = {"tweet_id", "text", "created_at"}
ROLES = frozenset({"publisher"})
_TABLES = {"delivery_reconciliations": (
    "reconciliation_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, actor_subject TEXT NOT NULL, "
    "result_json TEXT NOT NULL, authority_version INTEGER NOT NULL, recorded_at TEXT NOT NULL")}


class ReconciliationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _require(condition: Any, code: str) -> None:
    if not condition:
        raise ReconciliationError(code)


def _utc(value: Any) -> datetime:
    _require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?(Z|\+00:00)", value),
             "receipt_time_invalid")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="strict")).hexdigest()


def _draft_for(state: dict, event_id: str) -> dict | None:
    matches = [d for d in state.get("drafts") or [] if isinstance(d, dict) and (d.get("event_id") or d.get("id")) == event_id]
    return matches[0] if len(matches) == 1 else None


def _bound_elsewhere(state: dict, event_id: str, tweet_id: str) -> bool:
    for other, row in (state.get("publish_ledger") or {}).items():
        rows = [row, *(row.get("attempt_conflicts") or [])] if isinstance(row, dict) else []
        if other != event_id and any(isinstance(r, dict) and str(r.get("tweet_id") or "") == tweet_id for r in rows):
            return True
    return any(isinstance(d, dict) and str(d.get("tweet_id") or "") == tweet_id and (d.get("event_id") or d.get("id")) != event_id
               for d in state.get("drafts") or [])


def validate_request(request: Any) -> dict:
    _require(isinstance(request, dict), "reconciliation_request_invalid")
    keys = set(request)
    _require(REQUEST_KEYS <= keys <= REQUEST_KEYS | {"receipt"}, "reconciliation_request_invalid")
    _require(request["action"] in ACTIONS, "reconciliation_action_invalid")
    for key in ("reconciliation_id", "event_id", "intent_id", "reason"):
        _require(type(request[key]) is str and 0 < len(request[key]) <= 200, "reconciliation_request_invalid")
    _require(type(request["expected_decision_revision"]) is int and request["expected_decision_revision"] >= 0,
             "reconciliation_request_invalid")
    _require(type(request["expected_evidence_sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", request["expected_evidence_sha256"]),
             "reconciliation_request_invalid")
    if request["action"] == "confirm":
        receipt = request.get("receipt")
        _require(isinstance(receipt, dict), "receipt_required")
        _require(RECEIPT_KEYS <= set(receipt) <= RECEIPT_KEYS | {"alt_text"}, "receipt_invalid")
        _require(type(receipt["tweet_id"]) is str and re.fullmatch(r"[0-9]{1,30}", receipt["tweet_id"]), "receipt_invalid")
        _require(type(receipt["text"]) is str and type(receipt.get("alt_text", "")) is str, "receipt_invalid")
    else:
        _require("receipt" not in request, "reconciliation_request_invalid")
    return request


def inspect(state: dict) -> dict:
    """Read-only view of every ledger attempt and the actions each one allows."""
    rows = []
    ledger = state.get("publish_ledger") or {}
    for event_id in sorted(ledger):
        row = ledger[event_id]
        draft = _draft_for(state, event_id)
        if not isinstance(row, dict):
            rows.append({"event_id": event_id, "phase": "malformed", "actions": [], "hold": "malformed_evidence_preserved"})
            continue
        try:
            current = draft_identity(draft) if draft else None
            revision = decision_revision(draft) if draft else None
        except (ValueError, TypeError):
            current, revision = None, None
        confirmed = bool(row.get("tweet_id"))
        cancelled = bool(row.get("operator_cancellation"))
        conflicts = bool(row.get("attempt_conflicts"))
        open_attempt = not (confirmed or conflicts or draft is None)
        actions = (([] if row.get("phase") == "not_sent" else ["confirm"])
                   + ([] if cancelled else ["cancel"])) if open_attempt else []
        rows.append({
            "event_id": event_id, "draft_id": draft.get("id") if draft else None,
            "phase": "confirmed" if confirmed else str(row.get("phase") or "legacy_unknown"),
            "intent_id": row.get("intent_id"), "tweet_id": row.get("tweet_id"), "at": row.get("at"),
            "text_sha256": row.get("text_sha256"), "evidence_sha256": row.get("evidence_sha256"),
            "delivery_identity": deepcopy(row.get("delivery_identity")), "delivery_outcome": deepcopy(row.get("delivery_outcome")),
            "decision_revision": revision,
            "source_snapshot_current": current is not None and current.get("evidence_sha256") == row.get("evidence_sha256"),
            "retry_permitted": retry_permitted(row), "cancelled": cancelled, "conflicts": conflicts,
            "reconciliation": deepcopy(row.get("reconciliation") or row.get("operator_cancellation")),
            "actions": actions,
            "hold": ("attempt_conflicts_require_review" if conflicts else "draft_missing_or_ambiguous" if draft is None
                     else "receipt_required_unknown_stays_unknown" if not confirmed and row.get("phase") != "not_sent" else None),
        })
    return {"rows": rows, "mutation": "none"}


def decide(state: dict, request: Any, *, actor: str, at: str) -> tuple[dict, dict]:
    """Return ``(next_state, result)``; raise ReconciliationError on refusal."""
    request = validate_request(request)
    digest = fingerprint(request)
    ledger = state.get("publish_ledger")
    if not isinstance(ledger, dict) or request["event_id"] not in ledger:
        raise ReconciliationError("attempt_not_found")
    row = ledger[request["event_id"]]
    _require(isinstance(row, dict), "attempt_malformed")
    for recorded in (row.get("reconciliation"), row.get("operator_cancellation")):
        if isinstance(recorded, dict) and recorded.get("reconciliation_id") == request["reconciliation_id"]:
            _require(recorded.get("request_sha256") == digest, "reconciliation_id_reused")
            return state, {"status": "unchanged", "reconciliation_id": request["reconciliation_id"], "event_id": request["event_id"]}
    _require(not row.get("attempt_conflicts"), "attempt_conflicts_require_review")
    _require(row.get("intent_id") == request["intent_id"], "attempt_mismatch")
    draft = _draft_for(state, request["event_id"])
    if draft is None:
        raise ReconciliationError("draft_missing_or_ambiguous")
    _require(decision_revision(draft) == request["expected_decision_revision"], "stale_decision_revision")
    _require(row.get("evidence_sha256") == request["expected_evidence_sha256"]
             and draft_identity(draft)["evidence_sha256"] == row.get("evidence_sha256"), "source_snapshot_changed")
    record = {"reconciliation_id": request["reconciliation_id"], "request_sha256": digest, "actor": actor, "at": at,
              "reason": request["reason"]}
    updated = deepcopy(state)
    target = updated["publish_ledger"][request["event_id"]]
    if request["action"] == "cancel":
        _require(not row.get("tweet_id"), "delivered_content_retained")
        _require(not row.get("operator_cancellation"), "already_cancelled")
        target["operator_cancellation"] = record
        changed = _draft_for(updated, request["event_id"])
        assert changed is not None
        revoke_approval(changed)
        changed.update(status="rejected", rejected_reason="Publication intent cancelled; delivery evidence retained",
                       updated_at=at)
        return updated, {"status": "applied", "action": "cancel", "reconciliation_id": request["reconciliation_id"],
                         "event_id": request["event_id"], "phase": target.get("phase")}
    receipt = request["receipt"]
    _require(not row.get("tweet_id"), "attempt_already_confirmed")
    _require(row.get("phase") != "not_sent", "attempt_proven_not_sent")
    _require(isinstance(row.get("text"), str) and receipt["text"] == row["text"], "receipt_text_mismatch")
    _require(isinstance(row.get("at"), str) and _utc(receipt["created_at"]) >= _utc(row["at"]), "receipt_predates_attempt")
    _require(not _bound_elsewhere(state, request["event_id"], receipt["tweet_id"]), "receipt_bound_elsewhere")
    media = row.get("delivery_identity") or {}
    if media.get("alt_sha256"):
        _require(isinstance(receipt.get("alt_text"), str) and _sha(receipt["alt_text"]) == media["alt_sha256"],
                 "receipt_media_mismatch")
    record.update(receipt_sha256=fingerprint(receipt), evidence="operator_supplied_receipt",
                  png_receipt_verification="not_available_from_platform" if media.get("png_sha256") else None)
    target.update(tweet_id=receipt["tweet_id"], phase="confirmed", confirmed_at=receipt["created_at"], reconciliation=record)
    return updated, {"status": "applied", "action": "confirm", "reconciliation_id": request["reconciliation_id"],
                     "event_id": request["event_id"], "tweet_id": receipt["tweet_id"]}


def apply(connection: Any, request: Any, *, actor: str, role: str, now: str) -> dict:
    """Local SQLite authority transaction: state version and append-only journal together."""
    _require(role in ROLES, "forbidden")
    for table, columns in _TABLES.items():
        connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
    snapshot = connection.execute("SELECT version,state_json FROM authority_state WHERE singleton=1").fetchone()
    state, version = json.loads(snapshot["state_json"]), snapshot["version"]
    updated, result = decide(state, request, actor=actor, at=now)
    if result["status"] == "applied":
        version += 1
        connection.execute("UPDATE authority_state SET version=?,state_json=? WHERE singleton=1",
                           (version, canonical_json(updated)))
        connection.execute("INSERT INTO delivery_reconciliations VALUES(?,?,?,?,?,?)",
                           (request["reconciliation_id"], fingerprint(request), actor,
                            canonical_json(result), version, now))
    return {**result, "state_version": version}
