"""Immutable, bounded domain commands; authenticated identity comes from ingress."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from src.editorial.publication import valid_epoch

MAX_COMMAND_BYTES = 128 * 1024
MAX_TARGETS = 500
ACTIONS = frozenset({"edit_revision", "select_candidate", "record_review", "approve_revision",
                     "schedule_revision", "cancel_approval", "reject_revision", "bulk_reject"})
_HEX = re.compile(r"[a-f0-9]{64}")


class CommandError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_json(value: Any) -> str:
    try:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        text.encode("utf-8")
        return text
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CommandError("invalid_json", "Command must contain valid, finite JSON data") from exc


def utc_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise CommandError("invalid_time", "Use a complete UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CommandError("invalid_time", "Timestamp is not a real calendar date") from exc


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise CommandError("invalid_time", "An aware UTC clock is required")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _string(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise CommandError("invalid_command", f"{label} must be nonempty text within {limit} characters")
    canonical_json(value)
    return value


@dataclass(frozen=True)
class Principal:
    """A verified identity supplied by an adapter, never constructed from JSON.

    This value alone is not authentication. Hosted adapters must validate their
    session/token, and the consumer resolves current roles again at execution.
    """
    subject: str
    role: str
    authentication_context: str

    def __post_init__(self):
        _string(self.subject, "Subject", 200)
        _string(self.authentication_context, "Authentication context", 200)
        if not isinstance(self.role, str) or self.role not in {"viewer", "editor", "publisher"}:
            raise CommandError("invalid_principal", "Unknown operator role")


def authorize(principal: Principal, action: str) -> None:
    if principal.role == "viewer" or (action in {"approve_revision", "schedule_revision"} and principal.role != "publisher"):
        raise CommandError("forbidden", "This operator does not currently have permission for the action")


@dataclass(frozen=True)
class DraftTarget:
    draft_id: str
    content_revision: int
    decision_revision: int
    text_sha256: str
    evidence_sha256: str

    @classmethod
    def parse(cls, value: Any) -> DraftTarget:
        keys = {"draft_id", "content_revision", "decision_revision", "text_sha256", "evidence_sha256"}
        if not isinstance(value, dict) or set(value) != keys:
            raise CommandError("invalid_target", "Every target needs its exact draft, text, evidence and decision identity")
        _string(value["draft_id"], "Draft ID", 200)
        for key in ("content_revision", "decision_revision"):
            if type(value[key]) is not int or not 0 <= value[key] < 9007199254740991:
                raise CommandError("invalid_target", "Revision must be a nonnegative safe integer")
        for key in ("text_sha256", "evidence_sha256"):
            if not isinstance(value[key], str) or not _HEX.fullmatch(value[key]):
                raise CommandError("invalid_target", "Expected hashes must be lowercase SHA-256")
        return cls(**value)

    def as_dict(self) -> dict:
        return {"draft_id": self.draft_id, "content_revision": self.content_revision,
                "decision_revision": self.decision_revision, "text_sha256": self.text_sha256,
                "evidence_sha256": self.evidence_sha256}


def _validate_payload(action: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        raise CommandError("invalid_payload", "Payload must be an object")
    required = {
        "edit_revision": {"text"}, "select_candidate": {"candidate_rank", "candidate_sha256"},
        "record_review": {"confirmed", "reason"}, "approve_revision": {"reason"},
        "schedule_revision": {"delay_minutes", "publication_epoch", "reason"},
        "cancel_approval": {"reason"}, "reject_revision": {"reason"}, "bulk_reject": {"reason"},
    }[action]
    if set(payload) != required:
        raise CommandError("invalid_payload", "Payload fields do not match the action")
    if "text" in payload:
        _string(payload["text"], "Draft text", 280)
    if "reason" in payload:
        _string(payload["reason"], "Reason", 2000)
    if action == "record_review" and payload["confirmed"] is not True:
        raise CommandError("review_confirmation_required", "Confirm review against the exact source evidence")
    if action == "select_candidate" and (type(payload["candidate_rank"]) is not int or not 1 <= payload["candidate_rank"] <= 100):
        raise CommandError("invalid_candidate", "Candidate rank must be an integer from 1 to 100")
    if action == "select_candidate" and (not isinstance(payload["candidate_sha256"], str) or not _HEX.fullmatch(payload["candidate_sha256"])):
        raise CommandError("invalid_candidate", "Selected candidate must include its exact fingerprint")
    if action == "schedule_revision":
        if type(payload["delay_minutes"]) is not int or not 5 <= payload["delay_minutes"] <= 1440:
            raise CommandError("invalid_schedule", "Delay must be 5 to 1440 whole minutes")
        if not valid_epoch(payload["publication_epoch"]):
            raise CommandError("invalid_schedule", "A valid release epoch is required")
    return canonical_json(payload)


@dataclass(frozen=True)
class Command:
    command_id: str
    action: str
    environment: str
    actor_subject: str
    authentication_context: str
    requested_at: str
    expires_at: str
    targets: tuple[DraftTarget, ...]
    payload_json: str
    schema_version: int = 1

    @classmethod
    def from_request(cls, body: Any, principal: Principal, *, environment: str, now: datetime) -> Command:
        """Reject authority fields in input; callers retain IDs/timestamps on retry."""
        keys = {"command_id", "action", "requested_at", "expires_at", "targets", "payload"}
        if not isinstance(body, dict) or set(body) != keys:
            raise CommandError("invalid_command", "Command fields do not match the request contract")
        encoded = canonical_json(body)
        if len(encoded.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise CommandError("command_too_large", "Command exceeds the size limit")
        try:
            command_id = str(UUID(body["command_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise CommandError("invalid_command_id", "A canonical UUID is required") from exc
        if command_id != body["command_id"]:
            raise CommandError("invalid_command_id", "A canonical UUID is required")
        action = body["action"]
        if not isinstance(action, str) or action not in ACTIONS:
            raise CommandError("invalid_action", "Unsupported mutation action")
        if environment not in {"local", "preview", "production"}:
            raise CommandError("invalid_environment", "Unknown authority environment")
        authorize(principal, action)
        requested = utc_datetime(body["requested_at"])
        expires = utc_datetime(body["expires_at"])
        clock = utc_datetime(utc_text(now))
        if requested > clock + timedelta(minutes=5) or expires <= requested or expires > requested + timedelta(days=1):
            raise CommandError("invalid_time", "Command time window is invalid")
        rows = body["targets"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_TARGETS or (action != "bulk_reject" and len(rows) != 1):
            raise CommandError("invalid_targets", "Supply one target, or an explicit bounded set for bulk rejection")
        targets = tuple(DraftTarget.parse(row) for row in rows)
        if len({row.draft_id for row in targets}) != len(targets):
            raise CommandError("invalid_targets", "Duplicate draft targets are not allowed")
        return cls(command_id, action, environment, principal.subject, principal.authentication_context,
                   body["requested_at"], body["expires_at"], targets, _validate_payload(action, body["payload"]))

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)

    def as_dict(self) -> dict:
        return {"schema_version": self.schema_version, "command_id": self.command_id, "action": self.action,
                "environment": self.environment, "actor_subject": self.actor_subject,
                "authentication_context": self.authentication_context, "requested_at": self.requested_at,
                "expires_at": self.expires_at, "targets": [target.as_dict() for target in self.targets], "payload": self.payload}

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict()).encode("utf-8")).hexdigest()

    @classmethod
    def from_stored(cls, encoded: str) -> Command:
        """Validate stored structure without trusting its role or freshness.

        Execution re-authorizes the subject; expired commands get durable terminal
        results. The stored request is parsed against its own valid creation time.
        """
        try:
            row = json.loads(encoded)
        except (ValueError, TypeError) as exc:
            raise CommandError("invalid_journal", "Stored command is not valid JSON") from exc
        if not isinstance(row, dict) or type(row.get("schema_version")) is not int or row["schema_version"] != 1:
            raise CommandError("invalid_journal", "Unsupported stored command schema")
        request = {key: row[key] for key in ("command_id", "action", "requested_at", "expires_at", "targets", "payload") if key in row}
        principal = Principal(_string(row.get("actor_subject"), "Subject", 200), "publisher",
                              _string(row.get("authentication_context"), "Authentication context", 200))
        environment = _string(row.get("environment"), "Environment", 10)
        parsed = cls.from_request(request, principal, environment=environment, now=utc_datetime(row.get("requested_at")))
        if parsed.as_dict() != row:
            raise CommandError("invalid_journal", "Stored envelope contains unexpected fields")
        return parsed
