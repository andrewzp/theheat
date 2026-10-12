"""Local-only terminal absence records; never a normal mutation command."""
from datetime import timedelta
import hashlib
import re

from src.commands.schema import Command, CommandError, Principal, canonical_json, utc_datetime, utc_text

ACTION = "abandon_submission"
# Deliberately excludes itself and actions unavailable through local ingress.
ORIGINAL_ACTIONS = frozenset({"edit_revision", "record_review", "approve_revision", "reject_revision",
    "cancel_approval", "select_candidate", "request_candidate_checks", "admit_checked_candidate",
    "request_sourced_generation", "prepare_media_revision", "attach_media_revision", "review_media_revision",
    "remove_media_revision", "request_revision_checks", "approve_media_revision"})
REQUEST_FIELDS = ("command_id", "action", "requested_at", "expires_at", "targets", "payload")


def reference(value):
    if (type(value) is not dict or set(value) != {"action", "original_action", "request_sha256"}
        or value["action"] != ACTION or type(value["original_action"]) is not str
        or value["original_action"] not in ORIGINAL_ACTIONS or type(value["request_sha256"]) is not str
        or not re.fullmatch(r"[a-f0-9]{64}", value["request_sha256"])):
        raise CommandError("invalid_submission_reference", "Supply the original action and exact request fingerprint")
    return {key:value[key] for key in ("original_action", "request_sha256")}


def request(command):
    return {key:command.as_dict()[key] for key in REQUEST_FIELDS}


def request_sha(command):
    return hashlib.sha256(canonical_json(request(command)).encode()).hexdigest()


def stored(row):
    """Read only this immutable bookkeeping shape; ingress never calls it."""
    from uuid import UUID
    try:
        fields = {"schema_version", "environment", "actor_subject", "authentication_context", *REQUEST_FIELDS}
        if (type(row) is not dict or set(row) != fields or row["schema_version"] != 1
            or type(row["schema_version"]) is not int or row["environment"] != "local"
            or row["action"] != ACTION or row["targets"] != [] or str(UUID(row["command_id"])) != row["command_id"]):
            raise ValueError()
        payload = reference({"action":ACTION, **row["payload"]})
        if payload != row["payload"]:
            raise ValueError()
        at = utc_datetime(row["requested_at"])
        if utc_text(at) != row["requested_at"] or utc_text(at + timedelta(minutes=5)) != row["expires_at"]:
            raise ValueError()
        principal = Principal(row["actor_subject"], "editor", row["authentication_context"])
        return Command(row["command_id"], ACTION, "local", principal.subject, principal.authentication_context,
                       row["requested_at"], row["expires_at"], (), canonical_json(payload))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise CommandError("invalid_journal", "Invalid local submission closure") from None


def make(command_id, payload, principal, now):
    at = utc_text(now)
    return stored(dict(schema_version=1, command_id=command_id, action=ACTION, environment="local",
        actor_subject=principal.subject, authentication_context=principal.authentication_context,
        requested_at=at, expires_at=utc_text(now+timedelta(minutes=5)), targets=[], payload=payload))
