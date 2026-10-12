"""Fixed required-check provenance dispatch; shape validation is not authority."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import re

from src.commands.schema import DraftTarget, canonical_json, utc_datetime
from src.editorial.revisions import decision_revision, draft_identity, fingerprint, text_hash
from src.two_bot import candidate_derivation as candidate

ORIGIN = "saved_draft_revision_v1"
NAMESPACE = "draft-check-enrollment-v1"
SOURCE_NAMESPACE = "draft-source-origin-v1"
FIELDS = {"schema_version", "origin_kind", "enrollment_id", "draft_target", "final_text", "text_sha256",
          "state_version", "state_sha256", "source_origin", "current_context", "source_useful_until",
          "provenance_useful_until", "useful_until", "policy", "bundle", "memory", "required_stages",
          "checker_state", "checker_state_sha256", "check_date", "captured_at", "renderer_profile_sha256", "media"}
KEY_FIELDS = {"origin_kind", "draft_target", "state_version", "state_sha256", "source_origin",
              "current_context", "source_useful_until", "provenance_useful_until", "useful_until",
              "renderer_profile_sha256", "media", "check_date"}
EXECUTABLE = frozenset({"verified_current_formatter", "verified_saved_draft_revision", "verified_synchronous_writer"})


def require(value, code):
    if not value:
        raise ValueError(code)


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value), "invalid_revision_check_hash")


def raw_sha(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def enrollment_id(packet):
    return fingerprint({key: packet[key] for key in KEY_FIELDS})


def validate_revision(packet):
    require(type(packet) is dict and set(packet) == FIELDS, "invalid_revision_check_packet")
    require(type(packet["schema_version"]) is int and packet["schema_version"] == 3
            and packet["origin_kind"] == ORIGIN, "invalid_revision_check_origin")
    target = DraftTarget.parse(packet["draft_target"])
    require(type(packet["state_version"]) is int and 0 <= packet["state_version"] <= 2**53-1,
            "invalid_revision_check_state")
    for key in ("enrollment_id", "text_sha256", "state_sha256", "checker_state_sha256", "renderer_profile_sha256"):
        sha(packet[key])
    source = packet["source_origin"]
    require(type(source) is dict and set(source) == {"namespace", "snapshot_id", "canonical_sha256"}
            and source["namespace"] == SOURCE_NAMESPACE, "invalid_revision_source_origin")
    sha(source["snapshot_id"])
    sha(source["canonical_sha256"])
    context = packet["current_context"]
    require(type(context) is dict and set(context) == {"bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch"}
            and context["publication_epoch"] == "local-preview-paused-v1", "invalid_revision_check_context")
    for key in ("bundle", "memory", "checker_state"):
        require(type(packet[key]) is dict and len(canonical_json(packet[key]).encode()) <= 2_000_000,
                "invalid_revision_check_input")
        expected = packet["checker_state_sha256"] if key == "checker_state" else context[key + "_sha256"]
        require(fingerprint(packet[key]) == expected, "changed_revision_check_input")
    require(type(packet["policy"]) is dict and fingerprint(packet["policy"]) == context["policy_sha256"],
            "changed_revision_check_policy")
    require(raw_sha(packet["checker_state"]) == packet["state_sha256"], "changed_revision_check_state")
    drafts = packet["checker_state"].get("drafts")
    require(type(drafts) is list, "invalid_revision_check_state")
    matches = [d for d in drafts if type(d) is dict and d.get("id") == target.draft_id]
    require(len(matches) == 1, "invalid_revision_check_draft")
    draft = matches[0]
    identity = dict(draft_id=draft["id"], **draft_identity(draft), decision_revision=decision_revision(draft))
    require(canonical_json(identity) == canonical_json(target.as_dict())
            and packet["final_text"] == draft.get("text")
            and isinstance(packet["final_text"], str) and 0 < len(packet["final_text"]) <= 280
            and text_hash(packet["final_text"]) == packet["text_sha256"] == target.text_sha256,
            "changed_revision_check_text")
    bundle = draft.get("review_context", {}).get("two_bot", {}).get("bundle")
    require(canonical_json(bundle) == canonical_json(packet["bundle"]), "changed_revision_check_bundle")
    media = packet["media"]
    require(type(media) is dict and set(media) == {"proposal_sha256", "packet_sha256", "review_sha256", "review_command_id"},
            "invalid_revision_check_media")
    for key in ("proposal_sha256", "packet_sha256", "review_sha256"):
        sha(media[key])
    review = draft.get("media_review_binding")
    require(type(review) is dict and review.get("command_id") == media["review_command_id"]
            and all(review.get(k) == media[k] for k in ("proposal_sha256", "packet_sha256", "review_sha256")),
            "changed_revision_check_review")
    require(packet["required_stages"] == ["deterministic", "safety", "fact_check", "critic"], "missing_revision_check_stage")
    captured = utc_datetime(packet["captured_at"])
    require(packet["check_date"] == captured.date().isoformat(), "changed_revision_check_day")
    deadline = min(utc_datetime(packet["source_useful_until"]), utc_datetime(packet["provenance_useful_until"]),
                   captured.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    require(captured < utc_datetime(packet["useful_until"]) == deadline, "invalid_revision_check_deadline")
    require(enrollment_id(packet) == packet["enrollment_id"], "changed_revision_check_enrollment")
    return "verified_saved_draft_revision"


def packet_verification(packet):
    if type(packet) is dict and type(packet.get("schema_version")) is int and packet["schema_version"] == 4:
        from src.two_bot.synchronous_origin import validate
        return validate(packet)
    if type(packet) is dict and type(packet.get("schema_version")) is int and packet["schema_version"] == 3:
        return validate_revision(packet)
    return candidate.packet_verification(packet)


def checked_text(packet):
    result = packet_verification(packet)
    require(result in EXECUTABLE, result)
    if result == "verified_synchronous_writer":
        return packet["derivation"]["final_text"]
    return packet["final_text"] if result == "verified_saved_draft_revision" else candidate.checked_text(packet)


def spending_job(packet):
    if packet.get("schema_version") == 4:
        return packet["generation_id"]
    return "draftcheck_" + packet["enrollment_id"] if packet.get("schema_version") == 3 else packet["job_id"]
