"""Bind editorial decisions to exact draft text and evidence.

The equivalent JavaScript contract lives in dashboard/lib/draft-revisions.js.
These fingerprints detect stale decisions; they are not a storage lock.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import struct
import threading
from typing import Any

from src.editorial.publication import automatic_publication_policy, valid_epoch


def _canonical(value: Any) -> Any:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Revision evidence must contain finite numbers")
        # JSON numbers share one IEEE-754 representation across Python and JS.
        return ["number", struct.pack(">d", 0.0 if number == 0 else number).hex()]
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, list):
        return ["array", [_canonical(item) for item in value]]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return ["object", [
            [key, _canonical(value[key])]
            for key in sorted(value, key=lambda key: key.encode("utf-8"))
        ]]
    raise ValueError("Revision evidence must be JSON data")


def _fingerprint_value(value: Any) -> str:
    payload = json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _RetainedFingerprints:
    """Only pure digests of exact values within ONE retained review read."""
    def __init__(self):
        self.thread = threading.get_ident()
        self.open = True
        self.entries: dict[bytes, str] = {}
        self.byte_count = 0
        self.implementation: tuple | None = None

    def close(self):
        self.open = False
        self.entries.clear()
        self.byte_count = 0


_RETAINED_FINGERPRINTS: ContextVar[_RetainedFingerprints | None] = ContextVar(
    "retained_review_fingerprints", default=None)


@contextmanager
def _retained_fingerprint_scope():
    calculation = _RetainedFingerprints()
    token = _RETAINED_FINGERPRINTS.set(calculation)
    try:
        yield
    finally:
        calculation.close()
        _RETAINED_FINGERPRINTS.reset(token)


def _fingerprint_json(value):
    if type(value) is dict:
        return all(type(k) is str and _fingerprint_json(v) for k, v in value.items())
    if type(value) is list:
        return all(_fingerprint_json(v) for v in value)
    return type(value) in (str, int, float, bool, type(None))


def _fingerprint_key(value):
    try:
        # This lane serves retained graphic/source data, not small identity,
        # role, policy, approval or completed-check records.
        if type(value) is not dict or not any(k in value for k in (
            "evidence", "input_binding", "raw_signal_dump", "historical_context",
            "variables", "proposed_draft", "review_context")):
            return None
        if not _fingerprint_json(value):
            return None
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        # Small values retain the ordinary path. Exact bytes deliberately keep
        # Python numeric types distinct, even where the final digest coalesces.
        return raw if 4096 <= len(raw) <= 1_000_000 else None
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return None  # Preserve the original error and its precedence below.


def fingerprint(value: Any) -> str:
    calculation = _RETAINED_FINGERPRINTS.get()
    if calculation is None or not calculation.open or calculation.thread != threading.get_ident():
        return _fingerprint_value(value)
    implementation = (_fingerprint_value, _canonical, json.dumps, json.JSONEncoder,
        json.JSONEncoder.encode, json.JSONEncoder.iterencode, hashlib.sha256, struct.pack,
        math.isfinite)
    if calculation.implementation != implementation:
        calculation.entries.clear()
        calculation.byte_count = 0
        calculation.implementation = implementation
    key = _fingerprint_key(value)
    if key is not None and key in calculation.entries:
        return calculation.entries[key]
    result = _fingerprint_value(value)
    if (key is not None and len(calculation.entries) < 16
            and calculation.byte_count + len(key) + 64 <= 2_000_000
            and _fingerprint_key(value) == key):
        calculation.entries[key] = result
        calculation.byte_count += len(key) + 64
    return result


def text_hash(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Draft text must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evidence_payload(draft: dict) -> dict:
    review = deepcopy(draft.get("review_context"))
    if isinstance(review, dict):
        two_bot = review.pop("two_bot", None)
        if isinstance(two_bot, dict) and "bundle" in two_bot:
            review["two_bot"] = {"bundle": two_bot["bundle"]}
    payload = {
        "event_id": draft.get("event_id"),
        "type": draft.get("type"),
        "tweet_date": draft.get("tweet_date"),
        "review_context": review,
        "hot10_rows": draft.get("hot10_rows"),
    }
    # Preserve every legacy identity; presence (even null) is new content.
    if "media_attachment" in draft:
        payload["media_attachment"] = deepcopy(draft["media_attachment"])
    return payload


def draft_identity(draft: dict) -> dict:
    revision = draft.get("content_revision", 0)
    if type(revision) is not int or not 0 <= revision <= 9007199254740991:
        raise ValueError("Invalid content revision")
    return {
        "content_revision": revision,
        "text_sha256": text_hash(draft.get("text", "")),
        "evidence_sha256": fingerprint(_evidence_payload(draft)),
    }


def decision_revision(draft: dict) -> int:
    revision = draft.get("decision_revision", 0)
    if type(revision) is not int or not 0 <= revision < 9007199254740991:
        raise ValueError("Invalid decision revision")
    return revision


def _advance_decision(draft: dict) -> None:
    draft["decision_revision"] = decision_revision(draft) + 1


def binding_matches(draft: dict, binding: Any) -> bool:
    if not isinstance(binding, dict):
        return False
    if type(binding.get("content_revision")) is not int:
        return False
    try:
        return all(binding.get(key) == value for key, value in draft_identity(draft).items())
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False


def _two_bot(draft: dict) -> dict:
    review = draft.get("review_context")
    value = review.get("two_bot") if isinstance(review, dict) else None
    return value if isinstance(value, dict) else {}


def _checks(two_bot: dict) -> dict:
    return {"fact_check": two_bot.get("fact_check"), "critic": two_bot.get("critic")}


def required_checks_fingerprint(value: Any) -> str | None:
    """Validate the structured receipt proof; it does not itself prove a pass."""
    import re
    fields = {"schema_version", "check_set_id", "candidate_id", "derivation_id", "checker_state_sha256", "completion_sha256", "stages"}
    stages = ("deterministic", "safety", "fact_check", "critic")
    if not isinstance(value, dict) or set(value) != fields or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        return None
    def sha(item):
        return isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) is not None
    if not all(sha(value[k]) for k in fields - {"schema_version", "stages"}):
        return None
    if not isinstance(value["stages"], dict) or set(value["stages"]) != set(stages):
        return None
    for stage in stages:
        row = value["stages"][stage]
        if not isinstance(row, dict) or set(row) != {"grant_id", "request_sha256", "observation_sha256", "receipt_sha256"} or not all(sha(v) for v in row.values()):
            return None
    return fingerprint(value)


def _proof_matches(two_bot: dict, binding: dict) -> bool:
    if "required_checks_binding" not in two_bot:
        return "required_checks_sha256" not in binding
    digest = required_checks_fingerprint(two_bot["required_checks_binding"])
    return digest is not None and digest == binding.get("required_checks_sha256")


def _checks_pass(two_bot: dict) -> bool:
    return all(
        isinstance(two_bot.get(key), dict) and two_bot[key].get("passed") is True
        for key in ("fact_check", "critic")
    )


_CURRENT_POLICY = object()


def _editorial_policy(value=_CURRENT_POLICY):
    from src.editorial.policy import current_editorial_policy, valid_policy
    if value is _CURRENT_POLICY:
        return current_editorial_policy()
    return value if valid_policy(value) else None


def _policy_matches(binding, policy):
    from src.editorial.policy import valid_policy
    try:
        stored = binding.get("editorial_policy")
        return valid_policy(policy) and valid_policy(stored) and fingerprint(stored) == fingerprint(policy) == binding.get("policy_sha256")
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False


def _valid_delegation(value) -> bool:
    # Provenance references, not signatures. The trusted caller verifies actual
    # user authorization and retains the referenced evidence before recording.
    return (isinstance(value, dict)
            and set(value) == {"scope", "reviewer", "authorization_sha256", "review_receipt_sha256"}
            and value["scope"] == "one_manual_post" and value["reviewer"] == "codex"
            and all(isinstance(value[k], str) and len(value[k]) == 64
                    and all(c in "0123456789abcdef" for c in value[k])
                    for k in ("authorization_sha256", "review_receipt_sha256")))


def review_is_current(draft: dict, *, policy=_CURRENT_POLICY) -> bool:
    # Text-only reviews cannot authorize an image or silently drop it at send.
    media = "media_attachment" in draft
    binding = draft.get("review_binding")
    if media:
        try:
            from src.media.gist_media import NATIVE_KINDS, kind_of, required_attestations, validate_descriptor
            validate_descriptor(draft["media_attachment"], _two_bot(draft)["bundle"])
            if not isinstance(binding, dict) or binding.get("kind") not in ("human_media", "delegated_media") \
                    or binding.get("media_sha256") != fingerprint(draft["media_attachment"]):
                return False
            # A delegated joint review covers only a native image with no published-product attestation.
            if binding.get("kind") == "delegated_media" and (
                    kind_of(draft["media_attachment"]) not in NATIVE_KINDS
                    or required_attestations(draft["media_attachment"])
                    or not _valid_delegation(binding.get("delegation"))):
                return False
            # Published originals also need the person's exact label/context/reuse attestations.
            if binding.get("published_attestations") != _attestation_record(required_attestations(draft["media_attachment"])):
                return False
        except (ValueError, KeyError, TypeError, UnicodeError, OSError):
            return False
    if draft.get("revision_conflicts") or not isinstance(binding, dict) or not binding_matches(draft, binding):
        return False
    if not _policy_matches(binding, _editorial_policy(policy)):
        return False
    if binding.get("kind") == "human" or (media and binding.get("kind") in ("human_media", "delegated_media")):
        return True
    if binding.get("kind") == "delegated":
        return _valid_delegation(binding.get("delegation"))
    if binding.get("kind") != "model" or not _checks_pass(_two_bot(draft)):
        return False
    try:
        return _proof_matches(_two_bot(draft), binding) and binding.get("checks_sha256") == fingerprint(_checks(_two_bot(draft)))
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False


def approval_is_current(draft: dict, mode: str | None = None, *, policy=_CURRENT_POLICY) -> bool:
    binding = draft.get("approval_binding")
    policy = _editorial_policy(policy)
    if not isinstance(binding, dict) or not review_is_current(draft, policy=policy) or not binding_matches(draft, binding) or not _policy_matches(binding, policy):
        return False
    if binding.get("mode") not in ("manual", "auto"):
        return False
    if mode and binding.get("mode") != mode:
        return False
    try:
        if type(binding.get("decision_revision")) is not int or binding["decision_revision"] != decision_revision(draft):
            return False
    except ValueError:
        return False
    try:
        if (draft["review_binding"].get("kind") in ("delegated", "delegated_media") or "review_binding_sha256" in binding) and (
            binding.get("review_binding_sha256") != fingerprint(draft["review_binding"])
        ):
            return False
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False
    if binding.get("publish_intent_id") != draft.get("publish_intent_id"):
        return False
    if binding["mode"] == "auto" and draft["review_binding"].get("kind") != "model":
        return False
    return True


def has_unresolved_publish(draft: dict, state: Mapping[str, Any]) -> bool:
    """Unknown attempts and receipts for other content cannot be cleared by edits."""
    ledger = state.get("publish_ledger") or {}
    event_id = draft.get("event_id") or draft.get("id")

    def unresolved(attempt: Any) -> bool:
        if not isinstance(attempt, dict):
            return True
        conflicts = attempt.get("attempt_conflicts", [])
        if not isinstance(conflicts, list):
            return True
        if any(unresolved(other) for other in conflicts):
            return True
        if attempt.get("tweet_id"):
            if "text_sha256" in attempt:
                return not binding_matches(draft, attempt)
            return isinstance(attempt.get("text"), str) and attempt["text"] != draft.get("text")
        # A missing phase is legacy evidence of a possible send, not proof of expiry.
        return attempt.get("phase") != "not_sent"

    # Missing evidence and an explicitly malformed retained row are different.
    # Never treat null/scalar conflict members as proof that nothing was sent.
    if isinstance(ledger, dict) and event_id in ledger and unresolved(ledger[event_id]):
        return True
    if draft.get("publish_outcome") in ("submitted", "unknown"):
        return True
    if draft.get("status") == "posted" or draft.get("publish_outcome") in ("not_sent", "confirmed"):
        return False
    return bool(draft.get("autoship_attempted") or draft.get("last_publish_attempt_at"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_model_review(draft: dict, *, policy=_CURRENT_POLICY, at: str | None = None) -> dict:
    return _record_model_review(draft, policy=policy, at=at, verified_required_checks=False)


def _record_verified_checks_review(draft: dict, *, policy: dict, at: str) -> dict:
    """Internal authority boundary, called only after retained-byte verification.

    Generic save/initialization deliberately cannot mint this receipt-backed
    authority from caller-supplied structured metadata.
    """
    return _record_model_review(draft, policy=policy, at=at, verified_required_checks=True)


def _record_model_review(draft: dict, *, policy, at, verified_required_checks: bool) -> dict:
    revoke_approval(draft)
    two_bot = _two_bot(draft)
    policy = _editorial_policy(policy)
    try:
        proven = (
            "media_attachment" not in draft
            and policy is not None
            and two_bot.get("reviewed_policy_sha256") == fingerprint(policy)
            and _checks_pass(two_bot)
            and two_bot.get("reviewed_text_sha256") == text_hash(draft.get("text", ""))
            and "bundle" in two_bot
            and two_bot.get("reviewed_bundle_sha256") == fingerprint(two_bot["bundle"])
        )
    except (ValueError, TypeError, UnicodeError, OverflowError):
        proven = False
    proof = required_checks_fingerprint(two_bot.get("required_checks_binding"))
    if "required_checks_binding" in two_bot and (proof is None or not verified_required_checks):
        proven = False
    if proven and not draft.get("revision_conflicts"):
        draft["review_binding"] = {
            **draft_identity(draft), "kind": "model", "reviewed_at": at if at is not None else _now(),
            "checks_sha256": fingerprint(_checks(two_bot)),
            "editorial_policy": deepcopy(policy), "policy_sha256": fingerprint(policy),
        }
        if proof is not None:
            draft["review_binding"]["required_checks_sha256"] = proof
    else:
        draft.pop("review_binding", None)
    return draft


def initialize_revision(draft: dict, *, at: str | None = None, policy=_CURRENT_POLICY) -> dict:
    draft.setdefault("content_revision", 1)
    return record_model_review(draft, at=at, policy=policy)


def record_human_review(draft: dict, *, at: str | None = None, policy=_CURRENT_POLICY) -> dict:
    if "media_attachment" in draft:
        raise ValueError("Joint media review is required; text-only review cannot approve this draft")
    if draft.get("revision_conflicts"):
        raise ValueError("Resolve the conflicting revision before reviewing")
    text = draft.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 280:
        raise ValueError("Invalid draft text")
    policy = _editorial_policy(policy)
    if policy is None:
        raise ValueError("Editorial policy unverified; cannot establish a new review")
    draft["content_revision"] = max(1, draft_identity(draft)["content_revision"])
    revoke_approval(draft)
    draft["review_binding"] = {**draft_identity(draft), "kind": "human", "reviewed_at": at if at is not None else _now(),
                               "editorial_policy": deepcopy(policy), "policy_sha256": fingerprint(policy)}
    return draft


def _attestation_record(required):
    return {"version": 1, "confirmed": list(required)} if required else None


def record_joint_media_review(draft: dict, *, at: str | None = None, policy=_CURRENT_POLICY,
                              attestations: dict | None = None) -> dict:
    """Ordinary explicit manual joint review; never a scientific or model verdict.

    Published originals require every named attestation explicitly true; nothing
    defaults to confirmed and native kinds accept none.
    """
    from src.media.gist_media import required_attestations, validate_descriptor
    validate_descriptor(draft["media_attachment"], _two_bot(draft)["bundle"])
    required = required_attestations(draft["media_attachment"])
    supplied = attestations or {}
    if not isinstance(supplied, dict) or set(supplied) != set(required) or any(v is not True for v in supplied.values()):
        raise ValueError("Confirm every required published-image attestation")
    if draft.get("revision_conflicts"):
        raise ValueError("Resolve the conflicting revision before reviewing")
    text = draft.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 280:
        raise ValueError("Invalid draft text")
    text_hash(text)
    policy = _editorial_policy(policy)
    if policy is None:
        raise ValueError("Editorial policy unverified")
    draft["content_revision"] = max(1, draft_identity(draft)["content_revision"])
    revoke_approval(draft)
    draft["review_binding"] = {**draft_identity(draft), "kind": "human_media",
        "reviewed_at": at if at is not None else _now(), "editorial_policy": deepcopy(policy),
        "policy_sha256": fingerprint(policy), "media_sha256": fingerprint(draft["media_attachment"])}
    if required:
        draft["review_binding"]["published_attestations"] = _attestation_record(required)
    return draft


def record_delegated_review(draft: dict, *, authorization_sha256: str,
                            review_receipt_sha256: str, at: str | None = None,
                            policy=_CURRENT_POLICY) -> dict:
    """Trusted operator only: explicit user delegation, never a human rating.

    The caller retains and verifies both references. This does not authenticate
    a caller, validate factual claims, authorize automatic publishing or send.
    """
    delegation = {"scope": "one_manual_post", "reviewer": "codex",
                  "authorization_sha256": authorization_sha256,
                  "review_receipt_sha256": review_receipt_sha256}
    if not _valid_delegation(delegation):
        raise ValueError("Explicit delegated review provenance is required")
    # Reuse identical text/media/conflict/policy validation and revocation.
    # Only the completed delegated record is returned or persisted.
    record_human_review(draft, at=at, policy=policy)
    draft["review_binding"].update(kind="delegated", delegation=delegation)
    return draft


def record_delegated_joint_media_review(draft: dict, *, authorization_sha256: str, review_receipt_sha256: str,
                                        at: str | None = None, policy=_CURRENT_POLICY) -> dict:
    """Trusted operator only: an explicitly delegated joint text+native-image review.

    Never ``human``/``human_media``, a scientist verdict or a rating. It binds the
    exact text, native PNG/alt recipe, retained source and policy for one manual
    post. Published products with attestations and store-backed images stay
    human-held; a delegated review never authorizes automatic publication. The
    caller (src.editorial.delegated_media_review) verifies both retained references.
    """
    from src.media.gist_media import NATIVE_KINDS, kind_of, required_attestations

    delegation = {"scope": "one_manual_post", "reviewer": "codex",
                  "authorization_sha256": authorization_sha256,
                  "review_receipt_sha256": review_receipt_sha256}
    if not _valid_delegation(delegation):
        raise ValueError("Explicit delegated review provenance is required")
    if "media_attachment" not in draft:
        raise ValueError("A delegated joint review needs an attached native image")
    attachment = draft["media_attachment"]
    if kind_of(attachment) not in NATIVE_KINDS or required_attestations(attachment):
        raise ValueError("Published or store-backed images need an ordinary human joint review")
    # Reuse the ordinary joint review's descriptor, text, conflict and policy checks.
    record_joint_media_review(draft, at=at, policy=policy)
    draft["review_binding"].update(kind="delegated_media", delegation=delegation)
    return draft


def authorize_draft(draft: dict, mode: str, intent_id: str | None = None, *, publication_epoch: str | None = None) -> dict:
    if not review_is_current(draft):
        raise ValueError("This revision needs revalidation")
    if mode not in ("manual", "auto"):
        raise ValueError("Invalid approval mode")
    if mode == "auto" and draft["review_binding"].get("kind") != "model":
        raise ValueError("Scheduling requires a current model review")
    if mode == "auto":
        policy = automatic_publication_policy()
        if not policy["enabled"] or (publication_epoch is not None and publication_epoch != policy["epoch"]):
            raise ValueError(policy["reason"])
        publication_epoch = policy["epoch"]
    return bind_reviewed_revision(draft, mode, at=_now(), intent_id=intent_id, publication_epoch=publication_epoch)


def bind_reviewed_revision(draft: dict, mode: str, *, at: str,
                           intent_id: str | None = None, publication_epoch: str | None = None, policy=_CURRENT_POLICY) -> dict:
    """Record a binding deterministically after the caller's authorization check.

    This is a domain transition, not permission to send a post. Runtime callers
    must use authorize_draft; a command authority supplies its verified policy
    and clock explicitly. Final publication still requires the sender's checks.
    """
    policy = _editorial_policy(policy)
    if not review_is_current(draft, policy=policy):
        raise ValueError("This revision needs revalidation")
    if mode not in ("manual", "auto"):
        raise ValueError("Invalid approval mode")
    if mode == "auto" and draft["review_binding"].get("kind") != "model":
        raise ValueError("Scheduling requires a current model review")
    if mode == "auto" and not valid_epoch(publication_epoch):
        raise ValueError("A valid publication epoch is required")
    _advance_decision(draft)
    draft["approval_binding"] = {
        **draft_identity(draft), "decision_revision": draft["decision_revision"],
        "mode": mode, "authorized_at": at,
        "editorial_policy": deepcopy(policy), "policy_sha256": fingerprint(policy),
    }
    if draft["review_binding"].get("kind") in ("delegated", "delegated_media"):
        draft["approval_binding"]["review_binding_sha256"] = fingerprint(draft["review_binding"])
    if mode == "auto":
        draft["approval_binding"]["publication_epoch"] = publication_epoch
    if intent_id:
        draft["approval_binding"]["publish_intent_id"] = intent_id
        draft["publish_intent_id"] = intent_id
    return draft


def revoke_approval(draft: dict) -> dict:
    _advance_decision(draft)
    for key in (
        "approval_binding", "approved_at", "auto_approve_at", "auto_approve_requested_at",
        "publish_requested_at", "publish_intent_id", "autoship_on_critic_pass",
    ):
        draft.pop(key, None)
    draft["approval_mode"] = "manual"
    return draft


_REFERENCES_OMITTED = object()


def invalidate_text(draft: dict, new_text: str, *, at: str | None = None,
                    operator_claim_references: Any = _REFERENCES_OMITTED) -> dict:
    if not isinstance(new_text, str) or not new_text.strip() or len(new_text) > 280:
        raise ValueError("Invalid draft text")
    text_hash(new_text)  # Reject malformed Unicode before changing durable fields.
    from src.editorial.operator_claim_references import build_operator_claim_references, operator_claim_kind_matches
    review = draft.get("review_context")
    if review is not None and not isinstance(review, dict):
        raise ValueError("Invalid draft review context")
    old_references = (review or {}).get("operator_claim_references", _REFERENCES_OMITTED)
    if operator_claim_references is _REFERENCES_OMITTED:
        references = old_references if new_text == draft.get("text") else _REFERENCES_OMITTED
    else:
        two = (review or {}).get("two_bot")
        bundle = two.get("bundle") if isinstance(two, dict) else None
        if operator_claim_references and (not isinstance(bundle, dict) or bundle.get("event_id") != draft.get("event_id") or not operator_claim_kind_matches(draft.get("type"), bundle.get("signal_kind"))):
            raise ValueError("Saved source snapshot does not match this draft")
        built = build_operator_claim_references(new_text, bundle, operator_claim_references)
        references = built if built is not None else _REFERENCES_OMITTED
    same_references = (references is old_references or
                       (references is not _REFERENCES_OMITTED and old_references is not _REFERENCES_OMITTED and fingerprint(references) == fingerprint(old_references)))
    if new_text == draft.get("text") and same_references and not draft.get("revision_conflicts"):
        return draft
    _invalidate_content(draft, at=at)
    draft["text"] = new_text
    if references is _REFERENCES_OMITTED:
        if isinstance(draft.get("review_context"), dict):
            draft["review_context"].pop("operator_claim_references", None)
    else:
        draft.setdefault("review_context", {})
        if draft["review_context"] is None:
            draft["review_context"] = {}
        draft["review_context"]["operator_claim_references"] = deepcopy(references)
    return draft


def invalidate_media_attachment(draft: dict, attachment: dict | None, *, at: str) -> dict:
    """Content transition only; callers qualify media and resolve current state.

    None removes a present attachment. This never records a joint review or
    authorizes transport, and existing text-only review paths refuse the field.
    """
    if attachment is not None and not isinstance(attachment, dict):
        raise ValueError("Media content must be an object")
    if attachment is None and "media_attachment" not in draft:
        return draft
    if attachment is not None:
        fingerprint(attachment)
        if "media_attachment" in draft:
            def encode(value):
                return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
            if encode(attachment) == encode(draft["media_attachment"]):
                return draft
    _invalidate_content(draft, at=at)
    if attachment is None:
        draft.pop("media_attachment", None)
    else:
        draft["media_attachment"] = deepcopy(attachment)
    return draft


def _invalidate_content(draft: dict, *, at: str | None = None) -> dict:
    previous = {key: deepcopy(draft[key]) for key in (
        "text", "review_context", "review_binding", "approval_binding", "revision_conflicts", "decision_revision",
        "media_attachment", "media_review_binding",
    ) if key in draft}
    previous.update(draft_identity(draft))
    if previous["content_revision"] >= 9007199254740991:
        raise ValueError("Content revision exhausted")
    if decision_revision(draft) >= 9007199254740990:
        raise ValueError("Decision revision exhausted")
    history = draft.get("revision_history", [])
    if not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
        raise ValueError("Invalid revision history")
    previous["invalidated_at"] = at if at is not None else _now()
    draft.setdefault("revision_history", []).append(previous)
    draft["content_revision"] = previous["content_revision"] + 1
    draft["status"] = "pending"
    revoke_approval(draft)
    for key in ("review_binding", "media_review_binding", "revision_conflicts", "candidate_score", "selected_candidate_rank"):
        draft.pop(key, None)
    review = draft.get("review_context")
    if isinstance(review, dict) and isinstance(review.get("two_bot"), dict):
        review["two_bot"] = {key: value for key, value in review["two_bot"].items() if key in ("bundle", "signal_kind")}
    return draft


def project_draft(draft: dict, *, policy=_CURRENT_POLICY) -> dict:
    from src.editorial.operator_claim_references import project_operator_claim_reference_history, project_operator_claim_references
    policy = _editorial_policy(policy)
    current = review_is_current(draft, policy=policy)
    return {
        **draft, "revision_identity": {**draft_identity(draft), "decision_revision": decision_revision(draft)},
        "operator_claim_reference_view": project_operator_claim_references(draft),
        "operator_claim_reference_history": project_operator_claim_reference_history(draft),
        "review_status": "conflict" if draft.get("revision_conflicts") else "media_review_required" if "media_attachment" in draft and not current else "policy_unverified" if policy is None else "passed" if current else "needs_revalidation",
        "review_kind": draft.get("review_binding", {}).get("kind") if current else None,
    }

# Passive observations are deliberately excluded from draft_identity and every
# decision binding above. Digests bind retained JSON; they are not signatures.
def _passive_unicode_canonical(value: Any) -> Any:
    # Lossless typed JSON, including invalid Unicode code units. This is used
    # only to retain unavailable sidecar data, never for draft/check identities.
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, list):
        return ["array", [_passive_unicode_canonical(item) for item in value]]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return ["object", [[key, _passive_unicode_canonical(value[key])] for key in sorted(value)]]
    return _canonical(value)


def passive_comparison_value(value: Any) -> str:
    """Typed ASCII encoding for every passive value at an exact comparison."""
    return json.dumps(_passive_unicode_canonical(value), ensure_ascii=True, separators=(",", ":"))


_UNAVAILABLE_PREFIX = "unavailable-v1:"
_UNAVAILABLE_DOMAIN = "theheat.passive.unavailable-record.v1\0"


def _unavailable_record(category: str, value: Any) -> tuple[str, dict]:
    frame = {"passive_unavailable_record": {"schema_version": 1, "category": category,
             "raw_data": passive_comparison_value(value)}}
    digest = hashlib.sha256((_UNAVAILABLE_DOMAIN + passive_comparison_value(frame)).encode("ascii")).hexdigest()
    return _UNAVAILABLE_PREFIX + digest, frame


def _decode_passive_data(value: Any) -> Any:
    """Decode the complete typed data only to validate unavailable framing."""
    if not isinstance(value, list) or not value or not isinstance(value[0], str):
        raise ValueError("invalid_passive_data")
    kind = value[0]
    if kind == "null" and len(value) == 1:
        return None
    if len(value) != 2:
        raise ValueError("invalid_passive_data")
    item = value[1]
    if kind == "boolean" and type(item) is bool:
        return item
    if kind == "string" and isinstance(item, str):
        return item
    if kind == "number" and isinstance(item, str) and re.fullmatch(r"[0-9a-f]{16}", item):
        number = struct.unpack(">d", bytes.fromhex(item))[0]
        if math.isfinite(number):
            return number
    if kind == "array" and isinstance(item, list):
        return [_decode_passive_data(child) for child in item]
    if kind == "object" and isinstance(item, list):
        result = {}
        for pair in item:
            if (not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str)
                    or pair[0] in result):
                raise ValueError("invalid_passive_data")
            result[pair[0]] = _decode_passive_data(pair[1])
        return result
    raise ValueError("invalid_passive_data")


def _stored_unavailable(key: Any, value: Any) -> bool:
    # A validated key/frame denotes storage encoding, never writer provenance.
    # Ordinary envelope-shaped raw values under unverified keys stay raw values.
    if (not isinstance(key, str) or not key.startswith(_UNAVAILABLE_PREFIX)
            or not isinstance(value, dict) or set(value) != {"passive_unavailable_record"}):
        return False
    record = value["passive_unavailable_record"]
    if (not isinstance(record, dict) or set(record) != {"schema_version", "category", "raw_data"}
            or type(record["schema_version"]) not in (int, float) or record["schema_version"] != 1
            or record["category"] not in ("unicode_payload", "container")
            or not isinstance(record["raw_data"], str) or not record["raw_data"].isascii()):
        return False
    try:
        raw = _decode_passive_data(json.loads(record["raw_data"]))
        if passive_comparison_value(raw) != record["raw_data"]:
            return False
        if record["category"] == "container":
            if isinstance(raw, dict):
                return False
        else:
            try:
                fingerprint(raw)
            except UnicodeError:
                pass
            else:
                return False
        expected_key, expected_value = _unavailable_record(record["category"], raw)
        return key == expected_key and value == expected_value
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return False


def passive_payload(value: Any) -> tuple[str, Any]:
    """Normal payload hashes stay exact; unavailable records use a separate domain."""
    try:
        return fingerprint(value), deepcopy(value)
    except UnicodeError:
        return _unavailable_record("unicode_payload", value)


def merge_passive_maps(*maps: Any) -> dict:
    rows = {}
    for value in maps:
        if not isinstance(value, dict):
            digest, retained = _unavailable_record("container", value)
            rows[digest] = retained
            continue
        for key, payload in value.items():
            if _stored_unavailable(key, payload):
                rows[key] = deepcopy(payload)
            else:
                digest, retained = passive_payload(payload)
                rows[digest] = retained
    return dict(sorted(rows.items()))


def normalize_passive_snapshots(value: Any) -> Any:
    """Normalize only new namespaces along already-known snapshot paths."""
    out = deepcopy(value)
    if not isinstance(out, dict):
        return out
    for key in ("writer_observations", "publication_observations"):
        if key in out:
            out[key] = merge_passive_maps(out[key])
    review = out.get("review_context")
    two = review.get("two_bot") if isinstance(review, dict) else None
    if isinstance(two, dict) and "accepted_writer_observation" in two:
        two["accepted_writer_observation"] = passive_payload(two["accepted_writer_observation"])[1]
    for key in ("revision_history", "revision_conflicts", "attempt_conflicts"):
        if isinstance(out.get(key), list):
            out[key] = [normalize_passive_snapshots(row) for row in out[key]]
    if "published_revision" in out:
        out["published_revision"] = normalize_passive_snapshots(out["published_revision"])
    return out


def _passive_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _passive_identity(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"content_revision", "text_sha256", "evidence_sha256"}
            and type(value["content_revision"]) is int and 1 <= value["content_revision"] <= 9007199254740991
            and _passive_sha(value["text_sha256"]) and _passive_sha(value["evidence_sha256"]))


def _passive_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value) is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def accepted_writer_observation(text: str, bundle: dict, angle: str, event_id: str) -> dict:
    """Called only at the successful pipeline's final checked-result boundary."""
    return {"schema_version": 1, "basis": "accepted_writer_result", "event_id": event_id,
            "angle_chosen": angle, "text_sha256": text_hash(text), "bundle_sha256": fingerprint(bundle)}


