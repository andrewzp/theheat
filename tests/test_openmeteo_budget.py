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


def test_wait_raises_when_daily_ceiling_blocks():
    """A single weight that exceeds the daily ceiling must raise OpenMeteoSaturated."""
    b = _make_budget(per_minute=600, per_hour=5_000, per_day=10_000, reserve=0)
    # Exhaust the daily budget
    b.spend(10_000)
    with pytest.raises(OpenMeteoSaturated):
        b.wait_until_can_spend(1)
