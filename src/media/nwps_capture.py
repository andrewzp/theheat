"""Retain an already qualified NWPS capture outside the model-facing story.

The existing insert-only media writer owns retention. The protected preview uses
only the corresponding reader and the draft's exact artifact reference.
"""
from __future__ import annotations

from copy import deepcopy
import os
import re

from src.editorial.revisions import fingerprint
from src.media import gist_assets

ENV = "THEHEAT_NWPS_PACKET_RETENTION"
CONTEXT_KEY = "nwps_point_capture"
MAX_PACKET_BYTES = 450_000
OUTCOMES = ("retained", "capture_unavailable", "source_unqualified", "store_unavailable",
            "retention_unknown", "retention_error")
REFERENCE_KEYS = {"schema_version", "artifact_sha256", "capture_sha256", "bundle_sha256"}
PACKET_KEYS = {"schema_version", "capture", "bundle_sha256"}
SHA = re.compile(r"[a-f0-9]{64}\Z")


def enabled(environ=None):
    return (os.environ if environ is None else environ).get(ENV) == "1"


def _reference(value, bundle):
    if (type(value) is not dict or set(value) != REFERENCE_KEYS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or any(type(value[k]) is not str or SHA.fullmatch(value[k]) is None
                   for k in ("artifact_sha256", "capture_sha256", "bundle_sha256"))
            or value["bundle_sha256"] != fingerprint(bundle)):
        raise gist_assets.MediaStoreError("media_source_packet_invalid", "the river capture reference changed")
    return value


def retain(bundle, capture, store):
    """Return a bound reference and fixed outcome. A refusal changes no text evidence."""
    from src.media.nwps_graphic_adapter import nwps_graphic_spec

    if type(capture) is not dict:
        return None, "capture_unavailable"
    try:
        capture = deepcopy(capture)
        bundle_sha = fingerprint(bundle)
        capture_sha = fingerprint(capture)
        nwps_graphic_spec(bundle, capture, expected_bundle_sha256=bundle_sha,
                          expected_capture_sha256=capture_sha)
        packet = {"schema_version": 1, "capture": capture, "bundle_sha256": bundle_sha}
        encoded = gist_assets.encode_document(packet)
        if len(encoded) > MAX_PACKET_BYTES or capture["synthetic"] is not False:
            return None, "source_unqualified"
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None, "source_unqualified"
    except Exception:
        return None, "retention_error"
    if store is None:
        return None, "store_unavailable"
    try:
        key = gist_assets.put_document(store, packet)
        if key != gist_assets.digest(encoded):
            return None, "retention_unknown"
    except gist_assets.MediaStoreError as exc:
        return None, "retention_unknown" if exc.code == "media_retention_unknown" else "store_unavailable"
    except Exception:
        return None, "retention_error"
    return {"schema_version": 1, "artifact_sha256": key, "capture_sha256": capture_sha,
            "bundle_sha256": bundle_sha}, "retained"


def load(bundle, reference, store=None):
    """Read only the saved artifact. Never choose a newest or same-gauge packet."""
    reference = _reference(reference, bundle)
    store = gist_assets.configured() if store is None else store
    packet = gist_assets.get_document(store, reference["artifact_sha256"], limit=MAX_PACKET_BYTES)
    if (type(packet) is not dict or set(packet) != PACKET_KEYS
            or type(packet["schema_version"]) is not int or packet["schema_version"] != 1
            or packet["bundle_sha256"] != reference["bundle_sha256"]
            or fingerprint(packet["capture"]) != reference["capture_sha256"]):
        raise gist_assets.MediaStoreError("media_source_packet_mismatch", "the retained river capture changed")
    return packet["capture"]
