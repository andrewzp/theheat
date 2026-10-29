"""Exact published originals (charts/maps and NWS radar) for explicitly selected Gist posts.

Two allowlisted products only; never an arbitrary URL proxy or a new source:

- ``nws_ktlx_radar_v1``: the accepted P31-I4 KTLX Local Standard reflectivity frame,
  qualified by ``published_radar`` (catastrophic Tornado Warning, Oklahoma City
  named point strictly inside the warning polygon, frame minute inside the warning
  interval, 15-minute editorial ceiling).
- ``nhc_track_cone_v1``: an NHC track forecast cone graphic for the draft's own NHC
  storm and advisory (6-hour editorial ceiling from the advisory issue time).

The original bytes, a pixel-equivalent canonical PNG derivative (the bytes sent to
X), the product metadata document and the retained receipt/product/reuse references
live in the durable media store under one immutable manifest. Gist stores only the
manifest SHA256 in a bounded descriptor. Software checks bytes, identities, times
and the source association; a person attests the visible labels and reuse
conditions in the same joint review. Nothing here fetches, crops, recolours,
rescales, overlays or redraws. Reflectivity is not rainfall, impact or a tornado.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
import re

from src.commands.schema import utc_datetime, utc_text
from src.editorial.revisions import fingerprint
from src.media import canonical_png, gist_assets, published_radar as radar
from src.media.gist_hazard_media import (MAX_DELIVERY, MAX_DESCRIPTOR_BYTES, MAX_FULL_DESCRIPTION_BYTES,
                                         MediaWithheld, _aware_now, _digest, _exact, _is_sha, _resource,
                                         _text_identity)

RADAR, CHART = "gist_published_radar_v1", "gist_published_chart_v1"
KINDS = frozenset({RADAR, CHART})
SCHEMA_VERSION = 1
CONVERTER_VERSION = "gist-published-png-1"
METHOD = "decode_rgba_canonical_png_v1"
MANIFEST_KIND = "theheat_published_asset_v1"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_ORIGINAL_BYTES = 2 * 1024 * 1024
MAX_DERIVATIVE_BYTES = 8 * 1024 * 1024
MAX_REFERENCE_BYTES = 64 * 1024
CONVERTER_FILES = ("src/media/gist_media.py", "src/media/gist_published_media.py", "src/media/canonical_png.py",
                   "src/media/gist_assets.py", "src/media/published_radar.py")
NHC_PRODUCT_URL = "https://www.nhc.noaa.gov/aboutcone.shtml"
NHC_URL = re.compile(r"https://www\.nhc\.noaa\.gov/storm_graphics/(AT|EP|CP)(\d{2})/"
                     r"(AL|EP|CP)(\d{2})(\d{4})_5day_cone_with_line_and_wind(?:_sm2)?\.png\Z")
CYCLONE_SIGNALS = frozenset({"cyclone_rapid_intensification", "cyclone_tier_crossing", "cyclone_landfall",
                             "cyclone_land_threat", "cyclone_basin_record"})
CONE_HOURS = 6
CONE_CREDIT = "NATIONAL HURRICANE CENTER"
PRODUCTS = {
    radar.FAMILY: dict(kind=RADAR, derivation="ktlx_radar_delivery_v1", label="Published NWS radar",
                       attestations=("named_point_context_matches", "raster_labels_match",
                                     "unaltered_product_reuse_conditions_met")),
    "nhc_track_cone_v1": dict(kind=CHART, derivation="nhc_cone_delivery_v1", label="Published NHC forecast cone",
                              attestations=("chart_labels_match", "storm_and_advisory_match",
                                            "unaltered_product_reuse_conditions_met")),
}
ATTESTATION_TEXT = {
    "raster_labels_match": "The original shows KTLX, this exact UTC frame time, the dBZ scale and warning legend.",
    "named_point_context_matches": "The Oklahoma City label is visible and is the context this tweet uses.",
    "chart_labels_match": "The original shows this storm, advisory number, issue time and the cone legend.",
    "storm_and_advisory_match": "The cone is for the same storm and advisory as the tweet's NHC source.",
    "unaltered_product_reuse_conditions_met": "The image is unaltered, credits NWS/NHC and implies no endorsement.",
}
_TOP = frozenset({"schema_version", "kind", "product", "synthetic", "asset", "source", "converter",
                  "attestations", "description"})
_ASSET = frozenset({"manifest_sha256", "original_sha256", "original_bytes", "original_mime", "derivative_sha256",
                    "derivative_bytes", "width", "height"})
_SOURCE = {
    radar.FAMILY: frozenset({"bundle_sha256", "source_feature_sha256", "point_sha256", "frame_minute_utc",
                             "valid_end", "useful_until"}),
    "nhc_track_cone_v1": frozenset({"bundle_sha256", "storm_id", "advisory_number", "issued_utc", "useful_until"}),
}
_CONVERTER = frozenset({"version", "method", "png_codec", "pillow", "files"})
_DESCRIPTION = frozenset({"derivation", "delivery_text", "delivery_sha256", "delivery_scalars", "delivery_bytes",
                          "full_sha256", "full_bytes"})


def _require(condition, code, reason):
    if not condition:
        raise MediaWithheld(code, reason)


def product_for(bundle):
    """The single allowlisted product a retained source can request, else None."""
    if type(bundle) is not dict:
        return None
    raw = bundle.get("raw_signal_dump")
    if bundle.get("signal_kind") == "severe_weather" and type(raw) is dict and "source_evidence" in raw:
        return radar.FAMILY
    if bundle.get("signal_kind") in CYCLONE_SIGNALS and type(raw) is dict and raw.get("source") == "nhc":
        return "nhc_track_cone_v1"
    return None


def claims(bundle):
    return product_for(bundle) is not None


def converter_identity():
    from PIL import __version__ as pillow_version
    return {"version": CONVERTER_VERSION, "method": METHOD, "png_codec": canonical_png.PROFILE,
            "pillow": pillow_version, "files": {path: _digest(_resource(path)) for path in CONVERTER_FILES}}


# ------------------------------------------------------------------ documents

def _text(value, code="media_asset_invalid"):
    _require(type(value) is str and 0 < len(value.encode("utf-8")) <= 2048
             and not any(ord(c) < 32 for c in value), code, "invalid published metadata text")


def _cone_document(value):
    """Strict NHC cone metadata; caller assertions until a person attests them."""
    _require(len(gist_assets.encode_document(value)) <= radar.MAX_INPUT, "media_asset_invalid", "metadata too large")
    _require(_exact(value, {"schema_version", "family", "source_url", "original", "retrieved_at", "receipt",
                            "metadata", "references", "synthetic", "metadata_status"})
             and value["schema_version"] == 1 and type(value["schema_version"]) is int
             and value["family"] == "nhc_track_cone_v1" and value["metadata_status"] == "unreviewed"
             and type(value["synthetic"]) is bool, "media_asset_invalid", "unsupported published product")
    match = NHC_URL.fullmatch(value["source_url"]) if type(value["source_url"]) is str else None
    _require(match is not None, "media_asset_invalid", "source URL is outside the allowlisted NHC graphic path")
    assert match is not None
    original = value["original"]
    _require(_exact(original, {"sha256", "byte_count", "mime_type", "width", "height", "frame_count"})
             and _is_sha(original["sha256"])
             and all(type(original[k]) is int for k in ("byte_count", "width", "height", "frame_count"))
             and 0 < original["byte_count"] <= MAX_ORIGINAL_BYTES and original["mime_type"] in ("image/png", "image/gif")
             and 300 <= original["width"] <= 2400 and 300 <= original["height"] <= 2400
             and original["frame_count"] == 1, "media_asset_invalid", "unsupported original image")
    utc_datetime(value["retrieved_at"])
    _require(_exact(value["receipt"], {"sha256", "byte_count"}) and _is_sha(value["receipt"]["sha256"])
             and type(value["receipt"]["byte_count"]) is int
             and 0 < value["receipt"]["byte_count"] <= MAX_REFERENCE_BYTES, "media_asset_invalid", "invalid receipt")
    meta = value["metadata"]
    _require(_exact(meta, {"storm_id", "storm_name", "advisory_number", "issued_utc", "time_literal", "product",
                           "legend", "credit", "marks"}), "media_asset_invalid", "invalid cone metadata")
    for key in ("storm_name", "advisory_number", "time_literal"):
        _text(meta[key])
    _require(type(meta["storm_id"]) is str and re.fullmatch(r"(AL|EP|CP)\d{6}", meta["storm_id"]) is not None
             and meta["storm_id"][:2] == match[3] and meta["storm_id"][2:4] == match[4]
             and meta["storm_id"][4:] == match[5] and {"AL": "AT", "EP": "EP", "CP": "CP"}[match[3]] == match[1]
             and match[2] == match[4], "media_asset_invalid", "storm identity differs from the graphic path")
    _require(meta["issued_utc"] == utc_text(utc_datetime(meta["issued_utc"]))
             and utc_datetime(meta["issued_utc"]) <= utc_datetime(value["retrieved_at"]),
             "media_asset_invalid", "issue time must be exact UTC and precede retrieval")
    _require(meta["product"] == "NHC track forecast cone" and meta["credit"] == CONE_CREDIT,
             "media_asset_invalid", "unsupported product label")
    _require(type(meta["legend"]) is list and 0 < len(meta["legend"]) <= 32
             and type(meta["marks"]) is list and len(meta["marks"]) <= 8, "media_asset_invalid", "invalid legend")
    for label in [*meta["legend"], *meta["marks"]]:
        _text(label)
    refs = value["references"]
    _require(_exact(refs, {"product", "reuse"}), "media_asset_invalid", "invalid references")
    for key, url in (("product", NHC_PRODUCT_URL), ("reuse", radar.REUSE_URL)):
        ref = refs[key]
        _require(_exact(ref, {"url", "sha256", "byte_count"}) and ref["url"] == url and _is_sha(ref["sha256"])
                 and type(ref["byte_count"]) is int and 0 < ref["byte_count"] <= MAX_REFERENCE_BYTES,
                 "media_asset_invalid", "a required product or reuse reference is missing")
    return deepcopy(value)


def document(product, value):
    """Product-specific strict document; unknown rights/labels never default to accepted."""
    _require(product in PRODUCTS, "media_unsupported", "unsupported published product")
    try:
        return radar.document(value) if product == radar.FAMILY else _cone_document(value)
    except MediaWithheld:
        raise
    except (radar.RadarHold, ValueError, TypeError, KeyError, AttributeError) as exc:
        reason = getattr(exc, "code", None) or "invalid published metadata"
        raise MediaWithheld("media_asset_invalid", reason) from None


def _decode_rgba(raw, original):
    """Bounded decode of a GIF/PNG original after its header dimensions are checked."""
    from PIL import Image
    width, height = original["width"], original["height"]
    if original["mime_type"] == "image/png":
        dims = canonical_png.inspect(raw, max_bytes=MAX_ORIGINAL_BYTES, max_width=2400, max_height=2400)[:2]
    else:
        _require(raw[:6] in (b"GIF87a", b"GIF89a") and len(raw) >= 13, "media_asset_invalid", "original is not a GIF")
        dims = (int.from_bytes(raw[6:8], "little"), int.from_bytes(raw[8:10], "little"))
    _require(dims == (width, height), "media_asset_invalid", "original dimensions differ from its metadata")
    try:
        with Image.open(BytesIO(raw)) as image:
            _require(image.size == (width, height) and image.format == {"image/png": "PNG", "image/gif": "GIF"}[
                original["mime_type"]] and getattr(image, "n_frames", 1) == 1
                and not getattr(image, "is_animated", False), "media_asset_invalid",
                "original must be one static frame of its declared format")
            image.load()
            return image.convert("RGBA").tobytes()
    except MediaWithheld:
        raise
    except (OSError, ValueError, EOFError, Image.DecompressionBombError):
        raise MediaWithheld("media_asset_invalid", "the original image could not be decoded") from None


def derive(raw, original):
    """The bytes sent to X: canonical RGBA PNG of the exact decoded original pixels."""
    rgba = _decode_rgba(raw, original)
    try:
        png = canonical_png.encode("RGBA", original["width"], original["height"], rgba,
                                   max_bytes=MAX_DERIVATIVE_BYTES)
    except canonical_png.CanonicalPNGError:
        raise MediaWithheld("media_asset_invalid", "the pixel-equivalent PNG exceeds its bound") from None
    return png, _digest(rgba)


# ------------------------------------------------------------------ retention

def retain(store, product, value, original, references, receipt):
    """Local retention of already acquired bytes: no fetch, no review, no approval."""
    value = document(product, value)
    _require(type(original) is bytes and len(original) == value["original"]["byte_count"]
             and _digest(original) == value["original"]["sha256"], "media_asset_invalid",
             "original bytes differ from their metadata")
    _require(type(references) is dict and set(references) == {"product", "reuse"}, "media_asset_invalid",
             "product and reuse references are both required")
    for name, raw in {**references, "receipt": receipt}.items():
        expected = value["receipt"] if name == "receipt" else value["references"][name]
        _require(type(raw) is bytes and len(raw) == expected["byte_count"] and _digest(raw) == expected["sha256"],
                 "media_asset_invalid", "a retained reference differs from its metadata")
    png, pixels = derive(original, value["original"])
    manifest = {"schema_version": 1, "kind": MANIFEST_KIND, "product": product, "document": value,
                "derivative": {"sha256": _digest(png), "byte_count": len(png), "width": value["original"]["width"],
                               "height": value["original"]["height"], "mode": "RGBA", "pixels_sha256": pixels,
                               "codec": canonical_png.PROFILE, "method": METHOD}}
    raw_manifest = gist_assets.encode_document(manifest)
    _require(len(raw_manifest) <= MAX_MANIFEST_BYTES, "media_asset_invalid", "manifest too large")
    store.put_many([original, png, receipt, references["product"], references["reuse"], raw_manifest])
    return _digest(raw_manifest)


def read(store, manifest_sha256):
    """Exact retained asset: every byte, identity and the derivative relation re-verified."""
    try:
        manifest = gist_assets.get_document(store, manifest_sha256, limit=MAX_MANIFEST_BYTES)
        _require(_exact(manifest, {"schema_version", "kind", "product", "document", "derivative"})
                 and manifest["schema_version"] == 1 and manifest["kind"] == MANIFEST_KIND
                 and manifest["product"] in PRODUCTS, "media_asset_changed", "unsupported retained manifest")
        value = document(manifest["product"], manifest["document"])
        derivative = manifest["derivative"]
        _require(_exact(derivative, {"sha256", "byte_count", "width", "height", "mode", "pixels_sha256", "codec",
                                     "method"}) and derivative["codec"] == canonical_png.PROFILE
                 and derivative["method"] == METHOD and derivative["mode"] == "RGBA"
                 and (derivative["width"], derivative["height"]) == (value["original"]["width"],
                                                                    value["original"]["height"])
                 and type(derivative["byte_count"]) is int
                 and 0 < derivative["byte_count"] <= MAX_DERIVATIVE_BYTES, "media_renderer_changed",
                 "the retained derivative profile changed; retain and review again")
        original = store.get(value["original"]["sha256"], limit=value["original"]["byte_count"])
        for row in (value["receipt"], *value["references"].values()):
            _require(len(store.get(row["sha256"], limit=row["byte_count"])) == row["byte_count"],
                     "media_asset_changed", "a retained reference changed")
        png = store.get(derivative["sha256"], limit=derivative["byte_count"])
    except gist_assets.MediaStoreError as exc:
        code = "media_original_missing" if exc.code == "media_asset_missing" else exc.code
        raise MediaWithheld(code, str(exc).removeprefix("Image withheld: ")) from None
    _require(len(png) == derivative["byte_count"], "media_asset_changed", "derivative length changed")
    rebuilt, pixels = derive(original, value["original"])
    _require(rebuilt == png and pixels == derivative["pixels_sha256"], "media_asset_changed",
             "the derivative is no longer the exact canonical image of the original")
    return manifest, original, png


# ------------------------------------------------------------------ association

def _registry():
    raw = (Path(__file__).resolve().parents[2] / "data/place_registry.json").read_bytes()
    _require(len(raw) <= 2_000_000, "media_source_unqualified", "registry bound")
    rows = [p for p in json.loads(raw)["places"] if p["place_id"] == radar.POINT["place_id"]]
    _require(len(rows) == 1, "media_source_unqualified", "registry point changed")
    point = dict(place_id=rows[0]["place_id"], label=rows[0]["city"], latitude=rows[0]["lat"],
                 longitude=rows[0]["lon"])
    return point, _digest(raw)


def _radar_source(bundle):
    try:
        envelope, start, end = radar.source(bundle)
    except (radar.RadarHold, ValueError, KeyError, TypeError) as exc:
        raise MediaWithheld("media_source_unqualified", getattr(exc, "code", "radar source not qualified")) from None
    return envelope, start, end


def _exact_utc(value):
    """An aware ISO timestamp as canonical UTC text; never a date-only or naive value."""
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        parsed = None
    _require(parsed is not None and parsed.tzinfo is not None and "T" in str(value), "media_source_unqualified",
             "the NHC advisory time is not an exact UTC instant")
    assert parsed is not None
    return utc_text(parsed)


def association(product, bundle, value):
    """Exact source relation between the saved draft source and the retained product."""
    if product == radar.FAMILY:
        envelope, start, end = _radar_source(bundle)
        point, registry_sha = _registry()
        _require(point == radar.POINT and registry_sha == value["metadata"]["point"]["registry_sha256"],
                 "media_source_changed", "the named-point registry changed")
        try:
            radar.contains(envelope["feature"]["geometry"], point)
        except radar.RadarHold as exc:
            raise MediaWithheld("media_context_mismatch", exc.code) from None
        minute = utc_datetime(value["metadata"]["frame_minute_utc"])
        _require(utc_datetime(start) <= minute and minute + timedelta(minutes=1) <= utc_datetime(end),
                 "media_context_mismatch", "the radar frame is outside the warning interval")
        deadline = min(minute + timedelta(minutes=15), utc_datetime(end))
        return {"bundle_sha256": fingerprint(bundle), "source_feature_sha256": envelope["feature_sha256"],
                "point_sha256": fingerprint(dict(point=point, registry_sha256=registry_sha)),
                "frame_minute_utc": utc_text(minute), "valid_end": end, "useful_until": utc_text(deadline)}
    raw, meta = bundle["raw_signal_dump"], value["metadata"]
    issued = _exact_utc(raw.get("issued_at"))
    _require(raw.get("source") == "nhc" and raw.get("storm_id") == meta["storm_id"]
             and str(raw.get("advisory_number")) == meta["advisory_number"] and issued == meta["issued_utc"],
             "media_context_mismatch", "the cone is not for this draft's NHC storm and advisory")
    until = utc_datetime(meta["issued_utc"]) + timedelta(hours=CONE_HOURS)
    return {"bundle_sha256": fingerprint(bundle), "storm_id": meta["storm_id"],
            "advisory_number": meta["advisory_number"], "issued_utc": meta["issued_utc"],
            "useful_until": utc_text(until)}


def currentness(descriptor, now=None):
    """Editorial ceilings from the reviewed descriptor: radar 15 min, cone 6 h; None when current."""
    current = _aware_now(now)
    try:
        source = descriptor["source"]
        start = utc_datetime(source["frame_minute_utc"] if descriptor["kind"] == RADAR else source["issued_utc"])
        until = utc_datetime(source["useful_until"])
    except (KeyError, TypeError, ValueError):
        return ("media_source_unqualified", "the retained published time is not qualified")
    if current < start:
        return ("media_source_future", "the published image time is in the future")
    if current >= until:
        return ("media_published_stale", "the published image is past its editorial ceiling"
                + (" (15 minutes for radar)" if descriptor["kind"] == RADAR else " (6 hours for the forecast cone)"))
    return None


# ------------------------------------------------------------------ descriptions

def _radar_delivery(value, synthetic):
    meta = value["metadata"]
    return (("Invented offline test image. " if synthetic else "")
            + f"Published NWS radar: KTLX station reflectivity (dBZ), frame {meta['time_literal']}. "
            + radar.CONTEXT + " "
            + "Original NOAA/NWS image unaltered, shown as a pixel-equivalent PNG. "
            + "Reflectivity scale: " + ", ".join(radar.SCALE) + "; nd has no numeric value. "
            + "Warning legend: " + ", ".join(radar.LEGEND) + ". "
            + "Reflectivity is not rainfall, a tornado detection or damage. "
            + "Labels checked by a person; software did not read the image. "
            + "Credit: National Weather Service; no endorsement implied.")


def _cone_delivery(value, synthetic):
    meta = value["metadata"]
    return (("Invented offline test image. " if synthetic else "")
            + f"Published NHC track forecast cone: {meta['storm_name']} ({meta['storm_id']}), advisory "
            + f"{meta['advisory_number']}, issued {meta['time_literal']} ({meta['issued_utc']}). "
            + "Forecast, not observation. The cone shows the probable track of the storm's centre: circles along "
            + "the forecast track enclose about two-thirds of historical official forecast errors. "
            + "It does not show the storm's size, and hazards can occur outside it. "
            + "Legend: " + "; ".join(meta["legend"]) + ". "
            + "Original NHC graphic unaltered, shown as a pixel-equivalent PNG. "
            + "Labels checked by a person; software did not read the image. "
            + "Credit: National Hurricane Center (NWS); no endorsement implied.")


def _full(product, value, manifest_sha256, association_value):
    refs = value["references"]
    lines = [f"Product: {PRODUCTS[product]['label']} ({product}).",
             f"Source URL (not fetched here): {value['source_url']}.",
             f"Retrieved {value['retrieved_at']}; receipt SHA256 {value['receipt']['sha256']}.",
             f"Original {value['original']['mime_type']} {value['original']['width']}x{value['original']['height']}, "
             f"{value['original']['byte_count']} bytes, SHA256 {value['original']['sha256']}.",
             f"Reuse basis: {refs['reuse']['url']} (retained SHA256 {refs['reuse']['sha256']}); unaltered, "
             "credited, no ownership or endorsement implied.",
             f"Product reference: {refs['product']['url']} (retained SHA256 {refs['product']['sha256']}).",
             f"Asset manifest SHA256 {manifest_sha256}.",
             "Source association: " + json.dumps(association_value, sort_keys=True) + "."]
    if product == radar.FAMILY:
        meta = value["metadata"]
        lines += [f"Frame time literal: {meta['time_literal']}; minute precision; issue time, subtype and elevation "
                  "unknown.", radar.alt_text({"input": value, "synthetic": value["synthetic"]})]
    else:
        lines.append("Marks: " + (", ".join(value["metadata"]["marks"]) or "none listed") + ".")
    return "\n".join(lines)


def _bounded(text, code="media_description_too_long"):
    raw = _text_identity(text, "media_description_unicode")
    _require(len(text) <= MAX_DELIVERY and len(raw) <= MAX_DELIVERY, code,
             "the mandatory image description exceeds the 1000-character/1000-byte house limit; "
             "the text draft is unchanged")
    return raw


# ------------------------------------------------------------------ recipe

def prepare_media(bundle, store, manifest_sha256, *, synthetic=False, now=None):
    """Read and verify the retained asset, qualify its source relation, build the recipe."""
    product = product_for(bundle)
    _require(product is not None, "media_unsupported", "unsupported source for a published image")
    _require(_is_sha(manifest_sha256), "media_retained_input_required", "select a retained published asset")
    manifest, original, png = read(store, manifest_sha256)
    _require(manifest["product"] == product, "media_context_mismatch", "the retained asset is a different product")
    value = manifest["document"]
    _require(type(synthetic) is bool, "media_unsupported", "synthetic status must be explicit")
    _require(utc_datetime(value["retrieved_at"]) <= _aware_now(now), "media_source_future",
             "the retained retrieval time is in the future")
    relation = association(product, bundle, value)
    family = PRODUCTS[product]
    delivery = (_radar_delivery if product == radar.FAMILY else _cone_delivery)(value, value["synthetic"])
    delivery_raw = _bounded(delivery)
    full = _full(product, value, manifest_sha256, relation)
    full_raw = _text_identity(full, "media_description_unicode")
    _require(0 < len(full_raw) <= MAX_FULL_DESCRIPTION_BYTES, "media_description_too_long", "full description bound")
    derivative = manifest["derivative"]
    descriptor = {
        "schema_version": SCHEMA_VERSION, "kind": family["kind"], "product": product, "synthetic": value["synthetic"],
        "asset": {"manifest_sha256": manifest_sha256, "original_sha256": value["original"]["sha256"],
                  "original_bytes": value["original"]["byte_count"], "original_mime": value["original"]["mime_type"],
                  "derivative_sha256": derivative["sha256"], "derivative_bytes": derivative["byte_count"],
                  "width": derivative["width"], "height": derivative["height"]},
        "source": relation, "converter": converter_identity(),
        "attestations": {"version": 1, "required": list(family["attestations"])},
        "description": {"derivation": family["derivation"], "delivery_text": delivery,
                        "delivery_sha256": _digest(delivery_raw), "delivery_scalars": len(delivery),
                        "delivery_bytes": len(delivery_raw), "full_sha256": _digest(full_raw),
                        "full_bytes": len(full_raw)},
    }
    if not value["synthetic"]:
        validate_descriptor(descriptor, bundle)
    meta = value["metadata"]
    title = (f"KTLX reflectivity · {meta['time_literal']}" if product == radar.FAMILY
             else f"NHC forecast cone · {meta['storm_name']} advisory {meta['advisory_number']}")
    inspection = {"product": product, "label": family["label"], "source_url": value["source_url"],
                  "retrieved_at": value["retrieved_at"],
                  "attribution": "National Weather Service" if product == radar.FAMILY else "National Hurricane Center (NWS)",
                  "reuse_url": value["references"]["reuse"]["url"],
                  "product_reference_url": value["references"]["product"]["url"],
                  "time_literal": meta["time_literal"],
                  "quantity": ("station reflectivity, dBZ" if product == radar.FAMILY
                               else "forecast track of the storm centre (probable-track cone)"),
                  "context": (radar.CONTEXT if product == radar.FAMILY
                              else "Forecast cone for this draft's NHC storm and advisory; not storm size or hazards."),
                  "legend": (radar.SCALE + radar.LEGEND) if product == radar.FAMILY else list(meta["legend"]),
                  "required_attestations": [{"name": name, "text": ATTESTATION_TEXT[name]}
                                            for name in family["attestations"]]}
    return {"kind": family["kind"], "descriptor": descriptor, "png": png, "original": original, "title": title,
            "delivery_text": delivery, "full_text": full, "scope": inspection["context"], "inspection": inspection}


def validate_descriptor(value, bundle):
    """Structure and saved-source binding without the store; the sender rereads every byte."""
    _require(_exact(value, _TOP) and value["kind"] in KINDS, "media_unsupported", "unsupported attachment")
    _require(type(value["schema_version"]) is int and value["schema_version"] == SCHEMA_VERSION,
             "media_unsupported", "unsupported attachment")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MediaWithheld("media_descriptor_invalid", "attachment is not bounded finite JSON") from None
    _require(len(encoded) <= MAX_DESCRIPTOR_BYTES, "media_descriptor_invalid", "attachment too large")
    product = value["product"]
    _require(product in PRODUCTS and PRODUCTS[product]["kind"] == value["kind"], "media_unsupported",
             "unsupported published product")
    _require(value["synthetic"] is False, "media_synthetic", "invented test images cannot be posted")
    _require(product_for(bundle) == product, "media_source_changed", "source family changed")
    asset = value["asset"]
    _require(_exact(asset, _ASSET) and all(_is_sha(asset[k]) for k in ("manifest_sha256", "original_sha256",
                                                                       "derivative_sha256"))
             and all(type(asset[k]) is int for k in ("original_bytes", "derivative_bytes", "width", "height"))
             and 0 < asset["original_bytes"] <= MAX_ORIGINAL_BYTES
             and 0 < asset["derivative_bytes"] <= MAX_DERIVATIVE_BYTES
             and asset["original_mime"] in ("image/gif", "image/png")
             and 1 <= asset["width"] <= 2400 and 1 <= asset["height"] <= 2400,
             "media_descriptor_invalid", "invalid asset identity")
    source = value["source"]
    _require(_exact(source, _SOURCE[product]) and source["bundle_sha256"] == fingerprint(bundle),
             "media_source_changed", "source binding changed")
    raw = bundle["raw_signal_dump"]
    if product == radar.FAMILY:
        envelope, _, end = _radar_source(bundle)
        _require(source["source_feature_sha256"] == envelope["feature_sha256"] and source["valid_end"] == end,
                 "media_source_changed", "the warning source changed")
    else:
        _require(raw.get("storm_id") == source["storm_id"]
                 and str(raw.get("advisory_number")) == source["advisory_number"],
                 "media_source_changed", "the NHC storm or advisory changed")
    _require(value["converter"] == converter_identity(), "media_renderer_changed",
             "the published-image converter changed; preview and review again")
    _require(value["attestations"] == {"version": 1, "required": list(PRODUCTS[product]["attestations"])},
             "media_descriptor_invalid", "required published-image attestations changed")
    description = value["description"]
    _require(_exact(description, _DESCRIPTION) and description["derivation"] == PRODUCTS[product]["derivation"]
             and all(type(description[k]) is int for k in ("delivery_scalars", "delivery_bytes", "full_bytes"))
             and _is_sha(description["delivery_sha256"]) and _is_sha(description["full_sha256"])
             and 0 < description["full_bytes"] <= MAX_FULL_DESCRIPTION_BYTES,
             "media_descriptor_invalid", "invalid description identity")
    text = description["delivery_text"]
    _require(type(text) is str, "media_descriptor_invalid", "invalid description")
    raw_text = _bounded(text, "media_description_changed")
    _require(description["delivery_scalars"] == len(text) and description["delivery_bytes"] == len(raw_text)
             and description["delivery_sha256"] == _digest(raw_text), "media_description_changed",
             "description changed")
    return value


def recheck_before_upload(draft, *, now=None):
    reason = currentness(draft["media_attachment"], now)
    if reason:
        raise MediaWithheld(*reason)


def media_for_draft(draft, *, now=None, store=None):
    """Exact reviewed asset only: reread and reverify the store, refuse any difference."""
    bundle = draft["review_context"]["two_bot"]["bundle"]
    attached = validate_descriptor(draft["media_attachment"], bundle)
    _require(not draft.get("hot10_rows"), "media_two_images", "only one explicitly selected image is allowed")
    reason = currentness(attached, now)
    if reason:
        raise MediaWithheld(*reason)
    store = gist_assets.configured() if store is None else store
    prepared = prepare_media(bundle, store, attached["asset"]["manifest_sha256"], now=now)
    _require(prepared["descriptor"] == attached, "media_render_mismatch",
             "the published image, description or source relation changed; preview and review again")
    return prepared["png"], prepared["delivery_text"]