def valid_writer_observation(value: Any, *, admitted: bool = True) -> bool:
    fields = {"schema_version", "basis", "event_id", "angle_chosen", "text_sha256", "bundle_sha256"}
    if admitted:
        fields.add("original_identity")
    if not isinstance(value, dict) or set(value) != fields:
        return False
    return (type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["basis"] == "accepted_writer_result"
            and isinstance(value["event_id"], str) and bool(value["event_id"].strip())
            and isinstance(value["angle_chosen"], str) and len(value["angle_chosen"]) <= 80
            and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value["angle_chosen"]) is not None
            and _passive_sha(value["text_sha256"]) and _passive_sha(value["bundle_sha256"])
            and (not admitted or (_passive_identity(value["original_identity"])
                 and value["original_identity"]["text_sha256"] == value["text_sha256"])))


def admit_writer_observation(draft: dict) -> None:
    """No legacy angle, review, manual flag or selected candidate can mint this."""
    value = _two_bot(draft).get("accepted_writer_observation")
    bundle = _two_bot(draft).get("bundle")
    if not isinstance(value, dict) or not valid_writer_observation(value, admitted=False) or not isinstance(bundle, dict):
        return
    identity = draft_identity(draft)
    if (value["event_id"] != draft.get("event_id") or bundle.get("event_id") != value["event_id"]
            or value["text_sha256"] != identity["text_sha256"] or value["bundle_sha256"] != fingerprint(bundle)):
        return
    payload = {**deepcopy(value), "original_identity": identity}
    draft["writer_observations"] = merge_passive_maps({"captured": payload})


