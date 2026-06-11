"""Tests for fire footprint (NIFC WFIGS) data."""

from unittest.mock import patch

import responses

from src.data.fire_footprint import (
    FireComplex,
    TIERS_HECTARES,
    _classify_tier,
    detect_tier_crossings,
    fetch_active_fire_perimeters,
    GWIS_URL,
)


# NIFC ArcGIS-shape payload. IncidentSize is in acres; we convert to hectares
# before tier classification.
#
# Acre values chosen so resulting hectares are:
#   526_321 acres / 2.47105 ≈ 213,032 ha → tier 2 (100k–249k range)  [parent row]
#   148_264 acres / 2.47105 ≈  59,995 ha → tier 1  (50k–99k range)
#   148_264 acres / 2.47105 ≈  59,995 ha → tier 1  (50k–99k range, second good row)
#    12_355 acres / 2.47105 ≈   4,999 ha → below floor, filtered
SAMPLE_PAYLOAD = {
    "features": [
        {
            "attributes": {
                "UniqueFireIdentifier": "2026-CACND-000123",
                "IrwinID": "{AAA-111}",
                "IncidentName": "Dixie",
                "CpxName": "Dixie Complex",
                "IsCpxChild": 0,
                "IncidentSize": 526_321.0,
                "POOState": "US-CA",
                "FireDiscoveryDateTime": 1626220800000,
            }
        },
        {
            "attributes": {
                "UniqueFireIdentifier": "2026-AKFAS-000456",
                "IrwinID": "{BBB-222}",
                "IncidentName": "Yukon Fire",
                "CpxName": None,
                "IsCpxChild": None,
                "IncidentSize": 148_264.0,
                "POOState": "US-AK",
                "FireDiscoveryDateTime": 1625616000000,
            }
        },
        {
            "attributes": {
                "UniqueFireIdentifier": "2026-AK-000987",
                "IrwinID": "{DDD-444}",
                "IncidentName": "Tanana Fire",
                "CpxName": None,
                "IsCpxChild": None,
                "IncidentSize": 148_264.0,  # ~60k ha, tier 1 — used as "good row" in exception test
                "POOState": "US-AK",
                "FireDiscoveryDateTime": 1625616000000,
            }
        },
        {
            "attributes": {
                "UniqueFireIdentifier": "2026-ORMDF-000789",
                "IrwinID": "{CCC-333}",
                "IncidentName": "Small Fire",
                "CpxName": None,
                "IsCpxChild": None,
                "IncidentSize": 12_355.0,  # below floor (~4,999 ha)
                "POOState": "US-OR",
                "FireDiscoveryDateTime": 1625702400000,
            }
        },
    ]
}


