"""Actual diff HTTP/parser and update semantics, never independent weather truth."""
from datetime import date
from hashlib import sha256
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from src.data import ghcn
from tests.ghcn_intake_cases import DATES, INACTIVE, NOW, SID, TODAY, Replies, invoke, payloads


def test_actual_mixed_diff_intake_has_exact_exclusion_and_update_denominators():
    observations, metrics, _revisions, replies, data = invoke()
    assert list(observations) == [(SID, date(2026, 11, 18))]
    [observed] = observations[(SID, date(2026, 11, 18))]
    assert observed.element == "TMAX" and observed.value_c == 33
    assert observed.source_revision == sha256(data[DATES[-1]]).hexdigest()
    assert len(replies.calls) == 3 and all(kw == {"timeout": 60} for _url, kw in replies.calls)
    assert metrics["diff_intake"] == {
        "schema_version": 1, "window_day": "2026-11-21", "cutoff_day": "2026-11-17",
        "counts": {"parsed_temperature_rows": 9, "inactive_station_rows": 1,
                   "too_old_rows": 1, "future_rows": 1, "usable_updates": 4,
                   "delete_updates": 1, "unusable_updates": 1,
                   "final_values": 1, "final_station_days": 1},
    }


@pytest.mark.parametrize("case,parsed,inactive,usable,deletes,unusable", [
    ("empty", 9, 1, 3, 2, 1), ("inactive", 3, 3, 0, 0, 0),
    ("no_temperature", 0, 0, 0, 0, 0),
])
def test_empty_intake_names_rows_not_zero_weather(case, parsed, inactive, usable, deletes, unusable):
    observations, metrics, _revisions, _replies, _data = invoke(case)
    assert observations == {}
    counts = metrics["diff_intake"]["counts"]
    assert counts["parsed_temperature_rows"] == parsed and counts["inactive_station_rows"] == inactive
    assert counts["usable_updates"] == usable and counts["delete_updates"] == deletes
    assert counts["unusable_updates"] == unusable
    assert counts["final_values"] == counts["final_station_days"] == 0


def test_tracked_inactive_revision_is_preserved_without_becoming_an_observation():
    key = (INACTIVE, date(2026, 11, 18), "TMAX")
    observations, metrics, revisions, replies, _data = invoke(tracked_keys={key})
    assert all(sid == SID for sid, _day in observations)
    assert len(revisions) == 1 and revisions[0][0].station_id == INACTIVE
    assert metrics["diff_intake"]["counts"]["inactive_station_rows"] == 1
    assert len(replies.calls) == 3


def test_partial_available_diffs_keep_their_fetch_and_intake_scope_separate():
    observations, metrics, _revisions, replies, _data = invoke("missing")
    assert len(observations) == 2
    assert metrics["diff_dates_fetched"] == 1 and metrics["diff_dates_missing"] == 2
    assert metrics["diff_intake"]["counts"]["parsed_temperature_rows"] == 5
    assert len(replies.calls) == 1 + sum(len(ghcn._diff_urls_for_end_date(day)) for day in DATES[1:])


@pytest.mark.parametrize("case,error", [("unavailable", RuntimeError), ("malformed", ValueError)])
def test_unavailable_or_invalid_diff_never_claims_complete_intake(case, error):
    replies = Replies(payloads(case))
    metrics: dict = {}
    with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW), pytest.raises(error):
        ghcn._fetch_recent_obs(frozenset({SID}), today=TODAY, metrics_out=metrics, revisions_out=[])
    assert "diff_intake" not in metrics


def test_no_metrics_argument_preserves_existing_return_and_request_counts():
    replies = Replies(payloads())
    with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW):
        observations = ghcn._fetch_recent_obs(frozenset({SID}), today=TODAY, revisions_out=[])
    assert len(observations) == 1 and len(replies.calls) == 3


def test_failed_fetch_clears_a_reused_completed_intake_marker():
    _observations, metrics, _revisions, _replies, _data = invoke()
    assert metrics["diff_intake"]["counts"]["final_values"] == 1
    replies = Replies({})
    with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW), pytest.raises(RuntimeError):
        ghcn._fetch_recent_obs(frozenset({SID}), today=TODAY, metrics_out=metrics, revisions_out=[])
    assert "diff_intake" not in metrics
