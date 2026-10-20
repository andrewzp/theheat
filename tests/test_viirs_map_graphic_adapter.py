"""Invented NOAA-20/NOAA-21 VIIRS pixels exercise exact source/geometry bindings; no source truth claim."""

from copy import deepcopy
from datetime import timedelta
import json
import math
import xml.etree.ElementTree as ET

import pytest

from src.data.fire_source_contract import HMS_PRODUCT, _digest
from src.editorial.revisions import fingerprint
from src.media import fire_map_graphic_adapter as locator
from src.media import viirs_map_graphic_adapter as adapter
from src.media.evidence_graphic import build_alt_text, validate_graphic
from src.media.evidence_graphic_render import map_text_layout, render_svg
from src.media.temperature_graphic_adapter import _StoredBundle
from tests.viirs_graphic_helpers import WHEN, viirs_bundle

NS = "{http://www.w3.org/2000/svg}"
NEIGHBORS = [(35, -110), (35, -109.989), (35.009, -110), (35.009, -109.989)]
PLATFORM = {"VIIRS_NOAA20_NRT": ("NOAA-20", "N20"), "VIIRS_NOAA21_NRT": ("NOAA-21", "N21")}
CODE = {"low": "l", "nominal": "n", "high": "h"}


def adapt(bundle=None, **changes):
    bundle = bundle or viirs_bundle()
    raw = bundle.to_dict()
    receipts = [raw["raw_signal_dump"].get("acquisition_provenance"),
                *[r.get("acquisition_evidence") for r in raw.get("related_signals", [])]]
    options = dict(expected_bundle_sha256=fingerprint(raw),
                   expected_receipt_sha256=[fingerprint(r) for r in receipts], synthetic=True)
    return adapter.viirs_map_graphic_spec(bundle, **{**options, **changes})


def visible(svg):
    return ["".join(node.itertext()) for node in ET.fromstring(svg).findall(".//" + NS + "text")]


