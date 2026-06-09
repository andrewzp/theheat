"""Tests for wet-bulb two-bot intern bundles."""

from __future__ import annotations

from datetime import date

from src.data.open_meteo import WetBulbEvent
from src.two_bot.intern import build_wet_bulb_bundle


def test_build_wet_bulb_bundle_tier3() -> None:
    event = WetBulbEvent(
        city="Jacobabad",
        country="Pakistan",
        daily_max_tw_c=35.5,
        tier=3,
        tier_label="tier_3",
        tier_threshold_c=35.0,
        event_id="wetbulb_Jacobabad_2026-07-12_tier3",
        signal_date=date(2026, 7, 12),
    )

    bundle = build_wet_bulb_bundle(event)

    assert bundle.signal_kind == "wet_bulb_extreme"
    assert bundle.where == "Jacobabad, Pakistan"
    assert bundle.headline_metric["value"] == 35.5
    assert bundle.headline_metric["unit"] == "C_wetbulb"
    assert any(f["label"] == "tier" and f["value"] == 3 for f in bundle.current_facts)
    assert any(f["label"] == "tw_explainer" for f in bundle.current_facts)
    assert any(f["label"] == "audience_unit" for f in bundle.current_facts)
    assert bundle.historical_context == {}


def test_build_wet_bulb_bundle_with_archive_context() -> None:
    event = WetBulbEvent(
        city="Jacobabad",
        country="Pakistan",
        daily_max_tw_c=35.5,
        tier=3,
        tier_label="tier_3",
        tier_threshold_c=35.0,
        event_id="wetbulb_Jacobabad_2026-07-12_tier3",
        archive_max_tw_c=34.8,
        archive_max_year=2023,
        archive_years=30,
    )

    bundle = build_wet_bulb_bundle(event)

    assert bundle.historical_context["archive_max_tw_c"] == 34.8
    assert bundle.historical_context["archive_max_year"] == 2023
    assert bundle.historical_context["archive_years"] == 30
    assert bundle.historical_context["scope"] == "wet_bulb_archive_max"
