"""Pure synchronous check provenance. Structural validity grants no authority."""
from datetime import timedelta
import re

from src.commands.schema import canonical_json, utc_datetime
from src.editorial.revisions import fingerprint
from src.two_bot import candidate_derivation as derivation
from src.two_bot.check_origin import require, sha, raw_sha

ORIGIN = "synchronous_writer_v1"
NAMESPACE = "synchronous-check-enrollment-v1"
REFERENCES = {"generation_id", "grant_id", "observation_sha256", "resolution_sha256", "request_sha256", "candidate_id"}
FIELDS = REFERENCES | {"schema_version", "origin_kind", "enrollment_id", "candidate", "derivation", "derivation_id",
    "text_sha256", "current_context", "useful_until", "policy", "bundle", "memory", "required_stages", "checker_state",
    "checker_state_sha256", "state_sha256", "state_version", "check_date", "captured_at", "admission_input_id", "admission_input_sha256"}
KEY_FIELDS = FIELDS - {"enrollment_id", "candidate", "bundle", "memory", "checker_state", "policy", "captured_at"}


def enrollment_id(packet):
    return fingerprint({key: packet[key] for key in KEY_FIELDS})


def validate(packet, *, resolved=None):
    require(type(packet) is dict and set(packet) == FIELDS and type(packet["schema_version"]) is int
        and packet["schema_version"] in (4, 5) and packet["origin_kind"] == ORIGIN, "invalid_sync_check_packet")
    require(type(packet["generation_id"]) is str and re.fullmatch(r"gss_[0-9a-f]{64}", packet["generation_id"]), "invalid_sync_generation")
    for key in REFERENCES - {"generation_id"} | {"enrollment_id", "derivation_id", "text_sha256", "checker_state_sha256",
            "state_sha256", "admission_input_id", "admission_input_sha256"}:
        sha(packet[key])
    require(type(packet["state_version"]) is int and 0 <= packet["state_version"] <= 2**53-1, "invalid_sync_state")
    context = packet["current_context"]
    require(type(context) is dict and set(context) == {"bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch"}
        and context["publication_epoch"] == "local-preview-paused-v1", "invalid_sync_context")
    for key in ("bundle", "memory", "checker_state"):
        require(type(packet[key]) is dict and len(canonical_json(packet[key]).encode()) <= 2_000_000, "invalid_sync_check_input")
        require(fingerprint(packet[key]) == (packet["checker_state_sha256"] if key == "checker_state" else context[key+"_sha256"]),
            "changed_sync_check_input")
    require(raw_sha(packet["checker_state"]) == packet["state_sha256"] and fingerprint(packet["policy"]) == context["policy_sha256"],
        "changed_sync_check_policy_state")
    candidate_id = fingerprint(dict(origin_kind=ORIGIN, generation_id=packet["generation_id"], grant_id=packet["grant_id"],
        observation_sha256=packet["observation_sha256"], candidate=packet["candidate"]))
    require(candidate_id == packet["candidate_id"], "changed_sync_candidate")
    ghcn = packet["schema_version"] == 5
    require(derivation.has_ghcn_reference(packet["bundle"]) == ghcn, "invalid_sync_check_bundle_version")
    if ghcn:
        from src.two_bot.ghcn_claim_view import structural_view
        structural_view(packet["bundle"])
    verification = derivation.inspect_derivation(packet["derivation"], packet["candidate"], candidate_id,
        packet["bundle"], packet["policy"], resolved=resolved)
    require(verification in {"verified_current_formatter", "retained_ghcn_derivation"}, verification)
    require(fingerprint(packet["derivation"]) == packet["derivation_id"]
        and packet["derivation"]["text_sha256"] == packet["text_sha256"], "changed_sync_derivation")
    require(packet["required_stages"] == ["deterministic", "safety", "fact_check", "critic"], "missing_sync_check_stage")
    captured = utc_datetime(packet["captured_at"])
    require(packet["check_date"] == captured.date().isoformat() and captured < utc_datetime(packet["useful_until"])
        <= captured.replace(hour=0, minute=0, second=0, microsecond=0)+timedelta(days=1), "invalid_sync_check_window")
    require(enrollment_id(packet) == packet["enrollment_id"], "changed_sync_enrollment")
    return "retained_synchronous_writer" if verification == "retained_ghcn_derivation" else "verified_synchronous_writer"
