"""Tests for fire footprint (GWIS) data."""

import pytest

from src.data.fire_footprint import (
    FireComplex,
    TIERS_HECTARES,
    _classify_tier,
)


class TestClassifyTier:
    def test_below_floor_returns_negative_one(self):
        assert _classify_tier(0) == -1
        assert _classify_tier(19_999) == -1

    def test_exact_tier_thresholds(self):
        assert _classify_tier(20_000) == 0
        assert _classify_tier(50_000) == 1
        assert _classify_tier(100_000) == 2
        assert _classify_tier(250_000) == 3
        assert _classify_tier(500_000) == 4
        assert _classify_tier(1_000_000) == 5

    def test_between_tiers_rounds_down(self):
        assert _classify_tier(49_999) == 0
        assert _classify_tier(99_999) == 1
        assert _classify_tier(249_999) == 2

    def test_above_top_tier_clamps_to_top(self):
        assert _classify_tier(5_000_000) == 5
        assert _classify_tier(25_000_000) == 5  # Black Summer-scale

    def test_tiers_ladder_is_monotonic(self):
        assert TIERS_HECTARES == sorted(TIERS_HECTARES)
        assert TIERS_HECTARES[0] == 20_000
        assert TIERS_HECTARES[-1] == 1_000_000


class TestFireComplexDataclass:
    def test_fields_present(self):
        fc = FireComplex(
            complex_id="GWIS_123",
            name="Dixie Complex",
            country="US",
            region="California",
            hectares=213_000,
            start_date=None,
            tier=3,
            event_id="fire_footprint_GWIS_123_tier3",
        )
        assert fc.complex_id == "GWIS_123"
        assert fc.name == "Dixie Complex"
        assert fc.tier == 3
