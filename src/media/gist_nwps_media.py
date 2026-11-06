"""Manual Gist image for the exact source packet saved with a river draft."""

from src.editorial.revisions import fingerprint
from src.media import gist_hazard_media as media, nwps_capture
from src.media.nwps_forecast_png import VERSION, render_nwps_png
from src.media.nwps_graphic_adapter import TEMPLATE, TEMPLATE_VERSION, nwps_graphic_spec, source_context
from src.two_bot.intern.nwps_forecast import forecast_source_hold

KIND = "gist_nwps_forecast_v1"
SOURCE = "NOAA/NWS National Water Prediction Service"
_PINS = {"renderer_sha256": "src/media/nwps_forecast_png.py",
         "canvas_sha256": "src/media/gist_hazard_media.py",
         "codec_sha256": "src/media/canonical_png.py", "font_sha256": media.FONT}
_HASHES = {"source_evidence_sha256", "source_context_sha256", "png_sha256", "alt_sha256", *_PINS}


def claims(bundle):
    raw = bundle.get("raw_signal_dump") if type(bundle) is dict else None
    return type(raw) is dict and bundle.get("signal_kind") == "river_flood" and "nwps_index_hint" in raw


def validate_descriptor(value, bundle, review_context):
    require = media._require
    require(claims(bundle) and media._exact(value, {"kind", "schema_version", "reference", "binding",
                                                    "series_sha256", "alt_text", "byte_count"})
            and value["kind"] == KIND and type(value["schema_version"]) is int and value["schema_version"] == 1,
            "media_descriptor_invalid", "invalid river image recipe")
    reference = nwps_capture._reference(review_context.get(nwps_capture.CONTEXT_KEY), bundle)
    supplied = nwps_capture._reference(value["reference"], bundle)
    require(reference == supplied, "media_source_packet_mismatch", "the draft's own river packet changed")
    binding = value["binding"]
    require(media._exact(binding, {"template", "template_version", "renderer_version", *_HASHES})
            and binding["template"] == TEMPLATE and binding["template_version"] == TEMPLATE_VERSION
            and binding["renderer_version"] == VERSION and all(media._is_sha(binding[k]) for k in _HASHES)
            and all(binding[k] == media._digest(media._resource(path)) for k, path in _PINS.items()),
            "media_renderer_changed", "river image renderer changed; preview again")
    text = value["alt_text"]
    encoded = media._text_identity(text, "media_description_unicode")
    require(type(text) is str and 0 < len(text) <= media.MAX_DELIVERY and 0 < len(encoded) <= media.MAX_DELIVERY
            and media._digest(encoded) == binding["alt_sha256"] and media._is_sha(value["series_sha256"])
            and type(value["byte_count"]) is int and 0 < value["byte_count"] <= media.MAX_PNG_BYTES,
            "media_descriptor_invalid", "invalid river image or description identity")
    return value


def prepare(bundle, review_context, store=None):
    reference = nwps_capture._reference(review_context.get(nwps_capture.CONTEXT_KEY), bundle)
    capture = nwps_capture.load(bundle, reference, store)
    spec = nwps_graphic_spec(bundle, capture, expected_bundle_sha256=reference["bundle_sha256"],
                             expected_capture_sha256=reference["capture_sha256"])
    context = source_context(spec["evidence"])
    result = render_nwps_png(spec, context)
    descriptor = {"schema_version": 1, "kind": KIND, "reference": dict(reference),
                  "binding": result["binding"], "series_sha256": fingerprint(capture["forecast"]["data"]),
                  "alt_text": result["alt_text"], "byte_count": len(result["png"])}
    validate_descriptor(descriptor, bundle, review_context)
    return {**result, "descriptor": descriptor, "source_context": context,
            "delivery_text": result["alt_text"], "full_text": result["alt_text"]}


def currentness(bundle, now=None):
    if forecast_source_hold(bundle, live=False, clock=lambda: media._aware_now(now)):
        return "media_source_stale", "the saved river forecast is outside its current-source window"
    return None


def recheck_before_upload(draft, *, now=None):
    reason = currentness(draft["review_context"]["two_bot"]["bundle"], now)
    if reason:
        raise media.MediaWithheld(*reason)


def media_for_draft(draft, *, now=None, store=None):
    review = draft["review_context"]
    bundle = review["two_bot"]["bundle"]
    attached = validate_descriptor(draft["media_attachment"], bundle, review)
    recheck_before_upload(draft, now=now)
    prepared = prepare(bundle, review, store)
    media._require(prepared["descriptor"] == attached, "media_render_mismatch",
                   "river image, forecast series or description changed; preview and review again")
    return prepared["png"], prepared["delivery_text"]
