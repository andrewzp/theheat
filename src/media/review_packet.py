"""Pure local review identity for one qualified comparator, never posting approval.

Callers supply the current draft/request identity, policy and rendered bytes.
Hashes bind those inputs; neither matching hashes nor a PNG header certify the
image's scientific content or its agreement with the tweet. No I/O or model call.
"""

from __future__ import annotations

import binascii
from copy import deepcopy
import hashlib
import json
import re
import struct
from typing import Any

from src.editorial.policy import valid_policy
from src.editorial.revisions import draft_identity, fingerprint
from src.media.evidence_graphic import (
    HEIGHT,
    WIDTH,
    template_version,
    build_alt_text,
    validate_graphic,
)
from src.media.temperature_graphic_adapter import ADAPTER_VERSION

MAX_JSON_BYTES = 1_000_000
MAX_PNG_BYTES = 8 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}")
_FILES = {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}
_HASH_FIELDS = {
    "rasterizer_sha256",
    "implementation_sha256",
    "contract_sha256",
    "font_sha256",
    "adapter_sha256",
}


class MediaReviewError(ValueError):
    """A bounded diagnostic with no caller text or provider details."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MediaReviewError(message)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: Any) -> dict:
    _require(isinstance(value, dict), "Review inputs must be JSON objects")
    # fingerprint rejects non-string keys and non-JSON values; serialization also
    # rejects invalid Unicode and gives the same explicit bound as graphic specs.
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    _require(len(encoded) <= MAX_JSON_BYTES, "Review JSON exceeds the byte bound")
    fingerprint(value)
    return deepcopy(value)


def _identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value.strip()) <= 200
        and len(value) <= 200
        and all(ord(c) >= 32 for c in value)
    )


def _png_size(png: bytes) -> tuple[int, int]:
    _require(
        isinstance(png, bytes) and 33 <= len(png) <= MAX_PNG_BYTES,
        "PNG bytes are missing or outside the byte bound",
    )
    _require(
        png[:8] == b"\x89PNG\r\n\x1a\n" and png[8:16] == b"\x00\x00\x00\rIHDR",
        "PNG signature or IHDR is invalid",
    )
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", png[16:29]
    )
    _require((width, height) == (WIDTH, HEIGHT), "PNG dimensions differ from the template")
    _require(
        depth == 8 and color in (2, 6) and compression == filtering == 0 and interlace in (0, 1),
        "Unsupported rendered PNG header",
    )
    _require(
        binascii.crc32(png[12:29]) == struct.unpack(">I", png[29:33])[0],
        "PNG header checksum differs",
    )
    return width, height


def build_media_review_packet(
    draft: dict,
    *,
    expected_draft_identity: dict,
    editorial_policy: dict,
    graphic_spec: dict,
    renderer_manifest: dict,
    png_bytes: bytes,
) -> dict:
    """Revalidate independent current inputs and bind them without modifying any.

    The manifest's SVG/PDF bytes are not supplied here. A filesystem adapter must
    verify those assets separately. PNG validation is structural, not a decoder.
    The supplied policy is trusted current context, not loaded from this packet.
    """
    try:
        return _build(
            draft,
            expected_draft_identity=expected_draft_identity,
            editorial_policy=editorial_policy,
            graphic_spec=graphic_spec,
            renderer_manifest=renderer_manifest,
            png_bytes=png_bytes,
        )
    except MediaReviewError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
        struct.error,
    ):
        raise MediaReviewError("Malformed or unqualified media review input") from None


def _build(
    draft, *, expected_draft_identity, editorial_policy, graphic_spec, renderer_manifest, png_bytes
):
    draft, expected, policy, spec, manifest = map(
        _object, (draft, expected_draft_identity, editorial_policy, graphic_spec, renderer_manifest)
    )
    _require(
        _identifier(draft.get("id")) and _identifier(draft.get("event_id")),
        "Draft and event identities are required",
    )
    _require(
        draft.get("status") in {"pending", "approved"} and not draft.get("revision_conflicts"),
        "Draft is not an unambiguous editable revision",
    )
    text = draft.get("text")
    _require(
        isinstance(text, str) and bool(text.strip()) and len(text) <= 280, "Draft text is invalid"
    )
    _require(
        type(draft.get("content_revision")) is int and draft["content_revision"] >= 1,
        "An established draft revision is required",
    )
    identity = draft_identity(draft)
    _require(
        set(expected) == set(identity)
        and type(expected.get("content_revision")) is int
        and expected == identity,
        "Draft differs from the independent requested identity",
    )
    _require(valid_policy(policy), "Current editorial policy is unavailable")
    _require(
        set(spec) == {"template", "expected_evidence_sha256", "evidence"}
        and spec["template"] in {"temperature_comparator", "crw_regional_anomaly"},
        "Only a qualified single-bundle graphic is supported",
    )
    _require(_sha(spec["expected_evidence_sha256"]), "Graphic evidence fingerprint is invalid")
    evidence = validate_graphic(
        spec["template"],
        spec["evidence"],
        expected_evidence_sha256=spec["expected_evidence_sha256"],
    )
    from src.media.crw_graphic_adapter import ADAPTER_VERSION as CRW_ADAPTER_VERSION
    adapter_version = CRW_ADAPTER_VERSION if spec["template"] == "crw_regional_anomaly" else ADAPTER_VERSION
    input_binding = evidence["input_binding"]
    _require(
        input_binding["adapter_version"] == adapter_version and len(input_binding["bundles"]) == 1,
        "A current single-bundle adapter binding is required",
    )
    bound = input_binding["bundles"][0]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    _require(
        isinstance(bundle, dict)
        and fingerprint(bundle) == bound["bundle_sha256"]
        and bundle == bound["bundle"],
        "Graphic and draft use different retained bundles",
    )
    _require(
        draft["event_id"] == evidence["event_id"] == bundle["event_id"],
        "Graphic and draft event identities differ",
    )

    _require(
        set(manifest)
        == {
            "schema_version",
            "cache_key",
            "binding",
            "files",
            "synthetic",
            "alt_text",
            "publication_approved",
            "scope",
        }
        and type(manifest["schema_version"]) is int
        and manifest["schema_version"] == 1,
        "Render manifest schema is invalid",
    )
    binding = manifest["binding"]
    _require(
        isinstance(binding, dict)
        and set(binding) == {"template", "template_version", "source_evidence_sha256", "renderer"},
        "Render binding is invalid",
    )
    _require(
        binding["template"] == spec["template"]
        and binding["template_version"] == template_version(spec["template"])
        and binding["source_evidence_sha256"] == spec["expected_evidence_sha256"]
        and manifest["cache_key"] == fingerprint(binding),
        "Rendered identity differs from current spec",
    )
    renderer = binding["renderer"]
    _require(
        isinstance(renderer, dict)
        and set(renderer) == _HASH_FIELDS | {"library", "version", "width", "height"},
        "Renderer provenance is incomplete",
    )
    _require(
        renderer["library"] == "ReportLab"
        and _identifier(renderer["version"])
        and all(_sha(renderer[key]) for key in _HASH_FIELDS),
        "Renderer provenance is invalid",
    )
    _require(
        type(renderer["width"]) is type(renderer["height"]) is int
        and (renderer["width"], renderer["height"]) == (WIDTH, HEIGHT),
        "Renderer dimensions differ",
    )
    alt = build_alt_text(spec["template"], evidence)
    _require(
        manifest["synthetic"] is evidence["synthetic"]
        and manifest["publication_approved"] is False
        and manifest["scope"] == evidence["scope"]
        and manifest["alt_text"] == alt,
        "Render metadata differs from the qualified evidence",
    )
    files = manifest["files"]
    _require(
        isinstance(files, dict) and set(files) == _FILES and all(_sha(v) for v in files.values()),
        "Render asset set is incomplete or invalid",
    )
    expected_input = json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _require(
        files["input.json"] == _digest(expected_input.encode("utf-8"))
        and files["alt.txt"] == _digest((alt + "\n").encode("utf-8")),
        "Render input or alt asset differs",
    )
    width, height = _png_size(png_bytes)
    _require(
        files["preview.png"] == _digest(png_bytes), "PNG bytes differ from the render manifest"
    )
    packet = {
        "schema_version": 1,
        "draft_binding": {
            "draft_id": draft["id"],
            "event_id": draft["event_id"],
            **identity,
            "policy_sha256": fingerprint(policy),
        },
        "graphic_binding": {
            "template": spec["template"],
            "template_version": template_version(spec["template"]),
            "evidence_sha256": spec["expected_evidence_sha256"],
            "render_binding_sha256": fingerprint(binding),
            "render_manifest_sha256": fingerprint(manifest),
        },
        "media": {
            "mime_type": "image/png",
            "png_sha256": files["preview.png"],
            "byte_count": len(png_bytes),
            "width": width,
            "height": height,
            "alt_text": alt,
            "alt_text_sha256": _digest(alt.encode("utf-8")),
        },
        "synthetic": evidence["synthetic"],
        "claim_agreement_status": "unreviewed",
        "publication_approved": False,
    }
    if "media_attachment" in draft:
        # Derive content without the draft/packet/review identity to avoid a
        # circular hash. The supplied render must be the attachment being shown.
        attached = _object(draft["media_attachment"])
        def encoded(value):
            return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
        _require(
            encoded(attached) == encoded(media_attachment_content(packet)),
            "Draft attachment differs from the independently validated graphic",
        )
    return {**packet, "packet_sha256": fingerprint(packet)}


def media_attachment_content(validated_packet: dict) -> dict:
    """Extract content from a validated packet, never authority or a decision.

    This projection alone validates nothing. Attachment proposals call the packet
    builder first; approval paths must independently revalidate current inputs.
    """
    return deepcopy({
        "schema_version": 1,
        "graphic_binding": validated_packet["graphic_binding"],
        "media": validated_packet["media"],
        "synthetic": validated_packet["synthetic"],
    })


def media_review_packet_is_current(packet: dict, draft: dict, **current_inputs: Any) -> bool:
    """Compare the complete packet against independent current inputs, not itself."""
    try:
        checked = _object(packet)
        _require(type(checked.get("schema_version")) is int, "Invalid packet version")
        _require(
            type(checked["draft_binding"]["content_revision"]) is int, "Invalid packet revision"
        )
        _require(
            all(type(checked["media"][key]) is int for key in ("byte_count", "width", "height")),
            "Invalid packet dimensions or byte count",
        )
        expected = build_media_review_packet(draft, **current_inputs)
        # Fingerprinting in addition to equality rejects bool/int substitution.
        return checked == expected and fingerprint(checked) == fingerprint(expected)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return False
