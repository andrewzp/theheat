from datetime import date

from src.two_bot.intern import build_fire_bundle

from tests.two_bot.conftest import _fire_event


def test_build_fire_bundle_uses_fire_signal_fields():
    fire = _fire_event(event_id="fire_1", region="Southwestern US", country="US")
    bundle = build_fire_bundle(fire)

    assert bundle.signal_kind == "fire"
    assert bundle.where == "Southwestern US"
    assert bundle.when == date.today().isoformat()
    assert bundle.event_id == "fire_1"
    assert bundle.headline_metric == {"label": "FRP", "value": 361.0, "unit": "MW"}
    assert bundle.historical_context == {}
    assert bundle.raw_signal_dump["event_id"] == "fire_1"


def test_build_fire_bundle_falls_back_to_country_when_region_missing():
    fire = _fire_event(region="", country="ML")
    bundle = build_fire_bundle(fire)

    assert bundle.where == "ML"
    assert {"label": "nearest_region", "value": ""} in bundle.current_facts

