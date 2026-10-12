"""Invented coordinates exercise exact scientific/geometry bindings; no source truth claim."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from src.editorial.revisions import fingerprint
from src.media import fire_map_graphic_adapter as adapter
from src.media.evidence_graphic import validate_graphic
from src.media.evidence_graphic_render import render_svg
from tests.fire_graphic_helpers import graphic_bundle
from tests.test_fire_graphic_adapter import adapt as old_spec

NEIGHBORS = [(35, -110), (35, -109.989), (35.009, -110), (35.009, -109.989)]


def adapt(bundle=None, **changes):
    bundle = bundle or graphic_bundle()
    raw = bundle.to_dict()
    receipts = [
        raw["raw_signal_dump"]["acquisition_provenance"],
        *[r["acquisition_evidence"] for r in raw.get("related_signals", [])],
    ]
    options = dict(
        expected_bundle_sha256=fingerprint(raw),
        expected_receipt_sha256=[fingerprint(r) for r in receipts],
        synthetic=True,
    )
    return adapter.fire_map_graphic_spec(bundle, **{**options, **changes})


def test_same_sources_exact_values_no_new_fact_or_bar_language():
    bundle = graphic_bundle()
    before = deepcopy(bundle.to_dict())
    spec = adapt(bundle)
    legacy = old_spec(bundle)
    e = spec["evidence"]
    old = legacy["evidence"]
    for key in set(old) - {"input_binding"}:
        assert e[key] == old[key]
    assert e["input_binding"]["bundles"] == old["input_binding"]["bundles"]
    assert (
        e["input_binding"]["selected_receipt_sha256"]
        == old["input_binding"]["selected_receipt_sha256"]
    )
    assert bundle.to_dict() == before
    alt = adapter.map_alt_text(e)
    assert "Bars" not in alt and "Bar lengths" not in alt
    for word in (
        "MW",
        "500.1234",
        "not temperature",
        "not original HTTP",
        "same overpass",
        "not pixel footprints",
    ):
        assert word in alt
    assert (
        validate_graphic(
            **{k: spec[k] for k in ("template", "evidence", "expected_evidence_sha256")}
        )
        == e
    )


@pytest.mark.parametrize(
    "coordinates",
    [
        NEIGHBORS,
        [(35, -110 + i * 0.011) for i in range(4)],
        [(35 + i * 0.009, -110 + i * 0.011) for i in range(4)],
        [(35, 179.9945), (35, -179.9945), (35.009, 179.9945), (35.009, -179.9945)],
        [(-35, 25)],
        [(75, 10)],
        [(0, 180)],
        [(0, -180)],
    ],
)
def test_real_svg_closeups_neighbor_dateline_and_boundaries(coordinates):
    spec = adapt(
        graphic_bundle(
            values=[125.75, 500.1234, 750.25, 250][: len(coordinates)], coordinates=coordinates
        )
    )
    result = render_svg(**spec)
    assert result == render_svg(**spec)
    assert b"Coordinate close-up" in result["svg"]
    assert spec["evidence"]["map"]["context_mode"] == "coordinate_closeup"
    root = ET.fromstring(result["svg"])
    ns = "{http://www.w3.org/2000/svg}"
    all_text = " ".join(root.itertext())
    for p in spec["evidence"]["points"]:
        assert str(p["frp_source"]) + " MW" in all_text
    circles = root.findall(".//" + ns + "circle")
    assert sum(c.attrib.get("r") == "14" for c in circles) == len(coordinates)
    assert len(result["svg"]) <= 1_000_000


def test_actual_one_km_geometry_matches_approved_example():
    e = adapt(graphic_bundle(values=[1, 2, 3, 4], coordinates=NEIGHBORS))["evidence"]
    g = e["map"]
    a, b, c, d = g["markers"]
    assert g["bounds"] == pytest.approx([249.9955, 34.998, 250.0155, 35.011])
    assert math.dist(a, b) == pytest.approx(397.692307692, abs=1e-5)
    assert math.dist(a, c) == pytest.approx(325.384615385, abs=1e-5)
    assert all(label["x"] == p[0] and label["y"] == p[1] + 48 for label, p in zip(g["labels"], g["markers"]))


@pytest.mark.parametrize(
    "coordinates,code",
    [([(75.0001, 10)], "outside_locator_bounds"), ([(0, 0), (0, 130)], "outside_locator_bounds")],
)
def test_unsupported_geometry_holds_without_changing_sources(coordinates, code):
    bundle = graphic_bundle(values=[1] * len(coordinates), coordinates=coordinates)
    before = bundle.to_dict()
    with pytest.raises(adapter.MapQualificationError, match=code):
        adapt(bundle)
    assert bundle.to_dict() == before


def test_viewport_permutation_and_dateline_tie_are_deterministic():
    pts = [dict(lat=0, lon=179, frp_source=1), dict(lat=1, lon=-179, frp_source=2)]
    a = adapter.geometry(pts)
    b = adapter.geometry(pts[::-1])
    assert a["bounds"] == b["bounds"] and a["dateline_crossing"]
    with pytest.raises(adapter.MapQualificationError):
        adapter.geometry([dict(lat=0, lon=x, frp_source=1) for x in (0, 120, 240)])


@pytest.mark.parametrize("field", ["points", "map", "bundle"])
def test_rehashed_geometry_or_source_edits_are_not_authority(field):
    spec = adapt()
    e = spec["evidence"]
    if field == "points":
        e["points"][0]["frp_source"] += 1
    elif field == "map":
        e["map"]["markers"][0][0] += 1
    else:
        e["input_binding"]["bundles"][0]["bundle"]["where"] = "changed"
    with pytest.raises(ValueError):
        validate_graphic(spec["template"], e, expected_evidence_sha256=fingerprint(e))


def test_palette_luminance_monotonic_exact_zero_and_top():
    values = [adapter.color(i, 255) for i in range(256)]

    def lum(h):
        rgb = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(a * b for a, b in zip(linear, [0.2126, 0.7152, 0.0722]))

    assert values[0].upper() == adapter.PALETTE[0] and values[-1].upper() == adapter.PALETTE[-1]
    assert all(lum(a) <= lum(b) for a, b in zip(values, values[1:]))


@pytest.mark.parametrize("failure", ["missing", "derived", "manifest"])
def test_resource_failure_is_typed_even_in_current_preview(monkeypatch, failure):
    original = adapter.resource

    def changed(name, bound):
        if name == adapter.BASEMAP and failure == "missing":
            raise OSError("gone")
        raw = original(name, bound)
        return (
            raw + b" "
            if (name == adapter.BASEMAP and failure == "derived")
            or (name == adapter.MANIFEST and failure == "manifest")
            else raw
        )

    monkeypatch.setattr(adapter, "resource", changed)
    with pytest.raises(adapter.MapQualificationError, match="basemap_unavailable"):
        adapt()


def test_exact_pinned_resource_counts_and_source_numbers():
    rings, ref = adapter.basemap()
    assert len(rings) == 128 and sum(map(len, rings)) == 5143
    assert any(x > 180 for ring in rings for x, y in ring)
    assert ref["original_sha256"] == adapter.ORIGINAL_SHA
    assert ref["derived_sha256"] == adapter.DERIVED_SHA


def test_outline_segments_clip_dateline_without_connecting_the_world():
    rings = [[[179, 1], [-179, 1], [-179, 2], [179, 1]]]
    segments = list(adapter.clipped_segments(rings, [170, 0, 190, 3]))
    assert len(segments) == 3
    assert all(170 <= x <= 190 and 0 <= y <= 3 for seg in segments for x, y in [seg[:2], seg[2:]])
    assert max(abs(seg[2] - seg[0]) for seg in segments) <= 2


def test_close_duplicate_source_identity_refuses_before_display_gate():
    bundle = graphic_bundle(values=[1, 2], coordinates=[(0, 0), (0.000001, 0.000001)])
    with pytest.raises(ValueError, match="self_related_identity"):
        adapt(bundle)
    with pytest.raises(adapter.MapQualificationError, match="points_overlap"):
        adapter.geometry(
            [dict(lat=0, lon=0, frp_source=1), dict(lat=0.000001, lon=0.000001, frp_source=2)]
        )


def test_coarse_regions_zero_and_exact_values_keep_all_text_at_40px():
    spec = adapt(graphic_bundle(values=[0, 500.1234, 750.25, 250], coordinates=[(-20, 15), (0, 25), (5, 35), (10, 40)]))
    assert spec["evidence"]["map"]["context_mode"] == "coarse_land_locator"
    svg = render_svg(**spec)["svg"]
    root = ET.fromstring(svg)
    text = " ".join(root.itertext())
    assert "0.0 MW" in text and "500.1234 MW" in text
    styles = [node.attrib.get("style", "") for node in root.iter() if node.tag.endswith("text")]
    import re
    sizes = [float(x) for style in styles for x in re.findall(r"font-size: ([0-9.]+)px", style)]
    assert sizes and min(sizes) >= 40


def test_unreadable_exact_numeric_value_holds_without_shortening():
    spec = adapt(graphic_bundle(values=[1.2345678901234567e100]))
    with pytest.raises(adapter.MapQualificationError, match="labels_exceed_space"):
        render_svg(**spec)


def test_marker_overlap_guard_exact_boundary_without_source_clamping():
    # Pure layout probes retain exact source coordinates; this is not source qualification.
    span = .020
    scale = min(1088 / span, 470 / .010)
    for distance in (35.9, 36.1):
        points = [dict(lat=0, lon=0, frp_source=1), dict(lat=0, lon=distance / scale, frp_source=2)]
        if distance < 36:
            with pytest.raises(adapter.MapQualificationError, match="points_overlap"):
                adapter.geometry(points)
        else:
            g = adapter.geometry(points)
            assert math.dist(*g["markers"]) == pytest.approx(distance)


def test_original_world_segments_stay_inside_exact_viewport():
    rings, _ = adapter.basemap()
    for bounds in ([-180, -90, 180, 90], [170, -5, 190, 5], [12.5, -23, 42.5, 13]):
        segments = list(adapter.clipped_segments(rings, bounds))
        # This pinned coarse product has no coastline in the equatorial dateline
        # window; an empty outline must not fabricate land or establish water.
        assert bool(segments) is (bounds != [170, -5, 190, 5])
        for row in segments:
            for i in (0, 2):
                assert bounds[0] <= row[i] <= bounds[2]
                assert bounds[1] <= row[i + 1] <= bounds[3]


def test_root_counterexample_cannot_draw_a_leader_through_another_label():
    coordinates = [
        (37.39683884252334, -109.71580495635722),
        (37.801182992134464, -107.63586992814105),
        (37.93709394080457, -107.5998425381229),
        (36.7524897553822, -109.04853878538918),
    ]
    spec = adapt(graphic_bundle(values=[125.75] * 4, coordinates=coordinates))
    g = spec["evidence"]["map"]
    # caece05 accepted C's diagonal through B's box at this exact retained input.
    old_c_end = [983.8012067407437, 1024.8333333333323]
    old_b_box = [971.8894408270712, 1031.896983382698, 999.8894408270712, 1075.896983382698]
    assert adapter._segment_hits_box(g["markers"][2], old_c_end, old_b_box)
    assert (g["labels"][2]["leader_end"], g["labels"][1]["box"]) != (old_c_end, old_b_box)
    # Independently sample every resulting segment, including its endpoints.
    # The original collision covers a substantial span and fails this regression.
    for i, label in enumerate(g["labels"]):
        a, b = g["markers"][i], label["leader_end"]
        for j, other in enumerate(g["labels"]):
            if i == j:
                continue
            left, bottom, right, top = other["box"]
            for step in range(1001):
                t = step / 1000
                x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                assert not (left <= x <= right and bottom <= y <= top)
    assert render_svg(**spec)["publication_approved"] is False


def test_readiness_layout_uses_embedded_metrics_without_draw_or_native_work(monkeypatch):
    from reportlab.pdfbase import pdfmetrics
    from src.media import evidence_graphic_render as renderer
    def forbidden(*args, **kwargs):
        raise AssertionError("Layout preflight attempted drawing, registration, output or native work")
    monkeypatch.setattr(renderer, "_drawing", forbidden)
    monkeypatch.setattr(renderer.subprocess, "run", forbidden)
    monkeypatch.setattr(pdfmetrics, "registerFont", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    layout = renderer.map_text_layout(adapt()["evidence"])
    assert len(layout["longitudes"]) == len(layout["latitudes"]) == len(layout["rows"]) == 3
    spec = adapt(graphic_bundle(values=[1.2345678901234567e100]))
    with pytest.raises(adapter.MapQualificationError, match="graphic_map_labels_exceed_space"):
        renderer.map_text_layout(spec["evidence"])
