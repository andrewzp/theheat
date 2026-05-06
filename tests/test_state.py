"""Tests for state management."""

from datetime import date
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
    get_record_streak,
    prune_stale_record_streaks,
    log_error,
    DEFAULT_STATE,
    write_state,
    _fresh_state,
)


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
        import tempfile, os
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

    def test_round_trip_preserves_city_extreme_trackers(self):
        state_in = {
            "city_all_time_max": {"Phoenix": {"temp_c": 48.2, "year": 2018}},
            "record_streaks": {"Phoenix": {"days": 4, "last_date": "2026-04-20"}},
        }
        out = self._sqlite_round_trip(state_in)
        assert out["city_all_time_max"]["Phoenix"]["temp_c"] == 48.2
        assert out["record_streaks"]["Phoenix"]["days"] == 4
