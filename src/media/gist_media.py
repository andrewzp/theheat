"""Closed dispatch for explicitly selected Gist post images; never a plugin registry.

Every kind names one reviewed, versioned renderer. The deployed temperature kind
delegates unchanged to gist_temperature_media. A kind joins KINDS only together
with its complete preview, joint-review, approval and sender path; anything else,
including an experimental or PG attachment, stays refused for approval and send.
Callers look the family functions up on their modules at call time.

Store-backed kinds (CRW, published charts/maps and radar) need one explicitly
selected retained input: a CRW source packet or a published asset manifest, by its
exact SHA256 in the durable media store. Native recipes never read the store. Those
modules load lazily, only after a store is configured, so the sealed native preview
runtime keeps working (and holds those lanes) without packaging them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.media import gist_hazard_media as hazard, gist_temperature_media as temperature

TEMPERATURE = temperature.KIND
# Literal mirrors of gist_crw_media.KIND and gist_published_media.KINDS/product_for.
CRW = "gist_crw_anomaly_v1"
PUBLISHED = frozenset({"gist_published_radar_v1", "gist_published_chart_v1"})
STORE_KINDS = frozenset({CRW, *PUBLISHED})
KINDS = frozenset({TEMPERATURE, *hazard.KINDS, *STORE_KINDS})
_CYCLONE_SIGNALS = frozenset({"cyclone_rapid_intensification", "cyclone_tier_crossing", "cyclone_landfall",
                              "cyclone_land_threat", "cyclone_basin_record"})


def kind_of(value):
    """The allowlisted kind of an attachment object, else a refusal."""
    kind = value.get("kind") if type(value) is dict else None
    if type(kind) is not str or kind not in KINDS:
        raise ValueError("Image withheld: unsupported attachment")
    return kind


def _module(kind):
    if kind == TEMPERATURE:
        return temperature
    if kind == CRW:
        from src.media import gist_crw_media
        return gist_crw_media
    if kind in PUBLISHED:
        from src.media import gist_published_media
        return gist_published_media
    return hazard


def validate_descriptor(value, bundle):
    return _module(kind_of(value)).validate_descriptor(value, bundle)


def required_attestations(value):
    """The exact attestation names a joint review must confirm for this attachment."""
    if kind_of(value) not in PUBLISHED:
        return []
    from src.media import gist_published_media
    return list(gist_published_media.PRODUCTS[value["product"]]["attestations"])


def _crw_claims(bundle):
    return type(bundle) is dict and bundle.get("signal_kind") == "regional_sst_anomaly"


def _published_claims(bundle):
    raw = bundle.get("raw_signal_dump") if type(bundle) is dict else None
    return type(raw) is dict and (
        (bundle.get("signal_kind") == "severe_weather" and "source_evidence" in raw)
        or (bundle.get("signal_kind") in _CYCLONE_SIGNALS and raw.get("source") == "nhc"))


def needs_retained_input(bundle):
    return _crw_claims(bundle) or _published_claims(bundle)


def prepare_media(bundle, *, synthetic=False, retained_input_sha256=None, store=None, now=None):
    """Select the family from the retained source shape, never from a caller's kind."""
    if needs_retained_input(bundle):
        if retained_input_sha256 is None:
            raise hazard.MediaWithheld("media_retained_input_required",
                                       "select the retained source packet or published asset for this image")
        if store is None:
            from src.media import gist_assets
            store = gist_assets.configured()
        if _crw_claims(bundle):
            return _module(CRW).prepare_media(bundle, store, retained_input_sha256, synthetic=synthetic)
        return _module("gist_published_radar_v1").prepare_media(bundle, store, retained_input_sha256,
                                                                synthetic=synthetic, now=now)
    if retained_input_sha256 is not None:
        raise hazard.MediaWithheld("media_unsupported", "this source's image is rebuilt from its saved recipe")
    if hazard.claims(bundle):
        return hazard.prepare_media(bundle, synthetic=synthetic)
    return temperature.prepare_media(bundle, synthetic=synthetic)


def currentness(bundle, descriptor=None, *, now=None):
    """The kind's own unchanged source-time rule; None when current."""
    if _crw_claims(bundle):
        return _module(CRW).currentness(bundle, now)
    if _published_claims(bundle):
        return _module("gist_published_radar_v1").currentness(descriptor or {}, now)
    return hazard.currentness(hazard.family_for(bundle), bundle, now)


def posting_window(bundle, *, now=None, descriptor=None):
    """Preview disclosure only; approval and the sender recheck independently."""
    current = datetime.now(timezone.utc) if now is None else now
    reason = currentness(bundle, descriptor, now=current)
    checked = current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"status": "unavailable" if reason else "current", "code": reason[0] if reason else None,
            "reason": reason[1] if reason else None, "checked_at": checked}


def media_for_draft(draft, *, now=None, store=None):
    """Exact reviewed recipe only; any mismatch refuses before upload."""
    kind = kind_of(draft["media_attachment"])
    if kind == TEMPERATURE:
        return temperature.media_for_draft(draft)
    if kind in STORE_KINDS:
        return _module(kind).media_for_draft(draft, now=now, store=store)
    return hazard.media_for_draft(draft, now=now)


def recheck_before_upload(draft, *, now=None):
    """Every family rechecks its unchanged source-time rule immediately before upload."""
    return _module(kind_of(draft["media_attachment"])).recheck_before_upload(draft, now=now)
