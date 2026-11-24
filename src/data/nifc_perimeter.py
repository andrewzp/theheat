"""Closed decoding of retained NIFC polygon-view responses; never fetches data.

These are dated source-mapped footprints, not incident-point sizes, measured
fire growth, continuous burning, affected countries or current-source authority.
The caller must supply qualified retained origin; an endpoint label or digest
alone grants no production, publishing or physical-history permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import re
from typing import Any
import uuid

SOURCE_URL = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
              "WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query")
PRODUCT = "nifc.wfigs_interagency_perimeters_current"
SCHEMA = "theheat.nifc-mapped-perimeter-capture/v1"
MAX_BYTES = 4 * 1024 * 1024
MAX_FEATURES = 64
MAX_RINGS = 64
MAX_VERTICES = 16384
MAX_INTERSECTION_CHECKS = 2_000_000
_EPS = 1e-12


def _require(value: bool, code: str) -> None:
    if not value:
        raise ValueError("perimeter_" + code)


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("perimeter_nonfinite_json")


def _instant(value: Any) -> datetime:
    _require(type(value) is str and re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)", value) is not None,
        "clock")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(result.tzinfo is not None and result.utcoffset() == timedelta(0), "clock")
        return result.astimezone(UTC)
    except (ValueError, OverflowError, TypeError) as exc:
        raise ValueError("perimeter_clock") from exc


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _date(value: Any, captured: datetime, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    _require(type(value) is int and 0 < value < 2**53, "source_clock")
    try:
        result = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)
        _require(result <= captured, "future_source_clock")
        return _stamp(result)
    except (OverflowError, TypeError) as exc:
        raise ValueError("perimeter_source_clock") from exc


def _uuid(value: Any) -> str:
    _require(type(value) is str and len(value) <= 38, "source_identity")
    original = value[1:-1] if value.startswith("{") and value.endswith("}") else value
    try:
        parsed = uuid.UUID(original)
    except (ValueError, AttributeError) as exc:
        raise ValueError("perimeter_source_identity") from exc
    _require(original.lower() == str(parsed) and parsed.int != 0, "source_identity")
    return str(parsed)


def _text(value: Any, maximum: int, *, method: bool = False) -> str:
    _require(type(value) is str and 0 < len(value) <= maximum and value == value.strip(), "source_text")
    _require(not any(ord(char) < 32 or ord(char) == 127 for char in value), "source_text")
    if method:
        _require(value.casefold() not in {"unknown", "other", "none", "n/a", "unavailable", "not specified"},
                 "mapping_method_unknown")
    return value


def _number(value: Any, *, positive: bool = False) -> float:
    _require(type(value) in {int, float} and math.isfinite(value) and abs(value) <= 2**53, "number")
    _require(not positive or value > 0, "area")
    return float(value)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on(a, b, p):
    return (abs(_cross(a, b, p)) <= _EPS
            and min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS)


def _intersect(a, b, c, d):
    x, y, z, w = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return ((x * y < 0 and z * w < 0) or _on(a, b, c) or _on(a, b, d)
            or _on(c, d, a) or _on(c, d, b))


def _inside(point, ring):
    result = False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if point[0] < x:
                result = not result
    return result


def _geometry(value: Any, budget: list[int]) -> tuple[bytes, str, float]:
    _require(type(value) is dict and set(value) <= {"rings", "spatialReference"}, "geometry")
    if "spatialReference" in value:
        reference = value["spatialReference"]
        _require(type(reference) is dict and set(reference) == {"wkid"}
                 and type(reference["wkid"]) is int and reference["wkid"] == 4326, "geometry_crs")
    raw = value.get("rings")
    _require(type(raw) is list and 1 <= len(raw) <= MAX_RINGS, "rings")
    rings, areas, edges = [], [], []
    for ring_index, source_ring in enumerate(raw):
        _require(type(source_ring) is list and 4 <= len(source_ring) <= MAX_VERTICES, "ring")
        budget[0] -= len(source_ring)
        _require(budget[0] >= 0, "vertex_limit")
        ring = []
        for point in source_ring:
            _require(type(point) is list and len(point) == 2, "coordinate")
            x, y = _number(point[0]), _number(point[1])
            _require(-180 <= x <= 180 and -90 <= y <= 90, "coordinate_range")
            ring.append((x, y))
        _require(ring[0] == ring[-1] and len(set(ring[:-1])) == len(ring) - 1, "ring_closure")
        area = math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) / 2
        _require(abs(area) > _EPS, "degenerate_ring")
        for index, (a, b) in enumerate(zip(ring, ring[1:])):
            _require(abs(a[0] - b[0]) <= 180, "unsupported_dateline")
            prior = ring[index - 1] if index else ring[-2]
            if abs(_cross(prior, a, b)) <= _EPS:
                _require((a[0] - prior[0]) * (b[0] - a[0])
                         + (a[1] - prior[1]) * (b[1] - a[1]) >= 0, "ring_backtracking")
            edges.append((min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]),
                          ring_index, index, len(ring) - 1, a, b))
        rings.append(ring)
        areas.append(area)
    active: list = []
    for edge in sorted(edges):
        active = [old for old in active if old[1] >= edge[0] - _EPS]
        for old in active:
            if old[3] < edge[2] - _EPS or edge[3] < old[2] - _EPS:
                continue
            if old[4] == edge[4] and (abs(old[5] - edge[5]) == 1 or {old[5], edge[5]} == {0, edge[6] - 1}):
                continue
            budget[1] -= 1
            _require(budget[1] >= 0, "geometry_complexity")
            _require(not _intersect(old[7], old[8], edge[7], edge[8]), "geometry_topology")
        active.append(edge)
    canonical = []
    area_index = 0.0
    for index, ring in enumerate(rings):
        depth = sum(_inside(ring[0], other) for j, other in enumerate(rings) if j != index)
        # Esri exterior rings are clockwise and holes counter-clockwise. Never
        # repair winding or connect separated components to invent mapped land.
        _require((areas[index] < 0) == (depth % 2 == 0), "ring_orientation")
        area_index += (-1 if depth % 2 else 1) * abs(areas[index])
        start = min(range(len(ring) - 1), key=ring.__getitem__)
        vertices = ring[:-1]
        canonical.append((depth, vertices[start:] + vertices[:start]))
    _require(area_index > _EPS, "geometry_area")
    # A coordinate-area index is a comparison guard only, never public acres,
    # a measured surface area or a guarantee of geographic precision.
    return _json(value), _sha(_json(sorted(canonical))), area_index


@dataclass(frozen=True)
class Perimeter:
    incident_id: str
    polygon_id: str
    polygon_source: str
    mapping_method: str
    polygon_captured_at: str
    source_created_at: str | None
    source_edited_at: str | None
    source_area_acres: float
    name: str
    geometry_json: bytes
    geometry_sha256: str
    geometry_area_index: float
    source_revision_sha256: str
    source_feature_json: bytes

    @property
    def geometry(self) -> dict[str, Any]:
        return json.loads(self.geometry_json)


@dataclass(frozen=True)
class Capture:
    source_url: str
    captured_at: str
    raw_bytes: bytes
    raw_sha256: str
    perimeters: tuple[Perimeter, ...]


def _feature(value: Any, captured: datetime, budget: list[int]) -> Perimeter:
    _require(type(value) is dict and set(value) == {"attributes", "geometry"}, "feature")
    attrs = value["attributes"]
    _require(type(attrs) is dict, "attributes")
    incident = _uuid(attrs.get("attr_IrwinID"))
    _require(_uuid(attrs.get("poly_IRWINID")) == incident, "incident_identity")
    for key, expected in (("attr_IncidentTypeCategory", "WF"), ("poly_FeatureAccess", "Public"),
                          ("poly_FeatureStatus", "Approved"), ("poly_IsVisible", "Yes"), ("poly_DeleteThis", "No")):
        _require(attrs.get(key) == expected, "source_status")
    _require(type(attrs.get("attr_ActiveFireCandidate")) is int and attrs["attr_ActiveFireCandidate"] == 1,
             "source_candidate")
    _require(type(attrs.get("attr_IsCpxChild")) is int and attrs["attr_IsCpxChild"] == 0, "complex")
    _require(attrs.get("attr_CpxID") in (None, "") and attrs.get("attr_CpxName") in (None, ""), "complex")
    polygon_id = _uuid(attrs.get("poly_SourceGlobalID"))
    source = _text(attrs.get("poly_Source"), 50)
    method = _text(attrs.get("poly_MapMethod"), 25, method=True)
    when = _date(attrs.get("poly_PolygonDateTime"), captured)
    assert when is not None
    created = _date(attrs.get("poly_CreateDate"), captured, required=False)
    edited = _date(attrs.get("poly_DateCurrent"), captured, required=False)
    _require(not (created and edited) or _instant(created) <= _instant(edited), "edit_before_creation")
    area = _number(attrs.get("poly_GISAcres"), positive=True)
    name = _text(attrs.get("poly_IncidentName"), 50)
    geometry, shape_sha, area_index = _geometry(value["geometry"], budget)
    revision = _sha(_json({"product": PRODUCT, "incident": incident, "polygon_id": polygon_id,
                          "source": source, "method": method, "captured": when,
                          "area": area, "geometry": shape_sha}))
    return Perimeter(incident, polygon_id, source, method, when, created, edited, area, name,
                     geometry, shape_sha, area_index, revision, _json(value))


def decode_capture(raw: bytes, *, source_url: str, captured_at: str) -> Capture:
    """Decode complete selected results. This is not a global census or origin attestation."""
    _require(source_url == SOURCE_URL, "source_product")
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "capture_size")
    captured = _instant(captured_at)
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
        _require(type(body) is dict and body.get("geometryType") == "esriGeometryPolygon", "capture_schema")
        _require("transform" not in body, "unsupported_coordinate_transform")
        reference = body.get("spatialReference")
        _require(type(reference) is dict and reference.get("wkid") == 4326
                 and type(reference["wkid"]) is int and set(reference) <= {"wkid", "latestWkid"}
                 and type(reference.get("latestWkid", 4326)) is int
                 and reference.get("latestWkid", 4326) == 4326, "capture_crs")
        _require(body.get("exceededTransferLimit") is False, "capture_completeness")
        features = body.get("features")
        _require(type(features) is list and len(features) <= MAX_FEATURES, "feature_limit")
        records: dict[str, Perimeter] = {}
        owners: dict[tuple[str, str], str] = {}
        budget = [MAX_VERTICES, MAX_INTERSECTION_CHECKS]
        for value in features:
            record = _feature(value, captured, budget)
            source_identity = (record.polygon_source, record.polygon_id)
            _require(owners.get(source_identity, record.incident_id) == record.incident_id,
                     "conflicting_polygon_owner")
            owners[source_identity] = record.incident_id
            prior = records.get(record.incident_id)
            _require(prior is None or prior.source_feature_json == record.source_feature_json,
                     "conflicting_incident_editions")
            records[record.incident_id] = record
        return Capture(source_url, _stamp(captured), raw, _sha(raw),
                       tuple(records[key] for key in sorted(records)))
    except (json.JSONDecodeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("perimeter_capture_json") from exc
