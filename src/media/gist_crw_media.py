"""NOAA CRW regional SST anomaly sampled-cell chart for explicitly selected Gist posts.

The existing qualified adapter (crw_graphic_adapter) reconstructs every claim from a
retained CSV/metadata source packet. Production bundles carry only its provenance, so
the packet must already be retained in the durable media store; otherwise the image
holds with ``media_source_packet_missing``. No fetch, fallback or source substitution.

The chart shows each valid 1-degree sampled cell as a separate square on a symmetric
diverging scale: an L4 satellite analysis against the product's own daily
climatology (1985-1990 + 1993 reference), never a continuous surface, a full-grid
census, a thermometer reading or a 1991-2020 anomaly.
"""
from __future__ import annotations

import csv
from datetime import date
from io import StringIO
import json
import math

from src.data import crw_contract
from src.data.ocean_sst_anomaly import REGION_REGISTRY
from src.data.source_status import SourceFetchError
from src.editorial.revisions import fingerprint
from src.media import crw_graphic_adapter as adapter, gist_assets
from src.media import gist_hazard_media as hazard
from src.media.gist_hazard_media import HEIGHT, WIDTH, MediaWithheld
from src.media.temperature_graphic_adapter import _StoredBundle

KIND = "gist_crw_anomaly_v1"
SCHEMA_VERSION = 1
TEMPLATE = "crw_sampled_cells"
TEMPLATE_VERSION = "p31-crw-gist-cells-1"
RENDERER_VERSION = "gist-crw-png-1"
DERIVATION = "crw_delivery_v1"
SIGNAL = "regional_sst_anomaly"
FILES = ("src/media/gist_media.py", "src/media/gist_crw_media.py", "src/media/gist_hazard_media.py",
         "src/media/canonical_png.py", "src/media/gist_assets.py", hazard.FONT,
         "src/media/crw_graphic_adapter.py", "src/data/crw_contract.py", "src/data/ocean_sst_anomaly.py",
         "src/two_bot/intern/marine.py", "src/media/temperature_graphic_adapter.py")
MAX_PACKET_BYTES = adapter.PACKET_LIMIT
_TOP = frozenset({"schema_version", "kind", "template", "template_version", "adapter_version", "synthetic",
                  "source", "renderer", "image", "description"})
_SOURCE = frozenset({"bundle_sha256", "evidence_sha256", "packet_artifact_sha256", "packet_sha256",
                     "region_slug", "product_date", "valid_cells", "total_cells"})
_RENDERER = frozenset({"version", "files", "pillow", "freetype", "png_codec", "layout", "width", "height"})
# ColorBrewer RdBu (colourblind-safe diverging): cool, neutral, warm.
COOL, NEUTRAL, WARM = (33, 102, 172), (247, 247, 247), (178, 24, 43)
BACKGROUND, INK, MUTED, EXCLUDED = "#0b0f14", "#f4f4f5", "#b6bdcb", "#6b7280"


def _require(condition, code, reason):
    if not condition:
        raise MediaWithheld(code, reason)


def claims(bundle):
    return type(bundle) is dict and bundle.get("signal_kind") == SIGNAL


def renderer_identity():
    from PIL import features, __version__ as pillow_version
    from src.media import canonical_png
    return {"version": RENDERER_VERSION, "files": {path: hazard._digest(hazard._resource(path)) for path in FILES},
            "pillow": pillow_version, "freetype": features.version("freetype2"), "png_codec": canonical_png.PROFILE,
            "layout": "basic", "width": WIDTH, "height": HEIGHT}


def load_packet(store, packet_artifact_sha256):
    """The retained CRW packet by its exact store identity; never a URL or path."""
    try:
        packet = gist_assets.get_document(store, packet_artifact_sha256, limit=MAX_PACKET_BYTES)
    except gist_assets.MediaStoreError as exc:
        if exc.code == "media_asset_missing":
            raise MediaWithheld("media_source_packet_missing",
                                "the retained CRW source packet is not in the media store; "
                                "nothing can be redrawn without it") from None
        raise MediaWithheld(exc.code, str(exc).removeprefix("Image withheld: ")) from None
    return packet


