"""Offline resource admission at the real X metrics call boundary."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from src.data import twitter_metrics
from src.orchestrator import hot10


NOW = datetime(2026, 11, 17, 6, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_cap(monkeypatch):
    monkeypatch.delenv("THEHEAT_METRICS_MAX_IDS", raising=False)


def test_excess_unique_resources_refuse_before_client_or_paid_ticket(monkeypatch):
    from src.two_bot import call_inventory
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", "2")
    client = Mock(side_effect=AssertionError("must refuse before client construction"))
    ticket = Mock(side_effect=AssertionError("must refuse before spending admission"))
    monkeypatch.setattr(twitter_metrics, "_get_client", client)
    monkeypatch.setattr(call_inventory, "consume", ticket)
    with pytest.raises(ValueError, match="metrics_resource_limit_exceeded"):
        twitter_metrics.fetch_metrics(["1", "2", "3"])
    assert not client.called and not ticket.called


@pytest.mark.parametrize("raw", ["", "0", "-1", "51", "1.0", "01", " 1", "1 ", "\n1", "１", "١", "1e1"])
def test_bad_cap_fails_before_client_or_ticket_without_echoing_config(monkeypatch, raw):
    from src.two_bot import call_inventory
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", raw)
    client, ticket = Mock(), Mock()
    monkeypatch.setattr(twitter_metrics, "_get_client", client)
    monkeypatch.setattr(call_inventory, "consume", ticket)
    with pytest.raises(twitter_metrics.MetricsResourceLimitError) as error:
        twitter_metrics.fetch_metrics(["1"])
    assert str(error.value) == "metrics_resource_limit_invalid"
    client.assert_not_called()
    ticket.assert_not_called()


@pytest.mark.parametrize("limit", ["1", "10", "50"])
def test_unique_limit_admits_one_batch_and_preserves_missing_counts(monkeypatch, limit):
    from src.two_bot import call_inventory
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", limit)
    ids = [str(i) for i in range(1, int(limit) + 1)]
    client, ticket = Mock(), Mock()
    client.get_tweets.return_value = SimpleNamespace(data=[{
        "id": "1", "public_metrics": {"like_count": 0},
    }])
    monkeypatch.setattr(twitter_metrics, "_get_client", lambda: client)
    monkeypatch.setattr(call_inventory, "consume", ticket)
    result = twitter_metrics.fetch_metrics(ids + [" 1 ", "", "1"])
    client.get_tweets.assert_called_once_with(ids=ids, tweet_fields=["public_metrics", "created_at"], user_auth=True)
    ticket.assert_called_once_with("x_metrics_read", provider="x")
    ticket.return_value.settle.assert_called_once_with("returned")
    assert result["1"]["likes"] == 0 and result["1"]["impressions"] is None
    client.session.close.assert_called_once()


@pytest.mark.parametrize("enabled", [None, "0", "true", " 1", "01"])
def test_disabled_lane_ignores_invalid_cap_without_client_or_ticket(monkeypatch, enabled):
    from src.two_bot import call_inventory
    if enabled is None:
        monkeypatch.delenv("THEHEAT_METRICS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("THEHEAT_METRICS_ENABLED", enabled)
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", "not-a-cap")
    client, ticket = Mock(), Mock()
    monkeypatch.setattr(twitter_metrics, "_get_client", client)
    monkeypatch.setattr(call_inventory, "consume", ticket)
    assert twitter_metrics.fetch_metrics(["1"]) == {}
    client.assert_not_called()
    ticket.assert_not_called()


def _state():
    from src import state
    value = deepcopy(state.DEFAULT_STATE)
    value["publish_ledger"] = {
        f"event-{i}": {"tweet_id": str(i + 1), "at": (NOW - timedelta(hours=i)).isoformat()}
        for i in range(60)
    }
    value["drafts"] = [{"tweet_id": "1", "posted_at": NOW.isoformat()}]
    return value


def test_collector_limits_unique_recent_receipts_and_failed_day_stays_closed(monkeypatch):
    from src import state
    from src.orchestrator import telemetry
    monkeypatch.setattr(telemetry, "state", state)
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", "10")
    value = _state()
    run = {"started_at": NOW.isoformat(), "sources": []}
    fetch = Mock(side_effect=RuntimeError("invented provider denial"))
    monkeypatch.setattr(twitter_metrics, "credentials_available", lambda: True)
    monkeypatch.setattr(twitter_metrics, "fetch_metrics", fetch)
    hot10._run_twitter_metrics(value, run, now=NOW)
    fetch.assert_called_once_with([str(i) for i in range(1, 11)])
    assert run["sources"][-1]["status"] == "failed"
    assert run["sources"][-1]["observed"] == 10
    assert not value["tweet_metrics"]
    value["run_history"].append(deepcopy(run))
    second = {"started_at": NOW.isoformat(), "sources": []}
    hot10._run_twitter_metrics(value, second, now=NOW)
    assert fetch.call_count == 1 and second["sources"][-1]["status"] == "skipped"


def test_bad_cap_is_contained_in_real_observed_only_entry_and_report(monkeypatch):
    from src import runtime_inventory, state
    from src.orchestrator import telemetry
    monkeypatch.setattr(telemetry, "state", state)
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", "untrusted-invalid-value")
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    client, fetch = Mock(), Mock()
    monkeypatch.setattr(twitter_metrics, "_get_client", client)
    monkeypatch.setattr(twitter_metrics, "fetch_metrics", fetch)
    value, run = _state(), {"started_at": NOW.isoformat(), "sources": []}
    original = deepcopy(value)
    assert hot10.run_leaderboard(value, run) is value
    assert [source["source"] for source in run["sources"]] == ["leaderboard", "twitter_metrics"]
    assert run["sources"][-1]["status"] == "failed"
    assert run["sources"][-1]["error"] == "metrics_resource_limit_invalid"
    assert value["drafts"] == original["drafts"] and value["publish_ledger"] == original["publish_ledger"]
    flags = runtime_inventory.collect_runtime_inventory("both", now=NOW)["flags"]
    assert flags["metrics_limit_status"] == "invalid" and flags["metrics_max_ids"] is None
    client.assert_not_called()
    fetch.assert_not_called()


@pytest.mark.parametrize("raw,expected,status", [(None, 50, "legacy_default"), ("10", 10, "configured")])
def test_runtime_reports_effective_allowance_without_granting_access(monkeypatch, raw, expected, status):
    from src import runtime_inventory
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "0")
    if raw is not None:
        monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", raw)
    flags = runtime_inventory.collect_runtime_inventory("alerts", now=NOW)["flags"]
    assert flags["metrics_enabled"] is False
    assert flags["metrics_max_ids"] == expected and flags["metrics_limit_status"] == status


def test_new_workflow_fences_legacy_flag_and_delivers_capped_runtime_configuration(monkeypatch):
    # Recognize only this reviewed expression, not an invented GitHub evaluator.
    # Exact-head CI, separately, checks that GitHub accepts the workflow.
    workflow = yaml.load((Path(__file__).parents[1] / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    envs = [step.get("env", {}) for job in workflow["jobs"].values() for step in job.get("steps", [])]
    configured = [env for env in envs if "THEHEAT_METRICS_ENABLED" in env]
    assert configured
    # The run environment is also reused by the two post-collection steps.
    for env in configured:
        assert env["THEHEAT_METRICS_ENABLED"] == "${{ vars.THEHEAT_METRICS_V2_ENABLED == '1' && '1' || '0' }}"
        assert env["THEHEAT_METRICS_MAX_IDS"] == "${{ vars.THEHEAT_METRICS_MAX_IDS || '10' }}"
    monkeypatch.setenv("THEHEAT_METRICS_V2_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "0")  # New expression result, regardless of legacy repo flag.
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", "10")
    fetch = Mock()
    monkeypatch.setattr(twitter_metrics, "fetch_metrics", fetch)
    hot10._run_twitter_metrics(_state(), {}, now=NOW)
    fetch.assert_not_called()
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    assert hot10._metric_candidate_tweet_ids(_state(), NOW) == [str(i) for i in range(1, 11)]
