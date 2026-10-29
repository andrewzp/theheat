"""MODIS (and later NOAA-20/21 VIIRS) locator Gist post images on invented pixels only.

The existing strict adapters reconstruct every retained receipt; this layer draws
the validated geometry with Pillow, projects a bounded X description and enforces
the unchanged 0-2 UTC source-day freshness rule. No source/model/platform call.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import json
from typing import Any

from freezegun import freeze_time
from PIL import Image
import pytest

from src.data.fire_source_contract import FIRMS_PUBLIC_URL, make_receipt, parse_record
from src.editorial import revisions
from src.media import fire_map_graphic_adapter as locator, gist_hazard_media as hazard, gist_media
from tests.gist_hazard_helpers import CLOCKS, MODIS_COORDINATES, MODIS_VALUES, TEXTS, modis_bundle
from tests.gist_media_helpers import approve, attach, install_fake_x, run_manual, saved_draft, state_for

NEIGHBORS = [(35, -110), (35, -109.989), (35.009, -110), (35.009, -109.989)]
FAMILY_FIXTURES: dict[str, dict[str, Any]] = {
    "modis": dict(build=lambda **kw: modis_bundle(MODIS_VALUES, coordinates=MODIS_COORDINATES, **kw),
                  kind=hazard.MODIS, clock=CLOCKS["modis"][0]),
}


@pytest.fixture(autouse=True)
def clock():
    with freeze_time(CLOCKS["modis"][0]) as frozen:
        yield frozen


@pytest.fixture(scope="module")
def prepared():
    bundle = FAMILY_FIXTURES["modis"]["build"]()
    return bundle, hazard.prepare_media(bundle)


def draft_for(bundle, **changes):
    draft = saved_draft(bundle, draft_id="invented-modis", draft_type="fire", text=TEXTS["modis"],
                        created_at="2032-03-01T11:00:00Z")
    draft.update(changes)
    return draft


def attached(prepared):
    bundle, value = prepared
    return attach(draft_for(bundle), value["descriptor"], at="2032-03-01T11:30:00Z")


def drawn_texts(monkeypatch):
    seen = []
    real = hazard._Canvas.text

    def spy(self, xy, value, **options):
        seen.append(value)
        return real(self, xy, value, **options)
    monkeypatch.setattr(hazard._Canvas, "text", spy)
    return seen


# ------------------------------------------------------------- rendering

@pytest.mark.parametrize("case", ["one", "four", "neighbors", "dateline", "southern", "coarse"])
def test_modis_geometries_render_deterministic_bounded_rgb(case, monkeypatch):
    geometries: dict[str, dict[str, Any]] = {
        "one": dict(values=(812.5,), coordinates=[(-33.9, 151.2)]),
        "four": dict(values=MODIS_VALUES, coordinates=MODIS_COORDINATES),
        "neighbors": dict(values=(500.1234, 125.75, 750.25, 250), coordinates=NEIGHBORS),
        "dateline": dict(values=(500.1234, 125.75), coordinates=[(-17.5, 179.4), (-16.8, -179.2)]),
        "southern": dict(values=(500.1234, 125.75), coordinates=[(-23.6, -46.7), (-22.9, -43.2)]),
        "coarse": dict(values=(500.1234, 125.75), coordinates=[(30.0, -115.0), (44.4, -92.0)]),
    }
    options = geometries[case]
    bundle = modis_bundle(options["values"], coordinates=options["coordinates"])
    seen = drawn_texts(monkeypatch)
    first = hazard.prepare_media(deepcopy(bundle))
    second = hazard.prepare_media(deepcopy(bundle))
    assert first["png"] == second["png"] and first["descriptor"] == second["descriptor"]
    with Image.open(BytesIO(first["png"])) as image:
        assert (image.format, image.mode, image.size) == ("PNG", "RGB", (1200, 1500))
    assert len(first["png"]) <= 750_000
    assert len(json.dumps(first["descriptor"], ensure_ascii=False).encode()) <= 16_384
    text = first["delivery_text"]
    assert len(text) <= 1000 and len(text.encode()) <= 1000
    evidence = hazard._spec(hazard.MODIS, bundle, False)["evidence"]
    map_ = evidence["map"]
    # The primary A is the visible lead even when it is not the maximum.
    assert seen[:2] == ["THEHEAT", json.dumps(evidence["points"][0]["frp_source"]) + " MW"]
    assert ("Crosses the dateline." in text) is map_["dateline_crossing"]
    assert ("close-up, coarse coastlines omitted" in text) is (map_["context_mode"] == "coordinate_closeup")
    assert ("Coordinate close-up; coastline omitted" in seen) is (map_["context_mode"] == "coordinate_closeup")
    if case == "dateline":
        assert map_["dateline_crossing"] is True
    if case == "coarse":
        assert map_["context_mode"] == "coarse_land_locator" and "coarse Natural Earth 110m land 4.1.0" in text


def test_every_marker_is_drawn_at_its_validated_centre_converted_to_pillow_origin(prepared):
    bundle, value = prepared
    evidence = hazard._spec(hazard.MODIS, bundle, False)["evidence"]
    with Image.open(BytesIO(value["png"])) as image:
        pixels = image.convert("RGB")
        for point, (x, y) in zip(evidence["points"], evidence["map"]["markers"]):
            colour = locator.color(point["frp_source"], evidence["map"]["axis_max"])
            assert pixels.getpixel((round(x), round(1500 - y))) == tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
        # A flipped (y-up) placement would land elsewhere: north stays at the top.
        north = max(evidence["points"], key=lambda p: p["lat"])
        index = evidence["points"].index(north)
        assert 1500 - evidence["map"]["markers"][index][1] == min(1500 - y for _x, y in evidence["map"]["markers"])


def test_delivery_lists_each_exact_centre_frp_confidence_and_version(prepared):
    bundle, value = prepared
    text = value["delivery_text"]
    for (lat, lon), frp, label in zip(MODIS_COORDINATES, MODIS_VALUES, "ABCD"):
        assert f"{label} {json.dumps(float(lat))}, {json.dumps(float(lon))}, {json.dumps(frp)} MW" in text
    assert "All: confidence 91.0%, version synthetic-v1." in text
    assert "NASA FIRMS MODIS_NRT, Terra/MODIS, 2032-02-29T23:59:00Z (reported UTC minute)" in text
    assert "A primary; B-D related, in source order, not ranked." in text
    for phrase in ("Equal markers coloured by FRP, linear blue-yellow 0-1000 MW; A is primary, not selected by maximum FRP.",
                   "not temperature, area or severity; not summed", "not flames, footprints, perimeters or fire counts",
                   "do not prove one instant, overpass or incident", "Plate carrée locator, not distance or area",
                   "Small islands may be missing (not proof of water)", "Inset: location only, not fire area."):
        assert phrase in text, phrase
    for absent in ("wildfire", "burned", "perimeter of", "nominal", "cause of"):
        assert absent not in text
    assert value["full_text"] == locator.map_alt_text(hazard._spec(hazard.MODIS, bundle, False)["evidence"])


def test_distinct_confidence_or_version_is_stated_per_detection(monkeypatch):
    from tests.fire_graphic_helpers import graphic_bundle
    from src.media.temperature_graphic_adapter import story_bundle_snapshot
    bundle = graphic_bundle((500.1234, 125.75), coordinates=[(35.25, -110.5), (38.5, -104.2)])
    related = bundle.related_signals[0]
    record = dict(related.acquisition_evidence["record"], confidence="47", version="6.1NRT")
    related.acquisition_evidence = make_receipt(parse_record("MODIS_NRT", record), FIRMS_PUBLIC_URL)
    text = hazard.prepare_media(story_bundle_snapshot(bundle))["delivery_text"]
    assert "All: confidence" not in text
    assert "A 35.25, -110.5, 500.1234 MW, confidence 91.0%, version synthetic-v1" in text
    assert "B 38.5, -104.2, 125.75 MW, confidence 47.0%, version 6.1NRT" in text


# ------------------------------------------------------------- refusals

def _platform(bundle, platform):
    related = bundle["related_signals"][0]
    related["acquisition_evidence"] = make_receipt(parse_record("MODIS_NRT", dict(
        related["acquisition_evidence"]["record"], satellite=platform)), FIRMS_PUBLIC_URL)


SOURCE_REFUSALS: dict[str, dict[str, Any]] = {
    # Distinct source identities whose validated markers fall under 36 px apart.
    "overlap": dict(values=(500.1234, 125.75, 750.25), coordinates=[(35.0, -110.0), (35.02, -110.0), (45.0, -90.0)]),
    "all_zero": dict(values=(0.0, 0.0), coordinates=[(35.25, -110.5), (38.5, -104.2)]),
    "outside_bounds": dict(values=(500.1234, 125.75), coordinates=[(35.25, -110.5), (-12.4, 130.8)]),
    "polar": dict(values=(500.1234,), coordinates=[(80.5, 10.0)]),
    "five_points": dict(values=(1, 2, 3, 4, 5), coordinates=[(35 + i, -110 - i) for i in range(5)]),
}


@pytest.mark.parametrize("name", sorted(SOURCE_REFUSALS))
def test_geometry_scale_and_count_holds_refuse(name):
    with pytest.raises(ValueError) as refused:
        hazard.prepare_media(modis_bundle(**SOURCE_REFUSALS[name]))
    expected = {"overlap": "graphic_map_points_overlap", "all_zero": "all-zero FRP scale",
                "outside_bounds": "graphic_map_outside_locator_bounds", "polar": "graphic_map_outside_locator_bounds"}
    assert expected.get(name, "") in str(refused.value)


MUTATIONS = {
    "mixed_platform": lambda b: _platform(b, "Aqua"),
    "receipt_record": lambda b: b["related_signals"][0]["acquisition_evidence"]["record"].__setitem__("frp", "999.0"),
    "receipt_rehashed": lambda b: b["related_signals"][0].__setitem__("acquisition_evidence", make_receipt(
        parse_record("MODIS_NRT", dict(b["related_signals"][0]["acquisition_evidence"]["record"], frp="999.0")), FIRMS_PUBLIC_URL)),
    "primary_frp": lambda b: b["raw_signal_dump"].__setitem__("frp_source", 1.0),
    "product_label": lambda b: b["raw_signal_dump"].__setitem__("source_product", "VIIRS_NOAA20_NRT"),
    "snpp_primary": lambda b: b["raw_signal_dump"]["acquisition_provenance"].__setitem__("source_product", "VIIRS_SNPP_NRT"),
    "hms_primary": lambda b: b["raw_signal_dump"]["acquisition_provenance"].__setitem__("source_product", "noaa-hms-fire-points"),
    "extended": lambda b: b.__setitem__("source_extension", {"invented": True}),
    "related_kind": lambda b: b["related_signals"][0].__setitem__("signal_kind", "air_quality_hazard"),
    "minute": lambda b: b["raw_signal_dump"]["acquisition_provenance"].__setitem__("acquired_at", "2032-02-29T23:58:00Z"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_mixed_unsupported_or_altered_receipts_refuse(prepared, name):
    bundle = deepcopy(prepared[0])
    MUTATIONS[name](bundle)
    with pytest.raises(ValueError):
        gist_media.prepare_media(bundle)
    with pytest.raises(ValueError):
        hazard.validate_descriptor(prepared[1]["descriptor"], bundle)


def test_freshness_is_the_unchanged_zero_to_two_utc_day_rule_for_every_receipt(prepared):
    bundle = prepared[0]
    minute = datetime(2032, 2, 29, 23, 59, tzinfo=UTC)
    cases = [(minute - timedelta(microseconds=1), "media_detection_future"), (minute, None),
             (datetime(2032, 3, 2, 23, 59, 59, tzinfo=UTC), None), (datetime(2032, 3, 3, tzinfo=UTC), "media_detection_stale")]
    for at, code in cases:
        result = hazard.currentness(hazard.MODIS, bundle, at)
        assert (result[0] if result else None) == code, at
    # One related receipt from an earlier day makes the whole image stale.
    older = deepcopy(bundle)
    record = dict(older["related_signals"][0]["acquisition_evidence"]["record"], acq_date="2032-02-26", acq_time="2359")
    older["related_signals"][0]["acquisition_evidence"] = make_receipt(parse_record("MODIS_NRT", record), FIRMS_PUBLIC_URL)
    assert hazard.currentness(hazard.MODIS, older, datetime(2032, 3, 1, tzinfo=UTC))[0] == "media_detection_stale"


def test_modis_recipe_never_becomes_another_kind(prepared):
    bundle, value = prepared
    for kind in ("gist_viirs_locator_v1", hazard.PM25, "gist_temperature_comparator_v1"):
        swapped = dict(deepcopy(value["descriptor"]), kind=kind)
        with pytest.raises(ValueError):
            gist_media.validate_descriptor(swapped, bundle)


# ------------------------------------------------------------- sender

def test_reviewed_modis_image_reaches_fake_x_with_exact_bytes_and_delivery_text(prepared, monkeypatch):
    _bundle, value = prepared
    draft = approve(attached(prepared))
    original = deepcopy(draft)
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [("upload", value["png"], "hot10.png"), ("alt", "98765", value["delivery_text"]),
                          ("create", original["text"], {"media_ids": ["98765"]})]
    assert hashlib.sha256(fake.calls[0][1]).hexdigest() == original["media_attachment"]["image"]["png_sha256"]
    assert fake.persisted[0][0]["publish_ledger"][draft["event_id"]]["phase"] == "submitted"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed" and draft["status"] == "posted"
    fake.posting.run_manual_tweet(state)
    assert len(fake.calls) == 3


def test_detections_going_stale_during_rendering_are_caught_before_upload(prepared, monkeypatch):
    draft = approve(attached(prepared))
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    real = hazard.prepare_media
    with freeze_time("2032-03-02T23:59:59Z") as frozen:
        def slow(bundle, **options):
            value = real(bundle, **options)
            frozen.move_to("2032-03-03T00:00:00Z")
            return value
        monkeypatch.setattr(hazard, "prepare_media", slow)
        run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [] and draft["publish_outcome"] == "not_sent"
    assert "no longer current" in draft["post_error"]


@pytest.mark.parametrize("failure", ["upload", "create"])
def test_failed_or_lost_transport_is_unknown_and_never_resent(prepared, failure, monkeypatch):
    draft = approve(attached(prepared))
    fake = install_fake_x(monkeypatch)
    fake.failure = failure
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    first = list(fake.calls)
    assert draft["publish_outcome"] == "unknown"
    fake.failure = None
    fake.posting.run_manual_tweet(state)
    assert fake.calls == first


def test_reference_only_edit_invalidates_joint_review_but_keeps_text_source_and_image(prepared):
    draft = approve(attached(prepared))
    before = deepcopy(draft)
    items = [{"claim": {"start": 0, "end": 8, "text": draft["text"][:8]}, "sources": [{"pointer": "/current_facts/0"}]}]
    revisions.invalidate_text(draft, draft["text"], at="2032-03-01T11:45:00Z", operator_claim_references=items)
    assert draft["text"] == before["text"] and draft["media_attachment"] == before["media_attachment"]
    assert draft["review_context"]["two_bot"]["bundle"] == before["review_context"]["two_bot"]["bundle"]
    assert draft["review_context"]["operator_claim_references"]["items"][0]["claim"]["text"] == draft["text"][:8]
    assert draft["content_revision"] == before["content_revision"] + 1 and draft["status"] == "pending"
    assert not revisions.review_is_current(draft) and "approval_binding" not in draft
    assert revisions.project_draft(draft)["review_status"] == "media_review_required"
    assert gist_media.media_for_draft(draft) == (prepared[1]["png"], prepared[1]["delivery_text"])
    revisions.record_joint_media_review(draft)
    assert revisions.review_is_current(draft)


# ------------------------------------------------------------- NOAA-20/21 VIIRS

from tests.gist_hazard_helpers import VIIRS_CATEGORIES, viirs_bundle  # noqa: E402


@pytest.fixture(scope="module")
def viirs_prepared():
    bundle = viirs_bundle(MODIS_VALUES, categories=VIIRS_CATEGORIES, coordinates=MODIS_COORDINATES)
    return bundle, hazard.prepare_media(bundle)


@pytest.mark.parametrize("product,platform,code", [("VIIRS_NOAA20_NRT", "NOAA-20", "N20"), ("VIIRS_NOAA21_NRT", "NOAA-21", "N21")])
def test_both_viirs_products_render_their_own_kind_and_categorical_confidence(product, platform, code, monkeypatch):
    bundle = viirs_bundle(MODIS_VALUES, product=product, categories=VIIRS_CATEGORIES, coordinates=MODIS_COORDINATES)
    seen = drawn_texts(monkeypatch)
    value = hazard.prepare_media(deepcopy(bundle))
    assert value["kind"] == hazard.VIIRS and value["descriptor"]["source"]["source_product"] == product
    assert value == hazard.prepare_media(deepcopy(bundle))
    with Image.open(BytesIO(value["png"])) as image:
        assert (image.mode, image.size) == ("RGB", (1200, 1500))
    text = value["delivery_text"]
    assert len(text) <= 1000 and len(text.encode()) <= 1000
    assert f"NASA FIRMS {product}, {platform} VIIRS, 2032-02-29T23:59:00Z (reported UTC minute)" in text
    for label, category, (lat, lon), frp in zip("ABCD", VIIRS_CATEGORIES, MODIS_COORDINATES, MODIS_VALUES):
        assert f"{label} {json.dumps(float(lat))}, {json.dumps(float(lon))}, {json.dumps(frp)} MW, confidence {category}" in text
    assert "All: version synthetic-v1." in text and "Confidence: the source category, not cause or impact." in text
    assert "%" not in text and "MODIS" not in text and "Terra" not in text
    assert f"NASA FIRMS · {platform} VIIRS" in seen and "A high · B nominal · C low · D high" in seen
    assert seen[:2] == ["THEHEAT", json.dumps(MODIS_VALUES[0]) + " MW"]
    assert value["full_text"] == hazard.viirs_adapter.viirs_alt_text(hazard._spec(hazard.VIIRS, bundle, False)["evidence"])
    assert code in value["full_text"]


VIIRS_REFUSALS: dict[str, dict[str, Any]] = {
    "mixed_products": dict(products=["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT"]),
    "snpp": dict(product="VIIRS_SNPP_NRT"),
    "snpp_related": dict(products=["VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]),
    "mixed_minutes": dict(when=[datetime(2032, 2, 29, 23, 59, tzinfo=UTC), datetime(2032, 2, 29, 23, 58, tzinfo=UTC),
                                datetime(2032, 2, 29, 23, 59, tzinfo=UTC)]),
    "overlap": dict(coordinates=[(35.0, -110.0), (35.02, -110.0), (45.0, -90.0)]),
    "all_zero": dict(values=(0.0, 0.0, 0.0)),
}


@pytest.mark.parametrize("name", sorted(VIIRS_REFUSALS))
def test_unsupported_or_mixed_viirs_sources_refuse(name):
    options = dict(VIIRS_REFUSALS[name])
    values = options.pop("values", (500.1234, 125.75, 750.25))
    with pytest.raises(ValueError) as refused:
        gist_media.prepare_media(viirs_bundle(values, categories=("high", "nominal", "low", "high"), **options))
    if name == "overlap":
        assert "graphic_map_points_overlap" in str(refused.value)


def test_modis_and_viirs_recipes_never_cross(prepared, viirs_prepared):
    modis_bundle_, modis_value = prepared
    viirs_bundle_, viirs_value = viirs_prepared
    for descriptor, bundle in ((modis_value["descriptor"], viirs_bundle_), (viirs_value["descriptor"], modis_bundle_),
                               (dict(deepcopy(modis_value["descriptor"]), kind=hazard.VIIRS), modis_bundle_),
                               (dict(deepcopy(viirs_value["descriptor"]), kind=hazard.MODIS), viirs_bundle_)):
        with pytest.raises(ValueError):
            gist_media.validate_descriptor(descriptor, bundle)
    # A MODIS primary with a VIIRS related receipt is a mixed set, not either family.
    mixed = deepcopy(modis_bundle_)
    mixed["related_signals"][0]["acquisition_evidence"] = deepcopy(viirs_bundle_["raw_signal_dump"]["acquisition_provenance"])
    with pytest.raises(ValueError):
        gist_media.prepare_media(mixed)


def test_viirs_numeric_ranking_or_altered_category_refuses(viirs_prepared):
    bundle = deepcopy(viirs_prepared[0])
    bundle["raw_signal_dump"]["confidence"] = 95  # the internal ranking number, never the shown category
    with pytest.raises(ValueError):
        gist_media.prepare_media(bundle)
    altered = deepcopy(viirs_prepared[0])
    altered["raw_signal_dump"]["acquisition_provenance"]["record"]["confidence"] = "n"
    with pytest.raises(ValueError):
        gist_media.prepare_media(altered)


def test_reviewed_viirs_image_reaches_fake_x_with_exact_bytes_and_delivery_text(viirs_prepared, monkeypatch):
    bundle, value = viirs_prepared
    draft = saved_draft(bundle, draft_id="invented-viirs", draft_type="fire", text=TEXTS["viirs"],
                        created_at="2032-03-01T11:00:00Z")
    approve(attach(draft, value["descriptor"], at="2032-03-01T11:30:00Z"))
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [("upload", value["png"], "hot10.png"), ("alt", "98765", value["delivery_text"]),
                          ("create", TEXTS["viirs"], {"media_ids": ["98765"]})]
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed" and draft["status"] == "posted"
    with freeze_time("2032-03-03T00:00:00Z"):
        stale = saved_draft(bundle, draft_id="invented-viirs-stale", draft_type="fire", text=TEXTS["viirs"])
        approve(attach(stale, value["descriptor"]))
        with pytest.raises(hazard.MediaWithheld) as refused:
            gist_media.media_for_draft(stale)
    assert refused.value.code == "media_detection_stale"


def test_altered_geometry_helper_changes_the_rebuild_and_never_uploads(prepared, monkeypatch):
    draft = approve(attached(prepared))
    real = locator.geometry

    def shifted(points, frame=locator.MAP_FRAME):
        value = real(points, frame)
        value["markers"] = [[x + 3, y] for x, y in value["markers"]]  # an invented displaced marker
        return value
    monkeypatch.setattr(locator, "geometry", shifted)
    with pytest.raises(hazard.MediaWithheld) as refused:
        gist_media.media_for_draft(draft)
    assert refused.value.code == "media_render_mismatch"
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [] and draft["publish_outcome"] == "not_sent"


def test_editorial_policy_change_after_approval_never_uploads(prepared, monkeypatch):
    import src.editorial.policy as policy_module
    draft = approve(attached(prepared))
    real = policy_module.current_editorial_policy

    def changed():
        value = real()
        assert value is not None
        return dict(value, execution_sha256="0" * 64)
    monkeypatch.setattr(policy_module, "current_editorial_policy", changed)
    assert not revisions.approval_is_current(draft, "manual")
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [] and draft["status"] == "approved"
