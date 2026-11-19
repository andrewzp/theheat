"""Build conservative cartographic IMERG tiles from pinned public map bytes.

No network, station lookup or weather data. The angular inset is an operating
exclusion, not a positional-accuracy warranty or administrative certification.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GEOGRAPHY = ROOT / "data/geography"
SOURCE = GEOGRAPHY / "ne_110m_admin_0_countries_v5_1_2.geojson"
TARGET = GEOGRAPHY / "imerg_country_tiles_v1.json"
SOURCE_SHA256 = "6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f"
SOURCE_COMMIT = "f1890d9f152c896d250a77557a5751a93d494776"
SCALE = 1_000_000
MARGIN = SCALE // 2
Point = tuple[int, int]
Rect = tuple[int, int, int, int]
Ring = tuple[Point, ...]


def cross(a: Point, b: Point, p: Point) -> int:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def on_segment(a: Point, b: Point, p: Point) -> bool:
    return (cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def touching(a: Point, b: Point, c: Point, d: Point) -> bool:
    x, y, z, w = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    if ((x > 0 > y or y > 0 > x) and (z > 0 > w or w > 0 > z)):
        return True
    return (x == 0 and on_segment(a, b, c) or y == 0 and on_segment(a, b, d)
            or z == 0 and on_segment(c, d, a) or w == 0 and on_segment(c, d, b))


def relation(point: Point, ring: Ring) -> int:
    """Strict inside=1, boundary=0, outside=-1, with exact integer predicates."""
    inside = False
    for a, b in zip(ring, ring[1:]):
        if on_segment(a, b, point):
            return 0
        if (a[1] > point[1]) != (b[1] > point[1]):
            if (cross(a, b, point) > 0) == (b[1] > a[1]):
                inside = not inside
    return 1 if inside else -1


def corners(rect: Rect) -> tuple[Point, ...]:
    x0, y0, x1, y1 = rect
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def in_box(point: Point, rect: Rect) -> bool:
    return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def boxes_overlap(a: Rect, b: Rect) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def ring_touches_box(ring: Ring, rect: Rect) -> bool:
    points = corners(rect)
    edges = tuple(zip(points, points[1:] + points[:1]))
    return any(in_box(a, rect) or any(touching(a, b, c, d) for c, d in edges)
               for a, b in zip(ring, ring[1:]))


@dataclass(frozen=True)
class Polygon:
    feature: int
    code: str
    eligible: bool
    rings: tuple[Ring, ...]
    bounds: Rect


def polygon_relation(point: Point, polygon: Polygon) -> int:
    outer = relation(point, polygon.rings[0])
    if outer <= 0:
        return outer
    for hole in polygon.rings[1:]:
        result = relation(point, hole)
        if result >= 0:
            return 0 if result == 0 else -1
    return 1


def contains_box(polygon: Polygon, rect: Rect) -> bool:
    # Corners alone miss concave inlets, interior holes and boundary crossings.
    return (all(polygon_relation(point, polygon) == 1 for point in corners(rect))
            and not any(ring_touches_box(ring, rect) for ring in polygon.rings))


def intersects_box(polygon: Polygon, rect: Rect) -> bool:
    if not boxes_overlap(polygon.bounds, rect):
        return False
    return (any(polygon_relation(point, polygon) >= 0 for point in corners(rect))
            or any(ring_touches_box(ring, rect) for ring in polygon.rings))


def coordinate(value) -> int:
    if type(value) not in (int, Decimal):
        raise ValueError("geography_coordinate_type")
    scaled = Decimal(value) * SCALE
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError("geography_coordinate_precision")
    return int(scaled)


def polygons(document, names: dict[str, str]) -> tuple[list[Polygon], list[Rect]]:
    result, unsupported = [], []
    if document.get("type") != "FeatureCollection" or not 100 <= len(document["features"]) <= 300:
        raise ValueError("geography_document_shape")
    for index, feature in enumerate(document["features"]):
        props, geometry = feature["properties"], feature["geometry"]
        code = props.get("ISO_A2_EH")
        eligible = (isinstance(code, str) and re.fullmatch(r"[A-Z]{2}", code) is not None
                    and code in names and props.get("TYPE") in {"Sovereign country", "Country"}
                    and props.get("FCLASS_ISO") == "Admin-0 country"
                    and type(props.get("BRK_DIFF")) is int and props["BRK_DIFF"] == 0
                    and not props.get("NOTE_BRK"))
        kind = geometry.get("type")
        groups = ([geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"]
                  if kind == "MultiPolygon" else None)
        if groups is None:
            raise ValueError("geography_geometry_type")
        for group in groups:
            rings = tuple(tuple((coordinate(p[0]), coordinate(p[1])) for p in ring) for ring in group)
            if not rings or any(len(ring) < 4 or ring[0] != ring[-1] for ring in rings):
                raise ValueError("geography_ring_shape")
            points = [p for ring in rings for p in ring]
            if any(abs(x) > 180 * SCALE or abs(y) > 90 * SCALE for x, y in points):
                raise ValueError("geography_coordinate_bounds")
            bounds = (min(p[0] for p in points), min(p[1] for p in points),
                      max(p[0] for p in points), max(p[1] for p in points))
            if any(abs(a[0] - b[0]) > 180 * SCALE for ring in rings for a, b in zip(ring, ring[1:])):
                unsupported.append(bounds)
                continue
            result.append(Polygon(index, code if isinstance(code, str) else "", eligible, rings, bounds))
    return result, unsupported


def tile_rectangle(column: int, row: int) -> Rect:
    x, y = (column - 180) * SCALE, (row - 90) * SCALE
    return x - MARGIN, y - MARGIN, x + SCALE + MARGIN, y + SCALE + MARGIN


def build_tiles(shapes: list[Polygon], unsupported: list[Rect]) -> list[list]:
    accepted: dict[tuple[int, int], set[str]] = {}
    for polygon in shapes:
        if not polygon.eligible:
            continue
        x0, y0, x1, y1 = polygon.bounds
        for column in range(max(0, x0 // SCALE + 180), min(360, x1 // SCALE + 181)):
            for row in range(max(30, y0 // SCALE + 90), min(150, y1 // SCALE + 91)):
                rect = tile_rectangle(column, row)
                if not contains_box(polygon, rect) or any(boxes_overlap(rect, box) for box in unsupported):
                    continue
                if any(other.feature != polygon.feature and intersects_box(other, rect) for other in shapes):
                    continue
                accepted.setdefault((column, row), set()).add(polygon.code)
    return [[column, row, next(iter(codes))] for (column, row), codes in sorted(accepted.items()) if len(codes) == 1]


def generate() -> bytes:
    raw = SOURCE.read_bytes()
    if len(raw) != 838726 or sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("geography_source_identity")
    country_bytes = (ROOT / "data/country_names.json").read_bytes()
    names = json.loads(country_bytes)["names"]
    shapes, unsupported = polygons(json.loads(raw, parse_float=Decimal), names)
    tiles = build_tiles(shapes, unsupported)
    if not tiles or len(tiles) > 43200:
        raise ValueError("geography_tile_population")
    document = {
        "schema": "theheat.imerg-cartographic-tiles/v1",
        "source": {"product": "Natural Earth 110m admin0", "version": "5.1.2",
                   "commit": SOURCE_COMMIT, "sha256": SOURCE_SHA256},
        "country_names_sha256": sha256(country_bytes).hexdigest(),
        "tile_degrees": 1, "angular_margin_degrees": .5,
        "latitude_band": [-60, 60], "tiles": tiles,
        "scope": "Inland cartographic context only; excluded borders, coasts, holes and ambiguous regions. "
                 "Not administrative certification, global coverage or a rainfall-area statistic.",
    }
    return (json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = generate()
    if args.check:
        if not TARGET.is_file() or TARGET.is_symlink() or TARGET.read_bytes() != rendered:
            raise SystemExit("IMERG cartographic tiles stale. Run python scripts/gen_imerg_country_tiles.py")
    else:
        if TARGET.is_symlink() or GEOGRAPHY.is_symlink():
            raise ValueError("geography_output_refused")
        TARGET.write_bytes(rendered)
    doc = json.loads(rendered)
    print(json.dumps({"tiles": len(doc["tiles"]), "regions": len({r[2] for r in doc["tiles"]}),
                      "bytes": len(rendered), "sha256": sha256(rendered).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