def publication_observation(draft: dict, event_id: str, receipt: dict) -> dict | None:
    """Freeze only already-retained observations from the pretransport snapshot."""
    if "writer_observations" not in draft:
        return None
    writers = merge_passive_maps(draft["writer_observations"])
    bundle = _two_bot(draft).get("bundle")
    source = fingerprint(bundle) if isinstance(bundle, dict) and bundle.get("event_id") == event_id else None
    history, unavailable = {}, False
    sent_at = _passive_time(receipt.get("at"))
    retained = draft.get("revision_history", [])
    if not isinstance(retained, list):
        retained, unavailable = [], True
    for row in retained:
        try:
            at = _passive_time(row.get("invalidated_at")) if isinstance(row, dict) else None
            if (not isinstance(row, dict) or not _passive_identity({key: row.get(key) for key in draft_identity(draft)})
                    or row["content_revision"] >= receipt["content_revision"] or not isinstance(row.get("text"), str)
                    or text_hash(row["text"]) != row["text_sha256"] or at is None
                    or sent_at is None or at > sent_at):
                unavailable = True
                continue
            compact = {key: row[key] for key in ("content_revision", "text_sha256", "invalidated_at")}
            history[fingerprint(compact)] = compact
        except (ValueError, TypeError, UnicodeError, OverflowError):
            unavailable = True
    writer: Any = next(iter(writers.values())) if len(writers) == 1 else None
    valid = valid_writer_observation(writer)
    return {"schema_version": 1, "basis": "pretransport_snapshot", "event_id": event_id,
            "intent_id": receipt.get("intent_id"), "at": receipt.get("at"),
            "identity": draft_identity(draft), "source_bundle_sha256": source,
            "source_relation": ("matches" if writer["bundle_sha256"] == source else "differs") if valid and source else "unknown",
            "text_comparison": ("matches" if writer["text_sha256"] == text_hash(draft["text"]) else "differs") if valid else "unknown",
            "writer_observations": writers, "history_scope": "retained_incomplete",
            "history_unavailable": unavailable, "text_observations": dict(sorted(history.items()))}


