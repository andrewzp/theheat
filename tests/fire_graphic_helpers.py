"""Invented MODIS pixels only; no captured weather or physical incident claim."""

from datetime import UTC, datetime

from src.data.fire_source_contract import make_receipt, parse_record, FIRMS_PUBLIC_URL
from src.two_bot.intern.fire import build_fire_bundle
from src.two_bot.types import RelatedSignal
from tests.fire_source_fixtures import fire_event


def graphic_bundle(values=(500.1234, 125.75, 750.25), *, platforms=None, coordinates=None):
    bundles = []
    for i, value in enumerate(values):
        lat, lon = coordinates[i] if coordinates else (35.25 + i, -110.50 - i)
        event = fire_event(when=datetime(2032, 2, 29, 23, 59, tzinfo=UTC),
                           lat=lat, lon=lon, frp=value, confidence=91, product="MODIS_NRT",
                           region="Invented region", country="US")
        if platforms:
            raw = dict(event.acquisition_provenance["record"], satellite=platforms[i])
            event.acquisition_provenance = make_receipt(parse_record("MODIS_NRT", raw), FIRMS_PUBLIC_URL)
        bundles.append(build_fire_bundle(event))
    primary = bundles[0]
    primary.related_signals = [RelatedSignal(
        event_id=b.event_id, signal_kind="fire", where=b.where, when=b.when,
        headline_metric=b.headline_metric, country=b.country,
        acquisition_evidence=b.raw_signal_dump["acquisition_provenance"],
    ) for b in bundles[1:]]
    return primary
