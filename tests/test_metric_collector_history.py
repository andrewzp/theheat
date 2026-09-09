"""No platform calls: exercise the existing polling path with recorded responses."""
from datetime import UTC, datetime, timedelta

import pytest

from src.orchestrator import hot10

NOW = datetime(2026, 9, 9, tzinfo=UTC)


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    monkeypatch.setattr(hot10.twitter_metrics, "credentials_available", lambda: True)
    records = []
    monkeypatch.setattr(hot10, "_record_source_run", lambda *args, **kwargs: records.append(kwargs))
    state = {"drafts": [], "run_history": [], "tweet_metrics": {}, "publish_ledger": {
        "event": {"tweet_id": "123", "at": "2026-09-08T00:00:00Z"},
    }}
    return state, records


def test_daily_samples_accumulate_without_losing_old_values(collector, monkeypatch):
    state, records = collector
    calls = []
    def fetch(ids):
        calls.append(ids)
        return {"123": {"likes": len(calls), "impressions": 10 * len(calls), "created_at": "2026-09-08T00:00:00Z"}}
    monkeypatch.setattr(hot10.twitter_metrics, "fetch_metrics", fetch)
    hot10._run_twitter_metrics(state, {}, now=NOW)
    hot10._run_twitter_metrics(state, {}, now=NOW + timedelta(days=1))
    assert calls == [["123"], ["123"]]
    observations = list(state["tweet_metrics"]["123"]["samples"].values())
    assert sorted(row["counts"]["likes"] for row in observations) == [1, 2]
    assert sorted(row["post_age_seconds"] for row in observations) == [86400, 172800]
    assert all(row["counts"]["replies"] is None for row in observations)
    assert all(record["status"] == "success" for record in records)


@pytest.mark.parametrize("response", [{}, {"other": {"likes": 2}}, {"123": {}}, {"123": {"other": 2}}])
def test_empty_or_unusable_lookup_is_not_a_recovered_metrics_lane(collector, monkeypatch, response):
    state, records = collector
    monkeypatch.setattr(hot10.twitter_metrics, "fetch_metrics", lambda ids: response)
    hot10._run_twitter_metrics(state, {}, now=NOW)
    assert records[-1]["status"] == "partial_failure"
    assert records[-1]["promoted"] == 0
    assert "other" not in state["tweet_metrics"]


def test_collection_window_is_not_expanded_and_attempt_time_is_not_post_time(collector, monkeypatch):
    state, records = collector
    state["publish_ledger"] = {"old": {"tweet_id": "old", "at": "2026-07-01T00:00:00Z"},
                                "future": {"tweet_id": "future", "at": "2026-09-10T00:00:00Z"}}
    state["drafts"] = [{"tweet_id": "attempt", "last_publish_attempt_at": "2026-09-08T00:00:00Z"}]
    def forbidden(*args):
        raise AssertionError("No eligible receipt: must not make a lookup")
    monkeypatch.setattr(hot10.twitter_metrics, "fetch_metrics", forbidden)
    hot10._run_twitter_metrics(state, {}, now=NOW)
    assert records[-1]["status"] == "skipped"
    assert state["tweet_metrics"] == {}
