"""Versioned source descriptions and destination fit, never API qualification.

The small immutable record points to the existing raw alt artifact. It does not
change the renderer package or normalize text. Only the closed MODIS locator
projection may replace full raw text; every other family keeps exact raw reuse.
Profiles come from trusted server configuration, never the review submission.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io

from src.editorial.revisions import decision_revision, fingerprint
from src.media.review_packet import MAX_PNG_BYTES, _png_size

CONFIRMATION = "platform_description_faithful"
MAX_WIRE_BYTES = 1_000_000
BLUESKY_MAX_PNG = 2_000_000
FIXTURE_PROFILE = "credentialless-loopback-v1"
DESTINATIONS = ("x", "bluesky")
MODIS_DERIVATION = "modis_source_projection_v1"


def modis_wire_text(spec):
    """Lossless row projection with fixed scientific/map qualifications.

    Validate the retained source reconstruction, not a caller's claimed values.
    Common confidence/version columns apply explicitly to every row; otherwise
    every row carries both fields. Numbers use their existing round-trip spelling.
    There is no fit-dependent wording, omission, rounding or fallback.
    """
    from src.media.evidence_graphic import validate_graphic
    require(type(spec) is dict and set(spec) == {"template", "evidence", "expected_evidence_sha256"}
        and spec["template"] == "modis_thermal_detection_map", "platform_description_unqualified")
    evidence = validate_graphic(spec["template"], spec["evidence"],
        expected_evidence_sha256=spec["expected_evidence_sha256"])
    points, locator = evidence["points"], evidence["map"]
    require(all(type(p["source_version"]) is str and p["source_version"].strip()
        and p["source_version"].strip().casefold() not in {"unknown", "n/a", "na", "none", "null", "?"}
        for p in points), "platform_description_unqualified")
    common = len({(p["source_confidence"], p["source_version"]) for p in points}) == 1
    columns = "Lat,lon degrees/FRP MW"
    if common:
        prefix = f"All confidence {points[0]['source_confidence']}%, version {points[0]['source_version']}. "
    else:
        prefix = ""
        columns += "/confidence %/version"
    rows = "; ".join(f"{p['label']} {p['lat']},{p['lon']}/{p['frp_source']}" +
        ("" if common else f"/{p['source_confidence']}/{p['source_version']}") for p in points)
    context = ("Coasts omitted in close-up. " if locator["context_mode"] == "coordinate_closeup"
        else "Coarse land, not exact local boundaries. ")
    return (
        ("SYNTHETIC; not real weather. " if evidence["synthetic"] else "")
        + f"NASA FIRMS MODIS_NRT {evidence['satellite']}/MODIS {evidence['acquired_at']} (UTC minute, not seconds). "
        + "Source order: A primary, others related. " + prefix + columns + ": " + rows + ". "
        + f"Equal markers; linear blue-yellow FRP 0-{locator['axis_max']} MW; A lead, not max/severity. Rounded labels; exact rows. "
        + "FRP=pixel-integrated radiative power, not temperature/area/whole-fire intensity. "
        "Centres not flames/perimeters/footprints/separate-fire counts; scan/track/footprints unknown. "
        "Same minute/platform: instant/overpass/incident unproven. "
        "Confidence=source quality; no incident/cause/impact/location certification. "
        "Plate carree, not distance/area. " + context
        + ("Crosses dateline. " if locator["dateline_crossing"] else "")
        + "Inset=location/viewport, not fire area. Natural Earth110m land4.1.0 public domain; absent islands do not prove water. "
        "Selected receipts only; no original HTTP/source authentication/freshness/review/approval."
    )


class DescriptionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise DescriptionError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def text_identity(text):
    require(type(text) is str, "platform_description_invalid_utf8")
    try:
        raw = text.encode("utf-8", errors="strict")
    except UnicodeError:
        raise DescriptionError("platform_description_invalid_utf8") from None
    require(0 < len(raw) <= MAX_WIRE_BYTES, "platform_description_byte_bound")
    return dict(sha256=sha(raw), scalar_count=len(text), byte_count=len(raw))


def profiles(config=None):
    """Only an explicit private v2 loopback configuration qualifies the fixture."""
    from src.posting.local_delivery import configuration
    if config is not None:
        configuration(config)
    fixture = config is not None and config.get("platform_profile") == FIXTURE_PROFILE
    return dict(
        schema_version=1, destinations=list(DESTINATIONS),
        profile=FIXTURE_PROFILE if fixture else "unqualified-legacy-platforms-v1",
        configuration_sha256=fingerprint(config) if config is not None else None,
        routes=dict(x=["/1.1/media/upload.json", "/1.1/media/metadata/create.json", "/2/tweets"],
                    bluesky=["/xrpc/com.atproto.repo.uploadBlob", "/xrpc/com.atproto.repo.createRecord"]),
        sdk=dict(tweepy="4.17.0", atproto="0.0.72"),
    )


def build(draft, packet, proposal_sha256, raw_alt, png, profile, *, graphic_spec=None, derivation=None):
    """Called only after the canonical scientific package/packet was validated."""
    require(type(raw_alt) is bytes, "platform_description_invalid_utf8")
    try:
        wire = raw_alt.decode("utf-8", errors="strict")
    except UnicodeError:
        raise DescriptionError("platform_description_invalid_utf8") from None
    semantic = packet["media"]["alt_text"]
    require(raw_alt == semantic.encode("utf-8", errors="strict") + b"\n",
            "platform_description_unqualified")
    require(type(png) is bytes and packet["media"]["png_sha256"] == sha(png)
            and packet["media"]["byte_count"] == len(png), "platform_description_image_changed")
    require(derivation in (None, "full_raw_alt", MODIS_DERIVATION), "platform_description_unqualified")
    projected = packet.get("graphic_binding", {}).get("template") == "modis_thermal_detection_map" and derivation != "full_raw_alt"
    require(derivation != MODIS_DERIVATION or projected, "platform_description_unqualified")
    if projected:
        wire = modis_wire_text(graphic_spec)
        from src.media.evidence_graphic import build_alt_text
        require(raw_alt == (build_alt_text(graphic_spec["template"], graphic_spec["evidence"]) + "\n").encode("utf-8"),
            "platform_description_changed")
        require(packet["graphic_binding"]["evidence_sha256"] == graphic_spec["expected_evidence_sha256"],
            "platform_description_changed")
    body = dict(schema_version=2 if projected else 1,
        derivation=MODIS_DERIVATION if projected else "full_raw_alt", proposal_sha256=proposal_sha256,
        packet_sha256=packet["packet_sha256"], target={**packet["draft_binding"],
            "decision_revision": decision_revision(draft)},
        source_sha256=fingerprint(packet.get("published", packet["graphic_binding"])),
        raw_alt_sha256=sha(raw_alt), semantic_alt_sha256=sha(semantic.encode("utf-8")),
        wire=text_identity(wire), png={key:packet["media"][key] for key in
            ("mime_type", "png_sha256", "byte_count", "width", "height")},
        profiles=deepcopy(profile))
    if projected:
        body.update(graphic_spec_sha256=fingerprint(graphic_spec), wire_text=wire,
            source_sha256=fingerprint(graphic_spec["evidence"]["input_binding"]))
    return {**body, "description_sha256":fingerprint(body)}


def validate(record, *, raw_alt, png, graphic_spec=None):
    """Recheck exact artifacts and canonical record; no caller counts are trusted."""
    try:
        require(type(record) is dict, "platform_description_changed")
        body = {k:v for k,v in record.items() if k != "description_sha256"}
        projected = type(record.get("schema_version")) is int and record["schema_version"] == 2
        extension = {"graphic_spec_sha256", "wire_text"} if projected else set()
        require(type(record) is dict and set(body) == {"schema_version", "derivation", "proposal_sha256",
            "packet_sha256", "target", "source_sha256", "raw_alt_sha256", "semantic_alt_sha256", "wire", "png", "profiles"} | extension
            and type(record["schema_version"]) is int and record["schema_version"] == (2 if projected else 1)
            and fingerprint(body) == record["description_sha256"], "platform_description_changed")
        require(record["derivation"] == (MODIS_DERIVATION if projected else "full_raw_alt"), "platform_description_unqualified")
        require(type(raw_alt) is bytes and raw_alt.endswith(b"\n")
            and sha(raw_alt) == record["raw_alt_sha256"]
            and sha(raw_alt[:-1]) == record["semantic_alt_sha256"], "platform_description_changed")
        wire = raw_alt.decode("utf-8", errors="strict")
        if projected:
            from src.media.evidence_graphic import build_alt_text
            wire = modis_wire_text(graphic_spec)
            require(fingerprint(graphic_spec) == record["graphic_spec_sha256"]
                and fingerprint(graphic_spec["evidence"]["input_binding"]) == record["source_sha256"]
                and wire == record["wire_text"]
                and raw_alt == (build_alt_text(graphic_spec["template"], graphic_spec["evidence"]) + "\n").encode("utf-8"),
                "platform_description_changed")
        require(text_identity(wire) == record["wire"],
                "platform_description_changed")
        image = record["png"]
        require(type(png) is bytes and 0 < len(png) <= MAX_PNG_BYTES and image["mime_type"] == "image/png"
            and len(png) == image["byte_count"] and sha(png) == image["png_sha256"], "platform_description_image_changed")
        _png_size(png, dimensions=(image["width"], image["height"]))
        require(0 < image["width"] * image["height"] <= 1200 * 1500, "platform_description_image_changed")
        from PIL import Image
        with Image.open(io.BytesIO(png)) as decoded:
            require(decoded.format == "PNG" and decoded.size == (image["width"], image["height"])
                and getattr(decoded, "n_frames", 1) == 1, "platform_description_image_changed")
            decoded.verify()
        with Image.open(io.BytesIO(png)) as decoded:
            decoded.load()
        return wire
    except DescriptionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OSError, SyntaxError):
        raise DescriptionError("platform_description_changed") from None


def preflight(record, *, raw_alt, png, expected_profiles, graphic_spec=None):
    """All fixed destinations pass before *any* new mutation may be attempted."""
    wire = validate(record, raw_alt=raw_alt, png=png, graphic_spec=graphic_spec)
    require(record["profiles"] == expected_profiles
        and expected_profiles["destinations"] == list(DESTINATIONS), "platform_description_profile_changed")
    # Known fit is checked even for an unqualified API. This is deliberately
    # stricter than X's documented character limit; it is not an official byte limit.
    require(record["wire"]["scalar_count"] <= 1000 and record["wire"]["byte_count"] <= 1000,
            "platform_description_x_house_limit")
    require(len(png) <= BLUESKY_MAX_PNG, "platform_image_bluesky_limit")
    require(expected_profiles["profile"] == FIXTURE_PROFILE, "platform_api_unqualified")
    return wire
