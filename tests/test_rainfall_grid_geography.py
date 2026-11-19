"""Pinned public geography and invented integer geometry; no weather access."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts import gen_imerg_country_tiles as geo


def ring(points):
    return tuple((int(Decimal(str(x)) * geo.SCALE), int(Decimal(str(y)) * geo.SCALE)) for x, y in points)


def polygon(points, *, holes=(), feature=0, code="AA", eligible=True):
    rings = (ring(points), *(ring(hole) for hole in holes))
    all_points = [p for r in rings for p in r]
    bounds = (min(x for x, _ in all_points), min(y for _, y in all_points),
              max(x for x, _ in all_points), max(y for _, y in all_points))
    return geo.Polygon(feature, code, eligible, rings, bounds)


SQUARE = [(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]


def test_boundary_is_never_inside_and_ring_orientation_changes_no_result():
    value = ring(SQUARE)
    for point, expected in [((0, 0), 1), ((6, 0), -1), ((5, 0), 0), ((5, 5), 0)]:
        p = ring([point])[0]
        assert geo.relation(p, value) == geo.relation(p, tuple(reversed(value))) == expected


def test_hole_inside_the_rectangle_cannot_be_missed_by_its_four_corners():
    hole = [(-.1, -.1), (.1, -.1), (.1, .1), (-.1, .1), (-.1, -.1)]
    shape = polygon(SQUARE, holes=[hole])
    rect = geo.tile_rectangle(180, 90)
    assert all(geo.polygon_relation(point, shape) == 1 for point in geo.corners(rect))
    assert not geo.contains_box(shape, rect)


def test_concave_inlet_cannot_be_missed_by_rectangle_corners():
    inlet = [(-5, -5), (5, -5), (5, 5), (.2, 5), (.2, 0), (-.2, 0), (-.2, 5), (-5, 5), (-5, -5)]
    shape = polygon(inlet)
    rect = (-geo.SCALE, -geo.SCALE, geo.SCALE, geo.SCALE)
    assert all(geo.polygon_relation(point, shape) == 1 for point in geo.corners(rect))
    assert not geo.contains_box(shape, rect)


def test_the_margin_excludes_a_tile_that_fits_without_its_margin():
    shape = polygon([(-.1, -.1), (1.1, -.1), (1.1, 1.1), (-.1, 1.1), (-.1, -.1)])
    assert geo.contains_box(shape, (0, 0, geo.SCALE, geo.SCALE))
    assert not geo.contains_box(shape, geo.tile_rectangle(180, 90))
    assert geo.build_tiles([shape], []) == []


def test_disputed_or_other_region_inside_an_eligible_shape_blocks_it_in_either_order():
    large = polygon(SQUARE)
    small = polygon([(-.1, -.1), (.1, -.1), (.1, .1), (-.1, .1), (-.1, -.1)],
                    feature=1, code="BB", eligible=False)
    control = geo.build_tiles([large], [])
    assert [180, 90, "AA"] in control
    forward = geo.build_tiles([large, small], [])
    assert forward == geo.build_tiles([small, large], [])
    assert [180, 90, "AA"] not in forward
    assert {r[2] for r in forward} == {"AA"}


def test_overlapping_country_features_do_not_choose_an_input_order_winner():
    first = polygon(SQUARE, feature=1, code="AA")
    second = polygon(SQUARE, feature=2, code="BB")
    assert geo.build_tiles([first, second], []) == geo.build_tiles([second, first], []) == []


def test_unknown_geometry_bounds_block_affected_tiles_without_a_fabricated_label():
    shape = polygon(SQUARE)
    unknown = (-geo.SCALE, -geo.SCALE, geo.SCALE, geo.SCALE)
    rows = geo.build_tiles([shape], [unknown])
    assert [180, 90, "AA"] not in rows
    assert rows and all(r[2] == "AA" for r in rows)


@pytest.mark.parametrize("bad", [True, "1", float("nan"), Decimal("Infinity"), Decimal("0.0000001")])
def test_coordinates_cannot_be_coerced_or_rounded_into_membership(bad):
    with pytest.raises(ValueError):
        geo.coordinate(bad)


def test_pinned_provider_classifications_exclude_disputed_and_indeterminate_features():
    raw = geo.SOURCE.read_bytes()
    names = json.loads((geo.ROOT / "data/country_names.json").read_bytes())["names"]
    doc = json.loads(raw, parse_float=Decimal)
    shapes, unsupported = geo.polygons(doc, names)
    for shape in shapes:
        props = doc["features"][shape.feature]["properties"]
        if props["TYPE"] in {"Disputed", "Indeterminate"} or props["BRK_DIFF"]:
            assert not shape.eligible
    # The source's sole unsupported wrap is Antarctic and outside this band.
    assert unsupported and all(rect[3] < -60 * geo.SCALE for rect in unsupported)
    changed = deepcopy(doc)
    changed["features"][0]["properties"]["ISO_A2_EH"] = "XX"
    altered, _ = geo.polygons(changed, names)
    assert all(not shape.eligible for shape in altered if shape.feature == 0)


def test_pinned_raw_asset_cannot_be_replaced_or_self_rehashed(monkeypatch, tmp_path):
    changed = tmp_path / "modified.geojson"
    changed.write_bytes(geo.SOURCE.read_bytes().replace(b'"Fiji"', b'"Fake"', 1))
    monkeypatch.setattr(geo, "SOURCE", changed)
    with pytest.raises(ValueError, match="geography_source_identity"):
        geo.generate()


def test_real_generated_table_is_reproducible_bounded_and_contains_the_unmonitored_fixture():
    rendered = geo.generate()
    assert rendered == geo.TARGET.read_bytes()
    assert sha256(rendered).hexdigest() == "b863cd2dabb132da6dbda68d75c3649d68b8f95cf5768da9ea719a9c9f84ea16"
    table = json.loads(rendered)
    rows = table["tiles"]
    assert 0 < len(rows) <= 43200
    assert len({(x, y) for x, y, _ in rows}) == len(rows)
    assert all(type(x) is int and type(y) is int and 0 <= x < 360 and 30 <= y < 150 for x, y, _ in rows)
    assert [129, 79, "BR"] in rows
    assert table["source"]["sha256"] == geo.SOURCE_SHA256
    assert {code for _, _, code in rows} <= json.loads((geo.ROOT / "data/country_names.json").read_bytes())["names"].keys()
