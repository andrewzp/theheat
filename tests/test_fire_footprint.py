"""Tests for fire footprint (GWIS) data."""

from src.data.fire_footprint import (
    FireComplex,
    TIERS_HECTARES,
    _classify_tier,
)
from src.data.fire_footprint import detect_tier_crossings


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
            tier=2,
            event_id="fire_footprint_GWIS_123_tier2",
        )
        assert fc.complex_id == "GWIS_123"
        assert fc.name == "Dixie Complex"
        assert fc.hectares == 213_000
        assert fc.tier == 2
        assert fc.event_id == "fire_footprint_GWIS_123_tier2"


def _mk_complex(complex_id: str, hectares: float, name: str | None = None) -> FireComplex:
    tier = _classify_tier(hectares)
    return FireComplex(
        complex_id=complex_id,
        name=name,
        country="US",
        region="California",
        hectares=hectares,
        start_date=None,
        tier=tier,
        event_id=f"fire_footprint_{complex_id}_tier{tier}",
    )


class TestDetectTierCrossings:
    def test_new_complex_above_floor_emits(self):
        state = {"fire_complex_tiers": {}}
        complexes = [_mk_complex("A", 60_000)]  # tier 1

        crossings = detect_tier_crossings(complexes, state)

        assert len(crossings) == 1
        assert crossings[0].complex_id == "A"
        assert crossings[0].tier == 1

    def test_new_complex_below_floor_suppressed(self):
        state = {"fire_complex_tiers": {}}
        complexes = [_mk_complex("A", 15_000)]  # below tier 0

        crossings = detect_tier_crossings(complexes, state)

        assert crossings == []

    def test_same_tier_second_run_suppressed(self):
        state = {"fire_complex_tiers": {"A": 1}}
        complexes = [_mk_complex("A", 70_000)]  # still tier 1

        crossings = detect_tier_crossings(complexes, state)

        assert crossings == []

    def test_tier_upgrade_emits(self):
        state = {"fire_complex_tiers": {"A": 1}}
        complexes = [_mk_complex("A", 150_000)]  # now tier 2

        crossings = detect_tier_crossings(complexes, state)

        assert len(crossings) == 1
        assert crossings[0].tier == 2

    def test_shrink_is_not_a_crossing(self):
        state = {"fire_complex_tiers": {"A": 3}}
        complexes = [_mk_complex("A", 60_000)]  # shrunk to tier 1

        crossings = detect_tier_crossings(complexes, state)

        assert crossings == []  # don't tweet a fire getting smaller

    def test_does_not_mutate_input_state(self):
        state = {"fire_complex_tiers": {"A": 1}}
        complexes = [_mk_complex("A", 150_000)]

        detect_tier_crossings(complexes, state)

        assert state["fire_complex_tiers"] == {"A": 1}

    def test_multiple_complexes_independent(self):
        state = {"fire_complex_tiers": {"A": 2}}
        complexes = [
            _mk_complex("A", 260_000),   # upgrade to tier 3
            _mk_complex("B", 60_000),    # new at tier 1
            _mk_complex("C", 10_000),    # below floor
        ]

        crossings = detect_tier_crossings(complexes, state)
        emitted_ids = {c.complex_id for c in crossings}

        assert emitted_ids == {"A", "B"}

    def test_missing_state_key_treated_as_empty(self):
        state = {}  # no fire_complex_tiers key at all
        complexes = [_mk_complex("A", 60_000)]

        crossings = detect_tier_crossings(complexes, state)

        assert len(crossings) == 1