def _spec(bundle, packet, synthetic):
    try:
        return adapter.crw_graphic_spec(_StoredBundle(bundle), packet, expected_bundle_sha256=fingerprint(bundle),
                                        expected_packet_sha256=fingerprint(packet), synthetic=synthetic)
    except (ValueError, KeyError, TypeError, AttributeError, SourceFetchError) as exc:
        raise MediaWithheld("media_source_unqualified", str(exc)[:200] or "unqualified CRW source") from exc


def _cells(evidence):
    """Every sampled cell (lat, lon, value|None), after the adapter's strict validation."""
    region = next(r for r in REGION_REGISTRY if r.display_name == evidence["location"])
    text = evidence["input_binding"]["source_packet"]["csv_utf8"]
    crw_contract.decode_csv(text, region)  # Same strict rules again; never a looser parse.
    rows = list(csv.reader(StringIO(text), strict=True))[2:]
    cells = []
    for row in rows:
        if not row:
            continue
        lat, lon, value = float(row[1]), float(row[2]), float(row[3])
        valid = math.isfinite(value) and value != -327.68 and -15 <= value <= 15
        cells.append((lat, lon, value if valid else None))
    return region, cells


def _signed(value):
    return adapter.signed_anomaly(value).replace("-", "−")


def axis_limit(evidence, cells):
    largest = max([abs(evidence["value"])] + [abs(v) for _, _, v in cells if v is not None])
    return min(15, max(5, math.ceil(largest)))


def _colour(value, limit):
    t = max(-1.0, min(1.0, value / limit))
    end = WARM if t >= 0 else COOL
    t = abs(t)
    return tuple(round(a + (b - a) * t) for a, b in zip(NEUTRAL, end))


def _render(evidence):
    canvas = hazard._Canvas(BACKGROUND)
    region, cells = _cells(evidence)
    limit = axis_limit(evidence, cells)
    synthetic = evidence["synthetic"]
    canvas.text((64, 82), "SYNTHETIC DATA · NOT REAL WEATHER" if synthetic else "NOAA CORAL REEF WATCH · SST",
                size=42, fill=MUTED)
    canvas.wrapped(64, 160, evidence["location"], size=58, fill=INK, lines=2, pitch=68)
    canvas.text((64, 300), f"Product day {evidence['valid_date']} · L4 analysis", size=42, fill=MUTED)
    mean_colour = _colour(evidence["value"], limit)
    canvas.text((64, 450), _signed(evidence["value"]) + "°C", size=130, fill=mean_colour)
    canvas.text((64, 520), "Sampled mean vs CRW daily climatology", size=42, fill=INK)
    # Plate carrée sampled grid: one square per sampled cell with visible gaps between.
    lats = sorted({lat for lat, _, _ in cells}, reverse=True)
    lons = sorted({lon for _, lon, _ in cells})
    top, left, height, width = 560, 64, 520, 1072
    pitch = min(width / len(lons), height / len(lats))
    size = max(2.0, pitch * 0.78)
    x0 = left + (width - pitch * len(lons)) / 2
    y0 = top + (height - pitch * len(lats)) / 2
    row_of, col_of = {v: i for i, v in enumerate(lats)}, {v: i for i, v in enumerate(lons)}
    for lat, lon, value in cells:
        x, y = x0 + col_of[lon] * pitch, y0 + row_of[lat] * pitch
        box = (round(x), round(y), round(x + size), round(y + size))
        if value is None:
            canvas.draw.rectangle(box, outline=EXCLUDED, width=1)
        else:
            canvas.draw.rectangle(box, fill=_colour(value, limit))
    canvas.boxes.append((round(x0), round(y0), round(x0 + pitch * len(lons)), round(y0 + pitch * len(lats))))
    bounds = evidence["sampled_bounds"]
    canvas.text((64, 1130), f"Cells {_lat(bounds[0])}–{_lat(bounds[1])}, {_lon(bounds[2])}–{_lon(bounds[3])}",
                size=42, fill=MUTED)
    # Linear diverging colour bar, symmetric around an explicit zero.
    bar_top, bar_left, bar_width = 1170, 64, 1072
    for step in range(64):
        value = -limit + (2 * limit) * (step + 0.5) / 64
        x = bar_left + bar_width * step / 64
        canvas.draw.rectangle((round(x), bar_top, round(x + bar_width / 64), bar_top + 36), fill=_colour(value, limit))
    canvas.draw.line((bar_left + bar_width / 2, bar_top - 8, bar_left + bar_width / 2, bar_top + 44), fill=INK, width=3)
    canvas.boxes.append((bar_left, bar_top - 8, bar_left + bar_width, bar_top + 44))
    canvas.text((64, 1258), f"−{limit}°C", size=42, fill=MUTED)
    canvas.text((600, 1258), "0", size=42, fill=MUTED, anchor="ms")
    canvas.text((1136, 1258), f"+{limit}°C", size=42, fill=MUTED, anchor="rs")
    canvas.text((64, 1328), f"{evidence['valid_cells']} of {evidence['total_cells']} cells valid · grey excluded",
                size=42, fill=INK)
    canvas.text((64, 1392), "1° sample; not a full-grid average", size=42, fill=MUTED)
    canvas.text((64, 1456), "Ref. 1985–90 + 1993, not 1991–2020", size=42, fill=MUTED)
    return canvas.png()


