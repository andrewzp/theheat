"""Invented published-media inputs: a KTLX-shaped radar frame and an NHC-shaped cone graphic.

Every image says INVENTED; no real specimen, source fetch or rights verdict. The
documents are marked non-synthetic only so the offline fake-X journey can exercise
the posting path, exactly as the invented native fixtures do.
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw

from src.data.cyclones import LandThreatEvent
from src.media import gist_published_media as published, published_radar as radar
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.two_bot.intern.disasters import build_cyclone_land_threat_bundle, build_severe_weather_bundle
from tests import published_radar_fixtures as radar_fixtures

RADAR_AT = radar_fixtures.AT  # 2026-06-08T12:00Z; frame minute 11:59Z.
CONE_ISSUED = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
CLOCKS = {"radar": ("2026-06-08T12:03:00Z", "2026-06-08T12:15:00Z"),
          "cone": ("2026-09-15T04:00:00Z", "2026-09-15T09:00:00Z")}


# An official-form CAP identifier, so the existing NWS display/timing gates read it.
RADAR_ALERT_ID = "urn:oid:2.49.0.1.840.0.invented-radar-case"


def radar_feature():
    feature = radar_fixtures.feature()
    feature["id"] = "https://api.weather.gov/alerts/" + RADAR_ALERT_ID
    feature["properties"]["id"] = RADAR_ALERT_ID
    return feature


def radar_bundle(monkeypatch):
    return story_bundle_snapshot(build_severe_weather_bundle(radar_fixtures.parsed(monkeypatch, radar_feature())[0]))


def fake_nws_feed(monkeypatch):
    """Explicit offline stand-in for the sender's live NWS lookup: the unchanged retained warning."""
    from src.orchestrator import nws_publication
    monkeypatch.setattr(nws_publication, "_active_feed", lambda: {"features": [radar_feature()]})


def radar_inputs(*, synthetic=False):
    doc, raw, references, receipt = radar_fixtures.input_document()
    doc["synthetic"] = synthetic
    return doc, raw, references, receipt


def cone_bundle(*, storm_id="AL052026", advisory="12", issued=CONE_ISSUED, source="nhc"):
    event = LandThreatEvent(
        source=source, storm_id=storm_id, storm_name="Invented", basin="Atlantic", advisory_number=advisory,
        issued_at=issued.isoformat().replace("+00:00", "Z"), current_wind_kt=90, landmass_country="Invented Isles",
        nearest_city="Invented Harbour", min_distance_nm=80.0, closest_valid_at="2026-09-16T12:00:00Z",
        closest_tau_h=33, forecast_wind_kt_at_closest=95, event_id=f"cyclone_land_threat_{storm_id}_invented")
    return story_bundle_snapshot(build_cyclone_land_threat_bundle(event))


def cone_image(*, size=(897, 736), frames=1, mode="PNG"):
    image = Image.new("RGB", size, (232, 240, 248))
    draw = ImageDraw.Draw(image)
    draw.polygon([(120, 600), (420, 360), (760, 160), (840, 260), (470, 470), (190, 660)], fill=(255, 255, 255),
                 outline=(30, 30, 30))
    draw.line([(150, 620), (440, 410), (800, 210)], fill=(0, 0, 0), width=3)
    for x, y in ((150, 620), (440, 410), (800, 210)):
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(200, 30, 30))
    draw.text((20, 15), "INVENTED OFFLINE FIXTURE - NOT AN NHC PRODUCT", fill=(0, 0, 0))
    draw.text((20, 35), "Hurricane Invented Advisory 12 - 1100 PM AST Mon Sep 14 2026", fill=(0, 0, 0))
    draw.text((20, size[1] - 40), "NATIONAL HURRICANE CENTER (invented label fixture)", fill=(0, 0, 0))
    output = BytesIO()
    if mode == "GIF" and frames > 1:
        later = []
        for index in range(1, frames):
            frame = image.copy()
            ImageDraw.Draw(frame).rectangle((40 * index, 100, 40 * index + 30, 130), fill=(200, 30, 30))
            later.append(frame.convert("P"))
        image.convert("P").save(output, format="GIF", save_all=True, append_images=later, loop=0)
    else:
        image.save(output, format=mode)
    return output.getvalue()


def cone_inputs(*, storm_id="AL052026", advisory="12", issued=CONE_ISSUED, synthetic=False, raw=None,
                retrieved=None, legend=None):
    raw = cone_image() if raw is None else raw
    references = {"product": b"Invented retained cone-definition reference; not an NHC copy.",
                  "reuse": b"Invented retained reuse-reference fixture; not a rights verdict."}
    receipt = b"Invented local acquisition receipt; no network request."
    with Image.open(BytesIO(raw)) as image:
        width, height, fmt = image.width, image.height, image.format
    retrieved = retrieved or issued + timedelta(minutes=20)
    doc = {
        "schema_version": 1, "family": "nhc_track_cone_v1",
        "source_url": f"https://www.nhc.noaa.gov/storm_graphics/AT{storm_id[2:4]}/{storm_id}"
                      "_5day_cone_with_line_and_wind.png",
        "original": {"sha256": radar.digest(raw), "byte_count": len(raw),
                     "mime_type": "image/png" if fmt == "PNG" else "image/gif",
                     "width": width, "height": height, "frame_count": 1},
        "retrieved_at": retrieved.isoformat().replace("+00:00", "Z"),
        "receipt": {"sha256": radar.digest(receipt), "byte_count": len(receipt)},
        "metadata": {"storm_id": storm_id, "storm_name": "Invented", "advisory_number": advisory,
                     "issued_utc": issued.isoformat().replace("+00:00", "Z"),
                     "time_literal": "1100 PM AST Mon Sep 14 2026", "product": "NHC track forecast cone",
                     "legend": legend or ["Current information", "Forecast positions", "Potential track area",
                                          "Watches", "Warnings"],
                     "credit": published.CONE_CREDIT, "marks": ["NOAA logo", "NWS logo"]},
        "references": {"product": {"url": published.NHC_PRODUCT_URL, "sha256": radar.digest(references["product"]),
                                   "byte_count": len(references["product"])},
                       "reuse": {"url": radar.REUSE_URL, "sha256": radar.digest(references["reuse"]),
                                 "byte_count": len(references["reuse"])}},
        "synthetic": synthetic, "metadata_status": "unreviewed",
    }
    return doc, raw, references, receipt


def write_private_inputs(folder, doc, raw, references, receipt):
    """The retention CLI's private 0600 input files."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = {"metadata": folder / "metadata.json", "original": folder / "original.bin",
             "product": folder / "product-reference.bin", "reuse": folder / "reuse-reference.bin",
             "receipt": folder / "receipt.bin"}
    paths["metadata"].write_text(json.dumps(doc))
    paths["original"].write_bytes(raw)
    paths["product"].write_bytes(references["product"])
    paths["reuse"].write_bytes(references["reuse"])
    paths["receipt"].write_bytes(receipt)
    for path in paths.values():
        path.chmod(0o600)
    return paths


REGISTRY = Path(__file__).resolve().parents[1] / "data/place_registry.json"
