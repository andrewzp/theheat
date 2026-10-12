"""Qualified selected MODIS centers in a bounded locator; no network or incident inference."""

from __future__ import annotations

import hashlib
from importlib.resources import files
import itertools
import json
import math

from src.editorial.revisions import fingerprint
from src.media import fire_graphic_adapter as source
from src.media.temperature_graphic_adapter import _StoredBundle

TEMPLATE = "modis_thermal_detection_map"
TEMPLATE_VERSION = "p31-modis-locator-1"
ADAPTER_VERSION = "p31-firms-modis-map-1"
ORIGINAL_SHA = "1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de"
DERIVED_SHA = "a37b057aca4fc9714a0c24b5d6bc9778bb5845894646e4052383ea63fa3cd50d"
MANIFEST_SHA = "1af072edc46ae3252bf6cf0edb43993986de262a2840b2cd4907eb4866f970e9"
PALETTE = ["#00224E", "#434E6C", "#7D7C78", "#BCAE6C", "#FEE838"]
BASEMAP = "maps/ne_110m_land_v4_1_0.json"
MANIFEST = "maps/manifest.json"
EPSILON = 1e-12


class MapQualificationError(ValueError):
    """A bounded display/resource hold, never source eligibility or success."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise MapQualificationError(code)


def resource(name, bound):
    with files("src.media").joinpath(name).open("rb") as stream:
        data = stream.read(bound + 1)
    require(len(data) <= bound, "graphic_map_basemap_unavailable")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def basemap():
    try:
        raw, metadata = resource(BASEMAP, 512 * 1024), resource(MANIFEST, 32 * 1024)
        require(
            digest(raw) == DERIVED_SHA and digest(metadata) == MANIFEST_SHA,
            "graphic_map_basemap_unavailable",
        )
        value, manifest = json.loads(raw), json.loads(metadata)
        require(
            value["schema_version"] == 1
            and value["version"] == "4.1.0"
            and value["crs"] == "EPSG:4326"
            and manifest["original_sha256"] == ORIGINAL_SHA
            and manifest["derived_sha256"] == DERIVED_SHA
            and manifest["version"] == "4.1.0"
            and manifest["crs"] == "EPSG:4326"
            and manifest["license"] == "public_domain"
            and manifest["derived_bytes"] == len(raw),
            "graphic_map_basemap_unavailable",
        )
        rings = value["rings"]
        require(
            type(rings) is list and 0 < len(rings) <= 512 and sum(map(len, rings)) <= 20_000,
            "graphic_map_basemap_unavailable",
        )
        for ring in rings:
            require(
                type(ring) is list
                and 4 <= len(ring) <= 20_000
                and ring[0] == ring[-1]
                and all(
                    type(p) is list
                    and len(p) == 2
                    and all(type(n) in (int, float) and math.isfinite(n) for n in p)
                    and abs(p[0]) <= 180 + EPSILON
                    and abs(p[1]) <= 90 + EPSILON
                    for p in ring
                ),
                "graphic_map_basemap_unavailable",
            )
        return rings, dict(
            original_sha256=ORIGINAL_SHA,
            derived_sha256=DERIVED_SHA,
            manifest_sha256=digest(metadata),
            version="4.1.0",
            crs="EPSG:4326",
        )
    except (OSError, KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise MapQualificationError("graphic_map_basemap_unavailable") from exc


def wrapped(longitude):
    return (longitude + 180) % 360 - 180


def _distance_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.dist(p, a)
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _cross(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return (
        max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
        and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))
        and orient(a, b, c) * orient(a, b, d) <= 0
        and orient(c, d, a) * orient(c, d, b) <= 0
    )


def label_positions(markers, rectangle):
    left, bottom, width, height = rectangle
    options = [(0, 48), (48, 48), (48, 0), (48, -48), (0, -48), (-48, -48), (-48, 0), (-48, 48)]
    candidates = []
    for i, (x, y) in enumerate(markers):
        current = []
        for dx, dy in options:
            cx, cy = x + dx, y + dy
            box = (cx - 14, cy - 22, cx + 14, cy + 22)
            if not (
                left <= box[0]
                and box[2] <= left + width
                and bottom <= box[1]
                and box[3] <= bottom + height
            ):
                continue
            end = (
                cx if dx == 0 else cx - math.copysign(14, dx),
                cy if dy == 0 else cy - math.copysign(22, dy),
            )
            if any(
                j != i
                and (
                    math.hypot(max(box[0] - px, 0, px - box[2]), max(box[1] - py, 0, py - box[3]))
                    < 18
                    or _distance_segment((px, py), (x, y), end) < 18
                )
                for j, (px, py) in enumerate(markers)
            ):
                continue
            current.append(dict(x=cx, y=cy, box=list(box), leader_end=list(end)))
        candidates.append(current)
    for trial in itertools.product(*candidates):
        valid = True
        for i in range(len(trial)):
            for j in range(i):
                a, b = trial[i]["box"], trial[j]["box"]
                if not (a[2] + 4 < b[0] or b[2] + 4 < a[0] or a[3] + 4 < b[1] or b[3] + 4 < a[1]):
                    valid = False
                if _cross(markers[i], trial[i]["leader_end"], markers[j], trial[j]["leader_end"]):
                    valid = False
        if valid:
            return list(trial)
    raise MapQualificationError("graphic_map_labels_exceed_space")


def geometry(points):
    require(
        1 <= len(points) <= 4 and all(abs(p["lat"]) <= 75 for p in points),
        "graphic_map_outside_locator_bounds",
    )
    longitudes = sorted({p["lon"] % 360 for p in points})
    gaps = [
        (
            (longitudes[(i + 1) % len(longitudes)] - v) % 360 or 360,
            longitudes[(i + 1) % len(longitudes)],
        )
        for i, v in enumerate(longitudes)
    ]
    gap, start = min(gaps, key=lambda row: (-row[0], row[1]))
    span = 360 - gap
    center = start + span / 2
    raw_lats = [p["lat"] for p in points]
    lat_span = max(raw_lats) - min(raw_lats)
    middle = (min(raw_lats) + max(raw_lats)) / 2
    width = max(0.020, span + 2 * max(0.002, 0.1 * span))
    height = max(0.010, lat_span + 2 * max(0.002, 0.1 * lat_span))
    west, east = center - width / 2, center + width / 2
    south, north = middle - height / 2, middle + height / 2
    require(
        width <= 120 and height <= 60 and south >= -80 and north <= 80,
        "graphic_map_outside_locator_bounds",
    )
    scale = min(1088 / width, 470 / height)
    rect = [
        56 + (1088 - width * scale) / 2,
        620 + (470 - height * scale) / 2,
        width * scale,
        height * scale,
    ]
    markers = [
        [
            rect[0] + ((p["lon"] - center + 180) % 360 - 180 + width / 2) * scale,
            rect[1] + (p["lat"] - south) * scale,
        ]
        for p in points
    ]
    require(
        all(math.dist(a, b) >= 36 for i, a in enumerate(markers) for b in markers[:i]),
        "graphic_map_points_overlap",
    )
    labels = label_positions(markers, rect)
    return dict(
        version="p31-locator-1",
        projection="plate_carree",
        bounds=[west, south, east, north],
        rectangle=rect,
        scale=scale,
        markers=markers,
        labels=labels,
        dateline_crossing=math.floor((west + 180) / 360) != math.floor((east + 180) / 360),
        context_mode="coordinate_closeup" if width < 20 or height < 10 else "coarse_land_locator",
        palette=list(PALETTE),
        axis_max=source.frp_axis([p["frp_source"] for p in points]),
    )


def color(value, top):
    fraction = max(0, min(1, value / top)) * 4
    index = min(3, int(fraction))
    t = fraction - index
    values = [tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in PALETTE[index : index + 2]]
    return "#" + "".join(f"{math.floor(a + (b - a) * t + 0.5):02x}" for a, b in zip(*values))


def clipped_segments(rings, bounds):
    """Outline segments only; periodic copies and exact rectangular clipping."""
    west, south, east, north = bounds
    center = (west + east) / 2
    for ring in rings:
        for a, b in zip(ring, ring[1:]):
            x1 = center + wrapped(a[0] - center)
            x2 = x1 + wrapped(b[0] - a[0])
            y1, y2 = a[1], b[1]
            for shift in (-360, 0, 360):
                ax, bx = x1 + shift, x2 + shift
                dx, dy = bx - ax, y2 - y1
                lo, hi = 0.0, 1.0
                for p, q in (
                    (-dx, ax - west),
                    (dx, east - ax),
                    (-dy, y1 - south),
                    (dy, north - y1),
                ):
                    if p == 0:
                        if q < 0:
                            hi = -1
                            break
                    elif p < 0:
                        lo = max(lo, q / p)
                    else:
                        hi = min(hi, q / p)
                if lo <= hi:
                    yield [ax + lo * dx, y1 + lo * dy, ax + hi * dx, y1 + hi * dy]


def _project(bundle, bundle_sha, receipts, synthetic):
    value = source.fire_graphic_spec(
        bundle,
        expected_bundle_sha256=bundle_sha,
        expected_receipt_sha256=receipts,
        synthetic=synthetic,
    )["evidence"]
    _, retained = basemap()
    value["input_binding"]["adapter_version"] = ADAPTER_VERSION
    value["map"] = {
        **geometry(value["points"]),
        "basemap": retained,
        "source_adapter_sha256": digest(resource("fire_graphic_adapter.py", 128 * 1024)),
    }
    return value


def fire_map_graphic_spec(bundle, *, expected_bundle_sha256, expected_receipt_sha256, synthetic):
    value = _project(bundle, expected_bundle_sha256, expected_receipt_sha256, synthetic)
    return dict(template=TEMPLATE, expected_evidence_sha256=fingerprint(value), evidence=value)


def validate_map_adapter_binding(evidence):
    try:
        binding = evidence["input_binding"]
        require(
            binding["adapter_version"] == ADAPTER_VERSION and len(binding["bundles"]) == 1,
            "graphic_map_basemap_unavailable",
        )
        row = binding["bundles"][0]
        expected = _project(
            _StoredBundle(row["bundle"]),
            row["bundle_sha256"],
            binding["selected_receipt_sha256"],
            evidence["synthetic"],
        )
        if fingerprint(expected) != fingerprint(evidence):
            raise ValueError("Map differs from retained source or renderer resources")
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise ValueError("Malformed map evidence binding") from exc


def map_alt_text(evidence):
    # Reuse source qualifications, replacing only the bar-specific description.
    text = source.fire_alt_text(evidence)
    text = text.replace(
        "Bars begin at zero in retained primary/related order; no ranking of physical fires.",
        "Equal-size markers retain exact source centers; A-D retain primary/related source order, not a fire ranking.",
    )
    text = text.replace(
        "Bar lengths use exact source values; visible FRP labels are rounded to one decimal and pixel-center coordinates to four decimals.",
        "Blue-to-yellow colors show pixel FRP linearly from zero to "
        + str(evidence["map"]["axis_max"])
        + " MW. Exact round-trip FRP values are visible; coordinate labels round to four decimals.",
    )
    return (
        text
        + " Plate carree longitude-latitude locator, not a distance or area map. "
        + (
            "Coordinate close-up: coarse coastlines omitted; world inset supplies location only. "
            if evidence["map"]["context_mode"] == "coordinate_closeup"
            else "Coarse Natural Earth land outlines, not exact local boundaries. "
        )
        + ("Viewport crosses the dateline. " if evidence["map"]["dateline_crossing"] else "")
        + "Natural Earth 110m land4.1.0, public domain. Small islands may be absent; absence is not evidence of water. "
        "Markers are not pixel footprints or fire perimeters. Unreadable overlaps are withheld, never displaced."
    )
