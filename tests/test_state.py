"""Tests for state management."""

from datetime import UTC, date, datetime, timedelta
import tempfile
from unittest.mock import patch

import requests

from src.state import (
    add_source_run,
    is_duplicate,
    finalize_run,
    StateReadError,
    read_state,
    record_event,
    get_daily_count,
    increment_daily_count,
    init_run,
    check_daily_cap,
    update_streaks,
    update_record_streak,
    update_ch4_last_milestone,
    update_coral_dhw_tier,
    update_sst_anom_tier,
    update_cyclone_tier,
    update_flood_activation_tier,
    record_cyclone_wind_observation,
    increment_ch4_annual_count,
    increment_coral_dhw_annual_count,
    increment_sst_anom_annual_count,
    increment_oscillation_annual_count,
    increment_ozone_hole_annual_count,
    increment_cyclone_annual_count,
    increment_flood_annual_count,
    update_oscillation_last_phase,
    record_ozone_hole_peak,
    get_record_streak,
    prune_stale_record_streaks,
    log_error,
    DEFAULT_STATE,
    write_state,
    _fresh_state,
)


def _draft_timestamp(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _draft(draft_id: str, status: str, days_ago: int) -> dict:
    ts = _draft_timestamp(days_ago)
    return {
        "id": draft_id,
        "text": draft_id,
        "status": status,
        "type": "record",
        "created_at": ts,
        "updated_at": ts,
    }


class TestDuplicate:
    def test_new_event(self, fresh_state):
        assert not is_duplicate(fresh_state, "new_event")

    def test_existing_event(self, state_with_events):
        assert is_duplicate(state_with_events, "event_1")

    def test_record_event_adds_id(self, fresh_state):
        record_event(fresh_state, "new_event")
        assert is_duplicate(fresh_state, "new_event")

    def test_record_event_caps_at_500(self):
        state = {"posted_events": [f"event_{i}" for i in range(510)]}
        record_event(state, "final")
        assert len(state["posted_events"]) <= 501  # 500 kept + 1 new


class TestDailyCap:
    @patch("src.state.date")
    def test_fresh_state_has_zero_count(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 4, 7)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert get_daily_count(fresh_state) == 0

    @patch("src.state.date")
    def test_increment_count(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 4, 7)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        increment_daily_count(fresh_state)
        assert get_daily_count(fresh_state) == 1

    @patch("src.state.date")
    def test_cap_not_reached(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 4, 7)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert check_daily_cap(fresh_state, cap=10)

    @patch("src.state.date")
    def test_cap_reached(self, mock_date):
        mock_date.today.return_value = date(2026, 4, 7)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        state = {"daily_tweet_count": {"2026-04-07": 10}}
        assert not check_daily_cap(state, cap=10)

    @patch("src.state.date")
    def test_old_days_cleaned_up(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 4, 7)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        fresh_state["daily_tweet_count"] = {"2026-04-06": 5, "2026-04-05": 3}
        increment_daily_count(fresh_state)
        assert "2026-04-06" not in fresh_state["daily_tweet_count"]
        assert "2026-04-07" in fresh_state["daily_tweet_count"]


class TestStreaks:
    @patch("src.state.date")
    def test_new_city_starts_streak(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 4, 7)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        update_streaks(fresh_state, ["Miami"])
        assert fresh_state["streaks"]["Miami"]["consecutive_days"] == 1

    @patch("src.state.date")
    def test_city_drops_off(self, mock_date):
        mock_date.today.return_value = date(2026, 4, 9)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        state = {"streaks": {"Miami": {"consecutive_days": 5, "last_seen": "2026-04-07"}}}
        update_streaks(state, ["Phoenix"])
        assert "Miami" not in state["streaks"]
        assert "Phoenix" in state["streaks"]


class TestRecordStreaks:
    @patch("src.state.date")
    def test_new_city_starts_streak_at_1(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 4, 18)
        mock_date.fromisoformat = date.fromisoformat
        update_record_streak(fresh_state, "Phoenix", 42.5)
        assert get_record_streak(fresh_state, "Phoenix")["days"] == 1

    @patch("src.state.date")
    def test_consecutive_days_extend_streak(self, mock_date, fresh_state):
        mock_date.fromisoformat = date.fromisoformat
        mock_date.today.return_value = date(2026, 4, 17)
        update_record_streak(fresh_state, "Phoenix", 42.0)
        mock_date.today.return_value = date(2026, 4, 18)
        update_record_streak(fresh_state, "Phoenix", 43.5)
        entry = get_record_streak(fresh_state, "Phoenix")
        assert entry["days"] == 2
        assert entry["peak_temp_c"] == 43.5

    @patch("src.state.date")
    def test_gap_resets_streak(self, mock_date, fresh_state):
        mock_date.fromisoformat = date.fromisoformat
        mock_date.today.return_value = date(2026, 4, 10)
        update_record_streak(fresh_state, "Phoenix", 42.0)
        mock_date.today.return_value = date(2026, 4, 18)  # 8-day gap
        update_record_streak(fresh_state, "Phoenix", 41.0)
        entry = get_record_streak(fresh_state, "Phoenix")
        assert entry["days"] == 1

    @patch("src.state.date")
    def test_prune_stale_removes_old_streaks(self, mock_date, fresh_state):
        mock_date.fromisoformat = date.fromisoformat
        mock_date.today.return_value = date(2026, 4, 1)
        update_record_streak(fresh_state, "Phoenix", 42.0)
        mock_date.today.return_value = date(2026, 4, 18)  # 17 days later
        prune_stale_record_streaks(fresh_state, max_gap_days=2)
        assert get_record_streak(fresh_state, "Phoenix") is None

    @patch("src.state.date")
    def test_prune_keeps_recently_updated_lagged_station_streak(self, mock_date, fresh_state):
        mock_date.fromisoformat = date.fromisoformat
        mock_date.today.return_value = date(2026, 5, 5)
        update_record_streak(
            fresh_state,
            "USW00023183",
            42.0,
            event_date=date(2026, 5, 1),
        )

        prune_stale_record_streaks(fresh_state, max_gap_days=2)
        assert get_record_streak(fresh_state, "USW00023183") is not None

        mock_date.today.return_value = date(2026, 5, 8)
        prune_stale_record_streaks(fresh_state, max_gap_days=2)
        assert get_record_streak(fresh_state, "USW00023183") is None


class TestErrorLog:
    def test_log_error_appends(self, fresh_state):
        log_error(fresh_state, "test_source", "something broke")
        assert len(fresh_state["errors"]) == 1
        assert fresh_state["errors"][0]["source"] == "test_source"

    def test_log_error_caps_at_50(self):
        state = {"errors": [{"source": "x", "ts": "t", "msg": "m"} for _ in range(55)]}
        log_error(state, "new", "msg")
        assert len(state["errors"]) <= 51


class TestRunHistory:
    def test_init_run_creates_running_record(self):
        run = init_run("alerts")
        assert run["mode"] == "alerts"
        assert run["status"] == "running"
        assert run["sources"] == []

    def test_add_source_run_appends_source_metrics(self):
        run = init_run("alerts")
        add_source_run(run, source="firms", status="success", observed=3, promoted=1, drafted=1, duration_ms=150)
        assert len(run["sources"]) == 1
        assert run["sources"][0]["source"] == "firms"
        assert run["sources"][0]["drafted"] == 1

    def test_add_source_run_persists_optional_details(self):
        """Dashboard drill-down: details dict (pipeline_metrics + events) must
        round-trip through add_source_run when supplied."""
        run = init_run("alerts")
        add_source_run(
            run, source="open_meteo_extreme_signals", status="success",
            details={
                "provider": "ghcn",
                "pipeline_metrics": {"stations_active": 11907, "raw_signals": 2},
                "events": [
                    {"station_id": "USC0001", "decision": "rejected", "type": "anomaly_cold"},
                ],
            },
        )
        entry = run["sources"][0]
        assert entry["details"]["provider"] == "ghcn"
        assert entry["details"]["pipeline_metrics"]["stations_active"] == 11907
        assert entry["details"]["events"][0]["station_id"] == "USC0001"

    def test_add_source_run_omits_details_key_when_unset(self):
        """No details payload → no `details` key in the source row (smaller state file)."""
        run = init_run("alerts")
        add_source_run(run, source="firms", status="success")
        assert "details" not in run["sources"][0]

    def test_finalize_run_prepends_to_history(self, fresh_state):
        run = init_run("alerts")
        add_source_run(run, source="firms", status="success", drafted=1)
        finalize_run(fresh_state, run, status="success")
        assert len(fresh_state["run_history"]) == 1
        assert fresh_state["run_history"][0]["drafted_count"] == 1

    def test_finalize_run_caps_history(self):
        state = {"run_history": [{"id": f"old_{i}"} for i in range(25)]}
        run = init_run("alerts")
        finalize_run(state, run, status="success", max_runs=20)
        assert len(state["run_history"]) == 20


class TestOceanSSTStreak:
    def test_default_state_has_ocean_sst_streak(self):
        from src.state import DEFAULT_STATE
        assert "ocean_sst_streak" in DEFAULT_STATE
        assert DEFAULT_STATE["ocean_sst_streak"] == {
            "seeded": False,
            "last_milestone_fired": None,
        }

    def test_merge_state_prefers_incoming_ocean_sst_streak(self):
        from src.state import _merge_state
        current = {"ocean_sst_streak": {"seeded": True, "last_milestone_fired": 5}}
        incoming = {"ocean_sst_streak": {"seeded": True, "last_milestone_fired": 25}}
        merged = _merge_state(current, incoming)
        assert merged["ocean_sst_streak"] == {"seeded": True, "last_milestone_fired": 25}

    def test_merge_state_falls_back_to_current_when_incoming_missing(self):
        from src.state import _merge_state
        current = {"ocean_sst_streak": {"seeded": True, "last_milestone_fired": 10}}
        incoming = {}
        merged = _merge_state(current, incoming)
        # _normalize_state backfills `incoming` with DEFAULT_STATE values, so an
        # empty incoming dict becomes the default. Always-take-incoming semantics
        # (matching record_streaks) means current's seeded=True is clobbered — this
        # test documents and pins that known behaviour.
        assert merged["ocean_sst_streak"] == {"seeded": False, "last_milestone_fired": None}

    def test_update_ocean_sst_streak_replaces_dict(self):
        from src.state import update_ocean_sst_streak
        state = _fresh_state()
        result = update_ocean_sst_streak(state, {"seeded": True, "last_milestone_fired": 25})
        assert result["ocean_sst_streak"] == {"seeded": True, "last_milestone_fired": 25}

    def test_update_ocean_sst_streak_handles_missing_key(self):
        from src.state import update_ocean_sst_streak
        state = {}
        result = update_ocean_sst_streak(state, {"seeded": True, "last_milestone_fired": None})
        assert result["ocean_sst_streak"] == {"seeded": True, "last_milestone_fired": None}


class TestCycloneState:
    def test_default_state_has_cyclone_trackers(self):
        assert DEFAULT_STATE["cyclone_tiers"] == {}
        assert DEFAULT_STATE["cyclone_wind_history"] == {}
        assert DEFAULT_STATE["cyclone_annual_count"] == {}

    def test_update_cyclone_tier_keeps_highest_category(self, fresh_state):
        update_cyclone_tier(fresh_state, "nhc:al012026", 3)
        update_cyclone_tier(fresh_state, "nhc:al012026", 2)

        assert fresh_state["cyclone_tiers"]["nhc:al012026"] == 3

    def test_record_cyclone_wind_observation_dedupes_by_timestamp(self, fresh_state):
        record_cyclone_wind_observation(
            fresh_state,
            "nhc:al012026",
            "2026-07-01T00:00:00Z",
            70,
        )
        record_cyclone_wind_observation(
            fresh_state,
            "nhc:al012026",
            "2026-07-01T00:00:00Z",
            75,
        )

        assert fresh_state["cyclone_wind_history"]["nhc:al012026"] == [
            {"issued_at": "2026-07-01T00:00:00Z", "wind_kt": 75}
        ]

    def test_merge_state_max_merges_cyclone_tiers_and_history(self):
        from src.state import _merge_state

        current = {
            "cyclone_tiers": {"nhc:al012026": 2},
            "cyclone_wind_history": {
                "nhc:al012026": [{"issued_at": "2026-07-01T00:00:00Z", "wind_kt": 70}]
            },
        }
        incoming = {
            "cyclone_tiers": {"nhc:al012026": 4},
            "cyclone_wind_history": {
                "nhc:al012026": [{"issued_at": "2026-07-02T00:00:00Z", "wind_kt": 115}]
            },
        }

        merged = _merge_state(current, incoming)

        assert merged["cyclone_tiers"]["nhc:al012026"] == 4
        assert merged["cyclone_wind_history"]["nhc:al012026"] == [
            {"issued_at": "2026-07-01T00:00:00Z", "wind_kt": 70},
            {"issued_at": "2026-07-02T00:00:00Z", "wind_kt": 115},
        ]

    @patch("src.state.date")
    def test_increment_cyclone_annual_count(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 7, 2)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        increment_cyclone_annual_count(fresh_state)

        assert fresh_state["cyclone_annual_count"]["2026"] == 1


class TestCopernicusFloodState:
    def test_default_state_has_flood_trackers(self):
        assert DEFAULT_STATE["flood_activation_tiers"] == {}
        assert DEFAULT_STATE["flood_annual_count"] == {}

    def test_update_flood_activation_tier_keeps_highest_severity(self, fresh_state):
        update_flood_activation_tier(fresh_state, "EMSR999", "Major")
        update_flood_activation_tier(fresh_state, "EMSR999", "Moderate")
        update_flood_activation_tier(fresh_state, "EMSR999", "Extreme")

        assert fresh_state["flood_activation_tiers"]["EMSR999"] == "Extreme"

    def test_merge_state_keeps_highest_flood_severity_and_annual_count(self):
        from src.state import _merge_state

        current = {
            "flood_activation_tiers": {"EMSR999": "Major", "EMSR998": "Extreme"},
            "flood_annual_count": {"2026": 2},
        }
        incoming = {
            "flood_activation_tiers": {"EMSR999": "Extreme", "EMSR997": "Major"},
            "flood_annual_count": {"2026": 1, "2025": 3},
        }

        merged = _merge_state(current, incoming)

        assert merged["flood_activation_tiers"] == {
            "EMSR999": "Extreme",
            "EMSR998": "Extreme",
            "EMSR997": "Major",
        }
        assert merged["flood_annual_count"] == {"2026": 2, "2025": 3}

    @patch("src.state.date")
    def test_increment_flood_annual_count(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 5, 14)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        increment_flood_annual_count(fresh_state)

        assert fresh_state["flood_annual_count"]["2026"] == 1


class TestLane08State:
    def test_default_state_has_ch4_and_coral_trackers(self):
        assert DEFAULT_STATE["ch4_annual_count"] == {}
        assert DEFAULT_STATE["ch4_last_milestone"] is None
        assert DEFAULT_STATE["coral_dhw_last_tier"] == {}
        assert DEFAULT_STATE["coral_dhw_annual_count"] == {}
        assert DEFAULT_STATE["sst_anom_last_tier"] == {}
        assert DEFAULT_STATE["sst_anom_annual_count"] == {}

    def test_update_ch4_last_milestone_takes_max(self, fresh_state):
        update_ch4_last_milestone(fresh_state, 1940)
        update_ch4_last_milestone(fresh_state, 1930)
        assert fresh_state["ch4_last_milestone"] == 1940

    def test_update_coral_dhw_tier_takes_max(self, fresh_state):
        update_coral_dhw_tier(fresh_state, "gbr_northern", 8)
        update_coral_dhw_tier(fresh_state, "gbr_northern", 4)
        assert fresh_state["coral_dhw_last_tier"]["gbr_northern"] == 8

    def test_update_sst_anom_tier_uses_reading_year_and_takes_max(self, fresh_state):
        update_sst_anom_tier(fresh_state, "north_atlantic", 2, "2025-12-31")
        update_sst_anom_tier(fresh_state, "north_atlantic", 1, "2025-12-31")
        update_sst_anom_tier(fresh_state, "north_atlantic", 1, "2026-01-02")

        assert fresh_state["sst_anom_last_tier"] == {
            "2025/north_atlantic": 2,
            "2026/north_atlantic": 1,
        }

    @patch("src.state.date")
    def test_increment_lane08_annual_counts(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 5, 14)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        increment_ch4_annual_count(fresh_state)
        increment_coral_dhw_annual_count(fresh_state)
        increment_sst_anom_annual_count(fresh_state, "2025-12-31")

        assert fresh_state["ch4_annual_count"]["2026"] == 1
        assert fresh_state["coral_dhw_annual_count"]["2026"] == 1
        assert fresh_state["sst_anom_annual_count"]["2025"] == 1

    def test_merge_state_max_merges_lane08_trackers(self):
        from src.state import _merge_state

        current = {
            "ch4_annual_count": {"2026": 2},
            "ch4_last_milestone": 1930,
            "coral_dhw_last_tier": {"gbr_northern": 4},
            "coral_dhw_annual_count": {"2026": 3},
            "sst_anom_last_tier": {"2026/north_atlantic": 1},
            "sst_anom_annual_count": {"2026": 1},
        }
        incoming = {
            "ch4_annual_count": {"2026": 1},
            "ch4_last_milestone": 1940,
            "coral_dhw_last_tier": {"gbr_northern": 8, "florida_keys": 4},
            "coral_dhw_annual_count": {"2026": 4},
            "sst_anom_last_tier": {
                "2026/north_atlantic": 3,
                "2025/mediterranean": 2,
            },
            "sst_anom_annual_count": {"2026": 0, "2025": 2},
        }

        merged = _merge_state(current, incoming)

        assert merged["ch4_annual_count"]["2026"] == 2
        assert merged["ch4_last_milestone"] == 1940
        assert merged["coral_dhw_last_tier"] == {"gbr_northern": 8, "florida_keys": 4}
        assert merged["coral_dhw_annual_count"]["2026"] == 4
        assert merged["sst_anom_last_tier"] == {
            "2026/north_atlantic": 3,
            "2025/mediterranean": 2,
        }
        assert merged["sst_anom_annual_count"] == {"2026": 1, "2025": 2}


class TestLane14State:
    def test_default_state_has_climate_index_and_ozone_trackers(self):
        assert DEFAULT_STATE["nao_annual_count"] == {}
        assert DEFAULT_STATE["ao_annual_count"] == {}
        assert DEFAULT_STATE["pdo_annual_count"] == {}
        assert DEFAULT_STATE["nao_last_phase"] is None
        assert DEFAULT_STATE["ozone_hole_last_peak"] == {}
        assert DEFAULT_STATE["ozone_hole_annual_count"] == {}

    @patch("src.state.date")
    def test_increment_lane14_annual_counts(self, mock_date, fresh_state):
        mock_date.today.return_value = date(2026, 11, 5)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        increment_oscillation_annual_count(fresh_state, "NAO")
        increment_oscillation_annual_count(fresh_state, "PDO")
        increment_ozone_hole_annual_count(fresh_state)

        assert fresh_state["nao_annual_count"]["2026"] == 1
        assert fresh_state["pdo_annual_count"]["2026"] == 1
        assert fresh_state["ozone_hole_annual_count"]["2026"] == 1

    def test_update_oscillation_last_phase(self, fresh_state):
        update_oscillation_last_phase(fresh_state, "AO", "Negative")

        assert fresh_state["ao_last_phase"] == "Negative"

    def test_record_ozone_hole_peak_payload(self, fresh_state):
        from src.data.ozone_hole import OzoneHoleSeasonalEvent

        event = OzoneHoleSeasonalEvent(
            year=2026,
            peak_date="2026-09-20",
            area_million_km2=23.0,
            previous_year=2025,
            previous_area_million_km2=20.8,
            record_year=2000,
            record_area_million_km2=29.9,
            trailing_10yr_mean_area_million_km2=21.4,
            larger_than_previous_year=True,
            event_id="ozone_hole_peak_2026",
        )

        record_ozone_hole_peak(fresh_state, event)

        assert fresh_state["ozone_hole_last_peak"]["2026"]["peak_date"] == "2026-09-20"
        assert fresh_state["ozone_hole_last_peak"]["2026"]["area_million_km2"] == 23.0

    def test_merge_state_keeps_max_counts_and_larger_ozone_peak(self):
        from src.state import _merge_state

        current = {
            "nao_annual_count": {"2026": 2},
            "ao_annual_count": {"2026": 1},
            "pdo_annual_count": {"2026": 3},
            "ozone_hole_annual_count": {"2026": 1},
            "nao_last_phase": "Positive",
            "ozone_hole_last_peak": {
                "2026": {"peak_date": "2026-09-19", "area_million_km2": 22.0}
            },
        }
        incoming = {
            "nao_annual_count": {"2026": 1, "2025": 4},
            "ao_annual_count": {"2026": 3},
            "pdo_annual_count": {"2026": 1},
            "ozone_hole_annual_count": {"2026": 2},
            "nao_last_phase": "Negative",
            "ozone_hole_last_peak": {
                "2026": {"peak_date": "2026-09-20", "area_million_km2": 23.0}
            },
        }

        merged = _merge_state(current, incoming)

        assert merged["nao_annual_count"] == {"2026": 2, "2025": 4}
        assert merged["ao_annual_count"] == {"2026": 3}
        assert merged["pdo_annual_count"] == {"2026": 3}
        assert merged["ozone_hole_annual_count"] == {"2026": 2}
        assert merged["nao_last_phase"] == "Negative"
        assert merged["ozone_hole_last_peak"]["2026"]["area_million_km2"] == 23.0


class TestDraftTrimming:
    def test_rejected_drafts_older_than_30_days_are_trimmed(self):
        from src.state import trim_drafts

        old_rejected = _draft("old_rejected", "rejected", 31)
        old_rejected["updated_at"] = _draft_timestamp(0)
        state = {
            "drafts": [
                old_rejected,
                _draft("recent_rejected", "rejected", 29),
            ]
        }

        trim_drafts(state)

        assert [draft["id"] for draft in state["drafts"]] == ["recent_rejected"]

    def test_pending_drafts_never_trimmed_regardless_of_age(self):
        from src.state import trim_drafts

        state = {
            "drafts": [
                _draft("old_pending", "pending", 365),
                _draft("old_rejected", "rejected", 31),
            ]
        }

        trim_drafts(state)

        assert [draft["id"] for draft in state["drafts"]] == ["old_pending"]

    def test_posted_drafts_never_trimmed_regardless_of_age(self):
        from src.state import trim_drafts

        state = {
            "drafts": [
                _draft("old_posted", "posted", 365),
                _draft("old_rejected", "rejected", 31),
            ]
        }

        trim_drafts(state)

        assert [draft["id"] for draft in state["drafts"]] == ["old_posted"]

    def test_200_cap_still_enforced_after_time_trim(self):
        from src.state import trim_drafts

        state = {
            "drafts": [
                *[_draft(f"old_rejected_{i}", "rejected", 31) for i in range(50)],
                *[_draft(f"recent_rejected_{i}", "rejected", 1) for i in range(225)],
            ]
        }

        trim_drafts(state)

        assert len(state["drafts"]) == 200
        assert state["drafts"][0]["id"] == "recent_rejected_25"
        assert state["drafts"][-1]["id"] == "recent_rejected_224"

    def test_all_old_rejected_drafts_keep_newest_10_as_guardrail(self):
        from src.state import trim_drafts

        state = {
            "drafts": [
                _draft(f"old_rejected_{i}", "rejected", 230 - i)
                for i in range(200)
            ]
        }

        trim_drafts(state)

        assert len(state["drafts"]) == 10
        assert [draft["id"] for draft in state["drafts"]] == [
            f"old_rejected_{i}" for i in range(190, 200)
        ]

    def test_rejected_drafts_newer_than_30_days_kept(self):
        from src.state import trim_drafts

        state = {"drafts": [_draft("recent_rejected", "rejected", 29)]}

        trim_drafts(state)

        assert [draft["id"] for draft in state["drafts"]] == ["recent_rejected"]


class TestSqliteBackend:
    def test_round_trips_state_via_sqlite_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/theheat.sqlite"
            sample = {
                **DEFAULT_STATE,
                "last_hot10": {"date": "2026-04-08", "cities": ["Phoenix", "Miami"]},
                "posted_events": ["event_1"],
                "drafts": [{"id": "draft_1", "text": "hello", "status": "pending", "type": "hot10"}],
                "run_history": [{"id": "run_1", "mode": "alerts", "status": "success", "sources": []}],
            }

            with patch.multiple(
                "src.state",
                STATE_BACKEND="sqlite",
                DB_PATH=db_path,
                GIST_ID="",
                GITHUB_TOKEN="",
            ):
                assert write_state(sample) is True
                loaded = read_state()

            assert loaded["last_hot10"]["cities"] == ["Phoenix", "Miami"]
            assert loaded["posted_events"] == ["event_1"]
            assert loaded["drafts"][0]["id"] == "draft_1"
            assert loaded["run_history"][0]["id"] == "run_1"

    def test_sst_anom_dedup_keys_survive_sqlite_round_trip(self):
        # Regression (PR #198 gap): sst_anom_last_tier + sst_anom_annual_count are
        # in DEFAULT_STATE + _merge_state but were missing from _METADATA_JSON_KEYS,
        # so a SQLite-sourced load silently dropped the per-region tier dedup and
        # per-year count — risking a duplicate basin post or a reset annual counter.
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/theheat.sqlite"
            sample = {
                **DEFAULT_STATE,
                "sst_anom_last_tier": {"2026/north_atlantic": 3, "2026/mediterranean": 2},
                "sst_anom_annual_count": {"2026": 5},
            }

            with patch.multiple(
                "src.state",
                STATE_BACKEND="sqlite",
                DB_PATH=db_path,
                GIST_ID="",
                GITHUB_TOKEN="",
            ):
                assert write_state(sample) is True
                loaded = read_state()

            assert loaded["sst_anom_last_tier"] == {"2026/north_atlantic": 3, "2026/mediterranean": 2}
            assert loaded["sst_anom_annual_count"] == {"2026": 5}

    def test_write_state_serializes_date_values_via_sqlite_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/theheat.sqlite"
            sample = {
                **DEFAULT_STATE,
                "drafts": [{
                    "id": "draft_with_date",
                    "text": "date payload",
                    "status": "pending",
                    "type": "record",
                    "review_context": {"facts": [{"label": "Observed", "value": date(2026, 5, 7)}]},
                }],
            }

            with patch.multiple(
                "src.state",
                STATE_BACKEND="sqlite",
                DB_PATH=db_path,
                GIST_ID="",
                GITHUB_TOKEN="",
            ):
                assert write_state(sample) is True
                loaded = read_state()

            assert loaded["drafts"][0]["review_context"]["facts"][0]["value"] == "2026-05-07"

    def test_write_state_preserves_newer_draft_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/theheat.sqlite"
            current = {
                **DEFAULT_STATE,
                "drafts": [{
                    "id": "draft_1",
                    "text": "edited by reviewer",
                    "status": "pending",
                    "type": "record",
                    "created_at": "2026-04-08T12:00:00Z",
                    "updated_at": "2026-04-08T12:10:00Z",
                }],
            }
            stale_bot_state = {
                **DEFAULT_STATE,
                "drafts": [
                    {
                        "id": "draft_1",
                        "text": "stale bot copy",
                        "status": "pending",
                        "type": "record",
                        "created_at": "2026-04-08T12:00:00Z",
                        "updated_at": "2026-04-08T12:05:00Z",
                    },
                    {
                        "id": "draft_2",
                        "text": "new draft",
                        "status": "pending",
                        "type": "hot10",
                        "created_at": "2026-04-08T12:15:00Z",
                        "updated_at": "2026-04-08T12:15:00Z",
                    },
                ],
            }

            with patch.multiple(
                "src.state",
                STATE_BACKEND="sqlite",
                DB_PATH=db_path,
                GIST_ID="",
                GITHUB_TOKEN="",
            ):
                assert write_state(current) is True
                assert write_state(stale_bot_state) is True
                loaded = read_state()

            drafts = {draft["id"]: draft for draft in loaded["drafts"]}
            assert drafts["draft_1"]["text"] == "edited by reviewer"
            assert drafts["draft_2"]["text"] == "new draft"

    def test_read_state_raises_when_sqlite_backend_is_unreadable(self):
        with patch.multiple(
            "src.state",
            STATE_BACKEND="sqlite",
            DB_PATH="/tmp/theheat-broken.sqlite",
            GIST_ID="",
            GITHUB_TOKEN="",
        ), patch("src.state.sqlite_store.is_empty", side_effect=RuntimeError("db unavailable")):
            try:
                read_state()
                assert False, "Expected StateReadError"
            except StateReadError as exc:
                assert "Failed to read SQLite state store" in str(exc)

    def test_read_state_raises_when_gist_backend_cannot_be_read(self):
        with patch.multiple(
            "src.state",
            STATE_BACKEND="gist",
            DB_PATH="",
            GIST_ID="gist_123",
            GITHUB_TOKEN="token_123",
        ), patch("src.state.requests.get", side_effect=requests.RequestException("gist unavailable")):
            try:
                read_state()
                assert False, "Expected StateReadError"
            except StateReadError as exc:
                assert "Failed to read gist state" in str(exc)

    def test_read_state_handles_truncated_gist_via_raw_url(self):
        """The GitHub Gist REST API truncates the `content` field at ~900 KB.
        When the state file grows past that threshold, the API returns
        ``truncated: True`` alongside a ``raw_url`` pointing at the full
        content. The bot must follow the raw_url instead of trying to parse
        the truncated content, or every scheduled run fails with
        "state.json is not valid JSON" until the state shrinks back below
        the threshold. Observed in production 2026-05-13: three alerts
        runs failed (11:03, 13:34, 14:47 UTC) when state hit 928 KB.
        """
        import json as _json
        from unittest.mock import MagicMock

        full_state_dict = {
            "drafts": [],
            "memory": {"shipped_tweets": []},
            "ledger": {},
        }
        full_state_json = _json.dumps(full_state_dict)
        truncated_content = full_state_json[: len(full_state_json) // 2]
        raw_url = "https://gist.githubusercontent.com/raw/abc/def/state.json"

        api_response = MagicMock()
        api_response.raise_for_status = MagicMock()
        api_response.json.return_value = {
            "files": {
                "state.json": {
                    "content": truncated_content,
                    "truncated": True,
                    "raw_url": raw_url,
                }
            }
        }

        raw_response = MagicMock()
        raw_response.raise_for_status = MagicMock()
        raw_response.text = full_state_json

        def fake_get(url, headers=None, timeout=None):
            if url == raw_url:
                return raw_response
            return api_response

        with patch.multiple(
            "src.state",
            STATE_BACKEND="gist",
            DB_PATH="",
            GIST_ID="gist_123",
            GITHUB_TOKEN="token_123",
        ), patch("src.state.requests.get", side_effect=fake_get):
            state = read_state()

        # If the bug were still present, json.loads(truncated_content) would
        # raise and read_state would error. We get here only if the raw_url
        # path was followed.
        assert isinstance(state, dict)
        assert "drafts" in state


class TestIceMassDefaultState:
    def test_ice_mass_keys_in_default_state(self):
        from src.state import _fresh_state
        s = _fresh_state()
        assert s["ice_mass_max_loss"] == {}
        assert s["ice_mass_last_milestone"] == {}
        assert s["ice_mass_last_seen"] == {}
        assert s["ice_annual_count"] == {}


class TestIceMassMerge:
    def test_max_loss_keeps_most_negative_per_region(self):
        from src.state import _merge_state
        base = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -400.0, "month": "2024-08"},
                "antarctica": {"gt": -200.0, "month": "2020-01"},
            }
        }
        incoming = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -350.0, "month": "2025-08"},  # weaker
                "antarctica": {"gt": -250.0, "month": "2026-01"}, # stronger
            }
        }
        merged = _merge_state(base, incoming)
        assert merged["ice_mass_max_loss"]["greenland"] == {"gt": -400.0, "month": "2024-08"}
        assert merged["ice_mass_max_loss"]["antarctica"] == {"gt": -250.0, "month": "2026-01"}

    def test_last_milestone_keeps_most_negative_per_region(self):
        from src.state import _merge_state
        base = {"ice_mass_last_milestone": {"greenland": -5000.0, "antarctica": -2000.0}}
        incoming = {"ice_mass_last_milestone": {"greenland": -6000.0, "antarctica": -1000.0}}
        merged = _merge_state(base, incoming)
        assert merged["ice_mass_last_milestone"]["greenland"] == -6000.0
        assert merged["ice_mass_last_milestone"]["antarctica"] == -2000.0

    def test_last_seen_takes_lexicographic_max_per_region(self):
        from src.state import _merge_state
        base = {"ice_mass_last_seen": {"greenland": "2026-02", "antarctica": "2026-04"}}
        incoming = {"ice_mass_last_seen": {"greenland": "2026-03", "antarctica": "2026-01"}}
        merged = _merge_state(base, incoming)
        assert merged["ice_mass_last_seen"]["greenland"] == "2026-03"
        assert merged["ice_mass_last_seen"]["antarctica"] == "2026-04"

    def test_ice_annual_count_takes_max_per_year(self):
        from src.state import _merge_state
        base = {"ice_annual_count": {"2026": 3, "2025": 7}}
        incoming = {"ice_annual_count": {"2026": 5, "2024": 2}}
        merged = _merge_state(base, incoming)
        assert merged["ice_annual_count"]["2026"] == 5
        assert merged["ice_annual_count"]["2025"] == 7
        assert merged["ice_annual_count"]["2024"] == 2


