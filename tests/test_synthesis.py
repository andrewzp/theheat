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

    def test_naive_snapshot_timestamp_is_treated_as_utc(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["drought_snapshot"]["updated_at"] = "2999-01-01T00:00:00"
        assert len(detect_fire_drought_heat(state_ca_all_three)) == 1


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


class TestSynthesisHeatAnomalyField:
    """Regression: synthesis scorer expects heat anomaly (degrees above
    normal), but writers stored absolute temperature in value_c. Components
    must now carry heat_peak_anomaly_c, and the peak ranker must prefer
    anomaly when present."""

    def _state_with_heat(self, heats):
        from copy import deepcopy
        from src.state import (
            DEFAULT_STATE,
            record_synthesis_component,
            record_synthesis_drought_snapshot,
        )
        s = deepcopy(DEFAULT_STATE)
        record_synthesis_drought_snapshot(s, [
            {"state": "California", "d3_pct": 5.0, "d4_pct": 3.0, "total_drought_pct": 40.0},
        ])
        record_synthesis_component(
            s, kind="fire", region="California",
            event_id="fire_1",
            metadata={"frp": 1000.0, "region": "Sacramento County"},
            timestamp=_iso(offset_days=1),
        )
        for i, h in enumerate(heats):
            record_synthesis_component(
                s, kind="heat", region="California",
                event_id=f"heat_{i}",
                metadata=h,
                timestamp=_iso(offset_days=1),
            )
        return s

    def test_components_carry_heat_peak_anomaly_c(self):
        s = self._state_with_heat([
            {"kind": "calendar", "city": "Sacramento", "value_c": 40.0, "anomaly_c": 9.0},
        ])
        signals = detect_fire_drought_heat(s)
        assert len(signals) == 1
        comps = signals[0].components
        assert comps["heat_peak_anomaly_c"] == 9.0
        # value_c is still carried for context, but anomaly is separate.
        assert comps["heat_peak_value_c"] == 40.0

    def test_peak_heat_ranked_by_anomaly_not_value(self):
        # Two heats: one with bigger absolute temp, one with bigger anomaly.
        # The anomaly one should win the peak.
        s = self._state_with_heat([
            {"kind": "calendar", "city": "HotCity",   "value_c": 45.0, "anomaly_c": 4.0},
            {"kind": "anomaly",  "city": "Anomalous", "value_c": 32.0, "anomaly_c": 14.0},
        ])
        signals = detect_fire_drought_heat(s)
        comps = signals[0].components
        assert comps["heat_peak_city"] == "Anomalous"
        assert comps["heat_peak_anomaly_c"] == 14.0

    def test_legacy_missing_anomaly_falls_back_to_zero(self):
        s = self._state_with_heat([
            {"kind": "calendar", "city": "Old", "value_c": 40.0},  # no anomaly_c
        ])
        signals = detect_fire_drought_heat(s)
        comps = signals[0].components
        assert comps["heat_peak_anomaly_c"] == 0.0
