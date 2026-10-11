"""Invented dated PM2.5 samples, never captured production weather."""

from src.data.air_quality import _parse_single_location, detect_pm25_hazard
from src.two_bot.intern.air_quality import build_pm25_hazard_bundle
from tests.air_quality_fixtures import payload


def graphic_bundle(values=None, *, timezone="Asia/Kathmandu", offset=20700):
    day = "2026-06-08"
    data = payload(day=day, timezone=timezone, offset=offset, lat=27.75, lon=85.25)
    data["hourly"]["pm2_5"] = values if values is not None else list(range(160, 184))
    obs = _parse_single_location(
        data,
        "Example City",
        "Example Country",
        27.7,
        85.3,
        day,
        requested_at=day + "T12:00:00Z",
        retrieved_at=day + "T12:00:01Z",
    )
    assert obs is not None
    event = detect_pm25_hazard(obs)
    assert event is not None
    return build_pm25_hazard_bundle(event)
