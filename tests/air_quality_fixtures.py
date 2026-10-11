"""Invented complete forecast windows; no captured source readings or provider I/O."""
from datetime import UTC, datetime

from src.data import air_quality as source


def payload(*, day=None, lat=31.5, lon=74.3, pm25=150.0, dust=500.0, pm10=None,
            aod=0.6, us_aqi=210, timezone="GMT", offset=0):
    day = day or datetime.now(UTC).date().isoformat()
    return {
        "latitude": lat, "longitude": lon, "timezone": timezone, "utc_offset_seconds": offset,
        "hourly_units": {"pm2_5": "μg/m³", "pm10": "μg/m³", "dust": "μg/m³",
                         "aerosol_optical_depth": "", "us_aqi": "USAQI"},
        "hourly": {"time": [f"{day}T{h:02d}:00" for h in range(24)],
                   "pm2_5": [pm25] * 24, "pm10": [pm10] * 24, "dust": [dust] * 24,
                   "aerosol_optical_depth": [aod] * 24, "us_aqi": [us_aqi] * 24},
    }


def observation(*, city="Lahore", country="Pakistan", day="2026-06-08", lat=31.5, lon=74.3,
                pm25=150.0, dust=500.0, aod=0.6, us_aqi=210, pm10_24h_mean=None):
    value = source._parse_single_location(
        payload(day=day, lat=lat, lon=lon, pm25=pm25, dust=dust,
                aod=aod, us_aqi=us_aqi, pm10=pm10_24h_mean),
        city, country, lat, lon, day,
        requested_at=f"{day}T12:00:00Z", retrieved_at=f"{day}T12:00:01Z",
    )
    # This helper can deliberately construct a quiet or single-hazard observation.
    if value is None and pm25 is None and dust is None:
        return source.CityAirQuality(city, country, lat, lon, day, None, None, None, None, None)
    assert value is not None
    return value