class TestFireComplexTiers:
    def test_default_state_has_fire_complex_tiers(self):
        from src.state import DEFAULT_STATE
        assert "fire_complex_tiers" in DEFAULT_STATE
        assert DEFAULT_STATE["fire_complex_tiers"] == {}

    def test_update_fire_complex_tier_sets_new(self):
        from src.state import update_fire_complex_tier
        s = {"fire_complex_tiers": {}}
        update_fire_complex_tier(s, "A", 2)
        assert s["fire_complex_tiers"]["A"] == 2

    def test_update_fire_complex_tier_takes_max(self):
        from src.state import update_fire_complex_tier
        s = {"fire_complex_tiers": {"A": 3}}
        update_fire_complex_tier(s, "A", 2)  # lower value ignored
        assert s["fire_complex_tiers"]["A"] == 3
        update_fire_complex_tier(s, "A", 4)
        assert s["fire_complex_tiers"]["A"] == 4

    def test_update_fire_complex_tier_initializes_dict(self):
        from src.state import update_fire_complex_tier
        s = {}  # no key at all
        update_fire_complex_tier(s, "A", 1)
        assert s["fire_complex_tiers"]["A"] == 1

    def test_merge_takes_max_tier(self):
        from src.state import _merge_state
        base = {"fire_complex_tiers": {"A": 2, "B": 1}}
        incoming = {"fire_complex_tiers": {"A": 1, "B": 3, "C": 0}}
        merged = _merge_state(base, incoming)
        assert merged["fire_complex_tiers"] == {"A": 2, "B": 3, "C": 0}


