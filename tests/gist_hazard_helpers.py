"""Invented hazard source bundles for Gist post images; never captured weather.

Values, places and times are fabricated. Each bundle is built by the production
source builders, so its retained receipts/windows are internally consistent.
"""
from copy import deepcopy
import math

from src.data.air_quality import _parse_single_location, detect_pm25_hazard
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.two_bot.intern.air_quality import build_pm25_hazard_bundle
from tests.air_quality_fixtures import payload

PM25_TEXT = "Invented PM2.5 model forecast stays high through the local day at one grid point."
# A registered place identity: the existing sender gate refuses unregistered points.
# Its forecast values, times and grid are invented; this is not a weather claim.
SENDABLE_PM25 = dict(city="Kathmandu", country="Nepal", requested=(27.72, 85.32))


def pm25_bundle(values=None, *, day="2026-06-08", timezone="Asia/Kathmandu", offset=20700,
                requested_at=None, retrieved_at=None, city="Example City", country="Example Country",
                grid=(27.75, 85.25), requested=(27.7, 85.3)):
    data = payload(day=day, timezone=timezone, offset=offset, lat=grid[0], lon=grid[1])
    data["hourly"]["pm2_5"] = list(values) if values is not None else list(range(160, 184))
    obs = _parse_single_location(data, city, country, requested[0], requested[1], day,
                                 requested_at=requested_at or day + "T12:00:00Z",
                                 retrieved_at=retrieved_at or day + "T12:00:01Z")
    assert obs is not None, "invented forecast window must qualify"
    event = detect_pm25_hazard(obs)
    assert event is not None, "invented forecast must cross a PM2.5 tier"
    return story_bundle_snapshot(build_pm25_hazard_bundle(event))


def window(bundle):
    return bundle["raw_signal_dump"]["forecast_window"]


def with_bundle(draft, bundle):
    value = deepcopy(draft)
    value["review_context"]["two_bot"]["bundle"] = deepcopy(bundle)
    return value


# Per-family fixed clocks: one inside the image-path recency window, one after it.
CLOCKS = {"pm25": ("2026-06-08T13:00:00Z", "2026-06-08T18:15:00Z"),
          "modis": ("2032-03-01T12:00:00Z", "2032-03-03T00:00:00Z"),
          "viirs": ("2032-03-01T12:00:00Z", "2032-03-03T00:00:00Z")}
TYPES = {"pm25": "air_quality_hazard", "modis": "fire", "viirs": "fire"}
TEXTS = {"pm25": PM25_TEXT, "modis": "Invented satellite heat detections near a saved source minute.",
         "viirs": "Invented NOAA-20 VIIRS heat detections near a saved source minute."}
VIIRS_CATEGORIES = ("high", "nominal", "low", "high")
# Primary A deliberately not the maximum; four retained detections in source order.
MODIS_VALUES = (125.75, 500.1234, 750.25, 90.5)
MODIS_COORDINATES = [(35.25, -110.5), (38.5, -104.2), (31.9, -99.0), (44.4, -120.8)]
VARYING_PM25 = [round(160 + 30 * math.sin(i / 3.5) + i, 2) for i in range(24)]


def family_bundle(family):
    if family == "pm25":
        return pm25_bundle(VARYING_PM25, **SENDABLE_PM25)
    if family == "modis":
        return modis_bundle(MODIS_VALUES, coordinates=MODIS_COORDINATES)
    if family == "viirs":
        return viirs_bundle(MODIS_VALUES, categories=VIIRS_CATEGORIES, coordinates=MODIS_COORDINATES)
    raise ValueError(family)


def viirs_bundle(values=(500.1234, 125.75, 750.25), **options):
    from tests.viirs_graphic_helpers import viirs_bundle as build
    return story_bundle_snapshot(build(values, **options))


def modis_bundle(values=(500.1234, 125.75, 750.25), **options):
    from tests.fire_graphic_helpers import graphic_bundle
    return story_bundle_snapshot(graphic_bundle(values, **options))


def saved_state(family, *, runtime=None):
    """Two drafts sharing one invented retained source, plus an unrelated field."""
    from src.editorial import revisions

    bundle = family_bundle(family)
    drafts = []
    for suffix in ("", "-secondary"):
        draft = dict(id=f"invented-{family}{suffix}", event_id=bundle["event_id"], type=TYPES[family],
                     text=TEXTS[family], status="pending", created_at=CLOCKS[family][0],
                     review_context=dict(two_bot=dict(bundle=deepcopy(bundle))))
        revisions.initialize_revision(draft)
        draft.update(content_revision=1, decision_revision=0)
        drafts.append(draft)
    return {"drafts": drafts, "publish_ledger": {}, "errors": [], "unrelated": {"preserve": True},
            "run_history": [runtime] if runtime else []}
