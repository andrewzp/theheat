"""One bounded, unchanged NWS product; metadata assertions require joint review.

No source acquisition or model inference. Pure qualification is deliberately
separate from the isolated pixel conversion and current authority resolution.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct

from src.commands.schema import utc_datetime, utc_text
from src.editorial.revisions import fingerprint

FAMILY = "nws_local_standard_radar_v1"
TEMPLATE = "published_nws_radar"
SOURCE_URL = "https://radar.weather.gov/ridge/standard/KTLX_0.gif"
ALERT_URL = "https://api.weather.gov/alerts/active"
PRODUCT_URL = "https://www.weather.gov/media/notification/pdf2/pns22-09_ridge_ii_public_local_standard_radar_pages_aaa.pdf"
REUSE_URL = "https://www.weather.gov/disclaimer"
WIDTH, HEIGHT = 600, 550
MAX_ORIGINAL = 2 * 1024**2
MAX_INPUT = 64 * 1024
MAX_ENVELOPE = 128 * 1024
LIMITS = {
    "input.json": 1_000_000,
    "original.gif": MAX_ORIGINAL,
    "preview.png": 8 * 1024**2,
    "alt.txt": 100_000,
}
EXTRA_CONFIRMATIONS = frozenset(
    {"raster_labels_match", "named_point_context_matches", "unaltered_product_reuse_conditions_met"}
)
SCALE = ["nd", "-30", "-20", "-10", "0", "10", "20", "30", "40", "50", "60", "70", "80", "dBZ"]
LEGEND = ["TORNADO", "SEVERE THUNDERSTORM", "FLASH FLOOD", "SPECIAL MARINE", "SNOW SQUALL"]
CONTEXT = (
    "Radar context at Oklahoma City; not the full warning footprint or evidence of surface impacts."
)
POINT = {"place_id": "pl0406", "label": "Oklahoma City", "latitude": 35.47, "longitude": -97.52}
TIMES = ("sent", "effective", "onset", "expires", "ends")


class RadarHold(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise RadarHold(code)


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "radar_invalid_hash")


def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys), "radar_invalid_shape")


def text(value):
    require(
        type(value) is str
        and 0 < len(value.encode()) <= 2048
        and not any(ord(c) < 32 for c in value),
        "radar_invalid_text",
    )


def rare_tornado(properties):
    """OBSERVED is an attributed NWS tag, not an eyewitness/impact claim."""
    return (
        type(properties) is dict
        and properties.get("event") == "Tornado Warning"
        and properties.get("category") == "Met"
        and properties.get("status") == "Actual"
        and properties.get("messageType") in ("Alert", "Update")
        and type(properties.get("parameters")) is dict
        and properties["parameters"].get("tornadoDamageThreat") == ["CATASTROPHIC"]
        and properties["parameters"].get("tornadoDetection") == ["OBSERVED"]
    )


def source_time(value):
    text(value)
    require(
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
        ),
        "radar_source_time_invalid",
    )
    try:
        at = datetime.fromisoformat(value)
        return {"original": value, "utc": utc_text(at.astimezone(timezone.utc))}
    except ValueError:
        raise RadarHold("radar_source_time_invalid") from None


def warning_times(times):
    """Separate CAP message currency from the expected event's forecast window.

    NWS may replace an early warning before the forecast event begins. Message
    expiry is therefore not the event's end, nor a reason to erase its evidence.
    Radar still requires the stricter overlapping interval below.
    """
    require(
        times["sent"] is not None
        and times["effective"] is not None
        and times["expires"] is not None,
        "radar_source_time_missing",
    )
    sent = utc_datetime(times["sent"]["utc"])
    message_start = utc_datetime(times["effective"]["utc"])
    message_end = utc_datetime(times["expires"]["utc"])
    require(sent <= message_end and message_start < message_end, "radar_source_interval_invalid")
    event_start = message_start
    if times["onset"] is not None:
        event_start = max(event_start, utc_datetime(times["onset"]["utc"]))
    event_end = None if times["ends"] is None else utc_datetime(times["ends"]["utc"])
    require(event_end is None or (sent <= event_end and event_start < event_end),
            "radar_source_interval_invalid")
    return dict(message_start_utc=utc_text(message_start), message_end_utc=utc_text(message_end),
                event_start_utc=utc_text(event_start),
                event_end_utc=None if event_end is None else utc_text(event_end))


def interval(times):
    require(
        times["sent"] is not None
        and times["effective"] is not None
        and times["expires"] is not None,
        "radar_source_time_missing",
    )
    start = utc_datetime(times["effective"]["utc"])
    end = utc_datetime(times["expires"]["utc"])
    if times["onset"] is not None:
        start = max(start, utc_datetime(times["onset"]["utc"]))
    if times["ends"] is not None:
        end = min(end, utc_datetime(times["ends"]["utc"]))
    require(
        utc_datetime(times["sent"]["utc"]) <= end and start < end, "radar_source_interval_invalid"
    )
    return utc_text(start), utc_text(end)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on(a, b, c):
    return (
        _cross(a, b, c) == 0
        and min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])
    )


def _intersects(a, b, c, d):
    ac, ad, ca, cb = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return ((ac > 0) != (ad > 0) and (ca > 0) != (cb > 0)) or any(
        (_on(a, b, c), _on(a, b, d), _on(c, d, a), _on(c, d, b))
    )


def polygon(value):
    require(
        type(value) is dict
        and set(value) == {"type", "coordinates"}
        and value["type"] == "Polygon",
        "radar_polygon_unsupported",
    )
    rings = value["coordinates"]
    require(
        type(rings) is list
        and len(rings) == 1
        and type(rings[0]) is list
        and 4 <= len(rings[0]) <= 512,
        "radar_polygon_bound",
    )
    ring = rings[0]
    require(
        all(
            type(v) is list
            and len(v) == 2
            and all(type(n) in (int, float) and math.isfinite(n) for n in v)
            and -180 <= v[0] <= 180
            and -90 <= v[1] <= 90
            for v in ring
        ),
        "radar_polygon_coordinate",
    )
    require(
        ring[0] == ring[-1] and len({tuple(v) for v in ring[:-1]}) == len(ring) - 1,
        "radar_polygon_invalid",
    )
    edges = list(zip(ring, ring[1:]))
    require(all(abs(a[0] - b[0]) < 180 for a, b in edges), "radar_polygon_dateline")
    require(sum(a[0] * b[1] - b[0] * a[1] for a, b in edges) != 0, "radar_polygon_invalid")
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges[i + 1 :], i + 1):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            require(not _intersects(a, b, c, d), "radar_polygon_self_intersection")
    return ring


def contains(geometry, point):
    ring = polygon(geometry)
    q = (point["longitude"], point["latitude"])
    inside = False
    for a, b in zip(ring, ring[1:]):
        require(not _on(a, b, q), "radar_point_on_edge")
        if (a[1] > q[1]) != (b[1] > q[1]) and q[0] < (b[0] - a[0]) * (q[1] - a[1]) / (
            b[1] - a[1]
        ) + a[0]:
            inside = not inside
    require(inside, "radar_point_outside_warning")


def source_envelope(feature, captured_at):
    """Per-alert qualification cannot erase an ordinary source outcome."""
    times = {k: None for k in TIMES}
    props = feature.get("properties", {}) if type(feature) is dict else {}
    source_id = props.get("id") if type(props) is dict else None
    held = dict(
        schema_version=1,
        status="held",
        source_url=ALERT_URL,
        source_alert_id=source_id
        if type(source_id) is str and len(source_id.encode()) <= 2048
        else None,
        captured_at=captured_at,
        times=times,
        reasons=[],
        feature_sha256=None,
        feature_byte_count=None,
    )
    try:
        utc_datetime(captured_at)
        for k in TIMES:
            if props.get(k) is not None:
                times[k] = source_time(props[k])
        warning_times(times)
        text(source_id)
        raw = encoded(feature)
        held.update(feature_sha256=digest(raw), feature_byte_count=len(raw))
        require(len(raw) <= MAX_ENVELOPE, "radar_source_envelope_bound")
        require(
            type(feature) is dict and feature.get("type") == "Feature",
            "radar_source_feature_invalid",
        )
        complete = dict(
            schema_version=1,
            status="complete",
            source_url=ALERT_URL,
            source_alert_id=source_id,
            captured_at=captured_at,
            times=times,
            feature=deepcopy(feature),
            feature_sha256=digest(raw),
            feature_byte_count=len(raw),
            reasons=[],
        )
        require(len(encoded(complete)) <= MAX_ENVELOPE, "radar_source_envelope_bound")
        # Unsupported geography remains retained in a bounded complete envelope;
        # status is held so it cannot become a radar spec.
        try:
            interval(times)
            polygon(feature.get("geometry"))
        except RadarHold as exc:
            complete["status"], complete["reasons"] = "held", [exc.code]
        return complete
    except (RadarHold, ValueError, TypeError, OverflowError, RecursionError) as exc:
        held["reasons"] = [exc.code if isinstance(exc, RadarHold) else "radar_source_invalid"]
        return held


def source(bundle):
    raw = bundle["raw_signal_dump"]
    value = raw.get("source_evidence")
    require(type(value) is dict and value.get("status") == "complete", "radar_source_evidence_held")
    expected = source_envelope(value["feature"], value["captured_at"])
    require(encoded(value) == encoded(expected), "radar_source_evidence_changed")
    props = value["feature"]["properties"]
    require(rare_tornado(props), "radar_warning_context_unsupported")
    require(
        bundle["signal_kind"] == "severe_weather"
        and bundle["event_id"] == "nws_" + value["source_alert_id"],
        "radar_source_event_mismatch",
    )
    require(
        raw.get("provenance")
        == {k: value[k] for k in ("source_url", "source_alert_id", "feature_sha256")},
        "radar_source_provenance_mismatch",
    )
    start, end = interval(value["times"])
    require(bundle["when"] == start, "radar_source_time_mismatch")
    return value, start, end


def document(value):
    require(len(encoded(value)) <= MAX_INPUT, "radar_input_bound")
    shape(
        value,
        {
            "schema_version",
            "family",
            "station",
            "source_url",
            "original",
            "retrieved_at",
            "receipt",
            "metadata",
            "references",
            "synthetic",
            "metadata_status",
        },
    )
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["family"] == FAMILY
        and value["station"] == "KTLX"
        and value["source_url"] == SOURCE_URL
        and value["metadata_status"] == "unreviewed"
        and type(value["synthetic"]) is bool,
        "radar_input_unsupported",
    )
    original = value["original"]
    shape(original, {"sha256", "byte_count", "mime_type", "width", "height", "frame_count"})
    sha(original["sha256"])
    require(
        all(type(original[k]) is int for k in ("byte_count", "width", "height", "frame_count"))
        and 0 < original["byte_count"] <= MAX_ORIGINAL
        and (original["width"], original["height"], original["frame_count"], original["mime_type"])
        == (WIDTH, HEIGHT, 1, "image/gif"),
        "radar_original_shape",
    )
    utc_datetime(value["retrieved_at"])
    shape(value["receipt"], {"sha256", "byte_count"})
    sha(value["receipt"]["sha256"])
    require(
        type(value["receipt"]["byte_count"]) is int
        and 0 < value["receipt"]["byte_count"] <= MAX_INPUT,
        "radar_receipt_bound",
    )
    metadata = value["metadata"]
    shape(
        metadata,
        {
            "time_literal",
            "frame_minute_utc",
            "precision",
            "issued_utc",
            "subtype",
            "elevation_degrees",
            "product",
            "units",
            "reflectivity_legend",
            "warning_legend",
            "marks",
            "credit",
            "point",
        },
    )
    text(metadata["time_literal"])
    match = re.fullmatch(
        r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}) UTC \([^\r\n()]{1,64}\)", metadata["time_literal"]
    )
    require(match, "radar_time_literal_unsupported")
    assert match is not None
    try:
        minute = datetime.strptime(match[1], "%m/%d/%Y %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        raise RadarHold("radar_time_literal_invalid") from None
    require(
        metadata["frame_minute_utc"] == utc_text(minute)
        and metadata["precision"] == "minute"
        and metadata["issued_utc"] is metadata["subtype"] is metadata["elevation_degrees"] is None,
        "radar_metadata_time_or_subtype",
    )
    require(
        metadata["product"] == "station reflectivity"
        and metadata["units"] == "dBZ"
        and metadata["reflectivity_legend"] == SCALE
        and metadata["warning_legend"] == LEGEND
        and metadata["marks"] == ["NOAA logo", "NWS logo"]
        and metadata["credit"] == "NATIONAL WEATHER SERVICE",
        "radar_metadata_product",
    )
    shape(metadata["point"], {"place_id", "label", "registry_sha256"})
    require(
        metadata["point"]["place_id"] == POINT["place_id"]
        and metadata["point"]["label"] == POINT["label"],
        "radar_point_unsupported",
    )
    sha(metadata["point"]["registry_sha256"])
    shape(value["references"], {"product", "reuse"})
    for key, url in (("product", PRODUCT_URL), ("reuse", REUSE_URL)):
        ref = value["references"][key]
        shape(ref, {"url", "sha256", "byte_count"})
        require(
            ref["url"] == url
            and type(ref["byte_count"]) is int
            and 0 < ref["byte_count"] <= MAX_INPUT,
            "radar_reference_invalid",
        )
        sha(ref["sha256"])
    require(minute <= utc_datetime(value["retrieved_at"]), "radar_retrieved_before_frame")
    return deepcopy(value)


def make_spec(bundle, value, *, source_origin, registry_sha256, point, selection_sha256, now):
    value = document(value)
    shape(source_origin, {"namespace", "snapshot_id", "canonical_sha256"})
    require(source_origin["namespace"] == "draft-source-origin-v1", "radar_source_origin_invalid")
    sha(source_origin["snapshot_id"])
    sha(source_origin["canonical_sha256"])
    source_value, start, end = source(bundle)
    require(
        utc_datetime(source_value["times"]["sent"]["utc"])
        <= utc_datetime(source_value["captured_at"])
        <= now,
        "radar_source_capture_future",
    )
    sha(registry_sha256)
    sha(selection_sha256)
    require(
        point == POINT and registry_sha256 == value["metadata"]["point"]["registry_sha256"],
        "radar_registry_changed",
    )
    contains(source_value["feature"]["geometry"], point)
    minute = utc_datetime(value["metadata"]["frame_minute_utc"])
    deadline = min(minute + timedelta(minutes=15), utc_datetime(end))
    require(
        utc_datetime(start) <= minute and minute + timedelta(minutes=1) <= utc_datetime(end),
        "radar_frame_outside_warning",
    )
    require(
        utc_datetime(value["retrieved_at"]) <= now and minute <= now < deadline,
        "radar_frame_expired_or_future",
    )
    evidence = dict(
        schema_version=2,
        family=FAMILY,
        event_id=bundle["event_id"],
        bundle=deepcopy(bundle),
        bundle_sha256=fingerprint(bundle),
        source_origin=deepcopy(source_origin),
        source_feature_sha256=source_value["feature_sha256"],
        input=value,
        input_sha256=digest(encoded(value)),
        point=deepcopy(point),
        registry_sha256=registry_sha256,
        selection_sha256=selection_sha256,
        valid_start=start,
        valid_end=end,
        useful_until=utc_text(deadline),
        synthetic=value["synthetic"],
        scope="published_radar_context_human_labels_unreviewed",
    )
    return dict(
        template=TEMPLATE, expected_evidence_sha256=fingerprint(evidence), evidence=evidence
    )


def validate_spec(spec):
    shape(spec, {"template", "expected_evidence_sha256", "evidence"})
    require(spec["template"] == TEMPLATE, "radar_spec_family")
    e = spec["evidence"]
    # Rebuild the closed schema, without today's clock or registry. Authority
    # inputs separately resolve the actual current source/registry/selection.
    rebuilt = make_spec(
        e["bundle"],
        e["input"],
        source_origin=e["source_origin"],
        registry_sha256=e["registry_sha256"],
        point=e["point"],
        selection_sha256=e["selection_sha256"],
        now=max(
            utc_datetime(e["input"]["retrieved_at"]),
            utc_datetime(e["bundle"]["raw_signal_dump"]["source_evidence"]["captured_at"]),
        ),
    )
    require(encoded(rebuilt) == encoded(spec), "radar_spec_changed")
    return e


def alt_text(e):
    m = e["input"]["metadata"]
    result = (
        "Invented offline test image. " if e["synthetic"] else ""
    ) + f"NWS KTLX station reflectivity in dBZ. Displayed frame time {m['time_literal']}. "
    result += (
        CONTEXT
        + " Original image, labels, legend and NOAA/NWS marks preserved in a pixel-equivalent PNG display conversion. "
    )
    result += (
        "Reflectivity scale: "
        + ", ".join(SCALE)
        + "; nd has no interpreted numeric value. Warning legend: "
        + ", ".join(LEGEND)
        + ". "
    )
    result += "Visible labels and named-point context require human review; software has not extracted or verified raster labels. No rainfall accumulation, tornado detection or impact is inferred from this image. NATIONAL WEATHER SERVICE; no endorsement implied."
    require(len(result) <= 1000, "radar_alt_bound")
    return result


def original_header(raw, value):
    require(
        type(raw) is bytes
        and 13 <= len(raw) <= MAX_ORIGINAL
        and raw[:6] in (b"GIF87a", b"GIF89a")
        and struct.unpack("<HH", raw[6:10]) == (WIDTH, HEIGHT),
        "radar_original_invalid",
    )
    require(
        len(raw) == value["original"]["byte_count"] and digest(raw) == value["original"]["sha256"],
        "radar_original_changed",
    )


def convert(raw, value):
    """Called only outside SQL in the owned bounded preparation subprocess."""
    from PIL import Image

    original_header(raw, value)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            require(
                image.format == "GIF"
                and image.size == (WIDTH, HEIGHT)
                and getattr(image, "n_frames", None) == 1
                and getattr(image, "is_animated", None) is False
                and image.info.get("loop") is None
                and getattr(image, "disposal_method", 0) in (0, 1),
                "radar_animation_or_disposal",
            )
            image.load()
            rgba = image.convert("RGBA")
            pixels = rgba.tobytes()
            output = io.BytesIO()
            rgba.save(output, format="PNG", optimize=False, compress_level=6)
        png = output.getvalue()
        require(0 < len(png) <= LIMITS["preview.png"], "radar_png_bound")
        with Image.open(io.BytesIO(png)) as reread:
            reread.load()
            require(
                reread.format == "PNG"
                and reread.size == (WIDTH, HEIGHT)
                and reread.convert("RGBA").tobytes() == pixels,
                "radar_pixel_conversion_changed",
            )
        return png, digest(pixels)
    except RadarHold:
        raise
    except (OSError, ValueError, EOFError, Image.DecompressionBombError):
        raise RadarHold("radar_decode_failed") from None


def render(spec, raw, renderer, output_dir):
    e = validate_spec(spec)
    png, pixels = convert(raw, e["input"])
    assets = {
        "input.json": (
            json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
        "original.gif": raw,
        "preview.png": png,
        "alt.txt": (alt_text(e) + "\n").encode(),
    }
    binding = dict(
        template=TEMPLATE,
        template_version=1,
        source_evidence_sha256=spec["expected_evidence_sha256"],
        renderer=renderer,
        conversion=dict(
            original_sha256=digest(raw),
            rgba_sha256=pixels,
            method="gif_to_rgba_to_png_pixel_equal_v1",
        ),
    )
    manifest = dict(
        schema_version=2,
        family=FAMILY,
        cache_key=fingerprint(binding),
        binding=binding,
        files={k: digest(v) for k, v in assets.items()},
        synthetic=e["synthetic"],
        alt_text=alt_text(e),
        publication_approved=False,
        scope=e["scope"],
    )
    folder = Path(output_dir)
    for name, data in assets.items():
        (folder / name).write_bytes(data)
    target = folder / "manifest.json"
    target.write_bytes(encoded(manifest))
    return target


def packet(draft, identity, policy, spec, manifest, png, *, historical=False):
    """Structural retained-package binding; current authority is a separate join."""
    from src.media.review_packet import _png_size, media_attachment_content

    e = spec["evidence"] if historical else validate_spec(spec)
    require(
        spec["expected_evidence_sha256"] == fingerprint(e)
        and e["input_sha256"] == digest(encoded(e["input"]))
        and e["bundle_sha256"] == fingerprint(e["bundle"]),
        "radar_retained_evidence_changed",
    )
    shape(
        manifest,
        {
            "schema_version",
            "family",
            "cache_key",
            "binding",
            "files",
            "synthetic",
            "alt_text",
            "publication_approved",
            "scope",
        },
    )
    require(
        type(manifest["schema_version"]) is int
        and manifest["schema_version"] == 2
        and manifest["family"] == FAMILY,
        "radar_manifest_version",
    )
    b = manifest["binding"]
    shape(b, {"template", "template_version", "source_evidence_sha256", "renderer", "conversion"})
    require(
        b["template"] == TEMPLATE
        and type(b["template_version"]) is int
        and b["template_version"] == 1
        and b["source_evidence_sha256"] == spec["expected_evidence_sha256"]
        and manifest["cache_key"] == fingerprint(b),
        "radar_manifest_binding",
    )
    renderer = b["renderer"]
    shape(
        renderer,
        {"library", "version", "width", "height", "implementation_sha256", "dependencies_sha256"},
    )
    require(
        renderer["library"] == "Pillow"
        and renderer["version"] == "12.2.0"
        and type(renderer["width"]) is type(renderer["height"]) is int
        and (renderer["width"], renderer["height"]) == (WIDTH, HEIGHT),
        "radar_converter_profile",
    )
    sha(renderer["implementation_sha256"])
    sha(renderer["dependencies_sha256"])
    shape(b["conversion"], {"original_sha256", "rgba_sha256", "method"})
    require(
        b["conversion"]["original_sha256"] == e["input"]["original"]["sha256"]
        and b["conversion"]["method"] == "gif_to_rgba_to_png_pixel_equal_v1",
        "radar_conversion_binding",
    )
    sha(b["conversion"]["rgba_sha256"])
    shape(manifest["files"], LIMITS)
    for v in manifest["files"].values():
        sha(v)
    alt = manifest["alt_text"] if historical else alt_text(e)
    require(type(alt) is str and 0 < len(alt) <= 1000, "radar_alt_bound")
    require(
        manifest["files"]["input.json"]
        == digest((json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
        and manifest["files"]["original.gif"] == e["input"]["original"]["sha256"]
        and manifest["files"]["preview.png"] == digest(png)
        and manifest["files"]["alt.txt"] == digest((alt + "\n").encode())
        and manifest["alt_text"] == alt
        and manifest["synthetic"] is e["synthetic"]
        and manifest["publication_approved"] is False
        and manifest["scope"] == e["scope"],
        "radar_asset_metadata_changed",
    )
    _png_size(png, dimensions=(WIDTH, HEIGHT))
    require(
        draft["event_id"] == e["event_id"]
        and fingerprint(draft["review_context"]["two_bot"]["bundle"]) == e["bundle_sha256"],
        "radar_draft_bundle_changed",
    )
    published = dict(
        family=FAMILY,
        input_sha256=e["input_sha256"],
        original_sha256=e["input"]["original"]["sha256"],
        metadata_sha256=fingerprint(e["input"]["metadata"]),
        references_sha256=fingerprint(e["input"]["references"]),
        source_feature_sha256=e["source_feature_sha256"],
        source_origin=e["source_origin"],
        point_sha256=fingerprint(dict(point=e["point"], registry_sha256=e["registry_sha256"])),
        frame_minute_utc=e["input"]["metadata"]["frame_minute_utc"],
        valid_end=e["valid_end"],
        useful_until=e["useful_until"],
        confirmation_version=1,
        metadata_status="human_label_review_required",
        context=CONTEXT,
    )
    result = dict(
        schema_version=2,
        draft_binding=dict(
            draft_id=draft["id"],
            event_id=draft["event_id"],
            **identity,
            policy_sha256=fingerprint(policy),
        ),
        graphic_binding=dict(
            template=TEMPLATE,
            template_version=1,
            evidence_sha256=spec["expected_evidence_sha256"],
            render_binding_sha256=fingerprint(b),
            render_manifest_sha256=fingerprint(manifest),
        ),
        media=dict(
            mime_type="image/png",
            png_sha256=digest(png),
            byte_count=len(png),
            width=WIDTH,
            height=HEIGHT,
            alt_text=alt,
            alt_text_sha256=digest(alt.encode()),
        ),
        synthetic=e["synthetic"],
        claim_agreement_status="unreviewed",
        publication_approved=False,
        published=published,
    )
    if "media_attachment" in draft:
        require(
            encoded(draft["media_attachment"]) == encoded(media_attachment_content(result)),
            "radar_attachment_changed",
        )
    return {**result, "packet_sha256": fingerprint(result)}
