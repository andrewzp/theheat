"""Offline selection bounds, not claims about actual NOAA reporting coverage."""
from datetime import datetime, timedelta, timezone

import pytest

from src.data.ghcn import _select_archive_stations


START = datetime(2026, 9, 9, tzinfo=timezone.utc)


def stations(start, count):
    return {f"USC{i:08d}" for i in range(start, start + count)}


def select(tracked, candidates, bucket=0, limit=20):
    return _select_archive_stations(
        tracked, candidates, now=(START + timedelta(hours=4 * bucket)).isoformat(), limit=limit,
    )


@pytest.mark.parametrize("start", [0, 1, 17, 539])
def test_two_stable_eighty_station_lanes_are_selected_within_eight_opportunities(start):
    tracked, candidates = stations(0, 80), stations(80, 80)
    seen = set()
    for bucket in range(start, start + 8):
        selected, metrics = select(tracked, candidates, bucket)
        assert len(selected) == len(set(selected)) == 20
        assert len(set(selected) & tracked) == len(set(selected) & candidates) == 10
        assert metrics["tracked"]["stable_sweep_opportunities"] == 8
        assert metrics["candidates"]["stable_sweep_opportunities"] == 8
        seen.update(selected)
    assert seen == tracked | candidates


@pytest.mark.parametrize(("tracked_count", "candidate_count", "opportunities"), [
    (0, 80, 4), (80, 0, 4), (4, 80, 5), (80, 4, 5), (1, 1, 1), (0, 0, 0),
])
def test_empty_and_short_lanes_release_unused_slots(tracked_count, candidate_count, opportunities):
    tracked, candidates = stations(0, tracked_count), stations(100, candidate_count)
    seen = set()
    for bucket in range(opportunities):
        selected, metrics = select(tracked, candidates, bucket)
        assert len(selected) == min(20, len(tracked | candidates))
        assert sum(metrics[lane]["reserved_slots"] for lane in ("tracked", "candidates")) == len(selected)
        seen.update(selected)
    assert seen == tracked | candidates


@pytest.mark.parametrize("limit", [0, 1, 2, 3, 7, 19, 20, 999, -1])
@pytest.mark.parametrize("overlap", [0, 1, 13, 20])
def test_reported_bound_covers_unequal_overlapping_lanes_at_fixed_limits(limit, overlap):
    tracked, candidates = stations(0, 20), stations(20 - overlap, 31)
    effective = max(0, min(limit, 20))
    for start in (0, 1):
        _, initial = select(tracked, candidates, start, limit)
        bound = max(initial[lane]["stable_sweep_opportunities"] or 0 for lane in ("tracked", "candidates"))
        seen = set()
        for bucket in range(start, start + bound):
            selected, metrics = select(tracked, candidates, bucket, limit)
            assert len(selected) == len(set(selected)) == min(effective, len(tracked | candidates))
            assert set(selected) <= tracked | candidates
            assert metrics["overlap_stations"] == len(tracked & candidates)
            seen.update(selected)
        if effective:
            assert seen == tracked | candidates
        else:
            assert bound == 0
            assert initial["tracked"]["stable_sweep_opportunities"] is None
            assert initial["candidates"]["stable_sweep_opportunities"] is None


def test_limit_one_alternates_lanes_without_skipping_half_the_stations():
    tracked, candidates = stations(0, 80), stations(80, 80)
    seen = set()
    for bucket in range(160):
        selected, metrics = select(tracked, candidates, bucket, 1)
        assert bool(set(selected) & tracked) == (bucket % 2 == 0)
        assert metrics["tracked"]["stable_sweep_opportunities"] == 160
        seen.update(selected)
    assert seen == tracked | candidates


def test_overlapping_windows_are_preserved_before_filling_spare_capacity():
    tracked, candidates = stations(0, 80), stations(0, 80)
    seen = set()
    for bucket in range(8):
        selected, metrics = select(tracked, candidates, bucket)
        # Both guaranteed ten-station windows coincide. Ten extra distinct
        # stations fill the spare capacity without consuming more fetches.
        assert metrics["tracked"]["reserved_slots"] == 10
        assert metrics["tracked"]["selected_stations"] == 20
        assert len(set(selected)) == 20
        seen.update(selected)
    assert seen == tracked


def test_bucket_uses_utc_and_retries_are_deterministic_without_mutating_inputs():
    tracked, candidates = stations(0, 80), stations(80, 80)
    original = tracked.copy(), candidates.copy()
    values = [
        "2026-09-09T00:00:00Z", "2026-09-09T03:59:59.999999Z",
        "2026-09-08T22:00:00-04:00", "2026-09-09T05:30:00+05:30",
    ]
    results = [_select_archive_stations(tracked, candidates, now=now, limit=20) for now in values]
    assert all(result == results[0] for result in results)
    assert results[0][1]["bucket_start"] == "2026-09-09T00:00:00Z"
    assert (tracked, candidates) == original
    assert select(tracked, candidates, 1)[0] != results[0][0]


@pytest.mark.parametrize("now", ["2026-09-09", "2026-09-09T12:00:00", "invalid"])
def test_ambiguous_or_invalid_time_is_rejected(now):
    with pytest.raises(ValueError):
        _select_archive_stations(set(), set(), now=now, limit=20)


@pytest.mark.parametrize("limit", [True, False, "20", 1.5, None, float("nan"), float("inf"), -float("inf")])
def test_noninteger_budget_is_rejected(limit):
    with pytest.raises(ValueError, match="limit must be an integer"):
        select(stations(0, 80), set(), limit=limit)


def test_overflow_and_evidence_limits_remain_visible():
    selected, metrics = select(stations(0, 1000), stations(1000, 1000))
    assert len(selected) == metrics["selected_unique_stations"] == 20
    assert metrics["eligible_unique_stations"] == 2000
    assert metrics["unselected_unique_stations"] == 1980
    for lane in ("tracked", "candidates"):
        assert metrics[lane]["unselected_stations"] == 990
        assert metrics[lane]["stable_sweep_opportunities"] == 100
        assert metrics[lane]["verified_stations"] is None
    assert metrics["same_bucket_retries_reuse_selection"] is True
    assert metrics["timely_verification_guaranteed"] is False
    assert "stable lane membership and limit" in metrics["coverage_bound_scope"]


def test_skipped_buckets_do_not_inherit_consecutive_opportunity_coverage():
    tracked = stations(0, 24)
    first, _ = select(tracked, set(), 0)
    day_later, _ = select(tracked, set(), 6)
    assert day_later == first  # 6 * 20 slots wraps exactly five times.
    next_bucket, _ = select(tracked, set(), 1)
    assert set(first) | set(next_bucket) == tracked
