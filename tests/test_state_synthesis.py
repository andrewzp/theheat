"""Tests for synthesis-layer state helpers."""

from copy import deepcopy
from datetime import date, datetime, timedelta, UTC

import pytest

from src.state import (
    DEFAULT_STATE,
    record_synthesis_component,
    get_synthesis_components,
    record_synthesis_drought_snapshot,
    get_synthesis_drought_snapshot,
    is_synthesis_on_cooldown,
    record_synthesis_fired,
    prune_stale_synthesis_components,
)


def _now_iso(offset_days: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=offset_days)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def fresh_state():
    return deepcopy(DEFAULT_STATE)


class TestRecordSynthesisComponent:
    def test_fresh_state_creates_structure(self, fresh_state):
        record_synthesis_component(
            fresh_state, kind="fire", region="California",
            event_id="fire_abc", metadata={"frp": 1200.0},
            timestamp=_now_iso(),
        )
        fires = fresh_state["synthesis_components"]["fires"]["California"]
        assert len(fires) == 1
        assert fires[0]["event_id"] == "fire_abc"
        assert fires[0]["frp"] == 1200.0

    def test_multiple_components_same_state(self, fresh_state):
        record_synthesis_component(fresh_state, kind="heat", region="California",
            event_id="heat_1", metadata={"city": "Sacramento", "value_c": 42.0},
            timestamp=_now_iso())
        record_synthesis_component(fresh_state, kind="heat", region="California",
            event_id="heat_2", metadata={"city": "Fresno", "value_c": 43.5},
            timestamp=_now_iso())
        heats = fresh_state["synthesis_components"]["heats"]["California"]
        assert len(heats) == 2

    def test_duplicate_event_id_skipped(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="fire_abc", metadata={"frp": 1.0}, timestamp=_now_iso())
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="fire_abc", metadata={"frp": 999.0}, timestamp=_now_iso())
        assert len(fresh_state["synthesis_components"]["fires"]["California"]) == 1


class TestGetSynthesisComponents:
    def test_empty_state_returns_empty(self, fresh_state):
        assert get_synthesis_components(fresh_state, kind="fire", region="California") == []

    def test_filters_by_since(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="old", metadata={}, timestamp=_now_iso(offset_days=20))
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="new", metadata={}, timestamp=_now_iso(offset_days=3))
        since = (datetime.now(UTC) - timedelta(days=14)).isoformat().replace("+00:00", "Z")
        result = get_synthesis_components(fresh_state, kind="fire", region="California", since=since)
        assert len(result) == 1
        assert result[0]["event_id"] == "new"


class TestPruneStaleSynthesisComponents:
    def test_removes_items_older_than_ttl(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="old", metadata={}, timestamp=_now_iso(offset_days=20))
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="new", metadata={}, timestamp=_now_iso(offset_days=5))
        prune_stale_synthesis_components(fresh_state, ttl_days=14)
        fires = fresh_state["synthesis_components"]["fires"]["California"]
        assert [f["event_id"] for f in fires] == ["new"]

    def test_removes_empty_region_keys(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="Arizona",
            event_id="old", metadata={}, timestamp=_now_iso(offset_days=30))
        prune_stale_synthesis_components(fresh_state, ttl_days=14)
        assert "Arizona" not in fresh_state["synthesis_components"]["fires"]


class TestCooldown:
    def test_no_prior_fire_not_on_cooldown(self, fresh_state):
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "California") is False

    def test_within_14_days_on_cooldown(self, fresh_state):
        record_synthesis_fired(fresh_state, "fire_drought_heat", "California",
            timestamp=_now_iso(offset_days=5))
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "California") is True

    def test_after_14_days_not_on_cooldown(self, fresh_state):
        record_synthesis_fired(fresh_state, "fire_drought_heat", "California",
            timestamp=_now_iso(offset_days=16))
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "California") is False

    def test_cooldown_scoped_by_region(self, fresh_state):
        record_synthesis_fired(fresh_state, "fire_drought_heat", "California",
            timestamp=_now_iso(offset_days=1))
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "Arizona") is False


