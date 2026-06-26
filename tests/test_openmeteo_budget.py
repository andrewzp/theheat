"""Tests for OpenMeteoBudget — strict TDD, fake clock, no real sleeps."""

import pytest

from src.data.openmeteo_budget import OpenMeteoBudget, OpenMeteoSaturated


def _make_budget(*, per_minute=600, per_hour=5_000, per_day=10_000, reserve=0):
    """Return a budget wired to a fake clock list and a sleep that advances it."""
    t = [0.0]

    def clock():
        return t[0]

    def sleep(seconds):
        t[0] += seconds

    return OpenMeteoBudget(
        per_minute=per_minute,
        per_hour=per_hour,
        per_day=per_day,
        reserve=reserve,
        clock=clock,
        sleep=sleep,
    )


def test_pacing_spends_595_forecasts_plus_warm_under_minute_ceiling():
    """Spend 8 warm-up cities (weight 43 each) then 595 forecast cities
    (weight 1 each).  The minute window must never exceed 360 at any
    sample point after we start measuring.
    """
    b = _make_budget(per_minute=360, per_hour=5_000, per_day=10_000, reserve=0)

    # warm-up: 8 × weight-43 (simulate Hot-10 leaderboard calls)
    for _ in range(8):
        b.wait_until_can_spend(43)
        b.spend(43)

    # 595 single-city forecast calls
    for _ in range(595):
        b.wait_until_can_spend(1)
        b.spend(1)

    # After all spending, the rolling 60-second window must not exceed 360.
    assert b._spent_within(60) <= 360


def test_wait_raises_when_hourly_ceiling_blocks():
    """Spending past the hourly ceiling in one window raises OpenMeteoSaturated.

    ``next_available_delay`` checks the hourly ceiling before the daily one, so a
    single oversized spend trips the *hourly* guard first (this is the case the
    old ``..._daily_ceiling_blocks`` test actually exercised — it was misnamed).
    """
    b = _make_budget(per_minute=600, per_hour=5_000, per_day=10_000, reserve=0)
    b.spend(5_000)  # fill the hour window (also < per_day, so day ceiling is clear)
    with pytest.raises(OpenMeteoSaturated, match="hourly ceiling"):
        b.wait_until_can_spend(1)


def test_wait_raises_on_daily_ceiling_without_tripping_hourly():
    """Isolate the daily ceiling: stay under the hourly window but exceed the
    rolling 24h budget across two hours, so the daily guard — not the hourly one
    — is what raises.
    """
    b = _make_budget(per_minute=600, per_hour=600, per_day=1_000, reserve=0)
    # Hour 1: spend the full hourly budget.
    b.spend(600)
    # Advance past the 1h window (but inside the 24h window) via the injected
    # fake sleep, so the hourly accountant clears while the daily total persists.
    b._sleep(3_601)
    # Hour 2: spend up to the daily ceiling. The rolling-hour spend is now 400
    # (< per_hour=600), so the hourly check cannot fire on the next request.
    b.spend(400)  # daily total now 1_000 == per_day
    with pytest.raises(OpenMeteoSaturated, match="daily ceiling"):
        b.wait_until_can_spend(1)