class TestTwoBotMemoryState:
    def test_default_state_has_memory_schema(self):
        from src.state import DEFAULT_STATE

        assert DEFAULT_STATE["memory"] == {
            "ongoing_events": [],
            "used_era_anchors": [],
            "used_peer_comparisons": [],
            "used_framings": [],
            "shipped_tweets": [],
        }

    def test_get_memory_backfills_missing_schema(self):
        from src.state import get_memory

        state = {}
        memory = get_memory(state)

        assert "memory" in state
        assert memory["used_era_anchors"] == []
        assert memory["shipped_tweets"] == []

    def test_merge_preserves_memory_lists(self):
        from src.state import _merge_state

        base = {"memory": {"used_era_anchors": ["spider-man 2002"]}}
        incoming = {
            "memory": {
                "used_era_anchors": ["adele 21"],
                "used_peer_comparisons": ["hoover dam"],
            }
        }
        merged = _merge_state(base, incoming)

        assert merged["memory"]["used_era_anchors"] == ["spider-man 2002", "adele 21"]
        assert merged["memory"]["used_peer_comparisons"] == ["hoover dam"]


class TestFireFootprintLastRunMerge:
    def test_merge_takes_later_date_incoming_newer(self):
        from src.state import _merge_state
        base = {"fire_footprint_last_run": "2026-04-20"}
        incoming = {"fire_footprint_last_run": "2026-04-21"}
        merged = _merge_state(base, incoming)
        assert merged["fire_footprint_last_run"] == "2026-04-21"

    def test_merge_takes_later_date_base_newer(self):
        from src.state import _merge_state
        base = {"fire_footprint_last_run": "2026-04-21"}
        incoming = {"fire_footprint_last_run": "2026-04-20"}
        merged = _merge_state(base, incoming)
        assert merged["fire_footprint_last_run"] == "2026-04-21"

    def test_merge_all_none_produces_none(self):
        from src.state import _merge_state
        base = {"fire_footprint_last_run": None}
        incoming = {"fire_footprint_last_run": None}
        merged = _merge_state(base, incoming)
        assert merged["fire_footprint_last_run"] is None


