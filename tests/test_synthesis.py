"""Tests for cross-source synthesis rules."""

from copy import deepcopy
from datetime import datetime, timedelta, UTC

import pytest

from src.state import (
    DEFAULT_STATE,
    record_synthesis_component,
    record_synthesis_drought_snapshot,
    record_synthesis_fired,
)
from src.editorial.synthesis import detect_fire_drought_heat, SynthesisSignal


def _iso(offset_days: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=offset_days)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def state_ca_all_three():
    s = deepcopy(DEFAULT_STATE)
    record_synthesis_drought_snapshot(s, [
        {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
    ])
    record_synthesis_component(s, kind="fire", region="California",
        event_id="fire_1", metadata={"frp": 1200.0, "region": "Sacramento"},
        timestamp=_iso(offset_days=2))
    record_synthesis_component(s, kind="heat", region="California",
        event_id="heat_1",
        metadata={"kind": "calendar", "city": "Sacramento", "value_c": 40.1},
        timestamp=_iso(offset_days=1))
    return s


class TestFireDroughtHeatHappyPath:
    def test_fires_one_signal(self, state_ca_all_three):
        signals = detect_fire_drought_heat(state_ca_all_three)
        assert len(signals) == 1
        sig = signals[0]
        assert isinstance(sig, SynthesisSignal)
        assert sig.rule_name == "fire_drought_heat"
        assert sig.region == "California"
        assert "california" in sig.event_id.lower()

    def test_components_populated(self, state_ca_all_three):
        sig = detect_fire_drought_heat(state_ca_all_three)[0]
        assert sig.components["drought_d4_pct"] == 10.0
        assert sig.components["fire_peak_frp"] == 1200.0
        assert sig.components["heat_peak_city"] == "Sacramento"


class TestFireDroughtHeatMissingComponents:
    def test_missing_drought_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["drought_snapshot"] = None
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_drought_below_1pct_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["drought_snapshot"]["entries"][0]["d4_pct"] = 0.5
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_missing_fire_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["fires"] = {}
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_missing_heat_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["heats"] = {}
        assert detect_fire_drought_heat(state_ca_all_three) == []


class TestFireDroughtHeatRegionMismatch:
    def test_fire_and_heat_different_states_no_signal(self):
        s = deepcopy(DEFAULT_STATE)
        record_synthesis_drought_snapshot(s, [
            {"state": "California", "d3_pct": 20.0, "d4_pct": 8.0, "total_drought_pct": 80.0},
            {"state": "Arizona",    "d3_pct": 30.0, "d4_pct": 5.0, "total_drought_pct": 70.0},
        ])
        # Fire in CA, heat in AZ — CA lacks heat, AZ lacks fire.
        record_synthesis_component(s, kind="fire", region="California",
            event_id="fire_1", metadata={"frp": 800.0}, timestamp=_iso(offset_days=1))
        record_synthesis_component(s, kind="heat", region="Arizona",
            event_id="heat_1", metadata={"city": "Phoenix", "value_c": 46.0},
            timestamp=_iso(offset_days=1))
        assert detect_fire_drought_heat(s) == []


class TestFireDroughtHeatStaleness:
    def test_stale_fire_ignored(self):
        s = deepcopy(DEFAULT_STATE)
        record_synthesis_drought_snapshot(s, [
            {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
        ])
        record_synthesis_component(s, kind="fire", region="California",
            event_id="old", metadata={"frp": 1200.0}, timestamp=_iso(offset_days=20))
        record_synthesis_component(s, kind="heat", region="California",
            event_id="heat_1", metadata={"city": "Sacramento", "value_c": 40.0},
            timestamp=_iso(offset_days=1))
        assert detect_fire_drought_heat(s) == []

    def test_stale_drought_snapshot_no_signal(self, state_ca_all_three):
        # Make the snapshot 20 days old.
        state_ca_all_three["synthesis_components"]["drought_snapshot"]["updated_at"] = _iso(offset_days=20)
        assert detect_fire_drought_heat(state_ca_all_three) == []


class TestFireDroughtHeatCooldown:
    def test_within_cooldown_no_signal(self, state_ca_all_three):
        record_synthesis_fired(state_ca_all_three, "fire_drought_heat", "California",
            timestamp=_iso(offset_days=3))
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_after_cooldown_signal_fires(self, state_ca_all_three):
        record_synthesis_fired(state_ca_all_three, "fire_drought_heat", "California",
            timestamp=_iso(offset_days=20))
        assert len(detect_fire_drought_heat(state_ca_all_three)) == 1


class TestSynthesisEnabledToggle:
    def test_disabled_returns_empty(self, state_ca_all_three):
        state_ca_all_three["synthesis_enabled"] = False
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_default_enabled(self, state_ca_all_three):
        # No synthesis_enabled key → default to enabled.
        assert "synthesis_enabled" not in state_ca_all_three
        assert len(detect_fire_drought_heat(state_ca_all_three)) == 1