def _lat(value):
    return f"{abs(value):g}°{'N' if value >= 0 else 'S'}"


def _lon(value):
    return f"{abs(value):g}°{'E' if value >= 0 else 'W'}"


def _delivery(evidence, limit):
    prefix = "SYNTHETIC DEMONSTRATION; not actual weather. " if evidence["synthetic"] else ""
    bounds = evidence["sampled_bounds"]
    text = (prefix
            + f"Chart: NOAA Coral Reef Watch daily 5 km sea-surface temperature anomaly v3.1, {evidence['location']}, "
            + f"product day {evidence['valid_date']}. Satellite analysis (L4), not a thermometer reading. "
            + "Anomaly is against the product's daily climatology (1985-2012, recentred to 1985-1990 plus 1993), "
            + "not a 1991-2020 average. "
            + f"Sampled mean {adapter.signed_anomaly(evidence['value'])}°C, cos-latitude weighted over "
            + f"{evidence['valid_cells']} valid of {evidence['total_cells']} sampled cells "
            + f"({evidence['excluded_cells']} excluded: missing, masked or out of range). "
            + "Each square is one sampled cell on a 1-degree stride, not a continuous surface or full-grid average; "
            + f"grey outlines are excluded cells. Cell centres {_lat(bounds[0])} to {_lat(bounds[1])}, "
            + f"{_lon(bounds[2])} to {_lon(bounds[3])}. "
            + f"Colours: linear blue-white-red scale from -{limit} to +{limit}°C, zero marked. "
            + "No absolute temperature, record, El Niño classification or ecological impact is shown. "
            + f"Retrieved {evidence['evidence_as_of']}.")
    raw = text.encode("utf-8")
    _require(len(text) <= hazard.MAX_DELIVERY and len(raw) <= hazard.MAX_DELIVERY, "media_description_too_long",
             "the mandatory image description exceeds the 1000-character/1000-byte house limit; "
             "the text draft is unchanged")
    return text


