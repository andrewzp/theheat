"""CRW regional SST anomaly Gist image: retained packet, exact bytes and holds (invented data)."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO

from PIL import Image
import pytest

from src.media import canonical_png, gist_assets, gist_crw_media as crw, gist_media
from src.media.gist_hazard_media import MediaWithheld
from tests.crw_graphic_helpers import graphic_inputs
from tests.gist_crw_helpers import varied_inputs

NOW = datetime(2026, 6, 16, 13, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3")


@pytest.fixture
def retained(store):
    bundle, packet = varied_inputs("caribbean")
    return bundle, packet, crw.retain_packet(store, packet)


def test_sampled_cell_chart_binds_packet_bundle_and_exact_canonical_bytes(store, retained):
    bundle, packet, sha = retained
    prepared = crw.prepare_media(bundle, store, sha)
    descriptor = prepared["descriptor"]
    assert descriptor["kind"] == crw.KIND and descriptor["synthetic"] is False
    assert descriptor["source"]["packet_artifact_sha256"] == sha == sha256(gist_assets.encode_document(packet)).hexdigest()
    assert descriptor["source"]["region_slug"] == "caribbean" and descriptor["source"]["product_date"] == "2026-06-14"
    assert 10 <= descriptor["source"]["valid_cells"] < descriptor["source"]["total_cells"]
    png = prepared["png"]
    with Image.open(BytesIO(png)) as image:
        image.load()
        assert image.size == (1200, 1500) and image.mode == "RGB"
        assert canonical_png.is_canonical(png, image)
        colours = image.getcolors(1200 * 1500)
        assert colours is not None and len(colours) > 20  # A real diverging colour scale, not one fill.
    assert descriptor["image"]["png_sha256"] == sha256(png).hexdigest() and len(png) <= 750_000
    assert crw.prepare_media(bundle, store, sha) == prepared
    text = prepared["delivery_text"]
    assert len(text) <= 1000 and len(text.encode()) <= 1000
    for phrase in ("not a thermometer reading", "not a 1991-2020 average", "not a continuous surface",
                   "grey outlines are excluded cells", "No absolute temperature, record, El Niño"):
        assert phrase in text
    assert "SYNTHETIC" not in text and "1985–1990 + 1993" in prepared["full_text"]


def test_uniform_invented_fixtures_of_every_axis_extent_render(store):
    from src.data.ocean_sst_anomaly import REGION_REGISTRY
    for region, value in ((REGION_REGISTRY[0], 4.6), (REGION_REGISTRY[-1], 2.6), (REGION_REGISTRY[3], 3.6)):
        bundle, packet = graphic_inputs(value=value, region=region)
        from src.media.temperature_graphic_adapter import story_bundle_snapshot
        bundle = story_bundle_snapshot(bundle)
        prepared = crw.prepare_media(bundle, store, crw.retain_packet(store, packet))
        assert len(prepared["png"]) <= 750_000


def test_missing_packet_store_and_configuration_hold_explicitly(store, retained, tmp_path):
    bundle, packet, sha = retained
    empty = gist_assets.SQLiteMediaStore(tmp_path / "empty.sqlite3")
    with pytest.raises(MediaWithheld) as absent:
        crw.prepare_media(bundle, empty, sha)
    assert absent.value.code == "media_store_unavailable"  # The configured store file does not exist.
    empty.put_many([b"invented unrelated blob"])
    with pytest.raises(MediaWithheld) as missing:
        crw.prepare_media(bundle, empty, sha)
    assert missing.value.code == "media_source_packet_missing"
    with pytest.raises(MediaWithheld) as other:
        crw.prepare_media(bundle, store, "0" * 64)
    assert other.value.code == "media_source_packet_missing"
    with pytest.raises(ValueError) as unconfigured:  # gist_assets.MediaStoreError
        gist_media.prepare_media(bundle, retained_input_sha256=sha)
    assert getattr(unconfigured.value, "code", None) == "media_store_unavailable"
    with pytest.raises(MediaWithheld) as required:
        gist_media.prepare_media(bundle, store=store)
    assert required.value.code == "media_retained_input_required"


def test_a_packet_for_another_source_or_a_changed_claim_never_renders(store, retained):
    bundle, packet, sha = retained
    other_bundle, other_packet = varied_inputs("mediterranean")
    other_sha = crw.retain_packet(store, other_packet)
    with pytest.raises(MediaWithheld) as wrong:
        crw.prepare_media(bundle, store, other_sha)
    assert wrong.value.code == "media_source_unqualified"
    changed = deepcopy(bundle)
    changed["headline_metric"]["value"] = round(changed["headline_metric"]["value"] + 0.5, 2)
    with pytest.raises(MediaWithheld) as claim:
        crw.prepare_media(changed, store, sha)
    assert claim.value.code == "media_source_unqualified"
    edited = deepcopy(packet)
    edited["csv_utf8"] = edited["csv_utf8"].replace(",3.", ",4.", 1)
    with pytest.raises(MediaWithheld) as bytes_changed:
        crw.prepare_media(bundle, store, crw.retain_packet(store, edited))
    assert bytes_changed.value.code == "media_source_unqualified"


@pytest.mark.parametrize("field,value,code", [
    (("synthetic",), True, "media_synthetic"),
    (("template_version",), "p31-crw-gist-cells-0", "media_recipe_changed"),
    (("renderer", "png_codec"), "canonical-png-fixed-huffman-0", "media_renderer_changed"),
    (("renderer", "files", "src/media/canonical_png.py"), "0" * 64, "media_renderer_changed"),
    (("source", "product_date"), "2026-06-13", "media_source_changed"),
    (("source", "valid_cells"), 3, "media_descriptor_invalid"),
    (("description", "delivery_text"), "Edited free-form description.", "media_description_changed"),
    (("image", "width"), 1199, "media_descriptor_invalid"),
])
def test_descriptor_mutations_refuse(store, retained, field, value, code):
    bundle, _, sha = retained
    descriptor = deepcopy(crw.prepare_media(bundle, store, sha)["descriptor"])
    target = descriptor
    for key in field[:-1]:
        target = target[key]
    target[field[-1]] = value
    with pytest.raises(MediaWithheld) as refused:
        crw.validate_descriptor(descriptor, bundle)
    assert refused.value.code == code


def test_source_window_is_the_unchanged_crw_rule(retained):
    bundle = retained[0]
    assert crw.currentness(bundle, NOW) is None
    assert crw.currentness(bundle, datetime(2026, 6, 19, 23, tzinfo=timezone.utc)) is None
    assert crw.currentness(bundle, datetime(2026, 6, 20, 0, tzinfo=timezone.utc))[0] == "media_source_stale"
    assert crw.currentness(bundle, datetime(2026, 6, 13, 23, tzinfo=timezone.utc))[0] == "media_source_future"


def test_sender_rereads_the_packet_and_refuses_any_difference(store, retained, tmp_path):
    bundle, _, sha = retained
    prepared = crw.prepare_media(bundle, store, sha)
    draft = {"review_context": {"two_bot": {"bundle": bundle}}, "media_attachment": deepcopy(prepared["descriptor"])}
    assert gist_media.media_for_draft(draft, now=NOW, store=store) == (prepared["png"], prepared["delivery_text"])
    with pytest.raises(MediaWithheld) as stale:
        gist_media.media_for_draft(draft, now=datetime(2026, 6, 21, tzinfo=timezone.utc), store=store)
    assert stale.value.code == "media_source_stale"
    other = gist_assets.SQLiteMediaStore(tmp_path / "x.sqlite3")
    other.put_many([b"invented unrelated blob"])
    with pytest.raises(MediaWithheld) as gone:
        gist_media.media_for_draft(draft, now=NOW, store=other)
    assert gone.value.code == "media_source_packet_missing"
    tampered = deepcopy(draft)
    tampered["media_attachment"]["image"]["png_sha256"] = "1" * 64
    with pytest.raises(MediaWithheld) as mismatch:
        gist_media.media_for_draft(tampered, now=NOW, store=store)
    assert mismatch.value.code == "media_render_mismatch"
    with pytest.raises(ValueError) as unconfigured:  # gist_assets.MediaStoreError
        gist_media.media_for_draft(draft, now=NOW)
    assert getattr(unconfigured.value, "code", None) == "media_store_unavailable"


def test_invalid_packets_are_refused_before_retention(store, retained):
    packet = deepcopy(retained[1])
    packet["schema_version"] = 2
    with pytest.raises(MediaWithheld) as refused:
        crw.retain_packet(store, packet)
    assert refused.value.code == "media_asset_invalid"


GOLDEN_CARIBBEAN = "5b6ca0e1c7fcd33d39f73264c0ad790b5f4899ce16c1fadc7251443354560551"


def test_golden_crw_vector_is_host_independent(store, retained):
    bundle, _, sha = retained
    png = crw.prepare_media(bundle, store, sha)["png"]
    with Image.open(BytesIO(png)) as image:
        image.load()
        assert canonical_png.encode("RGB", 1200, 1500, image.tobytes(), max_bytes=750_000) == png
    assert sha256(png).hexdigest() == GOLDEN_CARIBBEAN
