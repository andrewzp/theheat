"""Real observed-alert caller and metrics SDK; every reply is invented/offline."""
from datetime import timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit

from freezegun import freeze_time
import pytest
import requests

from src import state as storage
from src.data import twitter_metrics as metrics
from src.orchestrator import hot10
from tests.test_awc_alert_modes import alerts as alerts, world as world
from tests.test_awc_observed import NOW

ID = "123456789"


@pytest.fixture
def metrics_http(monkeypatch):
    for key in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
        monkeypatch.setattr(metrics, key, "invented-offline-value")
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", "10")
    settings = {"status": 200, "timeout": False, "adapters": [],
                "created_at": (NOW-timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}

    class Adapter(requests.adapters.BaseAdapter):
        def __init__(self):
            self.sent = []
            self.closed = False

        def send(self, request, **kwargs):
            url = urlsplit(request.url)
            assert request.method == "GET" and url.hostname == "api.twitter.com"
            assert url.path == "/2/tweets"
            assert parse_qs(url.query)["ids"] == [ID]
            assert kwargs["timeout"] == (5.0, 15.0)
            auth = request.headers["Authorization"]
            assert (auth.decode() if isinstance(auth, bytes) else auth).startswith("OAuth ")
            self.sent.append(ID)  # Never retain signed headers, even invented ones.
            if settings["timeout"]:
                raise requests.ReadTimeout("Invented offline timeout")
            response = requests.Response()
            response.status_code = settings["status"]
            response.headers["Content-Type"] = "application/json"
            payload = {"data": [{"id": ID, "text": "Invented earlier post",
                "edit_history_tweet_ids": [ID], "created_at": settings["created_at"],
                "public_metrics": {"like_count": 0}}]} if settings["status"] == 200 else {"title": "Invented denial"}
            response._content = json.dumps(payload).encode()
            response.request = request
            response.url = request.url
            return response

        def close(self):
            self.closed = True

    original = metrics._MetricsSession.__init__

    def session(self):
        original(self)
        adapter = Adapter()
        settings["adapters"].append(adapter)
        self.mount("https://", adapter)

    monkeypatch.setattr(metrics._MetricsSession, "__init__", session)
    return settings


def receipts(state, *, at=NOW):
    state["publish_ledger"] = {"invented-earlier-event": {
        "tweet_id": ID, "at": (at-timedelta(hours=2)).isoformat(), "phase": "confirmed"}}


def sends(settings):
    return sum(len(a.sent) for a in settings["adapters"])


def test_actual_alerts_keeps_checked_draft_and_reads_existing_receipt_once(world, alerts, metrics_http):
    transport, state, run, called, _ = world
    receipts(state)
    run.update(mode="alerts", started_at=NOW.isoformat())
    with freeze_time(NOW):
        assert alerts.run_alerts(state, run) is state
    assert sends(metrics_http) == 1
    assert all(a.closed for a in metrics_http["adapters"])
    assert called == ["writer", "safety", "fact_check", "critic"]
    assert len(state["drafts"]) == 1 and state["drafts"][0]["approval_binding"]["mode"] == "auto"
    assert not transport.x_posts
    assert ID in state["tweet_metrics"], [x for x in run["sources"] if x["source"] == "twitter_metrics"]
    assert state["tweet_metrics"][ID]["likes"] == 0
    assert state["tweet_metrics"][ID]["impressions"] is None
    row = next(x for x in run["sources"] if x["source"] == "twitter_metrics")
    assert row["observed"] == row["promoted"] == 1


@pytest.mark.parametrize("order", [("alerts", "leaderboard"), ("leaderboard", "alerts")])
def test_both_callers_share_unfinished_run_without_buying_twice(world, alerts, metrics_http, order):
    _, state, run, _, _ = world
    receipts(state)
    run.update(mode="both", started_at=NOW.isoformat())
    with freeze_time(NOW):
        for mode in order:
            (alerts.run_alerts if mode == "alerts" else hot10.run_leaderboard)(state, run)
    assert sends(metrics_http) == 1
    assert not state["run_history"], "Do not insert an unfinished run to make the gate pass"
    assert len([x for x in run["sources"] if x["source"] == "twitter_metrics"]) == 2


@pytest.mark.parametrize("timeout", [False, True])
def test_failed_attempt_is_closed_in_current_run_before_any_final_save(world, metrics_http, timeout):
    _, state, run, _, _ = world
    receipts(state)
    metrics_http.update(status=401, timeout=timeout)
    run["started_at"] = NOW.isoformat()
    with freeze_time(NOW):
        hot10._run_twitter_metrics(state, run, now=NOW)
        hot10._run_twitter_metrics(state, run, now=NOW)
    assert sends(metrics_http) == 1
    assert not state["tweet_metrics"]
    assert run["sources"][0]["status"] == "failed"
    assert run["sources"][1]["status"] == "skipped"


def test_today_stays_spent_after_sender_history_rollover_and_json_reload(world, metrics_http):
    _, state, run, _, _ = world
    receipts(state)
    with freeze_time(NOW):
        run.update(started_at=NOW.isoformat())
        hot10._run_twitter_metrics(state, run, now=NOW)
        storage.finalize_run(state, run)
    for i in range(21):
        with freeze_time(NOW+timedelta(minutes=i+1)):
            storage.finalize_run(state, storage.init_run("auto_publish_due"))
    assert not any(x.get("source") == "twitter_metrics" for r in state["run_history"] for x in r["sources"])
    restored = json.loads(json.dumps(state))
    with freeze_time(NOW+timedelta(minutes=30)):
        hot10._run_twitter_metrics(restored, {"sources": []}, now=NOW+timedelta(minutes=30))
    assert sends(metrics_http) == 1


def test_midnight_attempt_day_survives_run_starting_yesterday(world, metrics_http):
    _, state, run, _, _ = world
    at = NOW.replace(hour=0, minute=2)
    receipts(state, at=at)
    metrics_http["created_at"] = (at-timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    run.update(started_at=(at-timedelta(minutes=4)).isoformat())
    with freeze_time(at):
        hot10._run_twitter_metrics(state, run, now=at)
        storage.finalize_run(state, run)
    restored = json.loads(json.dumps(state))
    # Independent run-detail proof for snapshots without a health summary.
    restored["source_health"] = {}
    with freeze_time(at+timedelta(minutes=1)):
        hot10._run_twitter_metrics(restored, {"sources": []}, now=at+timedelta(minutes=1))
    assert sends(metrics_http) == 1


@pytest.mark.parametrize("offset", [-8, 14])
def test_lookup_uses_utc_day_not_callers_local_calendar_day(world, metrics_http, offset):
    _, state, run, _, _ = world
    at = NOW.replace(hour=0, minute=5)
    receipts(state, at=at)
    metrics_http["created_at"] = (at-timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    run.update(started_at=at.isoformat())
    with freeze_time(at):
        hot10._run_twitter_metrics(state, run, now=at)
        storage.finalize_run(state, run)
        hot10._run_twitter_metrics(state, {"sources": []}, now=at.astimezone(timezone(timedelta(hours=offset))))
    assert sends(metrics_http) == 1


def test_next_utc_day_gets_only_its_ordinary_opportunity(world, metrics_http):
    _, state, run, _, _ = world
    receipts(state)
    with freeze_time(NOW):
        run["started_at"] = NOW.isoformat()
        hot10._run_twitter_metrics(state, run, now=NOW)
        storage.finalize_run(state, run)
    with freeze_time(NOW+timedelta(days=1)):
        other = {"started_at": (NOW+timedelta(days=1)).isoformat(), "sources": []}
        hot10._run_twitter_metrics(state, other, now=NOW+timedelta(days=1))
        hot10._run_twitter_metrics(state, other, now=NOW+timedelta(days=1))
    assert sends(metrics_http) == 2


def test_naive_clock_refuses_before_client_or_any_lookup(world, metrics_http):
    _, state, run, _, _ = world
    receipts(state)
    with freeze_time(NOW):
        hot10._run_twitter_metrics(state, run, now=NOW.replace(tzinfo=None))
    assert not metrics_http["adapters"] and sends(metrics_http) == 0
    assert not state["tweet_metrics"]
    assert run["sources"][-1]["error"] == "metrics_clock_invalid"


def test_clock_lost_after_return_holds_sample_and_keeps_attempt_spent(monkeypatch, world, metrics_http):
    _, state, run, _, _ = world
    receipts(state)
    clock = iter([NOW, NOW.replace(tzinfo=None)])
    monkeypatch.setattr(hot10, "_utc_now", lambda: next(clock))
    with freeze_time(NOW):
        hot10._run_twitter_metrics(state, run)
        hot10._run_twitter_metrics(state, run, now=NOW)
    assert sends(metrics_http) == 1 and not state["tweet_metrics"]
    assert run["sources"][0]["error"] == "metrics_sample_clock_invalid"
    assert run["sources"][1]["status"] == "skipped"


@pytest.mark.parametrize("setting", ["disabled-legacy", "bad-cap", "missing-credentials"])
def test_alerts_preserve_source_model_and_draft_when_metrics_cannot_run(monkeypatch, world, alerts, metrics_http, setting):
    transport, state, run, called, _ = world
    receipts(state)
    if setting == "disabled-legacy":
        monkeypatch.setenv("THEHEAT_METRICS_V2_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "0")
    elif setting == "bad-cap":
        monkeypatch.setenv("THEHEAT_METRICS_MAX_IDS", "1.0")
    else:
        monkeypatch.setattr(metrics, "API_KEY", "")
    run["started_at"] = NOW.isoformat()
    with freeze_time(NOW):
        alerts.run_alerts(state, run)
    assert not metrics_http["adapters"] and sends(metrics_http) == 0
    assert len(state["drafts"]) == 1 and called == ["writer", "safety", "fact_check", "critic"]
    assert not transport.x_posts
    rows = [x for x in run["sources"] if x["source"] == "twitter_metrics"]
    if setting == "disabled-legacy":
        assert not rows
    else:
        assert len(rows) == 1 and rows[0]["status"] == ("failed" if setting == "bad-cap" else "skipped")
