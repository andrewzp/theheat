"""Build attributed warning facts from explicitly supplied original evidence."""
from __future__ import annotations

from datetime import datetime

from src.editorial.official_warning import (
    WarningHold, WarningNomination, validate_warning_packet,
)
from src.two_bot.bundle_capture import BundleCaptureError, capture_bundle
from src.two_bot.types import StoryBundle


def build_warning_bundle(
    metadata_bytes: bytes,
    source_bytes: bytes,
    *,
    nomination: WarningNomination | None,
    now: datetime,
) -> StoryBundle:
    """Revalidate current inputs before creating writer facts; never fetch.

    This is not a production producer or an approval. The later dispatch/admission
    and send boundaries must resolve current nomination and expiry independently.
    """
    evidence = validate_warning_packet(metadata_bytes, source_bytes,
                                      nomination=nomination, now=now)
    packet = evidence.metadata()
    issuer = evidence.nomination.issuer_name
    provenance = {"source_name": issuer, "source_url": packet["source_url"],
                  "issued_at": packet["issued_at"],
                  "content_sha256": evidence.nomination.content_sha256}
    facts = [dict(label=label, value=value, **provenance) for label, value in (
        ("issuing_authority", issuer),
        ("warning_text", packet["warning"]["text"]),
        ("warning_place", packet["place"]["name"]),
        ("issued_at", packet["issued_at"]),
        ("source_message_expires_utc", packet["valid_until"]),
    )]
    bundle = StoryBundle(signal_kind="official_warning", where=packet["place"]["name"],
        when=packet["issued_at"], event_id=evidence.lineage_id,
        headline_metric={"label": "attributed_warning", "value": packet["warning"]["text"]},
        current_facts=facts, country=packet["place"]["country"], raw_signal_dump={
            "source_name": issuer, "source_url": packet["source_url"],
            "official_warning": {
                "metadata": packet, "source_utf8": source_bytes.decode("utf-8"),
                "metadata_sha256": evidence.nomination.metadata_sha256,
                "evidence_sha256": evidence.evidence_sha256,
                "assertion_kind": "attributed_warning_not_observation",
                "acquisition_limit": "supplied_retained_bytes_not_fresh_authentication",
            },
        })
    try:
        capture_bundle(bundle)
    except BundleCaptureError as exc:
        reason = "warning_bundle_bound" if str(exc) == "bundle_capture_too_large" else "warning_bundle_invalid"
        raise WarningHold(reason) from None
    return bundle
