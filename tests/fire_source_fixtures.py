"""Invented source rows; never retained production packets."""
from datetime import UTC, datetime
from types import SimpleNamespace

from src.data.fire_identity import source_event_id
from src.data.fire_source_contract import (
    FIRMS_PUBLIC_URL, HMS_BASE, HMS_PRODUCT, make_receipt, parse_record,
)


def firms_row(product="VIIRS_SNPP_NRT", *, when=None):
    stamp = when or datetime.now(UTC).replace(second=0, microsecond=0)
    return {
        "latitude": "35.25", "longitude": "-110.50", "frp": "500.1234",
        "confidence": "91.5" if product == "MODIS_NRT" else "h",
        "acq_date": stamp.date().isoformat(), "acq_time": stamp.strftime("%H%M"),
        "satellite": {"VIIRS_SNPP_NRT": "N", "VIIRS_NOAA20_NRT": "N20", "VIIRS_NOAA21_NRT": "N21", "MODIS_NRT": "Terra"}[product],
        "instrument": "MODIS" if product == "MODIS_NRT" else "VIIRS",
        "version": "synthetic-v1",
    }


def hms_row(*, when=None):
    stamp = when or datetime.now(UTC).replace(second=0, microsecond=0)
    return {
        "Lat": "35.25", "Lon": "-110.50", "FRP": "500.1234",
        "YearDay": stamp.strftime("%Y%j"), "Time": stamp.strftime("%H%M"),
        "Satellite": "Synthetic sensor", "Method": "Synthetic method", "Ecosystem": "",
    }


def source_event(product="VIIRS_SNPP_NRT", *, when=None, leg=None):
    stamp = when or datetime.now(UTC).replace(second=0, microsecond=0)
    row = parse_record(product, hms_row(when=stamp) if product == HMS_PRODUCT else firms_row(product, when=stamp))
    url = f"{HMS_BASE}/{stamp:%Y/%m}/hms_fire{stamp:%Y%m%d}.txt" if product == HMS_PRODUCT else FIRMS_PUBLIC_URL
    return SimpleNamespace(
        lat=row.lat, lon=row.lon, frp=row.frp, confidence=row.ranking_confidence,
        nearest_city="Synthetic region", country="US",
        event_id=source_event_id(row.lat, row.lon, row.acquired_at),
        source_product=product, acquired_at=row.acquired_at,
        source_leg="noaa_hms" if product == HMS_PRODUCT else leg,
        acquisition_provenance=make_receipt(row, url),
    )


def fire_event(*, when=None, lat=13.5, lon=-4.2, frp=361.0, confidence=95,
               country='ML', region='Mali', product=None, leg=None):
    """Complete invented wire evidence for orchestration/builder tests."""
    from src.data.firms import FireEvent
    stamp = when or datetime(2032, 3, 1, 0, 1, tzinfo=UTC)
    product = product or ('VIIRS_SNPP_NRT' if confidence in (30, 70, 95) else 'MODIS_NRT')
    raw = hms_row(when=stamp) if product == HMS_PRODUCT else firms_row(product, when=stamp)
    raw.update({'Lat' if product == HMS_PRODUCT else 'latitude': str(lat),
                'Lon' if product == HMS_PRODUCT else 'longitude': str(lon),
                'FRP' if product == HMS_PRODUCT else 'frp': str(frp)})
    if product != HMS_PRODUCT:
        raw['confidence'] = str(confidence) if product == 'MODIS_NRT' else {30: 'l', 70: 'n', 95: 'h'}[confidence]
    row = parse_record(product, raw)
    url = f'{HMS_BASE}/{stamp:%Y/%m}/hms_fire{stamp:%Y%m%d}.txt' if product == HMS_PRODUCT else FIRMS_PUBLIC_URL
    return FireEvent(lat=row.lat, lon=row.lon, frp=row.frp, confidence=row.ranking_confidence,
        country=country, nearest_city=region, event_id=source_event_id(row.lat, row.lon, row.acquired_at),
        source_product=product, acquired_at=row.acquired_at,
        source_leg='noaa_hms' if product == HMS_PRODUCT else leg,
        acquisition_provenance=make_receipt(row, url))