def prepare_media(bundle, store, packet_artifact_sha256, *, synthetic=False):
    """Rebuild from the retained packet only; refuse rather than approximate."""
    _require(claims(bundle), "media_unsupported", "unsupported source for a CRW image")
    _require(type(synthetic) is bool, "media_unsupported", "synthetic status must be explicit")
    packet = load_packet(store, packet_artifact_sha256)
    spec = _spec(bundle, packet, synthetic)
    evidence = spec["evidence"]
    try:
        png = _render(evidence)
        region, cells = _cells(evidence)
    except MediaWithheld:
        raise
    except (ValueError, KeyError, TypeError, StopIteration, SourceFetchError) as exc:
        raise MediaWithheld("media_source_unqualified", "retained CRW cells could not be drawn") from exc
    limit = axis_limit(evidence, cells)
    full = adapter.anomaly_alt_text(evidence)
    full_raw = full.encode("utf-8")
    _require(0 < len(full_raw) <= hazard.MAX_FULL_DESCRIPTION_BYTES, "media_description_too_long",
             "full description bound")
    delivery = _delivery(evidence, limit)
    delivery_raw = delivery.encode("utf-8")
    descriptor = {
        "schema_version": SCHEMA_VERSION, "kind": KIND, "template": TEMPLATE, "template_version": TEMPLATE_VERSION,
        "adapter_version": evidence["input_binding"]["adapter_version"], "synthetic": synthetic,
        "source": {"bundle_sha256": fingerprint(bundle), "evidence_sha256": spec["expected_evidence_sha256"],
                   "packet_artifact_sha256": packet_artifact_sha256, "packet_sha256": fingerprint(packet),
                   "region_slug": region.slug, "product_date": evidence["valid_date"],
                   "valid_cells": evidence["valid_cells"], "total_cells": evidence["total_cells"]},
        "renderer": renderer_identity(),
        "image": {"mime_type": "image/png", "png_sha256": hazard._digest(png), "byte_count": len(png),
                  "width": WIDTH, "height": HEIGHT, "mode": "RGB"},
        "description": {"derivation": DERIVATION, "delivery_text": delivery,
                        "delivery_sha256": hazard._digest(delivery_raw), "delivery_scalars": len(delivery),
                        "delivery_bytes": len(delivery_raw), "full_sha256": hazard._digest(full_raw),
                        "full_bytes": len(full_raw)},
    }
    if not synthetic:
        validate_descriptor(descriptor, bundle)
    title = f"Sea-surface temperature anomaly · {evidence['location']}"
    return {"kind": KIND, "descriptor": descriptor, "png": png, "title": title, "delivery_text": delivery,
            "full_text": full, "scope": evidence["scope"]}


def validate_descriptor(value, bundle):
    """Structure, saved-source binding and renderer profile; the sender also rebuilds bytes."""
    _require(hazard._exact(value, _TOP) and value["kind"] == KIND, "media_unsupported", "unsupported attachment")
    _require(type(value["schema_version"]) is int and value["schema_version"] == SCHEMA_VERSION,
             "media_unsupported", "unsupported attachment")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MediaWithheld("media_descriptor_invalid", "attachment is not bounded finite JSON") from None
    _require(len(encoded) <= hazard.MAX_DESCRIPTOR_BYTES, "media_descriptor_invalid", "attachment too large")
    _require(value["template"] == TEMPLATE and value["template_version"] == TEMPLATE_VERSION
             and value["adapter_version"] in adapter.SUPPORTED_ADAPTER_VERSIONS, "media_recipe_changed",
             "graphic template changed; preview and review again")
    _require(value["synthetic"] is False, "media_synthetic", "synthetic demonstrations cannot be posted")
    _require(claims(bundle), "media_source_changed", "source family changed")
    source = value["source"]
    _require(hazard._exact(source, _SOURCE)
             and all(hazard._is_sha(source[k]) for k in ("bundle_sha256", "evidence_sha256",
                                                          "packet_artifact_sha256", "packet_sha256"))
             and type(source["valid_cells"]) is int and type(source["total_cells"]) is int
             and 10 <= source["valid_cells"] <= source["total_cells"] <= 20_000,
             "media_descriptor_invalid", "invalid source binding")
    raw = bundle.get("raw_signal_dump", {}) if type(bundle) is dict else {}
    _require(source["bundle_sha256"] == fingerprint(bundle) and source["region_slug"] == raw.get("region_slug")
             and source["product_date"] == raw.get("date"), "media_source_changed", "source binding changed")
    renderer = value["renderer"]
    _require(hazard._exact(renderer, _RENDERER) and type(renderer["files"]) is dict
             and set(renderer["files"]) == set(FILES) and all(hazard._is_sha(v) for v in renderer["files"].values()),
             "media_descriptor_invalid", "invalid renderer")
    _require(renderer == renderer_identity(), "media_renderer_changed", "render profile changed; preview and review again")
    image = value["image"]
    _require(hazard._exact(image, hazard._IMAGE_KEYS) and image["mime_type"] == "image/png"
             and hazard._is_sha(image["png_sha256"]) and type(image["byte_count"]) is int
             and 0 < image["byte_count"] <= hazard.MAX_PNG_BYTES and image["width"] == WIDTH
             and image["height"] == HEIGHT and image["mode"] == "RGB", "media_descriptor_invalid",
             "invalid image identity")
    description = value["description"]
    _require(hazard._exact(description, hazard._DESCRIPTION_KEYS) and description["derivation"] == DERIVATION
             and all(type(description[k]) is int for k in ("delivery_scalars", "delivery_bytes", "full_bytes"))
             and hazard._is_sha(description["delivery_sha256"]) and hazard._is_sha(description["full_sha256"])
             and 0 < description["full_bytes"] <= hazard.MAX_FULL_DESCRIPTION_BYTES,
             "media_descriptor_invalid", "invalid description identity")
    text = description["delivery_text"]
    _require(type(text) is str, "media_descriptor_invalid", "invalid description")
    raw_text = hazard._text_identity(text, "media_description_unicode")
    _require(0 < len(text) <= hazard.MAX_DELIVERY and len(raw_text) <= hazard.MAX_DELIVERY
             and description["delivery_scalars"] == len(text) and description["delivery_bytes"] == len(raw_text)
             and description["delivery_sha256"] == hazard._digest(raw_text), "media_description_changed",
             "description changed or exceeds the house limit")
    return value


