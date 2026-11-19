"""Invented METAR packets: temperature cues follow values, never airport row order."""

from copy import deepcopy
from io import BytesIO

from PIL import Image, ImageColor
import pytest

from src.data import awc_observed
from src.editorial.revisions import fingerprint
from src.media import awc_graphic_adapter, gist_media
from src.media.gist_hazard_media import MediaWithheld
from tests.test_awc_observed import NOW, install, reports

WARM = ImageColor.getrgb("#ffb38a")
COOL = ImageColor.getrgb("#63d9d0")


def retained_pair(monkeypatch, values):
    rows = reports()
    for row, value in zip(rows, values, strict=True):
        signed = ("M" if value < 0 else "") + f"{abs(value):02d}"
        row[0] = f"{row[1]} 151200Z {signed}/M95 Q1010"
        row[5] = str(value)
    install(monkeypatch, rows=rows)
    finding = awc_observed.nominate(now=NOW)
    assert finding is not None
    return awc_observed.build_bundle(finding, now=NOW).to_dict()


@pytest.mark.parametrize("values,colours", [
    ((43, -27), (WARM, COOL)),
    ((-27, 43), (COOL, WARM)),
    ((65, 1), (WARM, COOL)),
    ((1, 65), (COOL, WARM)),
    ((-30, -90), (WARM, COOL)),
    ((-90, -30), (COOL, WARM)),
    ((60, 0), (WARM, COOL)),
    ((0, 60), (COOL, WARM)),
], ids=["hot-first", "cold-first", "positive-hot-first", "positive-cool-first",
        "negative-warmer-first", "negative-colder-first", "zero-lower", "zero-first"])
def test_actual_png_figures_and_axis_markers_use_relative_temperatures(monkeypatch, values, colours):
    bundle = retained_pair(monkeypatch, values)
    before = deepcopy(bundle)
    prepared = gist_media.prepare_media(bundle)
    image = Image.open(BytesIO(prepared["png"]))
    assert image.mode == "RGB" and image.size == (1200, 1500)
    axis = awc_graphic_adapter.awc_graphic_spec(
        bundle, expected_bundle_sha256=fingerprint(bundle)
    )["evidence"]["axis"]
    for index, (value, expected) in enumerate(zip(values, colours, strict=True)):
        # These are the rendered figure bands, not a call to the colour chooser.
        band = image.crop((700, 485 + index * 350, 1200, 625 + index * 350))
        pixels = list(band.get_flattened_data())
        assert pixels.count(expected) > 200
        other = COOL if expected == WARM else WARM
        assert pixels.count(other) == 0
        x = round(96 + (value - axis["min_c"]) / (axis["max_c"] - axis["min_c"]) * 1008)
        assert image.getpixel((x, 1206)) == expected
    assert bundle == before
    points = bundle["raw_signal_dump"]["evidence"]["points"]
    assert [p["station_id"] for p in points] == ["TAAA", "TBBB"]
    assert [p["temperature_c"] for p in points] == list(values)
    assert prepared["descriptor"]["source"]["points_sha256"] == fingerprint(points)


def test_description_explains_pair_relative_colour_without_risk_or_source_changes(monkeypatch):
    bundle = retained_pair(monkeypatch, (43, -27))
    prepared = gist_media.prepare_media(bundle)
    text = prepared["delivery_text"]
    assert "higher and lower" in text
    assert "not hazard categories" in text
    assert "A/B labels identify" in text
    assert "43°C" in text and "−27°C" in text
    assert len(text) <= 1000 and len(text.encode("utf-8")) <= 1000
    assert text in prepared["full_text"]
    assert gist_media.posting_window(bundle, now=NOW)["status"] == "current"


@pytest.mark.parametrize("field,old,code", [
    ("template_version", "p31-awc-airport-pair-1", "media_recipe_changed"),
    ("adapter_version", "p31-awc-observed-pair-1", "media_recipe_changed"),
    ("derivation", "awc_pair_delivery_v1", "media_descriptor_invalid"),
])
def test_old_colour_recipe_requires_a_new_preview_even_with_unchanged_source(monkeypatch, field, old, code):
    bundle = retained_pair(monkeypatch, (-27, 43))
    prepared = gist_media.prepare_media(bundle)
    draft = {"review_context": {"two_bot": {"bundle": bundle}},
             "media_attachment": deepcopy(prepared["descriptor"])}
    assert gist_media.media_for_draft(draft, now=NOW) == (prepared["png"], prepared["delivery_text"])
    if field == "derivation":
        draft["media_attachment"]["description"][field] = old
    else:
        draft["media_attachment"][field] = old
    with pytest.raises(MediaWithheld) as exc:
        gist_media.media_for_draft(draft, now=NOW)
    assert exc.value.code == code
