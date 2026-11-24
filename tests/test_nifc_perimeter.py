"""Invented NIFC polygon captures; point reports are never mapped perimeters."""
from copy import deepcopy
from datetime import datetime
import json

import pytest

from src.data import nifc_perimeter as perimeter

INCIDENT = "11111111-1111-4111-8111-111111111111"
POLYGON = "22222222-2222-4222-8222-222222222222"
SOURCE = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query"
CAPTURED = "2026-11-22T12:00:00Z"


def ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def feature(**attrs):
    return {"attributes": {
        "poly_IRWINID": "{" + INCIDENT.upper() + "}", "attr_IrwinID": INCIDENT,
        "poly_SourceGlobalID": "{" + POLYGON + "}", "poly_Source": "Invented polygon source",
        "poly_MapMethod": "invented-method-a", "poly_GISAcres": 23700.0,
        "poly_PolygonDateTime": ms("2026-11-21T12:00:00Z"),
        "poly_CreateDate": ms("2026-11-21T13:00:00Z"), "poly_DateCurrent": ms("2026-11-22T10:00:00Z"),
        "poly_IncidentName": "Invented fire, not current weather",
        "poly_FeatureAccess": "Public", "poly_FeatureStatus": "Approved", "poly_IsVisible": "Yes",
        "poly_DeleteThis": "No", "attr_ActiveFireCandidate": 1,
        "attr_IncidentTypeCategory": "WF", "attr_IsCpxChild": 0,
        "attr_CpxID": None, "attr_CpxName": None, **attrs},
        "geometry": {"rings": [[[-120.0, 40.0], [-120.0, 40.1], [-119.9, 40.1],
                                  [-119.9, 40.0], [-120.0, 40.0]]]}}


def body(*features):
    return {"geometryType": "esriGeometryPolygon", "spatialReference": {"wkid": 4326},
            "exceededTransferLimit": False, "features": list(features or [feature()])}


def decode(value):
    return perimeter.decode_capture(json.dumps(value, allow_nan=False).encode(),
                                    source_url=SOURCE, captured_at=CAPTURED)


def test_typed_snapshot_keeps_source_capture_geometry_and_incident_separate():
    original = body()
    capture = decode(original)
    record, = capture.perimeters
    assert record.incident_id == INCIDENT and record.polygon_id == POLYGON
    assert record.polygon_captured_at == "2026-11-21T12:00:00Z"
    assert record.source_edited_at == "2026-11-22T10:00:00Z"
    assert record.source_area_acres == 23700.0
    assert record.mapping_method == "invented-method-a"  # retained opaque source text, no instrument inference
    assert record.geometry["rings"] == original["features"][0]["geometry"]["rings"]
    assert capture.raw_bytes == json.dumps(original, allow_nan=False).encode()
    assert capture.captured_at == CAPTURED


@pytest.mark.parametrize("changes", [
    {"poly_IRWINID": "33333333-3333-4333-8333-333333333333"},
    {"attr_IrwinID": None}, {"poly_SourceGlobalID": None}, {"poly_Source": ""},
    {"poly_PolygonDateTime": None},
    {"poly_PolygonDateTime": ms("2026-11-23T00:00:00Z")},
    {"attr_IncidentTypeCategory": "RX"}, {"attr_IsCpxChild": 1}, {"attr_IsCpxChild": False},
    {"attr_CpxID": INCIDENT}, {"attr_CpxName": "Invented complex"},
    {"poly_FeatureAccess": "Private"}, {"poly_FeatureStatus": "Draft"},
    {"poly_IsVisible": "No"}, {"poly_DeleteThis": "Yes"},
    {"attr_ActiveFireCandidate": True}, {"poly_GISAcres": True},
    {"poly_GISAcres": -1}, {"poly_MapMethod": ""}, {"poly_MapMethod": "Unknown"},
])
def test_incomplete_or_contradictory_source_warrant_is_refused(changes):
    with pytest.raises(ValueError):
        decode(body(feature(**changes)))


def test_point_layer_size_cannot_be_relabelled_as_mapped_footprint():
    value = body()
    value["geometryType"] = "esriGeometryPoint"
    value["features"][0]["geometry"] = {"x": -120.0, "y": 40.0}
    with pytest.raises(ValueError):
        decode(value)
    with pytest.raises(ValueError):
        perimeter.decode_capture(json.dumps(body()).encode(),
            source_url=SOURCE.replace("WFIGS_Interagency_Perimeters_Current", "WFIGS_Incident_Locations_Current"),
            captured_at=CAPTURED)