class TestFetchActiveFirePerimeters:
    @responses.activate
    def test_happy_path_returns_complexes_above_floor(self):
        responses.add(responses.GET, GWIS_URL, json=SAMPLE_PAYLOAD, status=200)

        complexes = fetch_active_fire_perimeters()

        assert len(complexes) == 3  # small OR fire below floor filtered
        ids = {c.complex_id for c in complexes}
        assert ids == {"2026-CACND-000123", "2026-AKFAS-000456", "2026-AK-000987"}

    @responses.activate
    def test_complex_tier_classified_correctly(self):
        responses.add(responses.GET, GWIS_URL, json=SAMPLE_PAYLOAD, status=200)
        complexes = fetch_active_fire_perimeters()
        by_id = {c.complex_id: c for c in complexes}
        # 526_321 acres ≈ 213k ha → tier 2 (100k threshold, below 250k)
        assert by_id["2026-CACND-000123"].tier == 2
        # 148_264 acres ≈ 60k ha → tier 1 (50k threshold, below 100k)
        assert by_id["2026-AKFAS-000456"].tier == 1

    @responses.activate
    def test_event_id_includes_complex_and_tier(self):
        responses.add(responses.GET, GWIS_URL, json=SAMPLE_PAYLOAD, status=200)
        complexes = fetch_active_fire_perimeters()
        dixie = next(c for c in complexes if c.complex_id == "2026-CACND-000123")
        assert dixie.event_id == "fire_footprint_2026-CACND-000123_tier2"

    @responses.activate
    def test_http_error_returns_empty(self):
        responses.add(responses.GET, GWIS_URL, status=500)
        assert fetch_active_fire_perimeters() == []

    @responses.activate
    def test_row_missing_size_filtered_below_floor(self):
        # Verifies the below-floor filter: missing IncidentSize → 0 ha → filtered out.
        bad_payload = {
            "features": [
                {"attributes": {"UniqueFireIdentifier": "X", "IncidentName": "Bad"}}
            ]
        }
        responses.add(responses.GET, GWIS_URL, json=bad_payload, status=200)
        assert fetch_active_fire_perimeters() == []

    @responses.activate
    def test_row_raising_exception_skipped_continues_loop(self):
        """Per-row try/except prevents one poison row from killing the whole fetch."""
        responses.add(responses.GET, GWIS_URL, json=SAMPLE_PAYLOAD, status=200)

        real_classify = _classify_tier

        def flaky_classify(hectares):
            if 200_000 < hectares < 220_000:  # the 213k Dixie row
                raise RuntimeError("simulated per-row failure")
            return real_classify(hectares)

        with patch("src.data.fire_footprint._classify_tier", side_effect=flaky_classify):
            complexes = fetch_active_fire_perimeters()

        # The 213k row blew up during processing; the 60k row survived.
        ids = {c.complex_id for c in complexes}
        assert "2026-CACND-000123" not in ids  # poison row skipped
        assert "2026-AK-000987" in ids  # good row still returned

    @responses.activate
    def test_irwin_id_fallback_used_when_unique_identifier_missing(self):
        """When UniqueFireIdentifier is absent, IrwinID is used as complex_id."""
        irwin_id = "aabbccdd-0000-1111-2222-333344445555"
        payload = {
            "features": [
                {
                    "attributes": {
                        "UniqueFireIdentifier": None,
                        "IrwinID": irwin_id,
                        "IncidentName": "Fallback Fire",
                        "CpxName": None,
                        "IsCpxChild": None,
                        "IncidentSize": 148_264.0,  # ~60k ha, above floor
                        "POOState": "US-NV",
                        "FireDiscoveryDateTime": 1625616000000,
                    }
                }
            ]
        }
        responses.add(responses.GET, GWIS_URL, json=payload, status=200)

        complexes = fetch_active_fire_perimeters()

        assert len(complexes) == 1
        assert complexes[0].complex_id == irwin_id

    @responses.activate
    def test_child_rows_filtered(self):
        """IsCpxChild == 1 rows are skipped; only parent complex rows are returned."""
        payload = {
            "features": [
                {
                    "attributes": {
                        "UniqueFireIdentifier": "PARENT-001",
                        "IrwinID": None,
                        "IncidentName": "Parent Complex",
                        "CpxName": "Parent Complex",
                        "IsCpxChild": 0,
                        "IncidentSize": 526_321.0,
                        "POOState": "US-CA",
                        "FireDiscoveryDateTime": 1626220800000,
                    }
                },
                {
                    "attributes": {
                        "UniqueFireIdentifier": "CHILD-001",
                        "IrwinID": None,
                        "IncidentName": "Child Fire A",
                        "CpxName": "Parent Complex",
                        "IsCpxChild": 1,
                        "IncidentSize": 300_000.0,
                        "POOState": "US-CA",
                        "FireDiscoveryDateTime": 1626220800000,
                    }
                },
            ]
        }
        responses.add(responses.GET, GWIS_URL, json=payload, status=200)
        complexes = fetch_active_fire_perimeters()
        ids = {c.complex_id for c in complexes}
        assert "PARENT-001" in ids
        assert "CHILD-001" not in ids

    def test_network_exception_returns_empty(self):
        with patch("src.data.fire_footprint.fetch_with_retry", side_effect=Exception("boom")):
            assert fetch_active_fire_perimeters() == []


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
