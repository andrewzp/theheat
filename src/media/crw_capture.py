"""Explicit, default-off retention of the exact CRW source packet the collector already read.

No request, retry, walkback or reconstruction: the packet is this run's primary
ERDDAP CSV and metadata response bytes with the acquisition times the collector
recorded. Only a qualified primary event is eligible; the NOAA STAR fallback leg
(or any other leg) is never relabelled as a primary packet. Before any write the
packet is verified by the same offline adapter the preview and sender use, and it
is retained only through the separately configured insert-only writer.

Any failure holds the graphic (no reference is attached) and records one fixed
outcome code; the text story follows its existing source/check rules unchanged.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from typing import Any

from src.data import crw_contract
from src.data.source_status import SourceFetchError
from src.editorial.revisions import fingerprint
from src.media import gist_assets

ENV = "THEHEAT_CRW_PACKET_RETENTION"
REFERENCE_KEYS = frozenset({"schema_version", "artifact_sha256", "packet_sha256"})
OUTCOMES = ("retained", "store_unavailable", "retention_unknown", "unsupported_source_leg", "source_unqualified",
            "packet_unavailable", "packet_too_large", "packet_invalid", "retention_error")
_STORE_CODES = {"media_store_unavailable": "store_unavailable", "media_retention_unknown": "retention_unknown"}


def enabled(environ=None) -> bool:
    """Only the exact value "1" enables retention; anything else leaves it off."""
    return (os.environ if environ is None else environ).get(ENV, "") == "1"


def writer(environ=None):
    """(insert-only writer, None) or (None, outcome); never a reader or a fallback."""
    try:
        return gist_assets.configured_writer(environ), None
    except gist_assets.MediaStoreError:
        return None, "store_unavailable"


def packet_for(event: Any, captured: Any) -> tuple[dict | None, str | None]:
    """The exact packet for a qualified primary event, or (None, outcome)."""
    from src.media.crw_graphic_adapter import PACKET_LIMIT

    if event.source_leg is not None:
        return None, "unsupported_source_leg"
    if not crw_contract.qualified_provenance(event) or event.provenance.get("source_leg") != "coastwatch_erddap":
        return None, "source_unqualified"
    p = event.provenance
    if captured is None or event.region_slug not in captured.csv:
        return None, "packet_unavailable"
    csv_body, csv_retrieved_at = captured.csv[event.region_slug]
    metadata_body = captured.metadata_body
    # The captured bytes must be exactly the ones this event's provenance hashed.
    if (hashlib.sha256(csv_body).hexdigest() != p["response_sha256"] or len(csv_body) != p["response_bytes"]
            or csv_retrieved_at != p["retrieved_at"]
            or len(metadata_body) != p["primary_metadata"]["response_bytes"]):
        return None, "packet_unavailable"
    if len(csv_body) > 400_000 or len(metadata_body) > 100_000:
        return None, "packet_too_large"
    try:
        csv_text, metadata_text = csv_body.decode("utf-8"), metadata_body.decode("utf-8")
    except UnicodeDecodeError:
        return None, "packet_invalid"
    packet = {"schema_version": 1, "csv_utf8": csv_text, "metadata_utf8": metadata_text,
              "csv_retrieved_at": csv_retrieved_at,
              "metadata_retrieved_at": p["primary_metadata"]["retrieved_at"]}
    if len(json.dumps(packet, allow_nan=False, ensure_ascii=False).encode("utf-8")) > PACKET_LIMIT:
        return None, "packet_too_large"
    return packet, None


def reference(packet: dict) -> dict:
    return {"schema_version": 1, "artifact_sha256": hashlib.sha256(gist_assets.encode_document(packet)).hexdigest(),
            "packet_sha256": fingerprint(packet)}


def retain_for_event(event: Any, captured: Any, store: Any) -> tuple[Any, str]:
    """(event carrying the exact reference, "retained") or (unchanged event, outcome). Never raises."""
    from src.media import crw_graphic_adapter as adapter, gist_crw_media
    from src.media.gist_hazard_media import MediaWithheld
    from src.media.temperature_graphic_adapter import _StoredBundle, story_bundle_snapshot
    from src.two_bot.intern.marine_crw import build_regional_sst_anomaly_bundle

    try:
        packet, outcome = packet_for(event, captured)
        if packet is None:
            return event, outcome or "packet_unavailable"
        candidate = replace(event, retained_packet=reference(packet))
        bundle = story_bundle_snapshot(build_regional_sst_anomaly_bundle(candidate))
        adapter.crw_graphic_spec(_StoredBundle(bundle), packet, expected_bundle_sha256=fingerprint(bundle),
                                 expected_packet_sha256=fingerprint(packet), synthetic=False)
    except (ValueError, KeyError, TypeError, AttributeError, SourceFetchError):
        return event, "source_unqualified"
    except Exception:  # Unexpected: hold the graphic, never the text story.
        return event, "retention_error"
    if store is None:
        return event, "store_unavailable"
    try:
        key = gist_crw_media.retain_packet(store, packet)
    except (MediaWithheld, gist_assets.MediaStoreError) as exc:
        return event, _STORE_CODES.get(exc.code, "packet_invalid")
    except Exception:
        return event, "retention_error"
    if key != candidate.retained_packet["artifact_sha256"]:
        return event, "retention_unknown"
    return candidate, "retained"


def summary(outcomes: Counter) -> dict:
    """Bounded run-detail projection: fixed codes and counts only."""
    return {"enabled": True, **{code: int(outcomes.get(code, 0)) for code in OUTCOMES}}