@pytest.mark.parametrize("mutate", [
    lambda value: value["spatialReference"].update(wkid=3857),
    lambda value: value["features"][0]["geometry"].update(spatialReference={"wkid": 4326.0}),
    lambda value: value.update(exceededTransferLimit=True),
    lambda value: value["features"][0]["geometry"]["rings"][0].pop(),
    lambda value: value["features"][0]["geometry"]["rings"][0][1].__setitem__(1, 100),
    lambda value: value["features"][0]["geometry"]["rings"][0][1].__setitem__(0, True),
    lambda value: value["features"][0]["geometry"].update(rings=[[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]),
])
def test_unsupported_coordinates_topology_and_truncation_hold_whole_capture(mutate):
    value = body()
    mutate(value)
    with pytest.raises(ValueError):
        decode(value)


def test_duplicate_conflicting_incident_editions_are_not_first_one_wins():
    a, b = feature(), feature(poly_GISAcres=30000.0)
    for rows in ((a, b), (b, a)):
        with pytest.raises(ValueError):
            decode(body(*rows))
    capture = decode(body(a, deepcopy(a)))
    assert len(capture.perimeters) == 1


def test_subsecond_edit_clock_is_compared_as_time_not_lexical_iso_text():
    created = ms("2026-11-21T13:00:00Z")
    record, = decode(body(feature(poly_CreateDate=created, poly_DateCurrent=created + 1))).perimeters
    assert record.source_edited_at == "2026-11-21T13:00:00.001000Z"


def test_holes_and_multipart_survive_while_ring_order_and_start_do_not_change_shape_identity():
    f = feature(poly_GISAcres=38868.0)
    outer = f["geometry"]["rings"][0]
    hole = [[-119.98, 40.02], [-119.92, 40.02], [-119.92, 40.08],
            [-119.98, 40.08], [-119.98, 40.02]]
    other = [[-119.8, 40.0], [-119.8, 40.1], [-119.7, 40.1], [-119.7, 40.0], [-119.8, 40.0]]
    f["geometry"]["rings"] = [outer, hole, other]
    original, = decode(body(f)).perimeters
    altered = deepcopy(f)
    shifted = outer[1:-1] + [outer[0], outer[1]]
    altered["geometry"]["rings"] = [other, hole, shifted]
    changed, = decode(body(altered)).perimeters
    assert original.geometry_sha256 == changed.geometry_sha256
    assert original.source_revision_sha256 == changed.source_revision_sha256
    assert original.source_feature_json != changed.source_feature_json
    detached = original.geometry
    detached["rings"].clear()
    assert len(original.geometry["rings"]) == 3


def test_one_source_polygon_record_cannot_name_two_incidents_in_one_capture():
    other = "33333333-3333-4333-8333-333333333333"
    a, b = feature(), feature(poly_IRWINID=other, attr_IrwinID=other)
    for rows in ((a, b), (b, a)):
        with pytest.raises(ValueError, match="conflicting_polygon_owner"):
            decode(body(*rows))
    b["attributes"]["poly_SourceGlobalID"] = "44444444-4444-4444-8444-444444444444"
    assert len(decode(body(a, b)).perimeters) == 2


def test_quantized_coordinate_transform_is_not_read_as_literal_wgs84():
    value = body()
    value["transform"] = {"scale": [.001, .001], "translate": [-120., 40.], "originPosition": "upperLeft"}
    value["features"][0]["geometry"]["rings"] = [[[10, 10], [10, -10], [-10, -10], [-10, 10], [10, 10]]]
    with pytest.raises(ValueError, match="unsupported_coordinate_transform"):
        decode(value)


@pytest.mark.parametrize("clock", ["2026-11-22T12:00:00-00:00", "2026-11-22T12:00:00+00:00:00.5",
                                    "2026-11-22T12:00:00", "2026-11-22T13:00:00+01:00"])
def test_unknown_or_unsupported_capture_offsets_cannot_certify_utc(clock):
    with pytest.raises(ValueError, match="perimeter_clock"):
        perimeter.decode_capture(json.dumps(body()).encode(), source_url=SOURCE, captured_at=clock)
    assert perimeter.decode_capture(json.dumps(body()).encode(), source_url=SOURCE,
        captured_at="2026-11-22T12:00:00+00:00").captured_at == CAPTURED
