"""Pure, explicit joint-review decisions; no authentication or posting approval.

The caller authenticates reviewers and supplies independent current inputs. A
readback additionally needs the decision fingerprint from trusted retention, not
from the submitted record. Hashes bind bytes, not identity or human attention.
No provider, clock, filesystem, state mutation or production attachment is used.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from src.commands.schema import Principal, utc_datetime
from src.editorial.revisions import draft_identity, fingerprint
from src.media.review_packet import MediaReviewError, build_media_review_packet
from src.media.published_radar import EXTRA_CONFIRMATIONS
from src.media.platform_description import CONFIRMATION

CONFIRMATIONS = frozenset({
    "text_matches_data", "graphic_matches_data", "text_graphic_agree",
    "qualifications_visible", "alt_text_agrees",
})
MAX_REVIEW_BYTES = 128 * 1024
_SHA = re.compile(r"[a-f0-9]{64}")
_BODY_KEYS = {
    "schema_version", "reviewed_at", "reviewer", "decision", "confirmations",
    "reason", "packet", "synthetic", "publication_approved",
    "production_attachment_authorized",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MediaReviewError(message)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _encoded(value: dict) -> bytes:
    # Unlike Python equality and the shared cross-language numeric fingerprint,
    # this comparison distinguishes JSON integer/float substitutions as well.
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _object(value: Any) -> dict:
    _require(isinstance(value, dict), "Review must be a JSON object")
    _require(len(_encoded(value)) <= MAX_REVIEW_BYTES, "Review exceeds its byte bound")
    fingerprint(value)  # Reject non-string keys and non-JSON values.
    return deepcopy(value)


def _principal(value: Any) -> Principal:
    _require(isinstance(value, Principal), "A trusted caller principal is required")
    # Revalidate fields without deriving identity or permission from request JSON.
    checked = Principal(value.subject, value.role, value.authentication_context)
    _require(checked.role in {"editor", "publisher"}, "Reviewer permission is unavailable")
    return checked


def _payload(value: Any) -> dict:
    payload = _object(value)
    _require(
        set(payload) in ({"decision", "confirmations", "reason"},
            {"decision", "confirmations", "reason", "expected_platform_description_sha256"}),
        "Review payload fields differ from the contract",
    )
    _require(
        isinstance(payload["decision"], str)
        and payload["decision"] in {"accept", "reject", "needs_changes"},
        "Review decision is invalid",
    )
    checks = payload["confirmations"]
    _require(
        isinstance(checks, dict) and set(checks) in (CONFIRMATIONS, CONFIRMATIONS | EXTRA_CONFIRMATIONS,
            CONFIRMATIONS | {CONFIRMATION}, CONFIRMATIONS | EXTRA_CONFIRMATIONS | {CONFIRMATION})
        and all(value is None or type(value) is bool for value in checks.values()),
        "Supply each explicit joint-review confirmation",
    )
    _require(
        payload["decision"] != "accept" or all(value is True for value in checks.values()),
        "Acceptance requires all joint-review confirmations",
    )
    reason = payload["reason"]
    extended = "expected_platform_description_sha256" in payload
    _require((CONFIRMATION in checks) == extended and (not extended or _sha(payload["expected_platform_description_sha256"])),
             "Supply the exact platform description shown during review")
    _require(
        isinstance(reason, str) and bool(reason.strip()) and len(reason) <= 2000,
        "Review reason must be nonempty text within 2000 characters",
    )
    return payload


def validate_joint_review_payload(value: Any) -> dict:
    """The shared explicit decision contract, detached from caller-owned input."""
    try:
        return _payload(value)
    except MediaReviewError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MediaReviewError("Malformed joint-review payload") from None


def _body(packet: dict, payload: dict, principal: Principal, reviewed_at: str, platform_description=None) -> dict:
    utc_datetime(reviewed_at)
    body = {
        "schema_version": 3 if platform_description is not None else packet["schema_version"],
        "reviewed_at": reviewed_at,
        "reviewer": {
            "subject": principal.subject, "role_at_review": principal.role,
            "authentication_context": principal.authentication_context,
        },
        **{k:v for k,v in payload.items() if k != "expected_platform_description_sha256"},
        "packet": packet,
        "synthetic": packet["synthetic"],
        "publication_approved": False,
        "production_attachment_authorized": False,
    }
    if platform_description is not None:
        body["platform_description"] = deepcopy(platform_description)
    return body


def _record_packet(draft, packet, decision, actor, reviewed_at, expected_packet_sha256,
                   description, current_inputs):
    """Shared checks after this module has built a fresh packet in this call."""
    _require(
        packet["packet_sha256"] == expected_packet_sha256,
        "Preview changed since the requested review",
    )
    expected_checks = CONFIRMATIONS | EXTRA_CONFIRMATIONS if packet["schema_version"] == 2 else CONFIRMATIONS
    if description is not None:
        from src.media.platform_description import build
        rebuilt = build(draft, packet, description["proposal_sha256"],
            (packet["media"]["alt_text"] + "\n").encode("utf-8"), current_inputs["png_bytes"],
            description["profiles"], graphic_spec=current_inputs.get("graphic_spec"), derivation=description["derivation"])
        _require(description == rebuilt, "Platform description differs from verified source inputs")
        _require(decision.get("expected_platform_description_sha256") == description["description_sha256"]
            and description["packet_sha256"] == packet["packet_sha256"], "Platform description changed since review")
        expected_checks = expected_checks | {CONFIRMATION}
    _require(set(decision["confirmations"]) == expected_checks, "Joint confirmations differ from the media family")
    body = _object(_body(packet, decision, actor, reviewed_at, description))
    return {**body, "review_sha256": fingerprint(body)}


def record_joint_media_review(
    draft: dict, *, payload: dict, principal: Principal, reviewed_at: str,
    expected_packet_sha256: str, **current_inputs: Any,
) -> dict:
    """Bind a supplied decision to the exact independently rebuilt preview.

    expected_packet_sha256 is the package shown during review. The principal is
    trusted caller context, never decoded from payload. No draft approval fields
    are written. A synthetic acceptance remains an acceptance of that preview.
    """
    try:
        actor, decision = _principal(principal), _payload(payload)
        _require(_sha(expected_packet_sha256), "Expected packet fingerprint is invalid")
        description = current_inputs.pop("platform_description", None)
        packet = build_media_review_packet(draft, **current_inputs)
        return _record_packet(draft, packet, decision, actor, reviewed_at, expected_packet_sha256,
                              description, current_inputs)
    except MediaReviewError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MediaReviewError("Malformed joint-review input") from None


def _record_joint_media_review_with_description(
    draft, *, payload, principal, reviewed_at, expected_packet_sha256,
    editorial_policy, graphic_spec, renderer_manifest, png_bytes,
    proposal_sha256, raw_alt, platform_profiles, derivation=None,
):
    """Build the exact attach description and review together; accept no packet.

    Description validation precedes review validation just as in the two public
    calls. The packet is local to this pure call; no retained proof is reused.
    """
    from src.media.platform_description import build
    current_inputs = dict(expected_draft_identity=draft_identity(draft), editorial_policy=editorial_policy,
                          graphic_spec=graphic_spec, renderer_manifest=renderer_manifest, png_bytes=png_bytes)
    packet = build_media_review_packet(draft, **current_inputs)
    description = build(draft, packet, proposal_sha256, raw_alt, png_bytes, platform_profiles,
                        graphic_spec=graphic_spec, derivation=derivation)
    try:
        actor, decision = _principal(principal), _payload(payload)
        _require(_sha(expected_packet_sha256), "Expected packet fingerprint is invalid")
        return _record_packet(draft, packet, decision, actor, reviewed_at, expected_packet_sha256,
                              description, current_inputs)
    except MediaReviewError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise MediaReviewError("Malformed joint-review input") from None


def joint_media_review_status(
    record: dict, draft: dict, *, expected_review_sha256: str,
    current_principal: Principal, **current_inputs: Any,
) -> dict:
    """Recheck trusted retained decision identity, current authority and inputs.

    The expected review hash must come from separate trusted retention. A record
    with its own recomputed hash is not an authenticated decision. Refreshed login
    context may differ; the reviewer subject and current permission must remain.
    Incompatible review contracts must advance schema_version and refuse old ones.
    """
    return _joint_media_review_status(record, draft, expected_review_sha256=expected_review_sha256,
        current_principal=current_principal, current_inputs=current_inputs)


def _joint_media_review_status_with_description(
    record, draft, *, expected_review_sha256, current_principal, editorial_policy,
    graphic_spec, renderer_manifest, png_bytes, proposal_sha256, raw_alt, platform_profiles,
):
    """Build a fresh description and status for the same current draft inputs.

    Accept raw inputs only, never a supplied packet or status. As in the two
    independent public calls, description validation precedes retained review
    and current principal checks. Parked decision transitions use separate calls.
    """
    current_inputs = dict(expected_draft_identity=draft_identity(draft), editorial_policy=editorial_policy,
                          graphic_spec=graphic_spec, renderer_manifest=renderer_manifest, png_bytes=png_bytes)
    return _joint_media_review_status(record, draft, expected_review_sha256=expected_review_sha256,
        current_principal=current_principal, current_inputs=current_inputs,
        description_inputs=(proposal_sha256, raw_alt, platform_profiles))


def _joint_media_review_status(record, draft, *, expected_review_sha256, current_principal,
                              current_inputs, description_inputs=None):
    # Only the paired raw-input entry point builds here. Public status retains
    # its original ordering: verify record and reviewer before building a packet.
    if description_inputs is not None:
        from src.media.platform_description import build
        proposal_sha256, raw_alt, platform_profiles = description_inputs
        packet = build_media_review_packet(draft, **current_inputs)
        description = build(draft, packet, proposal_sha256, raw_alt, current_inputs["png_bytes"],
                            platform_profiles, graphic_spec=current_inputs["graphic_spec"])
    result = {
        "status": "invalid", "current": False, "accepted": False, "synthetic": None,
        "publication_approved": False, "production_attachment_authorized": False,
    }
    try:
        checked = _object(record)
        keys = _BODY_KEYS | ({"platform_description"} if checked.get("schema_version") == 3 else set())
        _require(set(checked) == keys | {"review_sha256"}, "Invalid review fields")
        body = {key: checked[key] for key in keys}
        _require(
            _sha(expected_review_sha256) and _sha(checked["review_sha256"])
            and fingerprint(body) == checked["review_sha256"] == expected_review_sha256,
            "Review differs from the trusted retained decision",
        )
        _require(
            type(body["schema_version"]) is int and (body["schema_version"] == 3 or
                body["schema_version"] in (1, 2) and body["schema_version"] == body["packet"]["schema_version"]),
            "Unsupported review schema",
        )
        payload = {key: body[key] for key in ("decision", "confirmations", "reason")}
        if body["schema_version"] == 3:
            payload["expected_platform_description_sha256"] = body["platform_description"]["description_sha256"]
        decision = _payload(payload)
        expected_checks = CONFIRMATIONS | EXTRA_CONFIRMATIONS if body["packet"]["schema_version"] == 2 else CONFIRMATIONS
        if body["schema_version"] == 3:
            expected_checks = expected_checks | {CONFIRMATION}
        _require(set(decision["confirmations"]) == expected_checks, "Joint confirmations differ from the media family")
        provenance = body["reviewer"]
        _require(
            isinstance(provenance, dict)
            and set(provenance) == {"subject", "role_at_review", "authentication_context"},
            "Invalid reviewer provenance",
        )
        # This validates retained shape only. Current caller authority is checked
        # separately below; a retained role does not grant current permission.
        original = _principal(Principal(
            provenance["subject"], provenance["role_at_review"],
            provenance["authentication_context"],
        ))
        canonical = _body(body["packet"], decision, original, body["reviewed_at"], body.get("platform_description"))
        _require(type(body["synthetic"]) is bool, "Invalid synthetic marker")
        _require(_encoded(canonical) == _encoded(body), "Invalid review metadata")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return result
    result["synthetic"] = body["synthetic"]
    try:
        actor = _principal(current_principal)
        _require(actor.subject == original.subject, "Reviewer identity differs")
    except (ValueError, TypeError, AttributeError):
        return {**result, "status": "reviewer_unavailable"}
    try:
        if description_inputs is None:
            description = current_inputs.pop("platform_description", None)
        _require(body.get("platform_description") == description, "Platform description review is obsolete")
        if description_inputs is None:
            packet = build_media_review_packet(draft, **current_inputs)
        # Rebuild from current evidence, never using the retained packet as input.
        _require(_encoded(body["packet"]) == _encoded(packet), "Review is obsolete")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return {**result, "status": "obsolete"}
    return {
        **result,
        "status": {"accept": "accepted", "reject": "rejected", "needs_changes": "needs_changes"}[
            body["decision"]
        ],
        "current": True, "accepted": body["decision"] == "accept",
        "synthetic": packet["synthetic"],
    }