def publication_observation_status(value: Any, event_id: str, receipt: dict) -> str:
    """Malformed passive evidence is unavailable, never a new publication gate."""
    try:
        return _publication_observation_status(value, event_id, receipt)
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return "unknown"


def _publication_observation_status(value: Any, event_id: str, receipt: dict) -> str:
    """Validate the complete send binding without consulting today's draft."""
    fields = {"schema_version", "basis", "event_id", "intent_id", "at", "identity", "source_bundle_sha256",
              "writer_observations", "history_scope", "history_unavailable", "text_observations", "source_relation", "text_comparison"}
    if not isinstance(value, dict) or set(value) != fields:
        return "unknown"
    sent_at = _passive_time(value["at"])
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["basis"] != "pretransport_snapshot"
            or value["event_id"] != event_id or not isinstance(event_id, str) or not event_id.strip()
            or not isinstance(value["intent_id"], str) or not value["intent_id"].strip()
            or value["intent_id"] != receipt.get("intent_id") or value["at"] != receipt.get("at")
            or sent_at is None or not _passive_identity(value["identity"])
            or value["identity"] != {key: receipt.get(key) for key in ("content_revision", "text_sha256", "evidence_sha256")}
            or not isinstance(receipt.get("text"), str) or text_hash(receipt["text"]) != value["identity"]["text_sha256"]
            or value["history_scope"] != "retained_incomplete" or type(value["history_unavailable"]) is not bool
            or not isinstance(value["writer_observations"], dict) or not isinstance(value["text_observations"], dict)):
        return "unknown"
    writers = list(merge_passive_maps(value["writer_observations"]).values())
    if len(writers) > 1:
        return "conflict"
    if (len(writers) != 1 or not valid_writer_observation(writers[0]) or writers[0]["event_id"] != event_id
            or writers[0]["original_identity"]["content_revision"] > value["identity"]["content_revision"]
            or writers[0]["bundle_sha256"] != value["source_bundle_sha256"]
            or value["source_relation"] != "matches"
            or value["text_comparison"] != ("matches" if writers[0]["text_sha256"] == value["identity"]["text_sha256"] else "differs")
            or (writers[0]["original_identity"]["content_revision"] == value["identity"]["content_revision"]
                and writers[0]["original_identity"] != value["identity"])):
        return "unknown"
    revisions: dict[int, set[str]] = {}
    for row in value["text_observations"].values():
        invalidated_at = _passive_time(row.get("invalidated_at")) if isinstance(row, dict) else None
        if (not isinstance(row, dict) or set(row) != {"content_revision", "text_sha256", "invalidated_at"}
                or type(row["content_revision"]) is not int or not 1 <= row["content_revision"] < value["identity"]["content_revision"]
                or not _passive_sha(row["text_sha256"]) or invalidated_at is None
                or sent_at is None or invalidated_at > sent_at):
            return "unknown"
        revisions.setdefault(row["content_revision"], set()).add(row["text_sha256"])
    return "conflict" if any(len(hashes) > 1 for hashes in revisions.values()) else "recorded"


def qualifying_publication_context(receipt: dict, event_id: str) -> str | None:
    """A sample reference requires a single unambiguous confirmed receipt map."""
    if (receipt.get("phase") != "confirmed" or not receipt.get("tweet_id")
            or ("attempt_conflicts" in receipt and (not isinstance(receipt["attempt_conflicts"], list)
                or any(not isinstance(row, dict) for row in receipt["attempt_conflicts"])))):
        return None
    if "publication_observations" not in receipt:
        return None
    values = merge_passive_maps(receipt["publication_observations"])
    if len(values) != 1:
        return None
    digest, value = next(iter(values.items()))
    return digest if publication_observation_status(value, event_id, receipt) == "recorded" else None
