"""Keep provider output separate from the exact, deterministically checked text.

Retained hashes prove binding, not formatter execution or scientific truth. Only
trusted current source can recompute a derivation; old code is never loaded.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields
import json
import re

from src.editorial.policy import source_manifest, valid_policy
from src.editorial.revisions import fingerprint, text_hash
from src.two_bot.source_links import format_source_link
from src.two_bot.types import RelatedSignal, StoryBundle, WriterResult

MAX_INPUT_BYTES = 2_000_000
MAX_DERIVATION_BYTES = 8192
_FIELDS = {"schema_version", "raw_candidate_id", "raw_candidate_sha256", "bundle_sha256",
           "policy_sha256", "formatter", "final_text", "text_sha256"}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _bounded(value: object, limit: int) -> None:
    try:
        fingerprint(value)
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
        _require(len(raw) <= limit, "derivation_input_too_large")
    except (TypeError, UnicodeError, OverflowError, RecursionError):
        raise ValueError("invalid_derivation_json") from None


def _sha(value: object) -> None:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
             "invalid_derivation_hash")


def retained_bundle(value: dict) -> StoryBundle:
    """Refuse silent constructor/default/projection repair of retained evidence."""
    _bounded(value, MAX_INPUT_BYTES)
    try:
        data = deepcopy(value)
        if "related_signals" in data:
            data["related_signals"] = [RelatedSignal(**item) for item in data["related_signals"]]
        bundle = StoryBundle(**data)
    except (TypeError, ValueError, KeyError, AttributeError):
        raise ValueError("invalid_derivation_bundle") from None
    _require(fingerprint(bundle.to_dict()) == fingerprint(value),
             "retained_check_input_roundtrip_changed")
    return bundle


def formatter_identity() -> dict:
    # Use the existing conservative full-source boundary, including dependencies.
    # A caller-supplied hash cannot select or install an implementation.
    return dict(name="cyclone-source-link", version=1,
                source_sha256=source_manifest()["source_sha256"])


def _inputs(candidate: dict, candidate_id: str, bundle: dict, policy: dict) -> None:
    _sha(candidate_id)
    _require(isinstance(candidate, dict) and isinstance(bundle, dict), "invalid_derivation_input")
    _bounded(candidate, MAX_INPUT_BYTES)
    _bounded(bundle, MAX_INPUT_BYTES)
    _require(valid_policy(policy), "invalid_derivation_policy")
    tweet = candidate.get("tweet")
    _require(isinstance(tweet, str) and bool(tweet.strip()) and len(tweet) <= 280,
             "invalid_derivation_candidate")


def derive_candidate(candidate: dict, candidate_id: str, bundle: dict, policy: dict) -> dict:
    """Build from an independently retained raw result, without mutating it."""
    _inputs(candidate, candidate_id, bundle, policy)
    _require(set(candidate) == {f.name for f in fields(WriterResult)}, "invalid_derivation_candidate")
    try:
        writer = WriterResult(**deepcopy(candidate))
        writer.validate_model_output()
    except (TypeError, ValueError, KeyError, AttributeError):
        raise ValueError("invalid_derivation_candidate") from None
    _require(fingerprint(asdict(writer)) == fingerprint(candidate), "changed_derivation_candidate")
    identity = formatter_identity()
    _require(policy["source_sha256"] == identity["source_sha256"], "formatter_unavailable")
    final = format_source_link(candidate["tweet"], retained_bundle(bundle))
    result = dict(schema_version=1, raw_candidate_id=candidate_id,
                  raw_candidate_sha256=fingerprint(candidate), bundle_sha256=fingerprint(bundle),
                  policy_sha256=fingerprint(policy), formatter=identity,
                  final_text=final, text_sha256=text_hash(final))
    _bounded(result, MAX_DERIVATION_BYTES)
    return result


def inspect_derivation(derivation: dict, candidate: dict, candidate_id: str,
                       bundle: dict, policy: dict) -> str:
    """Verify bindings; explicitly withhold recomputation for unavailable code."""
    _inputs(candidate, candidate_id, bundle, policy)
    _bounded(derivation, MAX_DERIVATION_BYTES)
    _require(isinstance(derivation, dict) and set(derivation) == _FIELDS, "invalid_derivation_fields")
    _require(type(derivation["schema_version"]) is int and derivation["schema_version"] == 1,
             "invalid_derivation_schema")
    formatter = derivation["formatter"]
    _require(isinstance(formatter, dict) and set(formatter) == {"name", "version", "source_sha256"},
             "invalid_derivation_formatter")
    _require(isinstance(formatter["name"], str) and 0 < len(formatter["name"]) <= 80
             and type(formatter["version"]) is int and 0 < formatter["version"] <= 255,
             "invalid_derivation_formatter")
    _sha(formatter["source_sha256"])
    for key in ("raw_candidate_id", "raw_candidate_sha256", "bundle_sha256", "policy_sha256", "text_sha256"):
        _sha(derivation[key])
    final = derivation["final_text"]
    _require(isinstance(final, str) and bool(final.strip()) and len(final) <= 280,
             "invalid_derived_text")
    _require(derivation["raw_candidate_id"] == candidate_id
             and derivation["raw_candidate_sha256"] == fingerprint(candidate)
             and derivation["bundle_sha256"] == fingerprint(bundle)
             and derivation["policy_sha256"] == fingerprint(policy)
             and formatter["source_sha256"] == policy["source_sha256"]
             and derivation["text_sha256"] == text_hash(final), "changed_derivation_binding")
    try:
        current = formatter_identity()
    except (OSError, ValueError, UnicodeError):
        return "formatter_unavailable"
    if formatter != current:
        return "formatter_unavailable"
    expected = derive_candidate(candidate, candidate_id, bundle, policy)
    _require(fingerprint(expected) == fingerprint(derivation), "changed_derived_text")
    return "verified_current_formatter"


def packet_verification(packet: dict) -> str:
    """History remains readable but never supplies an implicit text fallback."""
    version = packet.get("schema_version")
    _require(type(version) is int and version in (1, 2), "unsupported_check_packet")
    if version == 1:
        _require("derivation" not in packet and "derivation_id" not in packet,
                 "invalid_legacy_check_packet")
        _require(text_hash(packet["candidate"]["tweet"]) == packet["text_sha256"],
                 "changed_legacy_check_text")
        return "legacy_check_packet"
    result = inspect_derivation(packet["derivation"], packet["candidate"], packet["candidate_id"],
                                packet["bundle"], packet["policy"])
    _sha(packet["derivation_id"])
    _require(fingerprint(packet["derivation"]) == packet["derivation_id"]
             and packet["text_sha256"] == packet["derivation"]["text_sha256"],
             "changed_derivation_identity")
    return result


def checked_text(packet: dict) -> str:
    verification = packet_verification(packet)
    _require(verification == "verified_current_formatter", verification)
    return packet["derivation"]["final_text"]
