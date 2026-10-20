"""Invented NOAA-20/NOAA-21 VIIRS pixels only; no captured weather or physical incident claim."""

from datetime import UTC, datetime

from src.two_bot.intern.fire import build_fire_bundle
from src.two_bot.types import RelatedSignal
from tests.fire_source_fixtures import fire_event

WHEN = datetime(2032, 2, 29, 23, 59, tzinfo=UTC)
# Source ranking numbers used only to select the invented category spelling:
# 30 -> "l"/low, 70 -> "n"/nominal, 95 -> "h"/high (src/data/fire_source_contract.py).
RANKING = {"low": 30, "nominal": 70, "high": 95}


def viirs_bundle(values=(500.1234, 125.75, 750.25), *, product="VIIRS_NOAA20_NRT",
                 categories=("high", "nominal", "low", "high"), coordinates=None, products=None, when=None):
    bundles = []
    for i, value in enumerate(values):
        lat, lon = coordinates[i] if coordinates else (35.25 + i, -110.50 - i)
        event = fire_event(when=when[i] if isinstance(when, list) else (when or WHEN),
                           lat=lat, lon=lon, frp=value, confidence=RANKING[categories[i]],
                           product=products[i] if products else product,
                           region="Invented region", country="US")
        bundles.append(build_fire_bundle(event))
    primary = bundles[0]
    primary.related_signals = [RelatedSignal(
        event_id=b.event_id, signal_kind="fire", where=b.where, when=b.when,
        headline_metric=b.headline_metric, country=b.country,
        acquisition_evidence=b.raw_signal_dump["acquisition_provenance"],
    ) for b in bundles[1:]]
    return primary