def currentness(bundle, now=None):
    """The unchanged CRW source rule (product day 0-5 days old); None when current."""
    current = hazard._aware_now(now)
    try:
        crw_contract.fresh_day(bundle["raw_signal_dump"]["date"], current.date())
    except SourceFetchError:
        try:
            future = date.fromisoformat(bundle["raw_signal_dump"]["date"]) > current.date()
        except (ValueError, TypeError, KeyError):
            future = False
        if future:
            return ("media_source_future", "the CRW product day is in the future")
        return ("media_source_stale", "the CRW product day is older than the 0-5 day source window")
    except (KeyError, TypeError):
        return ("media_source_unqualified", "the retained CRW product day is not qualified")
    return None


def recheck_before_upload(draft, *, now=None):
    reason = currentness(draft["review_context"]["two_bot"]["bundle"], now)
    if reason:
        raise MediaWithheld(*reason)


def media_for_draft(draft, *, now=None, store=None):
    """Exact reviewed recipe only: reread the packet, rebuild bytes and descriptions, refuse differences."""
    bundle = draft["review_context"]["two_bot"]["bundle"]
    attached = validate_descriptor(draft["media_attachment"], bundle)
    _require(not draft.get("hot10_rows"), "media_two_images", "only one explicitly selected image is allowed")
    reason = currentness(bundle, now)
    if reason:
        raise MediaWithheld(*reason)
    store = gist_assets.configured() if store is None else store
    prepared = prepare_media(bundle, store, attached["source"]["packet_artifact_sha256"])
    _require(prepared["descriptor"] == attached, "media_render_mismatch",
             "image, description or render profile changed; preview and review again")
    return prepared["png"], prepared["delivery_text"]


def retain_packet(store, packet):
    """Local retention of an already acquired packet; no fetch, no review, no approval."""
    _require(type(packet) is dict, "media_asset_invalid", "invalid CRW source packet")
    try:
        adapter._packet(packet, fingerprint(packet))
    except (ValueError, TypeError) as exc:
        raise MediaWithheld("media_asset_invalid", str(exc)[:200]) from None
    return gist_assets.put_document(store, packet)