class TestDroughtSnapshot:
    def test_record_and_get(self, fresh_state):
        updates = [
            {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
            {"state": "Arizona",    "d3_pct": 15.0, "d4_pct": 2.0,  "total_drought_pct": 60.0},
        ]
        record_synthesis_drought_snapshot(fresh_state, updates)
        snap = get_synthesis_drought_snapshot(fresh_state)
        assert snap is not None
        assert snap["entries"][0]["state"] == "California"

    def test_missing_returns_none(self, fresh_state):
        assert get_synthesis_drought_snapshot(fresh_state) is None


class TestSynthesisMergePreservesState:
    """Regression: _merge_state used to drop synthesis_components and
    synthesis_cooldown, which meant every persisted write reset the
    14-day window and cooldown map to defaults. Keep the evidence."""

    def test_merge_preserves_synthesis_components_across_states(self):
        from src.state import _merge_state

        base = {
            "synthesis_components": {
                "fires": {
                    "California": [
                        {"event_id": "fire_1", "frp": 900.0, "at": "2026-04-18T10:00:00Z"},
                    ],
                },
                "heats": {},
                "drought_snapshot": {
                    "updated_at": "2026-04-15T12:00:00Z",
                    "entries": [{"state": "California", "d4_pct": 10.0}],
                },
            },
        }
        incoming = {
            "synthesis_components": {
                "fires": {
                    "California": [
                        {"event_id": "fire_1", "frp": 900.0, "at": "2026-04-18T10:00:00Z"},
                        {"event_id": "fire_2", "frp": 1500.0, "at": "2026-04-20T09:00:00Z"},
                    ],
                    "Arizona": [
                        {"event_id": "fire_3", "frp": 400.0, "at": "2026-04-20T11:00:00Z"},
                    ],
                },
                "heats": {
                    "California": [
                        {"event_id": "heat_1", "value_c": 42.1, "anomaly_c": 9.0,
                         "at": "2026-04-20T14:00:00Z"},
                    ],
                },
                "drought_snapshot": {
                    "updated_at": "2026-04-19T12:00:00Z",  # newer
                    "entries": [{"state": "California", "d4_pct": 12.0}],
                },
            },
        }
        merged = _merge_state(base, incoming)
        fires = merged["synthesis_components"]["fires"]
        assert len(fires["California"]) == 2
        assert {f["event_id"] for f in fires["California"]} == {"fire_1", "fire_2"}
        assert fires["Arizona"][0]["event_id"] == "fire_3"
        heats = merged["synthesis_components"]["heats"]
        assert heats["California"][0]["anomaly_c"] == 9.0
        # Drought snapshot takes the newer updated_at.
        assert merged["synthesis_components"]["drought_snapshot"]["updated_at"] == "2026-04-19T12:00:00Z"
        assert merged["synthesis_components"]["drought_snapshot"]["entries"][0]["d4_pct"] == 12.0

    def test_merge_preserves_cooldown_keeping_most_recent(self):
        from src.state import _merge_state

        base = {
            "synthesis_cooldown": {
                "synthesis_fire_drought_heat": {
                    "California": "2026-04-15T12:00:00Z",
                    "Arizona": "2026-04-10T12:00:00Z",
                },
            },
        }
        incoming = {
            "synthesis_cooldown": {
                "synthesis_fire_drought_heat": {
                    "California": "2026-04-20T12:00:00Z",  # newer, wins
                    "Arizona": "2026-04-08T12:00:00Z",     # older, loses
                },
            },
        }
        merged = _merge_state(base, incoming)
        ca = merged["synthesis_cooldown"]["synthesis_fire_drought_heat"]
        assert ca["California"] == "2026-04-20T12:00:00Z"
        assert ca["Arizona"] == "2026-04-10T12:00:00Z"

    def test_empty_base_accepts_incoming_synthesis(self):
        from src.state import _merge_state

        merged = _merge_state(
            {},
            {
                "synthesis_components": {
                    "fires": {"Oregon": [{"event_id": "f1", "at": "2026-04-20T00:00:00Z"}]},
                    "heats": {},
                    "drought_snapshot": None,
                },
                "synthesis_cooldown": {"rule_x": {"Oregon": "2026-04-20T00:00:00Z"}},
            },
        )
        assert merged["synthesis_components"]["fires"]["Oregon"][0]["event_id"] == "f1"
        assert merged["synthesis_cooldown"]["rule_x"]["Oregon"] == "2026-04-20T00:00:00Z"
