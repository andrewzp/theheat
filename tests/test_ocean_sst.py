"""Tests for global ocean SST fetch + marine-heatwave-streak detection."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests


def test_module_exports_public_api():
    from src.data import ocean_sst
    assert hasattr(ocean_sst, "GlobalSSTObservation")
    assert hasattr(ocean_sst, "MarineHeatwaveStreakEvent")
    assert hasattr(ocean_sst, "MILESTONES")
    assert hasattr(ocean_sst, "fetch_global_sst")
    assert hasattr(ocean_sst, "detect_streak_milestone")


def test_milestones_ladder_values():
    from src.data.ocean_sst import MILESTONES
    assert MILESTONES == (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)


def test_milestones_up_to_under_400():
    from src.data.ocean_sst import _milestones_up_to
    assert _milestones_up_to(4) == ()
    assert _milestones_up_to(5) == (5,)
    assert _milestones_up_to(47) == (5, 10, 25)
    assert _milestones_up_to(400) == (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)


def test_milestones_up_to_past_400():
    from src.data.ocean_sst import _milestones_up_to
    assert _milestones_up_to(450) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400, 450,
    )
    assert _milestones_up_to(500) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400, 450, 500,
    )
    assert _milestones_up_to(449) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400,
    )
    # Dead zone 401-449: no new milestone fires, same result as 400.
    assert _milestones_up_to(425) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400,
    )


def _fake_payload(current_year: int, today_doy: int,
                  current_year_values: list,
                  prior_years: dict[int, list]) -> dict:
    """Helper: build a ClimateReanalyzer-shaped JSON payload.

    current_year_values is the full 365/366-entry array (pad with None after today).
    prior_years maps year → 365/366-entry array.
    """
    payload = {str(y): arr for y, arr in prior_years.items()}
    payload[str(current_year)] = current_year_values
    return payload


def test_fetch_global_sst_happy_path():
    from src.data import ocean_sst

    # Scenario: today is doy 100 of year 2026.
    # Current year value at doy 100 = 20.5.
    # 44 prior years (1982-2025): doy 100 values are 19.5 for 1982,
    # 20.0 for all middle years (1983-2024), and 20.3 for 2025.
    # Archive max for doy 100 = 20.3, set 2025.
    # Streak: check only doy 100. Value 20.5 > 20.3 → streak = 1.
    today_doy = 100
    cur_values = [None] * 365
    cur_values[today_doy - 1] = 20.5
    prior = {}
    for y in range(1982, 2026):
        arr = [18.0] * 365  # baseline for all days
        arr[today_doy - 1] = 20.3 if y == 2025 else (19.5 if y == 1982 else 20.0)
        prior[y] = arr
    payload = _fake_payload(2026, today_doy, cur_values, prior)

    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()

    assert obs is not None
    assert obs.day_of_year == 100
    assert obs.today_c == pytest.approx(20.5)
    assert obs.archive_max_c == pytest.approx(20.3)
    assert obs.archive_max_year == 2025
    assert obs.years_of_data == 2026 - 1982  # 44
    assert obs.streak_days == 1
    assert obs.streak_peak_anomaly_c == pytest.approx(0.2)


def test_fetch_global_sst_returns_none_on_too_few_prior_years():
    """Fewer than 30 prior years → return None (can't claim a record)."""
    from src.data import ocean_sst
    today_doy = 100
    cur = [None] * 365
    cur[today_doy - 1] = 20.5
    # Only 3 prior years — not enough to claim a record
    prior = {y: [18.0] * 365 for y in range(1982, 1985)}
    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is None


def test_fetch_global_sst_streak_stops_at_first_non_exceedance():
    """3 days exceed archive, 4th does not → streak_days=3."""
    from src.data import ocean_sst
    today_doy = 50
    cur = [None] * 365
    # Days 47, 48, 49, 50 of current year.
    cur[46] = 18.0  # day 47 — NOT above (archive 18.5)
    cur[47] = 19.0  # day 48 — above (archive 18.5)
    cur[48] = 19.1  # day 49 — above (archive 18.6)
    cur[49] = 19.2  # day 50 — above (archive 18.7)
    # Build 32 prior years so validation passes; all with flat archive values.
    prior = {}
    for y in range(1982, 2026):
        arr = [18.0] * 365
        arr[47] = 18.5
        arr[48] = 18.6
        arr[49] = 18.7
        prior[y] = arr

    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is not None
    assert obs.streak_days == 3


def test_fetch_global_sst_streak_crosses_new_year():
    """Streak extends back through doy 1 of current year into prior December."""
    from src.data import ocean_sst
    today_doy = 3  # Jan 3
    cur = [None] * 365
    cur[0] = 19.0  # Jan 1 — above archive 18.5
    cur[1] = 19.1  # Jan 2 — above archive 18.5
    cur[2] = 19.2  # Jan 3 — above archive 18.5

    # Prior years: 1982..2025. 2025 is current_year - 1; its Dec 31 is above
    # archive to extend streak.
    prior: dict[int, list] = {}
    for y in range(1982, 2026):
        arr = [18.0] * 365
        arr[0] = 18.5   # baseline for Jan 1
        arr[1] = 18.5   # Jan 2
        arr[2] = 18.5   # Jan 3
        arr[364] = 18.5 if y != 2025 else 19.0  # Dec 31 in 2025 = 19.0
        prior[y] = arr
    # 2025's Dec 30: above archive?
    prior[2025][363] = 19.0  # Dec 30
    prior[2025][362] = 18.0  # Dec 29 — NOT above archive 18.5 → streak stops

    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    # Jan 3, 2, 1, Dec 31 2025, Dec 30 2025 = 5 days.
    assert obs is not None
    assert obs.streak_days == 5


def test_fetch_global_sst_returns_none_when_all_current_year_values_null():
    from src.data import ocean_sst
    today_doy = 100
    cur = [None] * 365  # all nulls
    prior = {y: [18.0] * 365 for y in range(1982, 2026)}
    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is None


def test_fetch_global_sst_returns_none_on_http_error():
    from src.data import ocean_sst
    with patch("src.data.ocean_sst.requests.get",
               side_effect=requests.RequestException("boom")):
        assert ocean_sst.fetch_global_sst() is None


def test_fetch_global_sst_rejects_out_of_range_values():
    """Values outside [-2, 40] are treated as invalid → archive max falls back."""
    from src.data import ocean_sst
    today_doy = 100
    cur = [None] * 365
    cur[99] = 20.5
    prior = {y: [18.0] * 365 for y in range(1982, 2026)}
    prior[2020][99] = 999.0  # absurd value — ignored
    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is not None
    assert obs.archive_max_c == pytest.approx(18.0)


def test_fetch_global_sst_handles_today_null_uses_latest_non_null():
    """Today's index null; latest non-null used as observation date."""
    from src.data import ocean_sst
    today_doy = 100
    cur = [None] * 365
    cur[97] = 20.5  # day 98 has value, 99 and 100 null
    prior = {y: [18.0] * 365 for y in range(1982, 2026)}
    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is not None
    assert obs.day_of_year == 98
    assert obs.today_c == pytest.approx(20.5)


def _obs(streak_days: int = 5, **overrides):
    from src.data.ocean_sst import GlobalSSTObservation
    defaults = dict(
        date="2026-04-20",
        day_of_year=110,
        today_c=20.5,
        archive_max_c=20.3,
        archive_max_year=2025,
        years_of_data=44,
        streak_days=streak_days,
        streak_start_date="2026-04-16",
        streak_peak_anomaly_c=0.2,
    )
    defaults.update(overrides)
    return GlobalSSTObservation(**defaults)


def test_detect_first_run_silent_seed():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": False, "last_milestone_fired": None}
    new_state, event = detect_streak_milestone(_obs(streak_days=20), prior)
    assert new_state == {"seeded": True, "last_milestone_fired": None}
    assert event is None


def test_detect_streak_under_5_no_fire():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": None}
    new_state, event = detect_streak_milestone(_obs(streak_days=4), prior)
    assert event is None
    assert new_state == {"seeded": True, "last_milestone_fired": None}


def test_detect_day_5_first_fire():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": None}
    new_state, event = detect_streak_milestone(_obs(streak_days=5), prior)
    assert event is not None
    assert event.kind == "first"
    assert event.days == 5
    assert event.event_id == "marine_heatwave_streak_5_2026-04-20"
    assert new_state == {"seeded": True, "last_milestone_fired": 5}


def test_detect_milestone_crossing():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 25}
    new_state, event = detect_streak_milestone(_obs(streak_days=50), prior)
    assert event is not None
    assert event.kind == "milestone"
    assert event.days == 50
    assert new_state == {"seeded": True, "last_milestone_fired": 50}


def test_detect_no_refire_same_milestone():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 50}
    new_state, event = detect_streak_milestone(_obs(streak_days=50), prior)
    assert event is None
    assert new_state == {"seeded": True, "last_milestone_fired": 50}


def test_detect_skip_missed_milestones():
    """Cron missed runs. Prior=5, streak=47 → fire 25 only (highest ≤ 47)."""
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 5}
    new_state, event = detect_streak_milestone(_obs(streak_days=47), prior)
    assert event is not None
    assert event.days == 25
    assert new_state == {"seeded": True, "last_milestone_fired": 25}


def test_detect_streak_break_clears_last_fired():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 50}
    new_state, event = detect_streak_milestone(_obs(streak_days=0), prior)
    assert event is None
    assert new_state == {"seeded": True, "last_milestone_fired": None}


def test_detect_past_400_every_50():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 400}
    new_state, event = detect_streak_milestone(_obs(streak_days=450), prior)
    assert event is not None
    assert event.kind == "milestone"
    assert event.days == 450
    assert new_state == {"seeded": True, "last_milestone_fired": 450}
