"""Published originals (KTLX radar, NHC cone) for Gist: exact retained bytes and holds (invented)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import socket

from PIL import Image
import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial import revisions
from src.media import canonical_png, gist_assets, gist_media, gist_published_media as published
from src.media.gist_hazard_media import MediaWithheld
from tests import gist_published_helpers as h

RADAR_NOW = datetime(2026, 6, 8, 12, 3, tzinfo=timezone.utc)
CONE_NOW = datetime(2026, 9, 15, 4, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3")


@pytest.fixture
def radar(store, monkeypatch):
    bundle = h.radar_bundle(monkeypatch)
    doc, raw, refs, receipt = h.radar_inputs()
    return bundle, raw, published.retain(store, published.radar.FAMILY, doc, raw, refs, receipt)


@pytest.fixture
def cone(store):
    doc, raw, refs, receipt = h.cone_inputs()
    return h.cone_bundle(), raw, published.retain(store, "nhc_track_cone_v1", doc, raw, refs, receipt)


def _rgba(raw):
    with Image.open(BytesIO(raw)) as image:
        image.load()
        return image.convert("RGBA").tobytes()


@pytest.mark.parametrize("case", ["radar", "cone"])
def test_exact_original_and_pixel_equivalent_canonical_derivative(case, store, request):
    bundle, original, manifest = request.getfixturevalue(case)
    now = RADAR_NOW if case == "radar" else CONE_NOW
    trapped = socket.socket.connect
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
    try:
        prepared = published.prepare_media(bundle, store, manifest, now=now)
    finally:
        socket.socket.connect = trapped
    descriptor, png = prepared["descriptor"], prepared["png"]
    assert prepared["original"] == original and descriptor["asset"]["original_sha256"] == sha256(original).hexdigest()
    assert descriptor["asset"]["derivative_sha256"] == sha256(png).hexdigest() != descriptor["asset"]["original_sha256"]
    width, height = (600, 550) if case == "radar" else (897, 736)
    assert canonical_png.inspect(png, max_bytes=len(png)) == (width, height, "RGBA")
    assert _rgba(png) == _rgba(original)  # No crop, recolour, rescale or overlay.
    assert canonical_png.encode("RGBA", width, height, _rgba(original), max_bytes=len(png)) == png
    text = prepared["delivery_text"]
    assert len(text) <= 1000 and len(text.encode()) <= 1000 and "no endorsement implied" in text
    if case == "radar":
        assert "not rainfall, a tornado detection or damage" in text and "dBZ" in text
        assert descriptor["source"]["useful_until"] == "2026-06-08T12:14:00Z"
        assert descriptor["attestations"]["required"] == ["named_point_context_matches", "raster_labels_match",
                                                          "unaltered_product_reuse_conditions_met"]
    else:
        assert "Forecast, not observation" in text and "does not show the storm's size" in text
        assert descriptor["source"]["useful_until"] == "2026-09-15T09:00:00Z"
    assert published.prepare_media(bundle, store, manifest, now=now)["descriptor"] == descriptor


def test_retention_refuses_unknown_rights_labels_formats_and_hosts(store):
    doc, raw, refs, receipt = h.cone_inputs()
    missing_reuse = deepcopy(doc)
    del missing_reuse["references"]["reuse"]
    cases = {
        "missing reuse reference": (missing_reuse, raw, refs),
        "reuse URL changed": (_with(doc, ["references", "reuse", "url"], "https://example.invalid/terms"), raw, refs),
        "arbitrary host": (_with(doc, ["source_url"], "https://example.invalid/AL052026_5day_cone_with_line_and_wind.png"),
                           raw, refs),
        "path storm mismatch": (_with(doc, ["metadata", "storm_id"], "AL062026"), raw, refs),
        "empty legend": (_with(doc, ["metadata", "legend"], []), raw, refs),
        "other credit": (_with(doc, ["metadata", "credit"], "INVENTED AGENCY"), raw, refs),
        "issued after retrieval": (_with(doc, ["metadata", "issued_utc"], "2026-09-15T05:00:00Z"), raw, refs),
        "reviewed status claimed": (_with(doc, ["metadata_status"], "reviewed"), raw, refs),
    }
    for name, (value, original, references) in cases.items():
        with pytest.raises(MediaWithheld) as refused:
            published.retain(store, "nhc_track_cone_v1", value, original, references, receipt)
        assert refused.value.code == "media_asset_invalid", name
    animated = h.cone_image(mode="GIF", frames=3)
    doc2, _, refs2, receipt2 = h.cone_inputs(raw=animated)
    doc2["original"]["frame_count"] = 1
    with pytest.raises(MediaWithheld, match="static frame"):
        published.retain(store, "nhc_track_cone_v1", doc2, animated, refs2, receipt2)
    with pytest.raises(MediaWithheld) as unknown:
        published.retain(store, "global_radar_mosaic_v1", doc, raw, refs, receipt)
    assert unknown.value.code == "media_unsupported"
    with pytest.raises(MediaWithheld, match="differ"):
        published.retain(store, "nhc_track_cone_v1", doc, raw + b"x", refs, receipt)


def _with(value, path, new):
    changed = deepcopy(value)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = new
    return changed


def test_missing_original_changed_bytes_and_unconfigured_store_hold(store, cone, tmp_path):
    bundle, original, manifest = cone
    only_manifest = gist_assets.SQLiteMediaStore(tmp_path / "partial.sqlite3")
    only_manifest.put_many([store.get(manifest, limit=published.MAX_MANIFEST_BYTES)])
    with pytest.raises(MediaWithheld) as missing:
        published.prepare_media(bundle, only_manifest, manifest, now=CONE_NOW)
    assert missing.value.code == "media_original_missing"
    raw = store.path.read_bytes()
    marker = original[:64]  # Every stored copy of the original's leading bytes, one byte flipped.
    store.path.write_bytes(raw.replace(marker, marker[:40] + bytes([marker[40] ^ 1]) + marker[41:]))
    with pytest.raises(MediaWithheld) as changed:
        published.prepare_media(bundle, store, manifest, now=CONE_NOW)
    assert changed.value.code == "media_asset_changed"
    with pytest.raises(ValueError) as unconfigured:
        gist_media.prepare_media(bundle, retained_input_sha256=manifest)
    assert unconfigured.value.code == "media_store_unavailable"


def test_association_requires_the_drafts_own_storm_advisory_warning_and_point(store, cone, radar, monkeypatch):
    bundle, _, manifest = cone
    for changed in (h.cone_bundle(storm_id="AL062026"), h.cone_bundle(advisory="13"),
                    h.cone_bundle(issued=h.CONE_ISSUED + timedelta(hours=6))):
        with pytest.raises(MediaWithheld) as mismatch:
            published.prepare_media(changed, store, manifest, now=CONE_NOW)
        assert mismatch.value.code in ("media_context_mismatch", "media_asset_invalid")
    assert published.product_for(h.cone_bundle(source="jtwc")) is None
    radar_bundle, _, radar_manifest = radar
    with pytest.raises(MediaWithheld) as product:
        published.prepare_media(radar_bundle, store, manifest, now=RADAR_NOW)
    assert product.value.code == "media_context_mismatch"
    moved = deepcopy(radar_bundle)
    feature = moved["raw_signal_dump"]["source_evidence"]["feature"]
    feature["geometry"]["coordinates"] = [[[-96.8, 36.2], [-96.2, 36.2], [-96.2, 36.8], [-96.8, 36.8], [-96.8, 36.2]]]
    with pytest.raises(MediaWithheld):
        published.prepare_media(moved, store, radar_manifest, now=RADAR_NOW)


def test_editorial_ceilings_and_future_frames(radar, cone, store):
    for (bundle, _, manifest), now, ceiling in ((radar, RADAR_NOW, datetime(2026, 6, 8, 12, 14, tzinfo=timezone.utc)),
                                                (cone, CONE_NOW, datetime(2026, 9, 15, 9, tzinfo=timezone.utc))):
        descriptor = published.prepare_media(bundle, store, manifest, now=now)["descriptor"]
        assert published.currentness(descriptor, now) is None
        assert published.currentness(descriptor, ceiling - timedelta(seconds=1)) is None
        assert published.currentness(descriptor, ceiling)[0] == "media_published_stale"
        assert published.currentness(descriptor, now - timedelta(hours=8))[0] == "media_source_future"
        # A historical asset stays inspectable; it never authorizes posting.
        assert published.prepare_media(bundle, store, manifest, now=ceiling + timedelta(days=30))["descriptor"] == descriptor


@pytest.mark.parametrize("path,value,code", [
    (("synthetic",), True, "media_synthetic"),
    (("attestations", "required"), ["raster_labels_match"], "media_descriptor_invalid"),
    (("converter", "png_codec"), "canonical-png-fixed-huffman-0", "media_renderer_changed"),
    (("source", "source_feature_sha256"), "0" * 64, "media_source_changed"),
    (("asset", "original_mime"), "image/jpeg", "media_descriptor_invalid"),
    (("description", "delivery_text"), "Edited free text.", "media_description_changed"),
    (("product",), "nhc_track_cone_v1", "media_unsupported"),
])
def test_radar_descriptor_mutations_refuse(radar, store, path, value, code):
    bundle, _, manifest = radar
    descriptor = _with(published.prepare_media(bundle, store, manifest, now=RADAR_NOW)["descriptor"], path, value)
    with pytest.raises(MediaWithheld) as refused:
        published.validate_descriptor(descriptor, bundle)
    assert refused.value.code == code


def _draft(bundle, descriptor):
    draft = {"id": "invented-published", "event_id": bundle["event_id"], "type": "invented", "status": "pending",
             "text": "Invented published-image draft.", "review_context": {"two_bot": {"bundle": bundle}}}
    revisions.initialize_revision(draft)
    revisions.invalidate_media_attachment(draft, descriptor, at="2026-06-08T12:02:00Z")
    return draft


def test_joint_review_requires_every_published_attestation(radar, store):
    bundle, _, manifest = radar
    draft = _draft(bundle, published.prepare_media(bundle, store, manifest, now=RADAR_NOW)["descriptor"])
    required = gist_media.required_attestations(draft["media_attachment"])
    assert required == ["named_point_context_matches", "raster_labels_match", "unaltered_product_reuse_conditions_met"]
    for supplied in (None, {}, {name: True for name in required[:2]}, {**{n: True for n in required}, "extra": True},
                     {**{n: True for n in required}, required[0]: "yes"}):
        with pytest.raises(ValueError, match="attestation"):
            revisions.record_joint_media_review(deepcopy(draft), attestations=supplied)
    reviewed = revisions.record_joint_media_review(deepcopy(draft), attestations={n: True for n in required})
    assert reviewed["review_binding"]["published_attestations"] == {"version": 1, "confirmed": required}
    assert revisions.review_is_current(reviewed)
    stripped = deepcopy(reviewed)
    del stripped["review_binding"]["published_attestations"]
    assert not revisions.review_is_current(stripped)


def test_sender_reverifies_store_and_ceiling_and_returns_the_derivative(radar, store):
    bundle, _, manifest = radar
    prepared = published.prepare_media(bundle, store, manifest, now=RADAR_NOW)
    draft = {"review_context": {"two_bot": {"bundle": bundle}}, "media_attachment": deepcopy(prepared["descriptor"])}
    assert gist_media.media_for_draft(draft, now=RADAR_NOW, store=store) == (prepared["png"], prepared["delivery_text"])
    with pytest.raises(MediaWithheld) as stale:
        gist_media.media_for_draft(draft, now=RADAR_NOW + timedelta(minutes=11), store=store)
    assert stale.value.code == "media_published_stale"
    with pytest.raises(MediaWithheld) as stale_upload:
        gist_media.recheck_before_upload(draft, now=RADAR_NOW + timedelta(minutes=11))
    assert stale_upload.value.code == "media_published_stale"
    with pytest.raises(ValueError) as unconfigured:
        gist_media.media_for_draft(draft, now=RADAR_NOW)
    assert unconfigured.value.code == "media_store_unavailable"


def _state(bundle, descriptor=None):
    draft = {"id": "invented-published", "event_id": bundle["event_id"], "type": "invented", "status": "pending",
             "text": "Invented published-image draft.", "review_context": {"two_bot": {"bundle": bundle}}}
    revisions.initialize_revision(draft)
    return {"drafts": [draft]}


def _request(state, **extra):
    draft = state["drafts"][0]
    return {"draft_id": draft["id"], "format": "png", "expected_policy_source_sha256": "a" * 64,
            "expected_preview_runtime_sha256": "b" * 64,
            "expected_revision": {**revisions.draft_identity(draft), "decision_revision": revisions.decision_revision(draft)},
            **extra}


def test_saved_draft_preview_returns_schema_5_and_names_each_hold(cone, store, monkeypatch):
    bundle, original, manifest = cone
    state = _state(bundle)
    from freezegun import freeze_time
    with freeze_time("2026-09-15T04:00:00Z"):
        body = json.loads(build_preview(_request(state, retained_input_sha256=manifest), policy_sha="a" * 64,
                                        runtime_sha="b" * 64, read_state=lambda: state, budget=Budget(), store=store))
    assert body["schema_version"] == 5 and body["media_kind"] == "gist_published_chart_v1"
    assert body["posting_window"]["status"] == "current" and body["original_mime"] == "image/png"
    import base64
    assert base64.b64decode(body["original_base64"]) == original
    assert [row["name"] for row in body["inspection"]["required_attestations"]] == [
        "chart_labels_match", "storm_and_advisory_match", "unaltered_product_reuse_conditions_met"]
    for extra, hold in (({}, "media_retained_input_required"),
                        ({"retained_input_sha256": "0" * 64}, "media_original_missing")):
        with pytest.raises(PreviewError) as held:
            build_preview(_request(state, **extra), policy_sha="a" * 64, runtime_sha="b" * 64,
                          read_state=lambda: state, budget=Budget(), store=store)
        assert held.value.code == "media_hold" and held.value.hold == hold
        assert held.value.payload()["hold"] == hold
    with pytest.raises(PreviewError) as unconfigured:
        build_preview(_request(state, retained_input_sha256=manifest), policy_sha="a" * 64, runtime_sha="b" * 64,
                      read_state=lambda: state, budget=Budget())
    assert unconfigured.value.hold == "media_store_unavailable"
    with pytest.raises(PreviewError) as malformed:
        build_preview(_request(state, retained_input_sha256="../etc/passwd"), policy_sha="a" * 64,
                      runtime_sha="b" * 64, read_state=lambda: state, budget=Budget(), store=store)
    assert malformed.value.code == "bad_request"
