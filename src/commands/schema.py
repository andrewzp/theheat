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
MEDIA_ACTIONS = frozenset({"attach_media_revision", "remove_media_revision", "review_media_revision"})
EDITOR_MEDIA_ACTIONS = frozenset({"prepare_media_revision", "request_revision_checks", "approve_media_revision"})
CANDIDATE_ACTIONS = frozenset({"request_candidate_checks", "admit_checked_candidate"})
SOURCE_ACTIONS = frozenset({"commit_nhc_source_run", "commit_ghcn_source_run"})
REPORT_ACTIONS = frozenset({"open_report_evidence"})
COVERAGE_ACTIONS = frozenset({"evaluate_reference_coverage"})
GENERATION_ACTIONS = frozenset({"request_sourced_generation"})
ACTIONS = SOURCE_ACTIONS | COVERAGE_ACTIONS | REPORT_ACTIONS | EDITOR_MEDIA_ACTIONS | GENERATION_ACTIONS | CANDIDATE_ACTIONS | MEDIA_ACTIONS | frozenset({"edit_revision", "select_candidate", "record_review", "approve_revision",
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
    if principal.role == "viewer" or (action in {"approve_revision", "schedule_revision", "approve_media_revision"} and principal.role != "publisher"):
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


def _validate_payload(action: str, payload: Any, *, allow_legacy_review: bool = False) -> str:
    if not isinstance(payload, dict):
        raise CommandError("invalid_payload", "Payload must be an object")
    required = {
        "commit_ghcn_source_run": {"supply_run_id", "supply_sha256", "runtime_input_sha256", "dependency_sha256", "expected_policy_sha256"},
        "commit_nhc_source_run": {"supply_run_id", "supply_sha256", "runtime_input_sha256", "expected_episode_heads", "expected_policy_sha256"},
        "evaluate_reference_coverage": {"set_id", "expected_set_sha256", "expected_state_version", "expected_policy_sha256"},
        "open_report_evidence": {"lineage_id", "report_sha256", "expected_policy_sha256", "episode_reference"},
        "prepare_media_revision": {"expected_policy_sha256", "expected_renderer_profile_sha256"},
        "request_revision_checks": {"expected_policy_sha256", "expected_renderer_profile_sha256", "expected_packet_sha256", "expected_review_sha256"},
        "approve_media_revision": {"expected_policy_sha256", "expected_renderer_profile_sha256", "expected_packet_sha256", "expected_review_sha256", "expected_check_completion_sha256", "reason"},
        "review_media_revision": {"proposal_sha256", "expected_packet_sha256", "expected_policy_sha256", "review"},
        "request_sourced_generation": {"brief_id", "brief_sha256", "expected_state_version", "expected_policy_sha256"},
        "edit_revision": {"text"}, "select_candidate": {"candidate_rank", "candidate_sha256"},
        "record_review": {"confirmed", "reason", "expected_policy_sha256"}, "approve_revision": {"reason"},
        "schedule_revision": {"delay_minutes", "publication_epoch", "reason"},
        "cancel_approval": {"reason"}, "reject_revision": {"reason"}, "bulk_reject": {"reason"},
        "attach_media_revision": {"proposal_sha256", "expected_packet_sha256", "expected_policy_sha256", "review"},
        "remove_media_revision": {"expected_proposal_sha256", "expected_policy_sha256", "confirmed", "reason"},
        "request_candidate_checks": {"admission_input_id", "admission_input_sha256", "job_id", "custom_id", "candidate_id", "expected_state_version", "expected_policy_sha256"},
        "admit_checked_candidate": {"admission_input_id", "admission_input_sha256", "job_id", "custom_id", "candidate_id", "expected_state_version", "expected_policy_sha256", "check_set_id", "expected_completion_sha256"},
    }[action]
    if action in CANDIDATE_ACTIONS and payload.get("origin_kind") == "synchronous_writer_v1":
        required = (required - {"job_id", "custom_id"}) | {"origin_kind", "generation_id"}
    if action == "record_review" and allow_legacy_review and set(payload) == {"confirmed", "reason"}:
        required = {"confirmed", "reason"}  # Retained old intent must receive a terminal refusal, not wedge the journal.
    if set(payload) != required:
        raise CommandError("invalid_payload", "Payload fields do not match the action")
    if action in SOURCE_ACTIONS:
        try:
            if str(UUID(payload["supply_run_id"])) != payload["supply_run_id"]:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise CommandError("invalid_source_identity", "Supply the exact retained source run") from None
        for key in (("supply_sha256", "runtime_input_sha256", "dependency_sha256") if action == "commit_ghcn_source_run" else ("supply_sha256", "runtime_input_sha256")):
            if type(payload[key]) is not str or not _HEX.fullmatch(payload[key]):
                raise CommandError("invalid_source_identity", "Supply exact retained source fingerprints")
        if action == "commit_nhc_source_run":
            heads = payload["expected_episode_heads"]
            if type(heads) is not dict or len(heads) > 64 or any(type(key) is not str
                    or not re.fullmatch(r"ep1:cyclone:nhc:(?:AL|EP)(?:0[1-9]|[1-4][0-9])[0-9]{4}", key)
                    or int(key[-4:]) == 0 or (value is not None and (type(value) is not str or not _HEX.fullmatch(value)))
                    for key, value in heads.items()):
                raise CommandError("invalid_source_heads", "Supply the complete bounded episode head map")
    if action in COVERAGE_ACTIONS:
        if not isinstance(payload["set_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", payload["set_id"]):
            raise CommandError("invalid_coverage_identity", "Supply the retained reference-set identity")
        if not isinstance(payload["expected_set_sha256"], str) or not _HEX.fullmatch(payload["expected_set_sha256"]):
            raise CommandError("invalid_coverage_identity", "Supply the exact reference-set fingerprint")
        if type(payload["expected_state_version"]) is not int or not 0 <= payload["expected_state_version"] <= 9007199254740991:
            raise CommandError("invalid_state_version", "Supply the exact authority version")
    if action in REPORT_ACTIONS:
        if not isinstance(payload["lineage_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", payload["lineage_id"]):
            raise CommandError("invalid_report_identity", "Supply the retained report identity")
        if not isinstance(payload["report_sha256"], str) or not _HEX.fullmatch(payload["report_sha256"]):
            raise CommandError("invalid_report_identity", "Supply the exact report fingerprint")
        episode = payload["episode_reference"]
        if episode is not None:
            if (not isinstance(episode, dict) or set(episode) != {"episode_id", "revision_sha256", "claim_id"}
                    or not isinstance(episode["episode_id"], str)
                    or not re.fullmatch(r"ep1:cyclone:nhc:(?:AL|EP)(?:0[1-9]|[1-4][0-9])[0-9]{4}", episode["episode_id"])
                    or not isinstance(episode["revision_sha256"], str) or not _HEX.fullmatch(episode["revision_sha256"])
                    or not isinstance(episode["claim_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", episode["claim_id"])):
                raise CommandError("invalid_report_identity", "Supply an exact source-scoped episode reference")
    if action in GENERATION_ACTIONS:
        for key in ("brief_id", "brief_sha256"):
            if not isinstance(payload[key], str) or not _HEX.fullmatch(payload[key]):
                raise CommandError("invalid_generation_identity", "Supply exact retained brief identities")
        if type(payload["expected_state_version"]) is not int or not 0 <= payload["expected_state_version"] <= 9007199254740991:
            raise CommandError("invalid_state_version", "Supply the exact authority version")
    if action in CANDIDATE_ACTIONS:
        for key in ("admission_input_id", "admission_input_sha256", "candidate_id", "check_set_id", "expected_completion_sha256"):
            if key in payload and (not isinstance(payload[key], str) or not _HEX.fullmatch(payload[key])):
                raise CommandError("invalid_candidate_identity", "Supply exact retained candidate identities")
        if payload.get("origin_kind") == "synchronous_writer_v1" and (not isinstance(payload["generation_id"], str) or not re.fullmatch(r"gss_[0-9a-f]{64}", payload["generation_id"])):
            raise CommandError("invalid_candidate_identity", "Supply the exact synchronous generation identity")
        for key in (() if "origin_kind" in payload else ("job_id", "custom_id")):
            if not isinstance(payload[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", payload[key]):
                raise CommandError("invalid_candidate_identity", "Supply bounded retained candidate identifiers")
        if type(payload["expected_state_version"]) is not int or not 0 <= payload["expected_state_version"] <= 9007199254740991:
            raise CommandError("invalid_state_version", "Supply the exact safe authority version")
    if "text" in payload:
        _string(payload["text"], "Draft text", 280)
    if "reason" in payload:
        _string(payload["reason"], "Reason", 2000)
    if "expected_policy_sha256" in payload and (not isinstance(payload["expected_policy_sha256"], str) or not _HEX.fullmatch(payload["expected_policy_sha256"])):
        raise CommandError("editorial_policy_unverified", "Supply the exact policy fingerprint shown during review")
    if action == "record_review" and payload["confirmed"] is not True:
        raise CommandError("review_confirmation_required", "Confirm review against the exact source evidence")
    if action in MEDIA_ACTIONS | EDITOR_MEDIA_ACTIONS:
        for key in ("proposal_sha256", "expected_proposal_sha256", "expected_packet_sha256", "expected_renderer_profile_sha256", "expected_review_sha256", "expected_check_completion_sha256"):
            if key in payload and (not isinstance(payload[key], str) or not _HEX.fullmatch(payload[key])):
                raise CommandError("invalid_media_identity", "Supply exact lowercase media fingerprints")
        if action in {"attach_media_revision", "review_media_revision"}:
            # Local import avoids the joint-review module's Principal dependency.
            from src.media.joint_review import validate_joint_review_payload
            try:
                review = validate_joint_review_payload(payload["review"])
            except ValueError:
                raise CommandError("invalid_media_review", "Supply a complete explicit joint review") from None
            if review["decision"] != "accept":
                raise CommandError("media_acceptance_required", "Attachment requires explicit joint acceptance")
        elif action == "remove_media_revision" and payload["confirmed"] is not True:
            raise CommandError("media_removal_confirmation_required", "Confirm removal of the exact graphic revision")
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
    def from_request(cls, body: Any, principal: Principal, *, environment: str, now: datetime, allow_legacy_review: bool = False) -> Command:
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
        if action in SOURCE_ACTIONS and expires > requested + timedelta(minutes=10):
            raise CommandError("invalid_time", "Source commands expire within ten minutes")
        rows = body["targets"]
        if not isinstance(rows, list) or (rows != [] if action in SOURCE_ACTIONS | CANDIDATE_ACTIONS | GENERATION_ACTIONS | REPORT_ACTIONS | COVERAGE_ACTIONS else not 1 <= len(rows) <= MAX_TARGETS or (action != "bulk_reject" and len(rows) != 1)):
            raise CommandError("invalid_targets", "Supply one target, or an explicit bounded set for bulk rejection")
        targets = tuple(DraftTarget.parse(row) for row in rows)
        if len({row.draft_id for row in targets}) != len(targets):
            raise CommandError("invalid_targets", "Duplicate draft targets are not allowed")
        return cls(command_id, action, environment, principal.subject, principal.authentication_context,
                   body["requested_at"], body["expires_at"], targets, _validate_payload(action, body["payload"], allow_legacy_review=allow_legacy_review))

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
        if row.get("action") == "abandon_submission":
            from src.commands.submission_recovery import stored
            return stored(row)
        request = {key: row[key] for key in ("command_id", "action", "requested_at", "expires_at", "targets", "payload") if key in row}
        principal = Principal(_string(row.get("actor_subject"), "Subject", 200), "publisher",
                              _string(row.get("authentication_context"), "Authentication context", 200))
        environment = _string(row.get("environment"), "Environment", 10)
        parsed = cls.from_request(request, principal, environment=environment, now=utc_datetime(row.get("requested_at")), allow_legacy_review=True)
        if parsed.as_dict() != row:
            raise CommandError("invalid_journal", "Stored envelope contains unexpected fields")
        return parsed
