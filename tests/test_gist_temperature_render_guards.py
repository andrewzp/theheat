"""Invented station data: visible fixture labels and bounded exact descriptions."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
import pytest

from src.media import gist_temperature_media as media
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from tests import ghcn_graphic_helpers
from tests.ghcn_graphic_helpers import graphic_bundles


@pytest.fixture(scope="module")
def bundle():
    return story_bundle_snapshot(graphic_bundles()[-1])


def test_invented_preview_is_visibly_distinct_in_the_actual_png(bundle, monkeypatch):
    labels = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        labels.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    real = media.prepare_media(bundle)
    assert not any("SYNTHETIC" in label for label in labels)
    labels.clear()
    invented = media.prepare_media(bundle, synthetic=True)
    assert any("SYNTHETIC" in label and "NOT REAL WEATHER" in label for label in labels)
    assert invented["png"] != real["png"]
    assert "SYNTHETIC" in invented["descriptor"]["alt_text"]


@pytest.mark.parametrize("description", ["x" * 1001, "é" * 501], ids=["scalar-limit", "utf8-limit"])
def test_well_hashed_overlong_description_is_refused_before_delivery(bundle, description):
    descriptor = deepcopy(media.prepare_media(bundle)["descriptor"])
    descriptor.update(alt_text=description, alt_sha256=sha256(description.encode()).hexdigest())
    with pytest.raises(ValueError, match="description"):
        media.validate_descriptor(descriptor, bundle)


def test_layout_engine_is_explicit_even_when_pillow_default_changes(bundle, monkeypatch):
    engines = []
    original = ImageFont.truetype

    def capture(*args, **kwargs):
        engines.append(kwargs.get("layout_engine"))
        return original(*args, **kwargs)

    monkeypatch.setattr(ImageFont, "truetype", capture)
    media.prepare_media(bundle)
    assert engines and all(engine == ImageFont.Layout.BASIC for engine in engines)


@pytest.mark.parametrize("direction", ["high", "low"])
@pytest.mark.parametrize("tier", ["all_time", "monthly", "calendar"])
def test_complete_description_covers_exact_source_counts_axis_and_scope(direction, tier):
    source = story_bundle_snapshot(graphic_bundles(direction=direction, tier=tier)[-1])
    result = media.prepare_media(source, synthetic=True)
    alt = result["descriptor"]["alt_text"]
    assert 0 < len(alt) <= 1000 and len(alt.encode("utf-8")) <= 1000
    assert "SYNTHETIC" in alt and "NOAA GHCN-Daily" in alt
    assert "USC99000001" in alt and "2026-09-08" in alt
    assert "2001-01-01" in alt and "2026-09-07" in alt
    assert "2026-09-09T12:00:00Z" in alt
    assert "9381 source-calendar cells" in alt and "1 missing" in alt and "1 QC-rejected" in alt
    assert "reporting interval and timezone unknown" in alt
    assert "not an official" in alt
    assert "linear" in alt and "zero" in alt
    assert {"all_time": "archive", "monthly": "month 09", "calendar": "calendar 09-08"}[tier] in alt
    assert {"all_time": "9379", "monthly": "757", "calendar": "25"}[tier] + " accepted" in alt
    expected = {("high", "calendar"): "+4.2°C", ("low", "calendar"): "-12.2°C"}
    assert expected.get((direction, tier), "+0.4°C" if direction == "high" else "-0.4°C") in alt


def test_every_drawn_label_fits_canvas_and_png_has_no_incidental_metadata(bundle, monkeypatch):
    original = ImageDraw.ImageDraw.text
    observed = []

    def capture(draw, xy, text, *args, **kwargs):
        box = draw.textbbox(xy, text, font=kwargs["font"])
        assert 0 <= box[0] <= box[2] <= media.WIDTH
        assert 0 <= box[1] <= box[3] <= media.HEIGHT
        observed.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    result = media.prepare_media(bundle, synthetic=True)
    assert observed
    assert Image.open(BytesIO(result["png"])).info == {}


def test_unicode_location_survives_real_qualification_without_shortening(monkeypatch):
    station = {**ghcn_graphic_helpers.STATION, "name": "ÎLE ÉTÉ ÉTÉ ÉTÉ ÉTÉ ÉTÉ", "country_name": "Exemple"}
    monkeypatch.setattr(ghcn_graphic_helpers, "STATION", station)
    source = story_bundle_snapshot(graphic_bundles()[-1])
    original = deepcopy(source)
    result = media.prepare_media(source, synthetic=True)
    assert source == original
    assert source["where"] in result["descriptor"]["alt_text"]
    assert "Île" in result["descriptor"]["alt_text"]
    assert len(result["descriptor"]["alt_text"].encode("utf-8")) <= 1000