class TestSqliteRoundTripLaneKeys:
    """Regression: sqlite_store used to persist only the legacy subset
    (last_hot10, posted_events, daily_tweet_count, streaks, drafts,
    run_history, errors). Lane-added keys (ocean/ice/fire/synthesis
    + city_monthly_* + co2/ice_annual_count + record_streaks) read back
    as defaults on any sqlite-backed deployment. That broke daily gates,
    weekly short-circuits, annual caps, and marine-heatwave continuity.
    """

    def _sqlite_round_trip(self, state_in: dict) -> dict:
        from src.storage import sqlite_store
        from src.state import DEFAULT_STATE
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "theheat.sqlite")
            assert sqlite_store.write_state(db_path, state_in)
            return sqlite_store.read_state(db_path, DEFAULT_STATE)

    def test_round_trip_preserves_ocean_sst_streak(self):
        state_in = {
            "ocean_sst_streak": {"seeded": True, "last_milestone_fired": 100},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["ocean_sst_streak"] == {"seeded": True, "last_milestone_fired": 100}

    def test_round_trip_preserves_ice_mass_state(self):
        state_in = {
            "ice_mass_max_loss": {"greenland": {"gt": -500.0, "month": "2026-03"}},
            "ice_mass_last_milestone": {"greenland": -6000.0},
            "ice_mass_last_seen": {"greenland": "2026-03"},
            "ice_annual_count": {"2026": 3},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["ice_mass_max_loss"]["greenland"]["gt"] == -500.0
        assert out["ice_mass_last_milestone"]["greenland"] == -6000.0
        assert out["ice_mass_last_seen"]["greenland"] == "2026-03"
        assert out["ice_annual_count"]["2026"] == 3

    def test_round_trip_preserves_fire_footprint_state(self):
        state_in = {
            "fire_complex_tiers": {"GWIS_AAA": 3, "NIFC_BBB": 1},
            "fire_footprint_last_run": "2026-04-21",
        }
        out = self._sqlite_round_trip(state_in)
        assert out["fire_complex_tiers"] == {"GWIS_AAA": 3, "NIFC_BBB": 1}
        assert out["fire_footprint_last_run"] == "2026-04-21"

    def test_round_trip_preserves_synthesis_state(self):
        state_in = {
            "synthesis_components": {
                "fires": {"California": [{"event_id": "f1", "frp": 1500.0, "at": "2026-04-20T10:00:00Z"}]},
                "heats": {"California": [{"event_id": "h1", "anomaly_c": 8.0, "at": "2026-04-20T11:00:00Z"}]},
                "drought_snapshot": {"updated_at": "2026-04-19T12:00:00Z", "entries": []},
            },
            "synthesis_cooldown": {
                "synthesis_fire_drought_heat": {"California": "2026-04-20T12:00:00Z"},
            },
        }
        out = self._sqlite_round_trip(state_in)
        assert out["synthesis_components"]["fires"]["California"][0]["event_id"] == "f1"
        assert out["synthesis_components"]["heats"]["California"][0]["anomaly_c"] == 8.0
        assert out["synthesis_components"]["drought_snapshot"]["updated_at"] == "2026-04-19T12:00:00Z"
        assert out["synthesis_cooldown"]["synthesis_fire_drought_heat"]["California"] == "2026-04-20T12:00:00Z"

    def test_round_trip_preserves_co2_annual_count(self):
        state_in = {"co2_annual_count": {"2026": 5, "2025": 11}}
        out = self._sqlite_round_trip(state_in)
        assert out["co2_annual_count"] == {"2026": 5, "2025": 11}

    def test_round_trip_preserves_lane08_state(self):
        state_in = {
            "ch4_annual_count": {"2026": 2},
            "ch4_last_milestone": 1940,
            "coral_dhw_last_tier": {"gbr_northern": 8},
            "coral_dhw_annual_count": {"2026": 4},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["ch4_annual_count"] == {"2026": 2}
        assert out["ch4_last_milestone"] == 1940
        assert out["coral_dhw_last_tier"] == {"gbr_northern": 8}
        assert out["coral_dhw_annual_count"] == {"2026": 4}

    def test_round_trip_preserves_flood_state(self):
        state_in = {
            "flood_activation_tiers": {"EMSR999": "Major"},
            "flood_annual_count": {"2026": 2},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["flood_activation_tiers"] == {"EMSR999": "Major"}
        assert out["flood_annual_count"] == {"2026": 2}

    def test_round_trip_preserves_cyclone_state(self):
        state_in = {
            "cyclone_tiers": {"nhc:al012026": 3},
            "cyclone_wind_history": {
                "nhc:al012026": [
                    {"issued_at": "2026-05-14T00:00:00Z", "wind_kt": 80},
                ],
            },
            "cyclone_annual_count": {"2026": 1},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["cyclone_tiers"] == {"nhc:al012026": 3}
        assert out["cyclone_wind_history"]["nhc:al012026"][0]["wind_kt"] == 80
        assert out["cyclone_annual_count"] == {"2026": 1}

    def test_round_trip_preserves_lane14_state(self):
        state_in = {
            "nao_annual_count": {"2026": 2},
            "ao_annual_count": {"2026": 3},
            "pdo_annual_count": {"2026": 1},
            "nao_last_phase": "Negative",
            "ao_last_phase": "Negative",
            "pdo_last_phase": "Positive",
            "ozone_hole_last_peak": {
                "2026": {"peak_date": "2026-09-20", "area_million_km2": 23.0}
            },
            "ozone_hole_annual_count": {"2026": 1},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["nao_annual_count"] == {"2026": 2}
        assert out["ao_annual_count"] == {"2026": 3}
        assert out["pdo_last_phase"] == "Positive"
        assert out["ozone_hole_last_peak"]["2026"]["area_million_km2"] == 23.0
        assert out["ozone_hole_annual_count"] == {"2026": 1}

    def test_round_trip_preserves_city_extreme_trackers(self):
        state_in = {
            "city_all_time_max": {"Phoenix": {"temp_c": 48.2, "year": 2018}},
            "record_streaks": {"Phoenix": {"days": 4, "last_date": "2026-04-20"}},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["city_all_time_max"]["Phoenix"]["temp_c"] == 48.2
        assert out["record_streaks"]["Phoenix"]["days"] == 4


class TestSuppressions:
    """Schema + merge for the suppression ledger added 2026-05-06."""

    def test_default_state_has_suppressions(self):
        from src.state import _fresh_state
        s = _fresh_state()
        assert s["suppressions"] == []

    def test_merge_dedupes_by_id_latest_ts_wins(self):
        from src.state import _merge_state
        base = {
            "suppressions": [
                {"id": "supp_a", "ts": "2026-05-06T10:00:00Z", "summary": "old"},
                {"id": "supp_b", "ts": "2026-05-06T11:00:00Z", "summary": "kept"},
            ]
        }
        incoming = {
            "suppressions": [
                {"id": "supp_a", "ts": "2026-05-06T12:00:00Z", "summary": "new"},
            ]
        }
        merged = _merge_state(base, incoming)
        ids = {s["id"]: s for s in merged["suppressions"]}
        assert ids["supp_a"]["summary"] == "new"
        assert ids["supp_a"]["ts"] == "2026-05-06T12:00:00Z"
        assert ids["supp_b"]["summary"] == "kept"

    def test_merge_caps_at_200(self):
        from src.state import _merge_suppressions
        many = [
            {"id": f"supp_{i}", "ts": f"2026-05-06T{i:02d}:00:00Z"}
            for i in range(0, 24)
        ]
        # Pad to 250 by varying minute
        many += [
            {"id": f"supp_pad_{i}", "ts": f"2026-05-07T00:{i:02d}:00Z"}
            for i in range(0, 250)
        ]
        merged = _merge_suppressions([], many)
        assert len(merged) == 200

    def test_merge_sorts_by_ts(self):
        from src.state import _merge_suppressions
        merged = _merge_suppressions(
            [],
            [
                {"id": "c", "ts": "2026-05-06T03:00:00Z"},
                {"id": "a", "ts": "2026-05-06T01:00:00Z"},
                {"id": "b", "ts": "2026-05-06T02:00:00Z"},
            ],
        )
        assert [s["id"] for s in merged] == ["a", "b", "c"]

    def test_round_trip_preserves_suppressions(self):
        from src.storage import sqlite_store
        from src.state import DEFAULT_STATE
        import tempfile
        import os
        state_in = {
            "suppressions": [
                {
                    "id": "supp_2026-05-06T10:00:00Z_abcd",
                    "ts": "2026-05-06T10:00:00Z",
                    "run_id": "run_abc",
                    "source": "alerts",
                    "event_id": "open_meteo_records_2026-05-06_navimumbai",
                    "category": "record_high",
                    "score_total": 64,
                    "threshold": 72,
                    "reasons": ["margin_small", "old_record_recent"],
                    "summary": "Navi Mumbai forecast 102.4F",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "theheat.sqlite")
            assert sqlite_store.write_state(db_path, state_in)
            out = sqlite_store.read_state(db_path, DEFAULT_STATE)
        assert out["suppressions"][0]["score_total"] == 64
        assert out["suppressions"][0]["threshold"] == 72
        assert out["suppressions"][0]["reasons"] == ["margin_small", "old_record_recent"]
        assert out["suppressions"][0]["summary"] == "Navi Mumbai forecast 102.4F"


class TestShouldDraftSuppressionCapture:
    """The _should_draft() context-driven capture wired into main.py."""

    def teardown_method(self, method):
        from src.main import _clear_suppression_ctx
        _clear_suppression_ctx()

    def _make_score(self, *, total, threshold, category="record_high", reasons=("margin_small",)):
        from src.editorial.scoring import EditorialScore
        return EditorialScore(
            category=category,
            severity=0,
            novelty=0,
            timeliness=0,
            confidence=0,
            shareability=0,
            sensitivity=0,
            total=total,
            threshold=threshold,
            reasons=list(reasons),
        )

    def test_passes_score_returns_true_no_capture(self):
        from src.main import _should_draft, _activate_suppression_ctx
        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts")
        score = self._make_score(total=80, threshold=72)
        assert _should_draft(score, "ev_1") is True
        assert bot_state.get("suppressions", []) == []

    def test_below_threshold_within_near_miss_captured(self, monkeypatch):
        from src.main import _should_draft, _activate_suppression_ctx
        monkeypatch.setenv("SUPPRESSION_NEAR_MISS_GAP", "15")
        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts", run_id="run_1")
        score = self._make_score(total=64, threshold=72)
        assert _should_draft(score, "open_meteo_records_2026-05-06_navimumbai") is False
        suppressions = bot_state["suppressions"]
        assert len(suppressions) == 1
        rec = suppressions[0]
        assert rec["source"] == "alerts"
        assert rec["run_id"] == "run_1"
        assert rec["event_id"] == "open_meteo_records_2026-05-06_navimumbai"
        assert rec["score_total"] == 64
        assert rec["threshold"] == 72
        assert rec["category"] == "record_high"
        assert rec["reasons"] == ["margin_small"]
        assert rec["id"].startswith("supp_")
        assert rec["ts"]

    def test_below_threshold_outside_near_miss_not_captured(self, monkeypatch):
        from src.main import _should_draft, _activate_suppression_ctx
        monkeypatch.setenv("SUPPRESSION_NEAR_MISS_GAP", "5")
        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts")
        score = self._make_score(total=40, threshold=72)
        assert _should_draft(score, "ev_far") is False
        assert bot_state.get("suppressions", []) == []

    def test_no_active_context_no_capture(self):
        from src.main import _should_draft, _clear_suppression_ctx
        _clear_suppression_ctx()
        bot_state = {}
        score = self._make_score(total=64, threshold=72)
        assert _should_draft(score, "ev_x") is False
        assert bot_state.get("suppressions", []) == []

    def test_capture_caps_at_200(self, monkeypatch):
        from src.main import _should_draft, _activate_suppression_ctx
        monkeypatch.setenv("SUPPRESSION_NEAR_MISS_GAP", "100")
        bot_state = {"suppressions": [{"id": f"old_{i}", "ts": "2026-05-01T00:00:00Z"} for i in range(190)]}
        _activate_suppression_ctx(bot_state, source="alerts")
        for i in range(15):
            _should_draft(self._make_score(total=60, threshold=72), f"ev_{i}")
        assert len(bot_state["suppressions"]) == 200

    def test_score_gate_record_has_stage_field(self, monkeypatch):
        from src.main import _should_draft, _activate_suppression_ctx
        monkeypatch.setenv("SUPPRESSION_NEAR_MISS_GAP", "15")
        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts")
        _should_draft(self._make_score(total=64, threshold=72), "ev_x")
        assert bot_state["suppressions"][0]["stage"] == "score_gate"


class TestDownstreamSuppressionCapture:
    """Suppression records for kills *after* the editorial score gate —
    writer kills, fact-check rejections, pipeline exceptions. These are
    the kills that swallowed today's GHCN bundles (signal_date date
    object → JSON serialization error → silent pipeline_error)."""

    def teardown_method(self, method):
        from src.main import _clear_suppression_ctx
        _clear_suppression_ctx()

    def _make_score(self, *, total=80, threshold=76, category="monthly_record"):
        from src.editorial.scoring import EditorialScore
        return EditorialScore(
            category=category,
            severity=0, novelty=0, timeliness=0, confidence=0,
            shareability=0, sensitivity=0,
            total=total, threshold=threshold, reasons=[],
        )

    def _bundle_stub(self, where="SISSONVILLE 1SW, United States"):
        class _Stub:
            pass
        b = _Stub()
        b.where = where
        b.signal_kind = "monthly_low"
        b.event_id = "monthly_low_USC00468191_05_2026-05-04"
        return b

    def test_pipeline_error_recorded_with_stage_and_reason(self, monkeypatch):
        from src.main import _try_two_bot_draft, _activate_suppression_ctx
        from src.two_bot import pipeline as pipeline_mod

        # Force a pipeline exception (mimics today's date-serialization bug).
        def boom(bundle, state, *, result_out=None):
            if result_out is not None:
                result_out["kill_stage"] = "pipeline_error"
                result_out["kill_reason"] = "TypeError: Object of type date is not JSON serializable"
            return None
        monkeypatch.setattr(pipeline_mod, "generate_draft", boom)

        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts", run_id="run_xyz")
        score = self._make_score(total=80, threshold=76)
        result = _try_two_bot_draft(
            self._bundle_stub(), bot_state, score,
            legacy_type="monthly_low",
            event_id="monthly_low_USC00468191_05_2026-05-04",
            review_context={},
        )
        assert result is False
        supps = bot_state["suppressions"]
        assert len(supps) == 1
        rec = supps[0]
        assert rec["stage"] == "pipeline_error"
        assert rec["score_total"] == 80
        assert rec["threshold"] == 76
        assert rec["category"] == "monthly_record"
        assert "JSON serializable" in rec["reasons"][0]
        assert rec["summary"] == "SISSONVILLE 1SW, United States"
        assert rec["run_id"] == "run_xyz"

    def test_writer_kill_recorded_with_writer_stage(self, monkeypatch):
        from src.main import _try_two_bot_draft, _activate_suppression_ctx
        from src.two_bot import pipeline as pipeline_mod

        def writer_kill(bundle, state, *, result_out=None):
            if result_out is not None:
                result_out["kill_stage"] = "writer"
                result_out["kill_reason"] = "no historical_context available"
            return None
        monkeypatch.setattr(pipeline_mod, "generate_draft", writer_kill)

        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts")
        score = self._make_score()
        _try_two_bot_draft(
            self._bundle_stub(), bot_state, score,
            legacy_type="monthly_low", event_id="ev_1",
            review_context={},
        )
        rec = bot_state["suppressions"][0]
        assert rec["stage"] == "writer"
        assert rec["reasons"] == ["no historical_context available"]

    def test_fact_check_rejection_recorded(self, monkeypatch):
        from src.main import _try_two_bot_draft, _activate_suppression_ctx
        from src.two_bot import pipeline as pipeline_mod

        def fc_reject(bundle, state, *, result_out=None):
            if result_out is not None:
                result_out["kill_stage"] = "fact_check"
                result_out["kill_reason"] = "tweet_says_record_year_does_not_match_bundle"
            return None
        monkeypatch.setattr(pipeline_mod, "generate_draft", fc_reject)

        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts")
        _try_two_bot_draft(
            self._bundle_stub(), bot_state, self._make_score(),
            legacy_type="monthly_low", event_id="ev_2",
            review_context={},
        )
        rec = bot_state["suppressions"][0]
        assert rec["stage"] == "fact_check"

    def test_success_does_not_record_suppression(self, monkeypatch):
        from src.main import _try_two_bot_draft, _activate_suppression_ctx
        from src.two_bot import pipeline as pipeline_mod

        def success(bundle, state, *, result_out=None):
            return {
                "type": "monthly_low",
                "text": "Sissonville hit -2.2C overnight",
                "event_id": "ev_3",
                "two_bot_metadata": {},
            }
        monkeypatch.setattr(pipeline_mod, "generate_draft", success)

        bot_state = {}
        _activate_suppression_ctx(bot_state, source="alerts")
        _try_two_bot_draft(
            self._bundle_stub(), bot_state, self._make_score(),
            legacy_type="monthly_low", event_id="ev_3",
            review_context={},
        )
        assert bot_state.get("suppressions", []) == []

    def test_city_cooldown_records_suppression(self):
        from src.editorial.scoring import EditorialScore
        from src.main import _activate_suppression_ctx, _utc_now_iso, save_draft

        bot_state = {
            "drafts": [
                {
                    "event_id": "old_ev",
                    "city": "Phoenix",
                    "tweet_date": "2026-05-06",
                    "status": "posted",
                    "posted_at": _utc_now_iso(),
                }
            ]
        }
        _activate_suppression_ctx(bot_state, source="alerts", run_id="run_1")
        score = EditorialScore(
            category="record_event",
            severity=80,
            novelty=80,
            timeliness=80,
            confidence=80,
            shareability=80,
            sensitivity=20,
            total=82,
            threshold=70,
            reasons=["calendar record"],
        )

        saved = save_draft(
            "Phoenix is challenging another record.",
            bot_state,
            "record",
            event_id="new_ev",
            score=score,
            city="Phoenix",
            tweet_date="2026-05-07",
        )

        assert saved is False
        rec = bot_state["suppressions"][0]
        assert rec["stage"] == "city_cooldown"
        assert rec["event_id"] == "new_ev"
        assert rec["score_total"] == 82
        assert rec["run_id"] == "run_1"

    def test_cycle_cap_prune_records_suppression(self):
        from src.main import _activate_suppression_ctx, _prune_weakest_cycle_drafts

        bot_state = {
            "drafts": [
                {
                    "event_id": f"ev_{score}",
                    "type": "record",
                    "text": f"Draft {score}",
                    "status": "pending",
                    "score": {
                        "category": "record_event",
                        "total": score,
                        "threshold": 70,
                        "reasons": ["passed"],
                    },
                }
                for score in (100, 95, 90, 75)
            ],
            "posted_events": ["ev_100", "ev_95", "ev_90", "ev_75"],
        }
        _activate_suppression_ctx(bot_state, source="alerts", run_id="run_2")

        drafted = _prune_weakest_cycle_drafts(
            bot_state,
            drafts_before=0,
            current_run={"sources": []},
            drafted=4,
        )

        assert drafted == 3
        assert [d["event_id"] for d in bot_state["drafts"]] == [
            "ev_100",
            "ev_95",
            "ev_90",
        ]
        assert "ev_75" not in bot_state["posted_events"]
        rec = bot_state["suppressions"][0]
        assert rec["stage"] == "cycle_cap"
        assert rec["event_id"] == "ev_75"
        assert rec["score_total"] == 75

    def test_no_active_context_no_capture_on_kill(self, monkeypatch):
        from src.main import _try_two_bot_draft, _clear_suppression_ctx
        from src.two_bot import pipeline as pipeline_mod
        _clear_suppression_ctx()

        def boom(bundle, state, *, result_out=None):
            return None
        monkeypatch.setattr(pipeline_mod, "generate_draft", boom)

        bot_state = {}
        _try_two_bot_draft(
            self._bundle_stub(), bot_state, self._make_score(),
            legacy_type="monthly_low", event_id="ev_4",
            review_context={},
        )
        assert bot_state.get("suppressions", []) == []


class TestSqliteRoundTripPreservesPythonOnlyKeys:
    """Regression: sqlite_store dropped 'memory' and 'data_source_failures'
    on every round-trip — the two-bot repetition guard and the structural
    source-failure history were lost on any sqlite-backed bot run. Found
    2026-05-08 via codex review of PRs #38-#45."""

    def _sqlite_round_trip(self, state_in: dict) -> dict:
        from src.storage import sqlite_store
        from src.state import DEFAULT_STATE
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "theheat.sqlite")
            assert sqlite_store.write_state(db_path, state_in)
            return sqlite_store.read_state(db_path, DEFAULT_STATE)

    def test_round_trip_preserves_memory(self):
        state_in = {
            "memory": {
                "ongoing_events": [{"event_id": "ev1", "first_seen": "2026-05-08"}],
                "used_era_anchors": ["1989 Berlin Wall fell"],
                "used_peer_comparisons": ["1.4x average gas plant"],
                "used_framings": ["off_season_irony"],
                "shipped_tweet_texts": ["Sissonville hit -2.2C overnight..."],
            }
        }
        out = self._sqlite_round_trip(state_in)
        # Without preservation, memory was lost: shipped_tweet_texts / etc
        # came back empty, breaking the bot's reuse guard.
        assert out["memory"]["shipped_tweet_texts"] == ["Sissonville hit -2.2C overnight..."]
        assert out["memory"]["used_era_anchors"] == ["1989 Berlin Wall fell"]
        assert out["memory"]["used_peer_comparisons"] == ["1.4x average gas plant"]
        assert out["memory"]["used_framings"] == ["off_season_irony"]
        assert out["memory"]["ongoing_events"][0]["event_id"] == "ev1"

    def test_round_trip_preserves_data_source_failures(self):
        state_in = {
            "data_source_failures": {
                "ghcn": 2,
                "firms": 5,
                "ocean_sst": 1,
            }
        }
        out = self._sqlite_round_trip(state_in)
        # Without preservation, the consecutive-failure counters reset
        # every run — never tripping the 3-in-a-row STRUCTURAL ALERT.
        assert out["data_source_failures"]["ghcn"] == 2
        assert out["data_source_failures"]["firms"] == 5
        assert out["data_source_failures"]["ocean_sst"] == 1


class TestBotStateSchemaRoundTrip:
    """Wire-format guarantee for the BotState TypedDict.

    TypedDict is erased at runtime, so JSON serialization is unchanged
    by the schema. But we want a regression test that catches any drift
    between DEFAULT_STATE and the BotState declaration — if someone
    adds a key to DEFAULT_STATE but forgets the schema, this test fails.
    """

    def test_default_state_keys_match_botstate_annotations(self):
        from src.state import DEFAULT_STATE
        from src.state_schema import BotState

        assert set(DEFAULT_STATE.keys()) == set(BotState.__annotations__.keys()), (
            "DEFAULT_STATE and BotState are out of sync — update src/state_schema.py "
            "whenever you add a top-level key to DEFAULT_STATE in src/state.py"
        )

    def test_json_round_trip_preserves_schema_shape(self):
        """Serialize DEFAULT_STATE, deserialize, normalize, and merge —
        verify no key is lost across the round-trip the durable backend
        uses (json.dumps with json_default → json.loads → _normalize_state)."""
        import json
        from src.state import DEFAULT_STATE, _fresh_state, _merge_state, _normalize_state
        from src.two_bot.json_utils import json_default

        # Round 1: DEFAULT_STATE → JSON bytes → dict → BotState
        serialized = json.dumps(DEFAULT_STATE, default=json_default)
        parsed = json.loads(serialized)
        normalized = _normalize_state(parsed)
        assert set(normalized.keys()) == set(DEFAULT_STATE.keys())

        # Round 2: merge empty + parsed (simulates concurrent-writer reconciliation)
        merged = _merge_state(_fresh_state(), normalized)
        assert set(merged.keys()) == set(DEFAULT_STATE.keys())

    def test_normalize_state_backfills_partial_payload(self):
        """Older gist payloads predating recent lane additions must still
        normalize cleanly. Strip a recent key and confirm _normalize_state
        backfills the default — guards against total=True regression."""
        from src.state import DEFAULT_STATE, _normalize_state

        partial = {k: v for k, v in DEFAULT_STATE.items() if k != "ice_annual_count"}
        normalized = _normalize_state(partial)
        assert normalized["ice_annual_count"] == {}
        assert set(normalized.keys()) == set(DEFAULT_STATE.keys())

    def test_precip_and_snow_state_keys_round_trip_through_merge(self):
        from src.state import _merge_state

        base = {
            "precip_daily_records": {"france:paris:05-14": {"mm": 40.0, "year": 2025}},
            "precip_recent_by_city": {
                "france:paris": [{"date": "2026-05-13", "mm": 30.0}],
            },
            "snow_daily_swe_gain_records": {"albro_lake:05-14": {"mm": 20.0, "year": 2025}},
            "snow_recent_by_station": {
                "albro_lake": [{"date": "2026-05-13", "mm": 12.0}],
            },
            "snow_annual_count": {"2026": 2},
            "seasonal_snow_records": {"albro_lake": {"mm": 300.0, "year": 2025}},
        }
        incoming = {
            "precip_daily_records": {"france:paris:05-14": {"mm": 55.0, "year": 2026}},
            "precip_recent_by_city": {
                "france:paris": [{"date": "2026-05-14", "mm": 55.0}],
            },
            "snow_daily_swe_gain_records": {"albro_lake:05-14": {"mm": 50.8, "year": 2026}},
            "snow_recent_by_station": {
                "albro_lake": [{"date": "2026-05-14", "mm": 50.8}],
            },
            "snow_annual_count": {"2026": 3},
            "seasonal_snow_records": {"albro_lake": {"mm": 350.0, "year": 2026}},
        }

        merged = _merge_state(base, incoming)

        assert merged["precip_daily_records"]["france:paris:05-14"]["mm"] == 55.0
        assert len(merged["precip_recent_by_city"]["france:paris"]) == 2
        assert merged["snow_daily_swe_gain_records"]["albro_lake:05-14"]["mm"] == 50.8
        assert len(merged["snow_recent_by_station"]["albro_lake"]) == 2
        assert merged["snow_annual_count"]["2026"] == 3
        assert merged["seasonal_snow_records"]["albro_lake"]["mm"] == 350.0

    def test_merge_state_handles_mixed_naive_and_utc_timestamps(self):
        from src.state import _merge_state

        base = {
            "suppressions": [{
                "id": "supp_1",
                "ts": "2026-05-14T10:00:00Z",
                "stage": "writer",
            }],
        }
        incoming = {
            "suppressions": [{
                "id": "supp_1",
                "ts": "2026-05-14T10:05:00",
                "stage": "fact_check",
            }],
        }

        merged = _merge_state(base, incoming)

        assert merged["suppressions"][0]["stage"] == "fact_check"


class TestSqliteRoundTripDropsTriageQueue:
    """Guard: _triage_queue must NOT be persisted to SQLite.

    The queue is a per-cron transient. If it survived a round-trip,
    a crashed cron's queue would re-process next cycle.
    """

    def _sqlite_round_trip(self, state_in: dict) -> dict:
        from src.storage import sqlite_store
        from src.state import DEFAULT_STATE
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "theheat.sqlite")
            assert sqlite_store.write_state(db_path, state_in)
            return sqlite_store.read_state(db_path, DEFAULT_STATE)

    def test_sqlite_round_trip_drops_triage_queue(self):
        """_triage_queue should NOT be present after a sqlite write + read cycle."""
        from src.two_bot.types import TriageCandidateBundle, StoryBundle
        from src.editorial.scoring._shared import EditorialScore

        bundle = StoryBundle(
            signal_kind="coral_bleaching",
            where="Test",
            when="2026-05-17",
            event_id="test_evt",
            headline_metric={"label": "DHW", "value": 8},
            current_facts=[],
        )
        score = EditorialScore(
            category="coral_bleaching",
            severity=80, novelty=80, timeliness=80,
            confidence=80, shareability=80, sensitivity=0,
            total=80, threshold=60, reasons=[],
        )
        candidate = TriageCandidateBundle(
            bundle=bundle,
            score=score,
            event_id="test_evt",
            source="coral_dhw",
            review_context={},
            city="",
            tweet_date="2026-05-17",
            cooldown_exempt=False,
            legacy_type="coral_bleaching",
            created_at="2026-05-17T12:00:00Z",
        )

        state_in = {"_triage_queue": [candidate]}
        out = self._sqlite_round_trip(state_in)

        # The triage queue must NOT survive the round-trip
        assert "_triage_queue" not in out, (
            "_triage_queue survived sqlite round-trip — add it to the skip-list "
            "in src/storage/sqlite_store.py::_METADATA_JSON_KEYS (or equivalent)"
        )
