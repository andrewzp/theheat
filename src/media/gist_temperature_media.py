"""Deterministic retained-GHCN PNGs for explicitly selected manual Gist posts."""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from importlib.resources import files
from io import BytesIO
import json
import math
import re
from typing import cast

from PIL import Image, ImageDraw, ImageFont, features, __version__ as pillow_version

from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import HEIGHT, WIDTH, build_alt_text, chart_title
from src.media.temperature_graphic_adapter import _StoredBundle, temperature_graphic_spec
from src.two_bot.types import StoryBundle

KIND = "gist_temperature_comparator_v1"
KEYS = frozenset({"schema_version", "kind", "bundle_sha256", "source_revision_sha256",
    "baseline_revision_sha256", "station_id", "valid_date", "renderer", "png_sha256", "alt_text", "alt_sha256"})
RENDER_KEYS = frozenset({"implementation_sha256", "font_sha256", "pillow", "freetype", "zlib", "width", "height"})
SHA = re.compile(r"[a-f0-9]{64}\Z")
MAX_DESCRIPTOR_BYTES = 16_384
FONT = "fonts/DejaVuSansMono.ttf"


def _require(value, reason):
    if not value:
        raise ValueError("Temperature image withheld: " + reason)


def _hash(raw):
    return sha256(raw).hexdigest()


def renderer_identity():
    root = files("src.media")
    return {"implementation_sha256": _hash(root.joinpath("gist_temperature_media.py").read_bytes()),
        "font_sha256": _hash(root.joinpath(FONT).read_bytes()), "pillow": pillow_version,
        "freetype": features.version("freetype2"), "zlib": features.version("zlib"),
        "width": WIDTH, "height": HEIGHT}


def validate_descriptor(value, bundle):
    """Structure and current source binding only; transport also regenerates bytes."""
    _require(type(value) is dict and set(value) == KEYS, "unsupported attachment")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1
             and value["kind"] == KIND, "unsupported attachment")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    _require(len(encoded) <= MAX_DESCRIPTOR_BYTES, "attachment too large")
    for key in ("bundle_sha256", "source_revision_sha256", "baseline_revision_sha256", "png_sha256", "alt_sha256"):
        _require(type(value[key]) is str and SHA.fullmatch(value[key]), "invalid attachment digest")
    _require(type(bundle) is dict and value["bundle_sha256"] == fingerprint(bundle), "source changed")
    raw = bundle.get("raw_signal_dump", {})
    _require(type(raw) is dict, "full station evidence missing")
    evidence = raw.get("evidence", {})
    _require(type(evidence) is dict and type(evidence.get("baseline")) is dict, "full station evidence missing")
    _require(value["source_revision_sha256"] == evidence.get("revision_id")
             and value["baseline_revision_sha256"] == evidence["baseline"].get("revision_id")
             and value["station_id"] == evidence.get("station_id")
             and value["valid_date"] == evidence.get("valid_date"), "source binding changed")
    _require(type(value["station_id"]) is str and re.fullmatch(r"[A-Z0-9]{11}", value["station_id"]), "invalid station")
    _require(type(value["valid_date"]) is str and date.fromisoformat(value["valid_date"]).isoformat() == value["valid_date"], "invalid source date")
    renderer = value["renderer"]
    _require(type(renderer) is dict and set(renderer) == RENDER_KEYS, "invalid renderer")
    _require(renderer["width"] == WIDTH and type(renderer["width"]) is int
             and renderer["height"] == HEIGHT and type(renderer["height"]) is int, "invalid dimensions")
    _require(all(type(renderer[k]) is str and SHA.fullmatch(renderer[k]) for k in ("implementation_sha256", "font_sha256")), "invalid render digest")
    _require(all(type(renderer[k]) is str and 0 < len(renderer[k]) <= 64 for k in ("pillow", "freetype", "zlib")), "unknown renderer profile")
    _require(renderer == renderer_identity(), "render profile changed; preview and review again")
    alt = value["alt_text"]
    _require(type(alt) is str and 0 < len(alt) <= 10_000 and _hash(alt.encode("utf-8")) == value["alt_sha256"], "description changed")
    return value


