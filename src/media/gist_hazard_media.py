"""Deterministic source-qualified PNGs and X descriptions for saved hazard drafts.

Each family reuses its existing strict adapter and full retained-source
reconstruction; nothing here fetches, geocodes, calls a model or reads an external
asset. Pillow 12.2.0 draws with the bundled DejaVu Sans Mono and the BASIC layout
engine. Every label is measured with that embedded font; text that does not fit
refuses the image rather than shrinking, clipping or rounding away a value.

Gist stores only the recipe below: source/spec/renderer identities, the PNG's
digest and a bounded delivery description. The sender rebuilds the PNG and both
descriptions from the retained source and refuses any difference. Hashes bind the
reviewed choice; they do not establish factual agreement between text and image.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from importlib.resources import files
from io import BytesIO
import json
import math
import re
import unicodedata

from PIL import Image, ImageColor, ImageDraw, ImageFont, features, __version__ as pillow_version

from src.data import air_quality_contract, fire_source_contract
from src.data.temperature_evidence import FORECAST_PRODUCT as HOT10_PRODUCT
from src.editorial import hot10_contract
from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import HEIGHT, WIDTH, build_alt_text, chart_title
from src.media import air_quality_graphic_adapter as pm25_adapter, canonical_png, fire_map_graphic_adapter as locator
from src.media import hot10_graphic_adapter as hot10_adapter, viirs_map_graphic_adapter as viirs_adapter
from src.media.temperature_graphic_adapter import _StoredBundle

# Schema 2 / renderer 2: canonical PNG bytes (canonical_png.py) replace the host
# zlib identity. Schema 1 recipes need a new preview and joint review.
SCHEMA_VERSION = 2
RENDERER_VERSION = "gist-hazard-png-2"
PM25 = "gist_pm25_forecast_v1"
MODIS = "gist_modis_locator_v1"
VIIRS = "gist_viirs_locator_v1"
HOT10 = "gist_hot10_bulletin_v1"
MAX_DESCRIPTOR_BYTES = 16_384
MAX_PNG_BYTES = 750_000
# Existing conservative house limit, both Unicode scalars and UTF-8 bytes. This
# guards the sender; it is not a claim about the platform's official byte policy.
MAX_DELIVERY = 1000
MAX_FULL_DESCRIPTION_BYTES = 100_000
FONT = "src/media/fonts/DejaVuSansMono.ttf"
MIN_TEXT = 42
SHA = re.compile(r"[a-f0-9]{64}\Z")

# Kind -> its one template, adapter versions, delivery derivation and every file
# whose bytes affect rendering, descriptions or source selection.
FAMILIES = {
    PM25: dict(
        template=pm25_adapter.TEMPLATE, template_version=pm25_adapter.TEMPLATE_VERSION,
        adapter_version=pm25_adapter.ADAPTER_VERSION, derivation="pm25_delivery_v1",
        signal_kind="air_quality_hazard", products=(air_quality_contract.PRODUCT,),
        files=("src/media/gist_media.py", "src/media/gist_hazard_media.py", "src/media/canonical_png.py", FONT,
               "src/media/evidence_graphic.py", "src/media/temperature_graphic_adapter.py",
               "src/media/air_quality_graphic_adapter.py", "src/data/air_quality_contract.py",
               "src/data/air_quality_evidence.py"),
    ),
    MODIS: dict(
        template=locator.TEMPLATE, template_version=locator.TEMPLATE_VERSION,
        adapter_version=locator.ADAPTER_VERSION, derivation="modis_delivery_v1",
        signal_kind="fire", products=("MODIS_NRT",),
        files=("src/media/gist_media.py", "src/media/gist_hazard_media.py", "src/media/canonical_png.py", FONT,
               "src/media/evidence_graphic.py", "src/media/temperature_graphic_adapter.py",
               "src/media/fire_graphic_adapter.py", "src/media/fire_map_graphic_adapter.py",
               "src/data/fire_source_contract.py", "src/data/fire_evidence.py",
               "src/media/maps/ne_110m_land_v4_1_0.json", "src/media/maps/manifest.json"),
    ),
    # Its own explicit family: NOAA-20/NOAA-21 only (Suomi NPP, HMS and any mix stay held),
    # categorical confidence, never routed through or labelled as MODIS.
    VIIRS: dict(
        template=viirs_adapter.TEMPLATE, template_version=viirs_adapter.TEMPLATE_VERSION,
        adapter_version=viirs_adapter.ADAPTER_VERSION, derivation="viirs_delivery_v1",
        signal_kind="fire", products=tuple(viirs_adapter.PLATFORMS),
        files=("src/media/gist_media.py", "src/media/gist_hazard_media.py", "src/media/canonical_png.py", FONT,
               "src/media/evidence_graphic.py", "src/media/temperature_graphic_adapter.py",
               "src/media/fire_graphic_adapter.py", "src/media/fire_map_graphic_adapter.py",
               "src/media/viirs_map_graphic_adapter.py", "src/data/fire_source_contract.py",
               "src/data/fire_evidence.py", "src/media/maps/ne_110m_land_v4_1_0.json",
               "src/media/maps/manifest.json"),
    ),
    # The qualified Hot10 bulletin: ten ranked forecast-vs-normal rows, rendered only
    # from the retained rows the contract validates (never re-ranked or refetched).
    HOT10: dict(
        template=hot10_adapter.TEMPLATE, template_version=hot10_adapter.TEMPLATE_VERSION,
        adapter_version=hot10_adapter.ADAPTER_VERSION, derivation="hot10_delivery_v1",
        signal_kind="hot10", products=(HOT10_PRODUCT,),
        files=("src/media/gist_media.py", "src/media/gist_hazard_media.py", "src/media/canonical_png.py", FONT,
               "src/media/evidence_graphic.py", "src/media/hot10_graphic_adapter.py",
               "src/editorial/hot10_contract.py", "src/data/temperature_evidence.py"),
    ),
}
# Bundle signals this module owns; any other signal keeps the temperature path.
SIGNALS = frozenset({"air_quality_hazard", "fire", "hot10"})
KINDS = frozenset(FAMILIES)
_TOP_KEYS = frozenset({"schema_version", "kind", "template", "template_version", "adapter_version",
                       "synthetic", "source", "renderer", "image", "description"})
_SOURCE_KEYS = {
    PM25: frozenset({"bundle_sha256", "evidence_sha256", "source_product", "window_sha256",
                     "selected_record_sha256", "valid_date", "timezone", "valid_start", "valid_end",
                     "requested_at", "retrieved_at"}),
    MODIS: frozenset({"bundle_sha256", "evidence_sha256", "source_product", "receipt_sha256", "acquired_at"}),
    VIIRS: frozenset({"bundle_sha256", "evidence_sha256", "source_product", "receipt_sha256", "acquired_at"}),
    HOT10: frozenset({"bundle_sha256", "evidence_sha256", "source_product", "baseline_product", "rows_sha256",
                      "local_days"}),
}
_RENDERER_KEYS = frozenset({"version", "files", "pillow", "freetype", "png_codec", "layout", "width", "height"})
_IMAGE_KEYS = frozenset({"mime_type", "png_sha256", "byte_count", "width", "height", "mode"})
_DESCRIPTION_KEYS = frozenset({"derivation", "delivery_text", "delivery_sha256", "delivery_scalars",
                               "delivery_bytes", "full_sha256", "full_bytes"})


class MediaWithheld(ValueError):
    """A bounded refusal; the text draft and its history stay unchanged."""

    def __init__(self, code, reason):
        self.code = code
        super().__init__("Image withheld: " + reason)


def _require(condition, code, reason):
    if not condition:
        raise MediaWithheld(code, reason)


def _digest(raw):
    return sha256(raw).hexdigest()


def _resource(path):
    # Resolve under the real package (src.media/src.data): in the sealed runtime ZIP,
    # resource folders such as fonts/ and maps/ are not importable packages.
    parts = path.split("/")
    return files(".".join(parts[:2])).joinpath("/".join(parts[2:])).read_bytes()


def renderer_identity(kind):
    family = FAMILIES[kind]
    return {"version": RENDERER_VERSION,
            "files": {path: _digest(_resource(path)) for path in family["files"]},
            "pillow": pillow_version, "freetype": features.version("freetype2"),
            "png_codec": canonical_png.PROFILE, "layout": "basic", "width": WIDTH, "height": HEIGHT}


def _bundle_signal(bundle):
    return bundle.get("signal_kind") if type(bundle) is dict else None


def claims(bundle):
    return _bundle_signal(bundle) in SIGNALS


def _receipts(bundle):
    related = bundle.get("related_signals", [])
    return [bundle["raw_signal_dump"]["acquisition_provenance"], *[r["acquisition_evidence"] for r in related]]


def family_for(bundle):
    """The single hazard family a retained bundle can request, else None.

    Only the bundle's own signal and retained primary product decide; the
    selected adapter then validates every row and holds any mixed product,
    platform, minute, extended or unsupported story. A MODIS receipt is never
    reinterpreted as VIIRS.
    """
    signal = _bundle_signal(bundle)
    product = None
    if signal in ("fire", "hot10"):
        try:
            raw = bundle["raw_signal_dump"]
            product = raw["acquisition_provenance"]["source_product"] if signal == "fire" else raw["source_product"]
        except (KeyError, TypeError):
            return None
    for kind, family in FAMILIES.items():
        if signal == family["signal_kind"] and (signal not in ("fire", "hot10") or product in family["products"]):
            return kind
    return None


def _spec(kind, bundle, synthetic):
    if kind == PM25:
        window = bundle["raw_signal_dump"]["forecast_window"]
        return pm25_adapter.pm25_graphic_spec(
            _StoredBundle(bundle), expected_bundle_sha256=fingerprint(bundle),
            expected_window_sha256=fingerprint(window), synthetic=synthetic)
    if kind in (MODIS, VIIRS):
        adapter = locator.fire_map_graphic_spec if kind == MODIS else viirs_adapter.viirs_map_graphic_spec
        return adapter(_StoredBundle(bundle), expected_bundle_sha256=fingerprint(bundle),
                       expected_receipt_sha256=[fingerprint(r) for r in _receipts(bundle)], synthetic=synthetic)
    if kind == HOT10:
        try:
            return hot10_adapter.hot10_graphic_spec(bundle, expected_bundle_sha256=fingerprint(bundle),
                                                    synthetic=synthetic)
        except hot10_adapter.Hot10GraphicRefused as exc:
            raise MediaWithheld(exc.code, str(exc).removeprefix("Hot 10 image withheld: ")) from None
    raise MediaWithheld("media_unsupported", "unsupported attachment")


def _source_fields(kind, bundle, evidence_sha256):
    if kind == PM25:
        window = bundle["raw_signal_dump"]["forecast_window"]
        return {"bundle_sha256": fingerprint(bundle), "evidence_sha256": evidence_sha256,
                "source_product": window["source_product"], "window_sha256": fingerprint(window),
                "selected_record_sha256": window["selected_record_sha256"], "valid_date": window["date"],
                **{key: window[key] for key in ("timezone", "valid_start", "valid_end", "requested_at", "retrieved_at")}}
    if FAMILIES.get(kind, {}).get("signal_kind") == "fire":
        receipts = _receipts(bundle)
        return {"bundle_sha256": fingerprint(bundle), "evidence_sha256": evidence_sha256,
                "source_product": receipts[0]["source_product"],
                "receipt_sha256": [fingerprint(r) for r in receipts], "acquired_at": receipts[0]["acquired_at"]}
    if kind == HOT10:
        raw = bundle["raw_signal_dump"]
        return {"bundle_sha256": fingerprint(bundle), "evidence_sha256": evidence_sha256,
                "source_product": raw["source_product"], "baseline_product": raw["evidence"]["baseline_product"],
                "rows_sha256": fingerprint([row["row_fingerprint"] for row in raw["cities"]]),
                "local_days": ",".join(raw["universe"]["local_days"])}
    raise MediaWithheld("media_unsupported", "unsupported attachment")


# ---------------------------------------------------------------- descriptions

def _number(value):
    """The retained JSON spelling of one finite source number; never rounded."""
    _require(type(value) in (int, float) and math.isfinite(value), "media_source_invalid", "nonfinite source value")
    return json.dumps(value)


def _pm25_delivery(evidence):
    window = evidence["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]
    location = window["requested_location"]
    lat, lon = evidence["grid_location"]
    samples = "; ".join(f"{hour[11:16]} {_number(value)}" for hour, value in zip(evidence["hours"], evidence["values"]))
    return (
        ("SYNTHETIC; not real weather. " if evidence["synthetic"] else "")
        + "Chart of a PM2.5 model forecast (CAMS via Open-Meteo) at one source grid point, not station measurements. "
        + f"{location['city']}, {location['country']}; grid point latitude {_number(lat)}, longitude {_number(lon)}. "
        + f"Local day {evidence['valid_date']} ({evidence['timezone']}), "
        + f"UTC {evidence['valid_start']} to {evidence['valid_end']}; "
        + f"retrieved {window['retrieved_at']}, not a model run time. "
        + f"Hourly samples, μg/m³, local time: {samples}. "
        + f"Mean of the 24 samples: {_number(evidence['sample_mean'])} μg/m³. "
        + "Straight lines join samples on a zero-based axis. "
        + "No station reading, personal exposure, health category or model-run certainty."
    )


def _map_delivery(evidence):
    """Every detection's exact centre, FRP, confidence and version, in source order.

    Shared confidence/version are stated once only when identical for every row.
    MODIS confidence stays a percentage; VIIRS keeps its retained category.
    """
    points, map_ = evidence["points"], evidence["map"]
    viirs = evidence["instrument"] == "VIIRS"

    def confidence(point):
        return point["confidence_category"] if viirs else _number(point["source_confidence"]) + "%"

    # Each field is stated once only when truly identical for every detection.
    one_confidence = len({confidence(p) for p in points}) == 1
    one_version = len({p["source_version"] for p in points}) == 1
    common = ([f"confidence {confidence(points[0])}"] if one_confidence else []) + (
        [f"version {points[0]['source_version']}"] if one_version else [])
    common_text = ((("All: " if len(points) > 1 else "") + ", ".join(common)).strip() + ". ") if common else ""
    rows = "; ".join(f"{p['label']} {_number(p['lat'])}, {_number(p['lon'])}, {_number(p['frp_source'])} MW"
                     + ("" if one_confidence else f", confidence {confidence(p)}")
                     + ("" if one_version else f", version {p['source_version']}") for p in points)
    related = {1: "", 2: "; B related", 3: "; B-C related", 4: "; B-D related"}[len(points)]
    platform = f"{evidence['satellite']} VIIRS" if viirs else f"{evidence['satellite']}/MODIS"
    return (
        ("SYNTHETIC; not real weather. " if evidence["synthetic"] else "")
        + f"Satellite heat-detection locator: NASA FIRMS {evidence['source_product']}, {platform}, "
        + f"{evidence['acquired_at']} (reported UTC minute). "
        + f"A primary{related}{', in source order, not ranked' if related else ''}. "
        + (common_text[0].upper() + common_text[1:] if common_text else "")
        + f"Pixel centres (lat, lon) and FRP: {rows}. "
        + f"Equal markers coloured by FRP, linear blue-yellow 0-{map_['axis_max']:g} MW; A is primary, not selected by maximum FRP. "
        + "FRP is pixel radiative power, not temperature, area or severity; not summed. "
        + "Pixel centres, not flames, footprints, perimeters or fire counts. "
        + "Same minute and platform do not prove one instant, overpass or incident. "
        + ("Confidence: the source category, not cause or impact. " if viirs else "Confidence: source quality, not cause or impact. ")
        + "Plate carrée locator, not distance or area; "
        + ("close-up, coarse coastlines omitted. " if map_["context_mode"] == "coordinate_closeup"
           else "coarse Natural Earth 110m land 4.1.0. ")
        + ("Crosses the dateline. " if map_["dateline_crossing"] else "")
        + "Small islands may be missing (not proof of water). Inset: location only, not fire area."
    )


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _short_day(value):
    """'2026-10-30' -> 'Oct 30': the per-row local day when the slate spans dates."""
    return f"{_MONTHS[int(value[5:7]) - 1]} {int(value[8:10])}"


def _hot10_delivery(evidence):
    """What the image shows, for every ranked row, plus its scope; never truncated.

    Rank, place and signed departure for all ten rows, and each row's local day
    when the slate spans more than one date. Forecast and normal values stay in
    the expanded details and the editor; the image does not draw them.
    """
    days = evidence["local_days"]
    multi = len(days) > 1
    rows = "; ".join(
        f"{row['rank']} {row['city']}, {row['country']} {hot10_adapter.signed(row['departure_c'], minus='-')}"
        + (f" ({_short_day(row['valid_date'])})" if multi else "") for row in evidence["rows"])
    return (
        ("SYNTHETIC; not real weather. " if evidence["synthetic"] else "")
        + "Hot 10 chart: each city's forecast daily high minus its point monthly normal, in °C, ranked. "
        + f"Open-Meteo forecasts, Meteostat normals; {evidence['qualified_cities']} qualified of "
        + f"{evidence['sampled_cities']} sampled cities; local day{'s' if multi else ''} {', '.join(days)}. "
        + "Warm bands above normal, cool below, on one scale. "
        + f"{rows}. Not observations, records or the world's hottest places."
    )


def delivery_text(kind, evidence):
    """Versioned deterministic source projection; refuses rather than shortens."""
    _require(kind in FAMILIES, "media_unsupported", "unsupported attachment")
    text = (_pm25_delivery(evidence) if kind == PM25 else _hot10_delivery(evidence) if kind == HOT10
            else _map_delivery(evidence))
    try:
        raw = text.encode("utf-8", errors="strict")
    except UnicodeError:
        raise MediaWithheld("media_description_unicode", "the source description contains malformed Unicode") from None
    _require(len(text) <= MAX_DELIVERY and len(raw) <= MAX_DELIVERY, "media_description_too_long",
             "the mandatory image description exceeds the 1000-character/1000-byte house limit; "
             "the text draft is unchanged")
    return text


def _text_identity(text, code):
    try:
        raw = text.encode("utf-8", errors="strict")
    except (UnicodeError, AttributeError):
        raise MediaWithheld(code, "malformed description") from None
    return raw


# ------------------------------------------------------------------- drawing

def _clear(a, b, gap=4):
    return a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1]


class _Canvas:
    """One measured drawing; every text box is checked before it is drawn."""

    def __init__(self, background):
        self.image = Image.new("RGB", (WIDTH, HEIGHT), background)
        self.draw = ImageDraw.Draw(self.image)
        self.boxes: list[tuple] = []
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}
        self._font_bytes = _resource(FONT)
        self._notdef: dict[int, bytes] = {}

    def font(self, size):
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(BytesIO(self._font_bytes), size=size,
                                                   layout_engine=ImageFont.Layout.BASIC)
            self._notdef[size] = bytes(self._fonts[size].getmask("￿"))
        return self._fonts[size]

    def _drawable(self, value, size):
        face = self.font(size)
        _require(type(value) is str and value.strip() != "", "media_label_invalid", "empty image label")
        for char in value:
            category = unicodedata.category(char)
            _require(category[0] not in "CZ" or char == " ", "media_label_invalid", "control or format character")
            _require(category not in ("Mn", "Me") and unicodedata.bidirectional(char) not in ("R", "AL", "AN"),
                     "media_label_script", "label script needs shaping this renderer does not support")
            _require(char == " " or bytes(face.getmask(char)) != self._notdef[size], "media_label_glyph",
                     "label character is missing from the bundled font")
        return face

    def measure(self, xy, value, *, size, anchor="ls"):
        _require(size >= MIN_TEXT, "media_label_unreadable", "label smaller than the readable minimum")
        face = self._drawable(value, size)
        return self.draw.textbbox(xy, value, font=face, anchor=anchor)

    def text(self, xy, value, *, size, fill, anchor="ls", maxwidth=WIDTH - 128, obstacles=()):
        box = self.measure(xy, value, size=size, anchor=anchor)
        _require(box[2] - box[0] <= maxwidth and box[0] >= 20 and box[1] >= 20
                 and box[2] <= WIDTH - 20 and box[3] <= HEIGHT - 20, "media_label_overflow",
                 "label does not fit the readable image area")
        _require(all(_clear(box, old) for old in [*self.boxes, *obstacles]), "media_label_overlap",
                 "labels would overlap")
        self.boxes.append(box)
        self.draw.text(xy, value, font=self.font(size), fill=fill, anchor=anchor)
        return box

    def wrapped(self, x, y, value, *, size, fill, lines, pitch, maxwidth=WIDTH - 128):
        face, rows, row = self.font(size), [], ""
        for word in value.split(" "):
            trial = (row + " " + word).strip()
            if self.draw.textlength(trial, font=face) > maxwidth:
                _require(bool(row), "media_label_overflow", "a label word exceeds the readable width")
                rows.append(row)
                row = word
            else:
                row = trial
        if row:
            rows.append(row)
        _require(0 < len(rows) <= lines, "media_label_overflow", "label exceeds its reserved lines")
        for index, row in enumerate(rows):
            self.text((x, y + index * pitch), row, size=size, fill=fill, maxwidth=maxwidth)
        return len(rows)

    def png(self):
        try:
            return canonical_png.encode_image(self.image, max_bytes=MAX_PNG_BYTES)
        except canonical_png.CanonicalPNGError:
            raise MediaWithheld("media_png_too_large", "the PNG exceeds its byte bound") from None


INK = "#f4f4f5"
MUTED = "#b6bdcb"
WARM = "#ffb38a"


def _offset_label(seconds):
    sign = "+" if seconds >= 0 else "−"
    minutes = abs(seconds) // 60
    return f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _render_pm25(evidence):
    """24 samples at true hourly positions; straight segments; zero-based linear axis."""
    window = evidence["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]
    values = evidence["values"]
    _require(len(values) == 24 and len(evidence["hours"]) == 24
             and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values),
             "media_source_invalid", "24 finite non-negative samples required")
    try:
        top, ticks = pm25_adapter.forecast_axis(values)
    except ValueError:
        raise MediaWithheld("media_scale_unrenderable", "unrenderable concentration axis") from None
    canvas = _Canvas("#0b1220")
    line, panel, grid = "#38bdf8", "#111a2e", "#2a3754"
    location = window["requested_location"]
    canvas.text((64, 72), "THEHEAT", size=42, fill=MUTED)
    if evidence["synthetic"]:
        canvas.text((1136, 72), "SYNTHETIC DATA", size=42, fill=WARM, anchor="rs")
    canvas.text((64, 148), "PM2.5 model forecast", size=64, fill=INK)
    canvas.wrapped(64, 222, f"{location['city']}, {location['country']}", size=56, fill=INK, lines=2, pitch=64)
    canvas.text((64, 350), f"Local day {evidence['valid_date']}", size=42, fill=MUTED)
    canvas.text((64, 402), f"{evidence['timezone']} · {_offset_label(window['utc_offset_seconds'])}",
                size=42, fill=MUTED)
    mean = pm25_adapter.concentration(evidence["sample_mean"])
    hero = canvas.text((64, 540), mean, size=130, fill=line)
    canvas.text((hero[2] + 24, 540), "μg/m³", size=56, fill=INK)
    canvas.text((64, 596), "mean of 24 hourly samples", size=42, fill=MUTED)

    plot_left, plot_right, plot_top, plot_bottom = 232, 1136, 676, 1066
    canvas.draw.rectangle((40, 640, 1160, 1150), fill=panel)
    obstacles = []

    def y_of(value):
        return plot_bottom - value / top * (plot_bottom - plot_top)

    def x_of(hour):
        return plot_left + hour / 23 * (plot_right - plot_left)

    for tick in ticks:
        y = y_of(tick)
        canvas.draw.line((plot_left, y, plot_right, y), fill=grid, width=2)
        canvas.text((208, y + 15), f"{tick:g}", size=42, fill=MUTED, anchor="rs", maxwidth=150)
    canvas.draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill=MUTED, width=3)
    for hour in (0, 6, 12, 18, 23):
        canvas.draw.line((x_of(hour), plot_bottom, x_of(hour), plot_bottom + 10), fill=MUTED, width=3)
        canvas.text((x_of(hour), plot_bottom + 56), f"{hour:02d}:00", size=42, fill=MUTED,
                    anchor="ms" if 0 < hour < 23 else ("ls" if hour == 0 else "rs"))
    # Separate sample-mean reference, dashed and labelled in the legend.
    mean_y = y_of(evidence["sample_mean"])
    for x in range(plot_left, plot_right, 28):
        canvas.draw.line((x, mean_y, min(x + 16, plot_right), mean_y), fill="#c4b5fd", width=3)
    points = [(x_of(hour), y_of(value)) for hour, value in enumerate(values)]
    canvas.draw.line(points, fill=line, width=6, joint="curve")
    for x, y in points:
        canvas.draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=line)
    obstacles.append((plot_left, plot_top, plot_right, plot_bottom))

    legend_y = 1196
    canvas.draw.line((64, legend_y - 14, 112, legend_y - 14), fill=line, width=6)
    canvas.draw.ellipse((81, legend_y - 21, 95, legend_y - 7), fill=line)
    canvas.text((124, legend_y), "hourly samples, μg/m³, local time", size=42, fill=INK)
    for x in (64, 92):
        canvas.draw.line((x, legend_y + 38, x + 16, legend_y + 38), fill="#c4b5fd", width=3)
    canvas.text((124, legend_y + 52), "mean of the 24 samples", size=42, fill=INK)
    lat, lon = evidence["grid_location"]
    canvas.text((64, 1302), "Model forecast · CAMS via Open-Meteo", size=42, fill=INK)
    canvas.text((64, 1352), f"Grid {abs(lat):.4f}°{'N' if lat >= 0 else 'S'} {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"
                " · not a station", size=42, fill=MUTED)
    canvas.text((64, 1402), f"Retrieved {window['retrieved_at'][:16].replace('T', ' ')} UTC", size=42, fill=MUTED)
    canvas.text((64, 1452), "Model run, resolution unknown", size=42, fill=MUTED)
    return canvas.png()


PLOT_BG, PLOT_GRID, LAND, MAP_INK = "#f0f3f5", "#c5cdd4", "#84939d", "#17212b"


def _pil_y(y):
    """Validated locator geometry is y-up (bottom origin); Pillow draws from the top."""
    return HEIGHT - y


def _pil_box(box):
    left, bottom, right, top = box
    return (left, _pil_y(top), right, _pil_y(bottom))


def _render_map(evidence):
    """Exact validated centres, labels, extents and palette; no displacement or jitter."""
    map_ = evidence["map"]
    viirs = evidence["instrument"] == "VIIRS"
    frame = map_["frame"] if viirs else list(locator.MAP_FRAME)
    left, bottom, width, height = map_["rectangle"]
    west, south, east, north = map_["bounds"]
    plot = (left, _pil_y(bottom + height), left + width, _pil_y(bottom))
    inset = (824, 110, 1144, 270)
    bar = (56, 1268, 56 + 64 * 17, 1292)
    canvas = _Canvas("#0b1220")
    draw = canvas.draw
    rings, _ = locator.basemap()

    def outline(bounds, box, color, line_width):
        a, b, c, d = bounds
        x0, y0, x1, y1 = box
        for x1_, y1_, x2_, y2_ in locator.clipped_segments(rings, bounds):
            draw.line((x0 + (x1_ - a) / (c - a) * (x1 - x0), y1 - (y1_ - b) / (d - b) * (y1 - y0),
                       x0 + (x2_ - a) / (c - a) * (x1 - x0), y1 - (y2_ - b) / (d - b) * (y1 - y0)),
                      fill=color, width=line_width)

    # Header and footer text is measured against fixed obstacles before drawing.
    obstacles = (plot, inset, bar)
    canvas.text((56, 52), "THEHEAT", size=42, fill=MUTED, obstacles=obstacles)
    if evidence["synthetic"]:
        canvas.text((794, 52), "SYNTHETIC DATA", size=42, fill=WARM, obstacles=obstacles, maxwidth=350)
    canvas.text((56, 174), _number(evidence["points"][0]["frp_source"]) + " MW", size=96, fill=INK,
                maxwidth=740, obstacles=obstacles)
    canvas.text((56, 248), "Pixel A radiative power", size=48, fill=INK, maxwidth=740, obstacles=obstacles)
    platform = f"{evidence['satellite']} VIIRS" if viirs else f"{evidence['satellite']} / MODIS"
    canvas.text((56, 308), "NASA FIRMS · " + platform, size=44, fill=MUTED, maxwidth=740, obstacles=obstacles)
    canvas.text((56, 360), evidence["acquired_at"][:16].replace("T", " ") + " UTC", size=44, fill=MUTED,
                maxwidth=740, obstacles=obstacles)
    canvas.text((56, 412), "Coordinate close-up; coastline omitted" if map_["context_mode"] == "coordinate_closeup"
                else "Coarse locator; not distance or area", size=42, fill=MUTED, maxwidth=1088, obstacles=obstacles)
    if viirs:
        # Exact retained categories beside the A-D labels; never a ranking number.
        canvas.text((56, 464), "Source detection confidence", size=42, fill=MUTED, maxwidth=1088, obstacles=obstacles)
        canvas.text((56, 516), viirs_adapter.confidence_row(evidence), size=42, fill=INK, maxwidth=1088,
                    obstacles=obstacles)
    canvas.text((824, 94), "World map", size=42, fill=MUTED, maxwidth=340, obstacles=obstacles)
    canvas.text((824, 314), "Location only", size=42, fill=MUTED, maxwidth=340, obstacles=obstacles)
    canvas.text((824, 362), "Not fire area", size=42, fill=MUTED, maxwidth=340, obstacles=obstacles)
    canvas.text((56, 1248), "Pixel radiative power (MW)", size=48, fill=INK, obstacles=obstacles)
    for fraction, anchor in ((0, "ls"), (0.5, "ms"), (1, "rs")):
        canvas.text((56 + 1088 * fraction, 1348), f"{map_['axis_max'] * fraction:g} MW", size=42, fill=MUTED,
                    anchor=anchor, obstacles=obstacles)
    canvas.text((56, 1412), "Pixel centers, not fire boundaries.", size=42, fill=MUTED, obstacles=obstacles)
    canvas.text((56, 1468), "Power, not fire area or severity.", size=42, fill=MUTED, obstacles=obstacles)
    for value, x, anchor in ((west, left, "ls"), (east, left + width, "rs")):
        value = locator.wrapped(value)
        label = "180°" if abs(value) == 180 else f"{abs(value):.4f}°{'W' if value < 0 else 'E'}"
        canvas.text((x, 1196), label, size=42, fill=MUTED, anchor=anchor, obstacles=obstacles)

    # Latitude edge captions read bottom-to-top in the left gutter, else in a
    # genuine vertical letterbox inside the frame; otherwise the map is withheld.
    captions = [f"{abs(v):.4f}°{'S' if v < 0 else 'N'}" for v in (south, north)]
    face = canvas.font(42)
    ascent, descent = face.getmetrics()
    tiles = []
    for caption, end in zip(captions, (False, True)):
        canvas._drawable(caption, 42)
        length = math.ceil(canvas.draw.textlength(caption, font=face))
        y0 = plot[1] if end else plot[3] - length
        tiles.append((caption, length, (64 - ascent, y0, 64 + descent, y0 + length)))
    rotated = all(box[1] >= plot[1] and box[3] <= plot[3] and box[0] >= 20 for _, _, box in tiles) \
        and _clear(tiles[0][2], tiles[1][2]) and all(_clear(box, old) for _, _, box in tiles for old in canvas.boxes)
    if rotated:
        for caption, length, box in tiles:
            tile = Image.new("L", (length, ascent + descent), 0)
            ImageDraw.Draw(tile).text((0, ascent), caption, font=face, fill=255, anchor="ls")
            turned = tile.transpose(Image.Transpose.ROTATE_90)
            canvas.image.paste(ImageColor.getrgb(MUTED), (int(box[0]), int(box[1])), turned)
            canvas.boxes.append(box)
    else:
        frame_top, frame_bottom = _pil_y(frame[1] + frame[3]), _pil_y(frame[1])
        lower = canvas.measure((left, plot[3] + ascent + 12), captions[0], size=42)
        upper = canvas.measure((left, plot[1] - descent - 12), captions[1], size=42)
        _require(frame_top <= upper[1] and lower[3] <= frame_bottom, "media_map_labels",
                 "map edge labels exceed space")
        canvas.text((left, plot[3] + ascent + 12), captions[0], size=42, fill=MUTED, obstacles=obstacles)
        canvas.text((left, plot[1] - descent - 12), captions[1], size=42, fill=MUTED, obstacles=obstacles)

    draw.rectangle(plot, fill=PLOT_BG, outline=PLOT_GRID, width=2)
    if map_["context_mode"] == "coarse_land_locator":
        outline(map_["bounds"], plot, LAND, 2)
    for fraction in (0, 0.5, 1):
        x, y = plot[0] + (plot[2] - plot[0]) * fraction, plot[1] + (plot[3] - plot[1]) * fraction
        draw.line((x, plot[1], x, plot[3]), fill=PLOT_GRID, width=1)
        draw.line((plot[0], y, plot[2], y), fill=PLOT_GRID, width=1)
    marker_boxes = []
    for point, (x, y), label in zip(evidence["points"], map_["markers"], map_["labels"]):
        y = _pil_y(y)
        end_x, end_y = label["leader_end"][0], _pil_y(label["leader_end"][1])
        draw.line((x, y, end_x, end_y), fill=MAP_INK, width=2)
        draw.ellipse((x - 17, y - 17, x + 17, y + 17), fill="#ffffff")
        draw.ellipse((x - 14, y - 14, x + 14, y + 14), fill=locator.color(point["frp_source"], map_["axis_max"]),
                     outline=MAP_INK, width=2)
        box = _pil_box(label["box"])
        draw.rectangle(box, fill=PLOT_BG)
        marker_boxes.append((point["label"], (label["x"], _pil_y(label["y"])), box))
    for letter, centre, box in marker_boxes:
        text = canvas.measure(centre, letter, size=locator.LABEL_SIZE, anchor="mm")
        _require(box[0] <= text[0] and box[1] <= text[1] and text[2] <= box[2] and text[3] <= box[3],
                 "media_map_labels", "map labels exceed their validated boxes")
        canvas.draw.text(centre, letter, font=canvas.font(locator.LABEL_SIZE), fill=MAP_INK, anchor="mm")
    for i in range(64):
        draw.rectangle((56 + i * 17, bar[1], 56 + (i + 1) * 17 - 1, bar[3]),
                       fill=locator.color((i + 0.5) / 64 * map_["axis_max"], map_["axis_max"]))
    # The true geographic viewport; a tiny crosshair is a locator, never a footprint.
    draw.rectangle(inset, fill="#14202b", outline=PLOT_GRID, width=1)
    outline([-180, -90, 180, 90], inset, "#9ba9b5", 1)
    ix, iy, iw, ih = inset[0], inset[1], inset[2] - inset[0], inset[3] - inset[1]
    viewport_width, viewport_height = (east - west) / 360 * iw, (north - south) / 180 * ih
    if viewport_width < 2 or viewport_height < 2:
        x = ix + (locator.wrapped((west + east) / 2) + 180) / 360 * iw
        y = iy + ih - ((south + north) / 2 + 90) / 180 * ih
        draw.line((max(ix, x - 5), y, min(ix + iw, x + 5), y), fill=INK, width=2)
        draw.line((x, max(iy, y - 5), x, min(iy + ih, y + 5)), fill=INK, width=2)
    else:
        for shift in (-360, 0, 360):
            a, b = max(-180, west + shift), min(180, east + shift)
            if a < b:
                top = iy + ih - (north + 90) / 180 * ih
                draw.rectangle((ix + (a + 180) / 360 * iw, top, ix + (b + 180) / 360 * iw, top + viewport_height),
                               outline=INK, width=2)
    return canvas.png()


HOT10_WARM_BAND, HOT10_COOL_BAND, HOT10_WARM, HOT10_COOL = "#7c2d12", "#1e3a8a", "#fb923c", "#60a5fa"


def _render_hot10(evidence):
    """Ten ranked rows as a departure table on one common °C scale.

    Each row is a band from the shared zero edge (warm above its normal, cool
    below) with the rank, place, signed departure and, when the slate spans more
    than one local date, the row's own local day written over it: meaning never
    rests on colour alone. Every label is measured; a name that does not fit at
    the readable minimum refuses the image instead of shrinking or eliding it.
    """
    rows, days = evidence["rows"], evidence["local_days"]
    _require(len(rows) == hot10_contract.SIZE, "media_source_invalid", "ten ranked rows required")
    values = [row["departure_c"] for row in rows]
    _require(all(type(v) in (int, float) and math.isfinite(v) for v in values), "media_source_invalid",
             "nonfinite departure")
    canvas = _Canvas("#0b1220")
    canvas.text((64, 64), "THEHEAT", size=42, fill=MUTED)
    if evidence["synthetic"]:
        canvas.text((1136, 64), "SYNTHETIC DATA", size=42, fill=WARM, anchor="rs")
    canvas.text((64, 128), "Hot 10: forecast high vs normal", size=56, fill=INK)
    canvas.text((64, 184), f"{evidence['qualified_cities']} of {evidence['sampled_cities']} sampled cities · "
                "not records", size=42, fill=MUTED)
    left, right, inset = 136, 1136, 148
    positive, negative = max(0.0, *values), max(0.0, *(-v for v in values))
    span = (positive + negative) or 1.0
    zero = left + (right - left) * negative / span
    multi = len(days) > 1
    top, pitch = 254, 110
    # Bands first, every one from the shared zero edge; every label is then drawn over them.
    for index, value in enumerate(values):
        y = top + index * pitch
        if value:
            length = max(6.0, (right - left) * abs(value) / span)
            band = (zero, y - 38, zero + length, y + 64) if value > 0 else (zero - length, y - 38, zero, y + 64)
            canvas.draw.rectangle(band, fill=HOT10_WARM_BAND if value > 0 else HOT10_COOL_BAND)
    for index, row in enumerate(rows):
        y, value = top + index * pitch, row["departure_c"]
        canvas.text((112, y), str(row["rank"]), size=42, fill=MUTED, anchor="rs", maxwidth=80)
        figure = canvas.text((right, y), hot10_adapter.signed(value) + " °C", size=42,
                             fill=HOT10_WARM if value > 0 else HOT10_COOL if value < 0 else INK, anchor="rs")
        canvas.text((inset, y), row["city"], size=42, fill=INK, maxwidth=figure[0] - 24 - inset)
        country = canvas.text((inset, y + 54), row["country"], size=42, fill=MUTED)
        if multi:
            canvas.text((right, y + 54), _short_day(row["valid_date"]), size=42, fill=MUTED, anchor="rs",
                        maxwidth=right - country[2] - 24)
    legend = 1362
    for x, colour, label in ((64, HOT10_WARM_BAND, "above normal"), (470, HOT10_COOL_BAND, "below normal")):
        canvas.draw.rectangle((x, legend - 32, x + 48, legend + 4), fill=colour, outline=MUTED, width=2)
        canvas.text((x + 60, legend), label, size=42, fill=INK)
    canvas.text((64, 1412), ("Local day " + days[0]) if not multi else
                ("Local days " + (", ".join(days) if len(days) == 2 else f"{days[0]} to {days[-1]}")),
                size=42, fill=MUTED)
    canvas.text((64, 1462), "Open-Meteo forecast · Meteostat normals", size=42, fill=MUTED)
    return canvas.png()


# ------------------------------------------------------------------- recipes

def prepare_media(bundle, *, synthetic=False):
    """No fetching: qualify the full retained source with its own adapter, then render."""
    kind = family_for(bundle)
    _require(kind is not None, "media_unsupported", "unsupported source for a post image")
    _require(type(synthetic) is bool, "media_unsupported", "synthetic status must be explicit")
    try:
        spec = _spec(kind, bundle, synthetic)
    except MediaWithheld:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise MediaWithheld("media_source_unqualified", str(exc)[:200] or "unqualified source") from exc
    template, evidence = spec["template"], spec["evidence"]
    _require(template == FAMILIES[kind]["template"], "media_unsupported", "unexpected template")
    png = _render_pm25(evidence) if kind == PM25 else _render_hot10(evidence) if kind == HOT10 else _render_map(evidence)
    full = hot10_adapter.full_description(evidence) if kind == HOT10 else build_alt_text(template, evidence)
    full_raw = _text_identity(full, "media_description_unicode")
    _require(0 < len(full_raw) <= MAX_FULL_DESCRIPTION_BYTES, "media_description_too_long", "full description bound")
    delivery = delivery_text(kind, evidence)
    delivery_raw = delivery.encode("utf-8")
    family = FAMILIES[kind]
    descriptor = {
        "schema_version": SCHEMA_VERSION, "kind": kind, "template": template,
        "template_version": family["template_version"], "adapter_version": family["adapter_version"],
        "synthetic": synthetic, "source": _source_fields(kind, bundle, spec["expected_evidence_sha256"]),
        "renderer": renderer_identity(kind),
        "image": {"mime_type": "image/png", "png_sha256": _digest(png), "byte_count": len(png),
                  "width": WIDTH, "height": HEIGHT, "mode": "RGB"},
        "description": {"derivation": family["derivation"], "delivery_text": delivery,
                        "delivery_sha256": _digest(delivery_raw), "delivery_scalars": len(delivery),
                        "delivery_bytes": len(delivery_raw), "full_sha256": _digest(full_raw),
                        "full_bytes": len(full_raw)},
    }
    if not synthetic:
        validate_descriptor(descriptor, bundle)
    title = hot10_adapter.TITLE if kind == HOT10 else chart_title(template, evidence)
    return {"kind": kind, "descriptor": descriptor, "png": png, "title": title,
            "delivery_text": delivery, "full_text": full, "scope": evidence["scope"]}


def _exact(value, keys):
    return type(value) is dict and set(value) == keys


def _is_sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def validate_descriptor(value, bundle):
    """Structure, current source binding and renderer profile; the sender also rebuilds bytes."""
    _require(_exact(value, _TOP_KEYS) and value["kind"] in FAMILIES, "media_unsupported", "unsupported attachment")
    _require(not (type(value["schema_version"]) is int and value["schema_version"] == 1), "media_renderer_changed",
             "render profile changed; preview and review again")
    _require(type(value["schema_version"]) is int and value["schema_version"] == SCHEMA_VERSION,
             "media_unsupported", "unsupported attachment")
    kind, family = value["kind"], FAMILIES[value["kind"]]
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MediaWithheld("media_descriptor_invalid", "attachment is not bounded finite JSON") from None
    _require(len(encoded) <= MAX_DESCRIPTOR_BYTES, "media_descriptor_invalid", "attachment too large")
    _require(value["template"] == family["template"] and value["template_version"] == family["template_version"]
             and value["adapter_version"] == family["adapter_version"], "media_recipe_changed",
             "graphic template changed; preview and review again")
    _require(value["synthetic"] is False, "media_synthetic", "synthetic demonstrations cannot be posted")
    _require(_bundle_signal(bundle) == family["signal_kind"], "media_source_changed", "source family changed")
    source = value["source"]
    receipts = source.get("receipt_sha256", []) if type(source) is dict else None
    _require(_exact(source, _SOURCE_KEYS[kind]) and all(type(source[k]) is str for k in source if k != "receipt_sha256")
             and all(_is_sha(source[k]) for k in source if k.endswith("_sha256") and k != "receipt_sha256")
             and type(receipts) is list and len(receipts) <= 4 and all(_is_sha(v) for v in receipts)
             and (("receipt_sha256" in source) == (family["signal_kind"] == "fire"))
             and (bool(receipts) or family["signal_kind"] != "fire"),
             "media_descriptor_invalid", "invalid source binding")
    _require(source["source_product"] in family["products"], "media_source_changed", "source product changed")
    try:
        expected = _source_fields(kind, bundle, source["evidence_sha256"])
    except (KeyError, TypeError, AttributeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise MediaWithheld("media_source_changed", "retained source missing or changed") from None
    _require(source == expected, "media_source_changed", "source binding changed")
    renderer = value["renderer"]
    _require(_exact(renderer, _RENDERER_KEYS) and type(renderer["files"]) is dict
             and set(renderer["files"]) == set(family["files"])
             and all(_is_sha(v) for v in renderer["files"].values())
             and all(type(renderer[k]) is str and 0 < len(renderer[k]) <= 64 for k in ("version", "pillow", "freetype", "png_codec", "layout"))
             and type(renderer["width"]) is int and type(renderer["height"]) is int,
             "media_descriptor_invalid", "invalid renderer")
    _require(renderer == renderer_identity(kind), "media_renderer_changed", "render profile changed; preview and review again")
    image = value["image"]
    _require(_exact(image, _IMAGE_KEYS) and image["mime_type"] == "image/png" and _is_sha(image["png_sha256"])
             and type(image["byte_count"]) is int and 0 < image["byte_count"] <= MAX_PNG_BYTES
             and image["width"] == WIDTH and type(image["width"]) is int
             and image["height"] == HEIGHT and type(image["height"]) is int and image["mode"] == "RGB",
             "media_descriptor_invalid", "invalid image identity")
    description = value["description"]
    _require(_exact(description, _DESCRIPTION_KEYS) and description["derivation"] == family["derivation"]
             and all(type(description[k]) is int for k in ("delivery_scalars", "delivery_bytes", "full_bytes"))
             and _is_sha(description["delivery_sha256"]) and _is_sha(description["full_sha256"])
             and 0 < description["full_bytes"] <= MAX_FULL_DESCRIPTION_BYTES,
             "media_descriptor_invalid", "invalid description identity")
    text = description["delivery_text"]
    _require(type(text) is str, "media_descriptor_invalid", "invalid description")
    raw = _text_identity(text, "media_description_unicode")
    _require(0 < len(text) <= MAX_DELIVERY and len(raw) <= MAX_DELIVERY
             and description["delivery_scalars"] == len(text) and description["delivery_bytes"] == len(raw)
             and description["delivery_sha256"] == _digest(raw), "media_description_changed",
             "description changed or exceeds the house limit")
    return value


# ------------------------------------------------------------------ currentness

def _aware_now(now):
    current = datetime.now(timezone.utc) if now is None else now
    _require(isinstance(current, datetime) and current.utcoffset() is not None, "media_clock_invalid",
             "current time must be timezone-aware")
    return current.astimezone(timezone.utc)


def currentness(kind, bundle, now=None):
    """Explicit image-path recency for manual approval/sending; None when current.

    Not a provider-certified expiry. A new render or review never refreshes source time.
    """
    current = _aware_now(now)
    if kind == PM25:
        window = bundle["raw_signal_dump"]["forecast_window"]
        try:
            air_quality_contract.validate_window(window)
            requested, retrieved = (air_quality_contract._utc(window[k]) for k in ("requested_at", "retrieved_at"))
            start, end = (air_quality_contract._utc(window[k]) for k in ("valid_start", "valid_end"))
        except Exception:  # SourceFetchError/ValueError: refuse, never infer a time
            return ("media_source_unqualified", "the retained forecast window is not qualified")
        if not requested <= retrieved or retrieved > current:
            return ("media_source_future", "the forecast retrieval time is in the future or inconsistent")
        if current < start:
            return ("media_forecast_not_started", "the forecast day has not started")
        if current >= end:
            return ("media_forecast_ended", "the forecast day has ended")
        if current - requested > timedelta(hours=24):
            return ("media_forecast_request_old", "the forecast was requested more than 24 hours ago")
        return None
    if FAMILIES.get(kind, {}).get("signal_kind") == "fire":
        try:
            results = [fire_source_contract.freshness(fire_source_contract.validate_receipt(r), current)
                       for r in _receipts(bundle)]
        except Exception:  # SourceFetchError/ValueError: refuse, never infer a time
            return ("media_source_unqualified", "a retained detection receipt is not qualified")
        if "future" in results:
            return ("media_detection_future", "a detection's reported minute is in the future")
        if any(result != "fresh" for result in results):
            return ("media_detection_stale", "a detection is older than the 0-2 UTC source-day window")
        return None
    if kind == HOT10:
        # The contract's own final-boundary rule over every ranked row; never repaired here.
        hold = hot10_contract.current_hold(bundle, current)
        if hold is None:
            return None
        return _HOT10_HOLDS.get(hold, ("media_source_unqualified", "the retained Hot 10 bulletin is not qualified"))
    return ("media_unsupported", "unsupported attachment")


_HOT10_HOLDS = {
    "hot10_local_day_over": ("media_hot10_local_day_over", "a ranked city's forecast local day has ended"),
    "hot10_not_yet_valid": ("media_hot10_not_yet_valid", "a ranked city's forecast day has not started or its "
                            "capture is in the future"),
    "hot10_capture_stale": ("media_hot10_capture_stale", "a ranked forecast was captured more than 12 hours ago"),
}


def recheck_before_upload(draft, *, now=None):
    """Immediately before the first upload: source time can expire during checks."""
    attached = draft["media_attachment"]
    reason = currentness(attached["kind"], draft["review_context"]["two_bot"]["bundle"], now)
    if reason:
        raise MediaWithheld(*reason)


def media_for_draft(draft, *, now=None):
    """Exact reviewed recipe only: rebuild PNG and both descriptions, refuse any difference."""
    bundle = draft["review_context"]["two_bot"]["bundle"]
    attached = validate_descriptor(draft["media_attachment"], bundle)
    # The legacy Hot10 card never attaches beside a selected image; the Hot10 family
    # is that bulletin's own image, so its compact legacy rows are not a second one.
    _require(not draft.get("hot10_rows") or attached["kind"] == HOT10, "media_two_images",
             "only one explicitly selected image is allowed")
    reason = currentness(attached["kind"], bundle, now)
    if reason:
        raise MediaWithheld(*reason)
    prepared = prepare_media(bundle)
    _require(prepared["descriptor"] == attached, "media_render_mismatch",
             "image, description or render profile changed; preview and review again")
    return prepared["png"], prepared["delivery_text"]
