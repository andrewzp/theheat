from copy import deepcopy
from datetime import timedelta
import io
import json

from PIL import Image
import pytest

from src.media import published_radar as r
from src.two_bot.intern.disasters import build_severe_weather_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.bundle_capture import capture_bundle, BundleCaptureError
from tests import published_radar_fixtures as f


def test_actual_parser_intern_has_real_warning_and_original_interval(monkeypatch):
    alert = f.parsed(monkeypatch)[0]
    bundle = build_severe_weather_bundle(alert)
    assert alert.event_type == "Tornado Warning" and alert.tornado_detection == "OBSERVED"
    assert bundle.when == "2026-06-08T11:58:00Z"
    assert alert.source_evidence["feature"] == f.feature()
    assert alert.source_evidence["times"]["sent"]["original"] == "2026-06-08T06:58:00-05:00"
    assert audit_story_bundle(bundle).prompt_ready
    assert len(capture_bundle(bundle).serialized.encode()) < 32768
    r.source(bundle.to_dict())


@pytest.mark.parametrize(
    "change",
    [
        {"event": "Tornado Emergency"},
        {"event": "Flash Flood Emergency"},
        {"event": "Flash Flood Warning"},
        {"event": "Severe Thunderstorm Warning"},
        {"messageType": "Cancel"},
        {"status": "Test"},
        {"status": "Exercise"},
        {"parameters": {}},
        {"parameters": {"tornadoDamageThreat": ["CONSIDERABLE"], "tornadoDetection": ["OBSERVED"]}},
        {
            "parameters": {
                "tornadoDamageThreat": ["CATASTROPHIC", "CONSIDERABLE"],
                "tornadoDetection": ["OBSERVED"],
            }
        },
        {
            "parameters": {
                "tornadoDamageThreat": ["CATASTROPHIC"],
                "tornadoDetection": ["RADAR INDICATED"],
            }
        },
    ],
)
def test_only_documented_rare_trigger_selected(monkeypatch, change):
    item = f.feature()
    item["properties"].update(change)
    assert f.parsed(monkeypatch, item) == []


def test_documented_update_is_selected_without_new_request(monkeypatch):
    item = f.feature()
    item["properties"]["messageType"] = "Update"
    assert f.parsed(monkeypatch, item)[0].source_evidence["feature"] == item


@pytest.mark.parametrize(
    "event",
    ["Extreme Heat Warning", "Extreme Cold Warning", "Hurricane Warning", "Storm Surge Warning"],
)
def test_ordinary_source_outcome_preserved_but_radar_ineligible(monkeypatch, event):
    item = f.feature()
    item["properties"]["event"] = event
    alerts = f.parsed(monkeypatch, item)
    assert len(alerts) == 1
    with pytest.raises(r.RadarHold, match="radar_warning_context_unsupported"):
        r.source(build_severe_weather_bundle(alerts[0]).to_dict())


@pytest.mark.parametrize(
    "change,reason",
    [
        (None, "radar_polygon_unsupported"),
        ({"type": "MultiPolygon", "coordinates": []}, "radar_polygon_unsupported"),
    ],
)
def test_geography_hold_preserves_selected_alert(monkeypatch, change, reason):
    item = f.feature()
    item["geometry"] = change
    alert = f.parsed(monkeypatch, item)[0]
    assert alert.source_evidence["status"] == "held" and alert.source_evidence["reasons"] == [
        reason
    ]
    assert alert.source_evidence["feature"] == item
    assert build_severe_weather_bundle(alert).when == "2026-06-08T11:58:00Z"


def test_missing_source_time_never_uses_today(monkeypatch):
    item = f.feature()
    del item["properties"]["effective"]
    alert = f.parsed(monkeypatch, item)[0]
    bundle = build_severe_weather_bundle(alert)
    assert bundle.when == "" and not audit_story_bundle(bundle).prompt_ready
    assert alert.source_evidence["status"] == "held"


def test_oversized_source_is_visible_hold_and_bundle_cap_stays(monkeypatch):
    item = f.feature()
    item["properties"]["instruction"] = "x" * 150000
    alert = f.parsed(monkeypatch, item)[0]
    assert alert.source_evidence["status"] == "held" and alert.source_evidence["reasons"] == [
        "radar_source_envelope_bound"
    ]
    assert (
        "feature" not in alert.source_evidence
        and alert.source_evidence["feature_byte_count"] > 128 * 1024
    )
    item = f.feature()
    item["properties"]["instruction"] = "x" * 40000
    alert = f.parsed(monkeypatch, item)[0]
    assert alert.source_evidence["status"] == "complete"
    with pytest.raises(BundleCaptureError, match="bundle_capture_too_large"):
        capture_bundle(build_severe_weather_bundle(alert))


def test_pixel_equivalent_original_and_unchanged_dimensions(monkeypatch, tmp_path):
    spec, raw = f.spec(monkeypatch)
    png, pixels = r.convert(raw, spec["evidence"]["input"])
    with Image.open(io.BytesIO(raw)) as gif, Image.open(io.BytesIO(png)) as display:
        assert gif.convert("RGBA").tobytes() == display.convert("RGBA").tobytes()
        assert r.digest(display.convert("RGBA").tobytes()) == pixels
    renderer = dict(
        library="Pillow",
        version="12.2.0",
        width=600,
        height=550,
        implementation_sha256="d" * 64,
        dependencies_sha256="e" * 64,
    )
    manifest = json.loads(r.render(spec, raw, renderer, tmp_path).read_text())
    assert (
        set(manifest["files"]) == set(r.LIMITS) and (tmp_path / "original.gif").read_bytes() == raw
    )
    assert "not the full warning footprint" in r.alt_text(spec["evidence"])


