"""Trusted operator seam for a delegated joint text+native-image review.

The operator retains two files: Andrew's explicit authorization for one manual
post of one draft, and the delegated reviewer's receipt naming the exact draft
revision, text, native image/description recipe, retained source and editorial
policy it reviewed. This module re-reads both, recomputes their SHA256 digests
and every identity from the current draft, and only then records the delegated
binding. A browser cannot reach it, so a browser-supplied hash never
authenticates a reviewer. It never sends, schedules or grants automatic
authority, and it is not a human rating or scientific verdict.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

AUTHORIZATION_SCHEMA = "theheat.delegated-review-authorization/v1"
RECEIPT_SCHEMA = "theheat.delegated-native-media-review/v1"
MAX_FILE_BYTES = 16_384


def _read(path: Path) -> tuple[bytes, dict]:
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise ValueError("Retained delegation file is missing or too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Retained delegation file must be a JSON object")
    return raw, value


def expected_receipt(draft: dict, *, authorization_sha256: str, policy: Any = None) -> dict:
    """The exact identities a receipt must name for this draft as it stands now."""
    from src.editorial.policy import current_editorial_policy
    from src.editorial.revisions import draft_identity, fingerprint

    policy = current_editorial_policy() if policy is None else policy
    attachment = draft["media_attachment"]
    image = attachment.get("image") if isinstance(attachment.get("image"), dict) else {}
    description = attachment.get("description") if isinstance(attachment.get("description"), dict) else {}
    return {"schema": RECEIPT_SCHEMA, "reviewer": "codex", "decision": "approve_one_manual_post",
            "draft_id": draft["id"], **draft_identity(draft),
            "media_sha256": fingerprint(attachment),
            "png_sha256": image.get("png_sha256", attachment.get("png_sha256")),
            "alt_sha256": description.get("delivery_sha256", attachment.get("alt_sha256")),
            "source_sha256": fingerprint(draft["review_context"]["two_bot"]["bundle"]),
            "policy_sha256": fingerprint(policy), "authorization_sha256": authorization_sha256}


def record_verified(draft: dict, *, authorization_path: Path, receipt_path: Path, policy: Any = None) -> dict:
    """Verify both retained references against the current draft, then record the delegation."""
    from src.editorial.revisions import record_delegated_joint_media_review

    if "media_attachment" not in draft:
        raise ValueError("A delegated joint review needs an attached native image")
    authorization_raw, authorization = _read(authorization_path)
    receipt_raw, receipt = _read(receipt_path)
    authorization_sha256 = sha256(authorization_raw).hexdigest()
    if authorization != {"schema": AUTHORIZATION_SCHEMA, "scope": "one_manual_post", "draft_id": draft["id"],
                         "granted_by": "andrew", "reviewer": "codex"}:
        raise ValueError("Authorization does not grant one manual post of this draft to the delegated reviewer")
    if receipt != expected_receipt(draft, authorization_sha256=authorization_sha256, policy=policy):
        raise ValueError("Review receipt does not name this exact text, image, description, source and policy")
    kwargs = {} if policy is None else {"policy": policy}
    return record_delegated_joint_media_review(draft, authorization_sha256=authorization_sha256,
                                               review_receipt_sha256=sha256(receipt_raw).hexdigest(), **kwargs)


__all__ = ["AUTHORIZATION_SCHEMA", "RECEIPT_SCHEMA", "expected_receipt", "record_verified"]