def _png(spec):
    evidence = spec["evidence"]
    point, baseline = evidence["points"][0], evidence["baseline"]
    current, prior = point["value"], baseline["point"]["value"]
    _require(all(type(x) in (int, float) and math.isfinite(x) for x in (current, prior)), "invalid values")
    font_bytes = files("src.media").joinpath(FONT).read_bytes()
    def font(size):
        return ImageFont.truetype(BytesIO(font_bytes), size=size)
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0a0a0a")
    draw = ImageDraw.Draw(image)
    text, muted, grid = "#f4f4f5", "#b5b5bd", "#35353b"
    accent = "#ff8659" if evidence["variable"] == "daily_maximum_temperature" else "#65c8ff"

    def line(value, y, size=44, colour=text):
        face = font(size)
        _require(draw.textlength(value, font=face) <= 1072, "label exceeds readable width")
        draw.text((64, y), value, font=face, fill=colour)

    def wrap(value, y, size=44, max_lines=3):
        face, chunks, row = font(size), [], ""
        for word in value.split():
            trial = (row + " " + word).strip()
            if draw.textlength(trial, font=face) > 1072:
                _require(bool(row), "word exceeds readable width")
                chunks.append(row)
                row = word
            else:
                row = trial
        if row:
            chunks.append(row)
        _require(len(chunks) <= max_lines, "label exceeds readable lines")
        for i, row in enumerate(chunks):
            line(row, y + i * (size + 12), size)

    def number(value):
        rendered = str(value).replace("-", "−")
        _require(len(rendered) <= 12, "value precision exceeds display")
        return rendered + "°C"

    line("THE HEAT · STATION CHECK", 40, 40, muted)
    wrap(evidence["location"], 112, 58, 2)
    line(point["valid_date"] + " · SOURCE-CALENDAR DAY", 278, 42, muted)
    line(number(current), 350, 150, accent)
    line("Observed daily " + ("high" if "maximum" in evidence["variable"] else "low"), 548, 48)
    lo, hi = math.floor(min(0, current, prior) / 5) * 5, math.ceil(max(0, current, prior) / 5) * 5
    _require(hi > lo, "invalid common scale")
    def x(value):
        return 64 + (value - lo) / (hi - lo) * 1072
    wrap(baseline["scope"], 610, 40, 2)
    origin = x(0)
    for y, value, label, colour in ((800, current, "Observed · " + point["valid_date"], accent),
                                   (1000, prior, "Comparator · " + baseline["point"]["valid_date"], muted)):
        line(label + " · " + number(value), y - 72, 40, colour)
        draw.line((64, y + 40, 1136, y + 40), fill=grid, width=3)
        draw.rectangle((min(origin, x(value)), y, max(origin, x(value)), y + 48), fill=colour)
        draw.line((origin, y - 8, origin, y + 64), fill=text, width=3)
    for fraction in (0, .5, 1):
        value = lo + fraction * (hi - lo)
        label = f"{value:g}".replace("-", "−")
        face = font(40)
        left = max(64, min(x(value) - draw.textlength(label, font=face) / 2, 1136 - draw.textlength(label, font=face)))
        draw.text((left, 1070), label, fill=muted, font=face)
    line("COMMON SCALE · °C", 1120, 40, muted)
    line("NOAA GHCN-Daily · " + evidence["station_id"], 1178, 42)
    line("Archive through " + baseline["cutoff"], 1236, 42, muted)
    wrap("Accepted station samples; not an official record. Reporting interval and timezone unknown.", 1300, 40, 3)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    body = output.getvalue()
    _require(0 < len(body) <= 750_000, "PNG exceeds bound")
    return body


def prepare_media(bundle, *, synthetic=False):
    """No fetching: independently qualify the full retained comparator and render."""
    _require(type(bundle) is dict and "ghcn_claim" not in bundle, "full retained bundle required")
    spec = temperature_graphic_spec("temperature_comparator", [cast(StoryBundle, _StoredBundle(bundle))],
        expected_bundle_sha256=[fingerprint(bundle)], synthetic=synthetic)
    png = _png(spec)
    alt = build_alt_text("temperature_comparator", spec["evidence"])
    evidence = bundle["raw_signal_dump"]["evidence"]
    descriptor = {"schema_version": 1, "kind": KIND, "bundle_sha256": fingerprint(bundle),
        "source_revision_sha256": evidence["revision_id"], "baseline_revision_sha256": evidence["baseline"]["revision_id"],
        "station_id": evidence["station_id"], "valid_date": evidence["valid_date"], "renderer": renderer_identity(),
        "png_sha256": _hash(png), "alt_text": alt, "alt_sha256": _hash(alt.encode("utf-8"))}
    validate_descriptor(descriptor, bundle)
    return {"descriptor": descriptor, "png": png, "title": chart_title("temperature_comparator", spec["evidence"])}


def media_for_draft(draft, *, today=None):
    """Exact reviewed recipe only; any mismatch refuses before upload."""
    bundle = draft["review_context"]["two_bot"]["bundle"]
    attached = validate_descriptor(draft["media_attachment"], bundle)
    current_day = datetime.now(timezone.utc).date() if today is None else today
    _require(type(current_day) is date and 0 <= (current_day - date.fromisoformat(attached["valid_date"])).days <= 4,
             "source date is future or stale")
    prepared = prepare_media(bundle)
    _require(prepared["descriptor"] == attached, "image, description or render profile changed; preview and review again")
    return prepared["png"], attached["alt_text"]