@pytest.mark.parametrize("kind", ["outside", "edge", "hole", "crossed", "dateline"])
def test_geometry_exact_negatives(kind):
    g = f.feature()["geometry"]
    if kind == "outside":
        point = {**r.POINT, "longitude": -99}
    elif kind == "edge":
        point = {**r.POINT, "longitude": -97.8}
    else:
        point = r.POINT
        if kind == "hole":
            g["coordinates"].append(g["coordinates"][0])
        if kind == "crossed":
            g["coordinates"][0] = [[-98, 35], [-97, 36], [-97, 35], [-98, 36], [-98, 35]]
        if kind == "dateline":
            g["coordinates"][0] = [[179, 35], [-179, 35], [-179, 36], [179, 36], [179, 35]]
    with pytest.raises(r.RadarHold):
        r.contains(g, point)


def test_fixed_clock_does_not_renew_on_retrieval_or_restore(monkeypatch):
    spec, _ = f.spec(monkeypatch)
    e = spec["evidence"]
    assert e["useful_until"] == "2026-06-08T12:14:00Z"
    r.validate_spec(deepcopy(spec))
    with pytest.raises(r.RadarHold, match="radar_frame_expired_or_future"):
        r.make_spec(
            e["bundle"],
            e["input"],
            source_origin=e["source_origin"],
            registry_sha256=e["registry_sha256"],
            point=e["point"],
            selection_sha256=e["selection_sha256"],
            now=f.AT + timedelta(minutes=14),
        )


@pytest.mark.parametrize(
    "mutation", ["timestamp", "subtype", "dimensions", "unknown", "registry", "boolean"]
)
def test_strict_input_refuses_unsupported_claims(mutation):
    doc, _, _, _ = f.input_document()
    if mutation == "timestamp":
        doc["metadata"]["time_literal"] = "06/08/2026 11:59 CDT"
    if mutation == "subtype":
        doc["metadata"]["subtype"] = "base"
    if mutation == "dimensions":
        doc["original"]["width"] = 1200
    if mutation == "unknown":
        doc["human_verified"] = True
    if mutation == "registry":
        doc["metadata"]["point"]["latitude"] = 35.47
    if mutation == "boolean":
        doc["schema_version"] = True
    with pytest.raises(r.RadarHold):
        r.document(doc)


def test_animation_and_corrupt_bytes_refuse():
    doc, raw, _, _ = f.input_document()
    other = Image.new("P", (600, 550), 2)
    output = io.BytesIO()
    with Image.open(io.BytesIO(raw)) as first:
        first.save(output, format="GIF", save_all=True, append_images=[other], loop=0)
    animated = output.getvalue()
    doc["original"].update(sha256=r.digest(animated), byte_count=len(animated))
    with pytest.raises(r.RadarHold, match="radar_animation_or_disposal"):
        r.convert(animated, doc)
    broken = raw[:20]
    doc["original"].update(sha256=r.digest(broken), byte_count=len(broken))
    with pytest.raises(r.RadarHold, match="radar_decode_failed"):
        r.convert(broken, doc)


@pytest.mark.parametrize(
    "change",
    [
        "event_id",
        "date_only",
        "wrong_registry",
        "minute_overflow",
        "future_frame",
        "stale_frame",
        "point_outside",
    ],
)
def test_actual_association_refusals_preserve_warning_semantics(monkeypatch, change):
    spec, _ = f.spec(monkeypatch)
    e = spec["evidence"]
    bundle, value = deepcopy(e["bundle"]), deepcopy(e["input"])
    registry = e["registry_sha256"]
    if change == "event_id":
        bundle["event_id"] = "nws_wrong-source"
    elif change == "date_only":
        bundle["when"] = "2026-06-08"
    elif change == "wrong_registry":
        registry = "f" * 64
    elif change in {"minute_overflow", "point_outside"}:
        feature = deepcopy(bundle["raw_signal_dump"]["source_evidence"]["feature"])
        if change == "minute_overflow":
            feature["properties"]["ends"] = "2026-06-08T06:59:30-05:00"
        else:
            feature["geometry"]["coordinates"] = [
                [[-100, 30], [-99, 30], [-99, 31], [-100, 31], [-100, 30]]
            ]
        envelope = r.source_envelope(feature, "2026-06-08T12:00:00Z")
        bundle["raw_signal_dump"]["source_evidence"] = envelope
        bundle["raw_signal_dump"]["provenance"] = {
            k: envelope[k] for k in ("source_url", "source_alert_id", "feature_sha256")
        }
    elif change == "future_frame":
        value["metadata"].update(
            time_literal="06/08/2026 12:01 UTC (07:01 CDT)", frame_minute_utc="2026-06-08T12:01:00Z"
        )
        value["retrieved_at"] = "2026-06-08T12:01:00Z"
    else:
        value["metadata"].update(
            time_literal="06/08/2026 11:40 UTC (06:40 CDT)", frame_minute_utc="2026-06-08T11:40:00Z"
        )
    with pytest.raises(r.RadarHold):
        r.make_spec(
            bundle,
            value,
            source_origin=e["source_origin"],
            registry_sha256=registry,
            point=e["point"],
            selection_sha256=e["selection_sha256"],
            now=f.AT,
        )