@pytest.mark.parametrize("count", [1, 4])
@pytest.mark.parametrize("product", ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"])
def test_supported_products_render_exact_source_order_values_categories_and_minute(product, count):
    values = [125.75, 500.1234, 750.25, 250][:count]
    categories = ("high", "nominal", "low", "high")[:count]
    bundle = viirs_bundle(values, product=product, categories=categories, coordinates=NEIGHBORS[:count])
    before = deepcopy(bundle.to_dict())
    spec = adapt(bundle)
    e = spec["evidence"]
    platform, code = PLATFORM[product]
    assert spec["template"] == "viirs_thermal_detection_map"
    assert (e["source_product"], e["instrument"], e["satellite"], e["satellite_code"]) == (product, "VIIRS", platform, code)
    assert (e["acquired_at"], e["acquisition_precision"], e["confidence_kind"]) == ("2032-02-29T23:59:00Z", "minute", "categorical")
    assert [p["label"] for p in e["points"]] == list("ABCD")[:count]
    assert [p["role"] for p in e["points"]] == ["primary"] + ["related"] * (count - 1)
    assert [p["frp_source"] for p in e["points"]] == values
    assert [p["confidence_category"] for p in e["points"]] == list(categories)
    assert [p["source_confidence_code"] for p in e["points"]] == [CODE[c] for c in categories]
    # The internal 30/70/95 ranking never enters the projection.
    assert all(set(p) == {"label", "role", "event_id", "lat", "lon", "frp_source", "confidence_category",
                          "source_confidence_code", "source_version", "receipt_sha256"} for p in e["points"])
    assert e["input_binding"]["bundles"][0]["bundle"] == before
    assert e["input_binding"]["adapter_version"] == adapter.ADAPTER_VERSION
    assert bundle.to_dict() == before
    assert validate_graphic(spec["template"], e, expected_evidence_sha256=spec["expected_evidence_sha256"]) == e

    result = render_svg(**spec)
    assert result == render_svg(**spec)
    assert result["binding"]["template_version"] == "p31-viirs-locator-1"
    assert result["publication_approved"] is False and result["synthetic"] is True
    texts = visible(result["svg"])
    for expected in ["THEHEAT", "SYNTHETIC DATA", f"{values[0]} MW", "Pixel A radiative power",
                     f"NASA FIRMS · {platform} VIIRS", "2032-02-29 23:59 UTC", "Source detection confidence",
                     " · ".join(f"{label} {c}" for label, c in zip("ABCD", categories))]:
        assert expected in texts
    for letter in "ABCD"[:count]:
        assert letter in texts
    assert sum(c.attrib.get("r") == "14" for c in ET.fromstring(result["svg"]).iter(NS + "circle")) == count
    alt = result["alt_text"]
    assert alt == build_alt_text(spec["template"], e) and alt.startswith("SYNTHETIC DEMONSTRATION")
    for p in e["points"]:
        assert f"latitude {p['lat']}, longitude {p['lon']}; source FRP {p['frp_source']} MW" in alt
        assert f"detection confidence category {p['confidence_category']} (source code {p['source_confidence_code']})" in alt
    assert f"{platform}/VIIRS (satellite code {code})" in alt and "minute precision" in alt
    # Never a MODIS label, a percentage or a numeric confidence.
    for text in [*texts, alt, result["title"]]:
        assert "MODIS" not in text and "%" not in text
    assert "not a percentage, probability, numeric quality score, severity" in alt
    assert "pixel-integrated fire radiative power in megawatts" in alt and "never combined into a total" in alt
    assert "do not establish simultaneity, the same overpass or a common incident" in alt


def test_southern_hemisphere_and_dateline_geometry():
    south = adapt(viirs_bundle([88.4, 12.5], coordinates=[(-33.9, 18.6), (-33.909, 18.611)]))["evidence"]
    west, low, east, high = south["map"]["bounds"]
    assert low < high < 0 and not south["map"]["dateline_crossing"]
    captions = [row["text"] for row in map_text_layout(south)["latitudes"]]
    assert all(c.endswith("°S") for c in captions)
    # Ordered south -> north: the lower edge is further from the equator.
    assert float(captions[0][:-2]) > float(captions[1][:-2])

    for coordinates in ([(35, 179.9945), (35, -179.9945), (35.009, 179.9945), (35.009, -179.9945)],
                        [(-16.5, 179.9945), (-16.5, -179.9945)]):
        spec = adapt(viirs_bundle([125.75, 500.1234, 750.25, 250][:len(coordinates)], coordinates=coordinates))
        e = spec["evidence"]
        assert e["map"]["dateline_crossing"]
        assert [(p["lat"], p["lon"]) for p in e["points"]] == [(float(a), float(b)) for a, b in coordinates]
        result = render_svg(**spec)
        assert "Viewport crosses the dateline." in result["alt_text"]
        # The west edge lies in the eastern hemisphere and the east edge in the western one.
        west_caption, east_caption = (row["text"] for row in map_text_layout(e)["longitudes"])
        assert west_caption.endswith("°E") and east_caption.endswith("°W")
        assert west_caption in visible(result["svg"]) and east_caption in visible(result["svg"])


def test_shorter_frame_keeps_every_row_clear_of_the_map_and_inset():
    spec = adapt(viirs_bundle([125.75, 500.1234, 750.25, 250], coordinates=NEIGHBORS,
                              categories=("nominal",) * 4))
    e = spec["evidence"]
    assert e["map"]["frame"] == list(adapter.MAP_FRAME) == [112, 354, 1032, 610]
    left, bottom, width, height = e["map"]["rectangle"]
    assert bottom + height <= 354 + 610
    layout = map_text_layout(e)
    rows = [row for row in layout["texts"] if row not in layout["point_labels"]]
    assert all(row["size"] >= 40 for row in layout["texts"])
    for row in rows:
        x0, y0, x1, y1 = row["box"]
        assert 20 <= x0 < x1 <= 1180 and 20 <= y0 < y1 <= 1480
        assert x1 <= left or left + width <= x0 or y1 <= bottom or bottom + height <= y0
    for i, a in enumerate(layout["texts"]):
        for b in layout["texts"][:i]:
            assert a["box"][2] <= b["box"][0] or b["box"][2] <= a["box"][0] or a["box"][3] <= b["box"][1] or b["box"][3] <= a["box"][1]
    # Worst-case category width still fits one row at the 40 px floor.
    assert "A nominal · B nominal · C nominal · D nominal" in [row["text"] for row in layout["texts"]]


@pytest.mark.parametrize("synthetic", [None, 0, "false"])
def test_synthetic_status_is_explicit(synthetic):
    with pytest.raises(ValueError, match="synthetic"):
        adapt(synthetic=synthetic)


def test_non_synthetic_preview_is_labeled_review_not_synthetic():
    result = render_svg(**adapt(synthetic=False))
    assert "REVIEW PREVIEW" in visible(result["svg"]) and "SYNTHETIC DATA" not in visible(result["svg"])
    assert "SYNTHETIC" not in result["alt_text"] and result["synthetic"] is False


def _rehash(receipt):
    receipt["record_sha256"] = _digest(receipt["record"])


def _tamper(s, target, change):
    holder, key = ((s["raw_signal_dump"], "acquisition_provenance") if target == "primary"
                   else (s["related_signals"][0], "acquisition_evidence"))
    receipt = holder[key]
    if change == "missing":
        holder[key] = None
    elif change == "altered":
        receipt["record"]["frp"] = "999"  # not rehashed
    elif change == "rehashed_frp":
        receipt["record"]["frp"] = "999"
        _rehash(receipt)
    elif change == "rehashed_category":
        receipt["record"]["confidence"] = "l" if receipt["record"]["confidence"] != "l" else "h"
        _rehash(receipt)
    elif change == "product":
        receipt["source_product"] = "VIIRS_SNPP_NRT"
    elif change == "platform":
        receipt["record"]["satellite"] = "N21"
        _rehash(receipt)
    elif change == "instrument":
        receipt["record"]["instrument"] = "MODIS"
        _rehash(receipt)
    elif change == "minute":
        receipt["record"]["acq_time"] = "2358"
        _rehash(receipt)
    else:
        receipt["record"]["confidence"] = "high"  # category word, not the source spelling
        _rehash(receipt)


# A related summary carries no confidence field, so a related row's internally
# rehashed category is caught only by the independent receipt binding (below).
_SELF_CONSISTENT = {("related", "rehashed_category")}


@pytest.mark.parametrize("target,change", [
    (target, change) for target in ("primary", "related")
    for change in ("missing", "altered", "rehashed_frp", "rehashed_category", "product", "platform",
                   "instrument", "minute", "category_spelling")
    if (target, change) not in _SELF_CONSISTENT])
def test_missing_altered_or_rehashed_receipts_are_refused(target, change):
    s = viirs_bundle().to_dict()
    _tamper(s, target, change)
    before = deepcopy(s)
    # Bindings are recomputed from the tampered story, so only content consistency can refuse.
    with pytest.raises(ValueError):
        adapt(_StoredBundle(s))
    assert s == before


@pytest.mark.parametrize("target", ["primary", "related"])
@pytest.mark.parametrize("change", ["rehashed_frp", "rehashed_category", "minute"])
def test_rehashed_receipt_cannot_replace_the_independent_receipt_binding(target, change):
    original = viirs_bundle().to_dict()
    receipts = [original["raw_signal_dump"]["acquisition_provenance"],
                *[r["acquisition_evidence"] for r in original["related_signals"]]]
    reviewed = [fingerprint(r) for r in receipts]
    s = deepcopy(original)
    _tamper(s, target, change)
    # Even with a current bundle hash, the reviewed receipt binding refuses the rewrite.
    with pytest.raises(ValueError):
        adapter.viirs_map_graphic_spec(_StoredBundle(s), expected_bundle_sha256=fingerprint(s),
                                       expected_receipt_sha256=reviewed, synthetic=True)


@pytest.mark.parametrize("change", ["bundle", "receipt", "order", "missing", "extra"])
def test_obsolete_or_incomplete_expected_bindings_are_refused(change):
    b = viirs_bundle()
    hashes = adapt(b)["evidence"]["input_binding"]["selected_receipt_sha256"]
    changes = {"expected_receipt_sha256": hashes}
    if change == "bundle":
        changes["expected_bundle_sha256"] = "a" * 64
    elif change == "receipt":
        hashes[0] = "a" * 64
    elif change == "order":
        hashes.reverse()
    elif change == "missing":
        hashes.pop()
    else:
        hashes.append("a" * 64)
    with pytest.raises(ValueError):
        adapt(b, **changes)


@pytest.mark.parametrize("change", ["snpp", "hms", "modis", "mixed_viirs", "viirs_with_modis", "minute",
                                    "duplicate", "five", "colliding_identity", "other_hazard", "extension",
                                    "footprint"])
def test_unsupported_full_stories_are_held_never_trimmed(change):
    from src.two_bot.intern.fire import build_fire_bundle
    from tests.fire_source_fixtures import fire_event

    b = viirs_bundle()
    if change == "snpp":
        b = viirs_bundle(product="VIIRS_SNPP_NRT")
    elif change == "hms":
        b = build_fire_bundle(fire_event(product=HMS_PRODUCT))
    elif change == "modis":
        b = build_fire_bundle(fire_event(product="MODIS_NRT", confidence=91))
    elif change == "mixed_viirs":
        b = viirs_bundle([10, 20], products=["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"])
    elif change == "viirs_with_modis":
        b = viirs_bundle([10, 20], products=["VIIRS_NOAA20_NRT", "MODIS_NRT"], categories=("high", "high"))
    elif change == "minute":
        b = viirs_bundle([10, 20], when=[WHEN, WHEN - timedelta(minutes=1)])
    elif change == "duplicate":
        b.related_signals.append(deepcopy(b.related_signals[0]))
    elif change == "five":
        b = viirs_bundle([1, 2, 3, 4, 5], categories=("high",) * 5)
    elif change == "colliding_identity":
        b = viirs_bundle([10, 20], coordinates=[(35.2501, -110.5), (35.2502, -110.5)])
    elif change == "other_hazard":
        b.related_signals[0].signal_kind = "dust_event"
    else:
        s = b.to_dict()
        if change == "footprint":
            s["signal_kind"] = "fire_footprint"
        else:
            s["human_impact"] = {"unqualified": True}
        b = _StoredBundle(s)
    before = deepcopy(b.to_dict())
    with pytest.raises(ValueError):
        adapt(b)
    assert b.to_dict() == before


@pytest.mark.parametrize("field,value", [("lat", True), ("frp_source", True), ("frp_source", float("inf")),
                                         ("frp_source", float("nan")), ("frp_source", "500.1234"),
                                         ("confidence", 95), ("confidence", True)])
def test_projection_values_must_be_exact_typed_not_coerced(field, value):
    s = viirs_bundle().to_dict()
    s["raw_signal_dump"][field] = value
    with pytest.raises(ValueError):
        adapt(_StoredBundle(s))


@pytest.mark.parametrize("values", [[0, 0], [1.7e308], [5e-324]])
def test_all_zero_or_unrenderable_frp_scale_is_refused_without_a_modis_label(values):
    with pytest.raises(ValueError) as error:
        adapt(viirs_bundle(values, categories=("high",) * len(values),
                           coordinates=NEIGHBORS[:len(values)]))
    assert "MODIS" not in str(error.value)


def test_unreadable_exact_lead_value_holds_without_shortening():
    spec = adapt(viirs_bundle([1.2345678901234567e100], categories=("high",)))
    with pytest.raises(locator.MapQualificationError, match="labels_exceed_space"):
        render_svg(**spec)


@pytest.mark.parametrize("coordinates,code", [([(75.0001, 10)], "outside_locator_bounds"),
                                              ([(0, 0), (0, 130)], "outside_locator_bounds")])
def test_unsupported_geometry_holds_without_changing_sources(coordinates, code):
    bundle = viirs_bundle([1] * len(coordinates), coordinates=coordinates, categories=("high",) * len(coordinates))
    before = bundle.to_dict()
    with pytest.raises(locator.MapQualificationError, match=code):
        adapt(bundle)
    assert bundle.to_dict() == before


def test_marker_overlap_guard_uses_the_viirs_frame_exactly():
    span = .020
    frame = adapter.MAP_FRAME
    scale = min(frame[2] / span, frame[3] / .010)
    for distance in (35.9, 36.1):
        points = [dict(lat=0, lon=0, frp_source=1), dict(lat=0, lon=distance / scale, frp_source=2)]
        if distance < 36:
            with pytest.raises(locator.MapQualificationError, match="points_overlap"):
                locator.geometry(points, frame=frame)
        else:
            assert math.dist(*locator.geometry(points, frame=frame)["markers"]) == pytest.approx(distance)


@pytest.mark.parametrize("change", ["frp", "category", "code", "order", "dropped", "satellite", "instrument",
                                    "product", "minute", "markers", "frame", "shared_code", "synthetic",
                                    "adapter_version", "bundle"])
def test_rehashed_evidence_edits_are_not_authority(change):
    e = adapt(viirs_bundle([125.75, 500.1234, 750.25, 250], coordinates=NEIGHBORS))["evidence"]
    if change == "frp":
        e["points"][1]["frp_source"] += 1
    elif change == "category":
        e["points"][0]["confidence_category"] = "low"
    elif change == "code":
        e["points"][0]["source_confidence_code"] = "l"
    elif change == "order":
        e["points"].reverse()
    elif change == "dropped":
        e["points"].pop()
    elif change == "satellite":
        e["satellite"] = "NOAA-21"
    elif change == "instrument":
        e["instrument"] = "MODIS"
    elif change == "product":
        e["source_product"] = "VIIRS_NOAA21_NRT"
    elif change == "minute":
        e["acquired_at"] = "2032-03-01T00:00:00Z"
    elif change == "markers":
        e["map"]["markers"][0][0] += 1
    elif change == "frame":
        e["map"]["frame"] = list(locator.MAP_FRAME)
    elif change == "shared_code":
        e["map"]["shared_code_sha256"]["fire_map_graphic_adapter.py"] = "a" * 64
    elif change == "synthetic":
        e["input_binding"]["synthetic"] = False
    elif change == "adapter_version":
        e["input_binding"]["adapter_version"] = "p31-firms-modis-map-2"
    else:
        e["input_binding"]["bundles"][0]["bundle"]["where"] = "changed"
    with pytest.raises(ValueError):
        validate_graphic(adapter.TEMPLATE, e, expected_evidence_sha256=fingerprint(e))


@pytest.mark.parametrize("name", ["fire_map_graphic_adapter.py", "fire_graphic_adapter.py"])
def test_shared_locator_or_axis_code_drift_obsoletes_existing_evidence(monkeypatch, name):
    spec = adapt()
    original = locator.resource
    monkeypatch.setattr(locator, "resource", lambda key, bound: original(key, bound) + (b"#" if key == name else b""))
    with pytest.raises(ValueError, match="differs"):
        validate_graphic(spec["template"], spec["evidence"], expected_evidence_sha256=spec["expected_evidence_sha256"])
    # A fresh projection binds the new bytes instead of relabeling the old evidence.
    assert adapt()["evidence"]["map"]["shared_code_sha256"][name] != spec["evidence"]["map"]["shared_code_sha256"][name]


@pytest.mark.parametrize("failure", ["missing", "derived", "manifest"])
def test_basemap_resource_failure_is_typed(monkeypatch, failure):
    original = locator.resource

    def changed(name, bound):
        if name == locator.BASEMAP and failure == "missing":
            raise OSError("gone")
        raw = original(name, bound)
        return raw + b" " if (name, failure) in ((locator.BASEMAP, "derived"), (locator.MANIFEST, "manifest")) else raw

    monkeypatch.setattr(locator, "resource", changed)
    with pytest.raises(locator.MapQualificationError, match="basemap_unavailable"):
        adapt()


def test_template_and_instrument_cannot_be_confused():
    from tests.fire_graphic_helpers import graphic_bundle
    from tests.test_fire_map_graphic_adapter import adapt as modis_adapt

    viirs, modis = adapt(), modis_adapt(graphic_bundle())
    with pytest.raises(ValueError):
        validate_graphic("modis_thermal_detection_map", viirs["evidence"],
                         expected_evidence_sha256=viirs["expected_evidence_sha256"])
    with pytest.raises(ValueError):
        validate_graphic(adapter.TEMPLATE, modis["evidence"], expected_evidence_sha256=modis["expected_evidence_sha256"])
    with pytest.raises(ValueError):
        render_svg(template="modis_thermal_detection_map", evidence=viirs["evidence"],
                   expected_evidence_sha256=viirs["expected_evidence_sha256"])


def test_modis_map_keeps_original_rows_frame_and_evidence_shape():
    from tests.fire_graphic_helpers import graphic_bundle
    from tests.test_fire_map_graphic_adapter import adapt as modis_adapt

    e = modis_adapt(graphic_bundle())["evidence"]
    assert "frame" not in e["map"] and "shared_code_sha256" not in e["map"]
    texts = [row["text"] for row in map_text_layout(e)["texts"]]
    assert "NASA FIRMS · Terra / MODIS" in texts
    assert "Source detection confidence" not in texts and not any("VIIRS" in t for t in texts)


def test_preview_dispatch_is_opt_in_and_keeps_modis_and_editor_scope():
    from src.dashboard_preview.preview import qualified_spec
    from tests.fire_graphic_helpers import graphic_bundle

    viirs = viirs_bundle().to_dict()
    spec, source, context = qualified_spec(deepcopy(viirs), synthetic=True, include_viirs=True)
    assert spec["template"] == adapter.TEMPLATE and source == "NASA FIRMS · VIIRS"
    assert context == {"kind": "viirs_acquisition", "acquired_at": "2032-02-29T23:59:00Z"}
    # Without the explicit opt-in (the editor media command), VIIRS stays held by the MODIS adapter.
    with pytest.raises(ValueError, match="MODIS"):
        qualified_spec(deepcopy(viirs), synthetic=True)
    modis = graphic_bundle().to_dict()
    for opt_in in (False, True):
        spec, source, context = qualified_spec(deepcopy(modis), synthetic=True, include_viirs=opt_in)
        assert spec["template"] == "modis_thermal_detection_map" and source == "NASA FIRMS · MODIS"
        assert context["kind"] == "modis_acquisition"


def test_evidence_is_bounded_json_and_reconstructs_from_its_own_binding():
    spec = adapt(viirs_bundle([125.75, 500.1234, 750.25, 250], coordinates=NEIGHBORS))
    encoded = json.dumps(spec["evidence"], allow_nan=False)
    assert len(encoded.encode()) <= 1_000_000
    adapter.validate_viirs_map_binding(json.loads(encoded))
