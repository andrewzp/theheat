"""Actual lock-bearing news result -> runner/lane -> invented metadata storage.

Only storage I/O is replaced; no DB, source, provider or model is contacted.
"""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.data.newsworthiness import NewsRetrievalResult
from src.orchestrator import telemetry
from src.orchestrator.sources import newsworthiness as runner
from src.storage import postgres_projection as p
from src.storage.retained_reports import RetainedNewsReportLane, RetainedReportSession, digest
from src.state_schema import BotState
from src.two_bot.call_inventory import OperationAllowance
from tests.live_content_harness import trap_network

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
NOW_TEXT = "2026-10-11T12:00:00Z"


@pytest.fixture(autouse=True)
def offline_clock(monkeypatch):
    trap_network(monkeypatch.setattr)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no real database is permitted")
    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr(p, "_driver", forbidden)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(runner.state, "datetime", Clock)
    # Replace these two module bindings, never the shared global time singleton.
    clock = SimpleNamespace(perf_counter=lambda: 1.0)
    monkeypatch.setattr(runner, "time", clock)
    monkeypatch.setattr(telemetry, "time", clock)
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")


def returned_result():
    result = NewsRetrievalResult(events=[dict(kind="fire", headline="Invented retained news",
        window_start="2026-10-11", window_end="2026-10-11", confidence="verified",
        impact=[dict(claim="reported effects", value=4, source_name="Invented agency",
                     url="https://example.test/news", as_of="unknown")])],
        notes=["invented metadata only"], verify_calls=1, verify_fetches=1)
    for stage in ("newsworthiness_search", "newsworthiness_verify", "news_verification_page"):
        assert result.allowance.reserve(stage)
        result.allowance.attempt(stage)
        result.allowance.settle(stage, "returned")
    return result


def lane(monkeypatch, result, *, mismatch=False, outage=False):
    # Preserve the real exact-type session validation; replace only its storage I/O.
    repository = p.PostgresProjectionRepository.__new__(p.PostgresProjectionRepository)
    repository.environment = "local"
    session = RetainedReportSession(repository)
    captured = SimpleNamespace(raw=[], documents=[], order=[])
    def artifact(_self, raw, *, declared_sha256, metadata):
        captured.order.append("artifact")
        if outage:
            raise OSError("invented storage outage")
        assert hashlib.sha256(raw).hexdigest() == declared_sha256
        assert metadata["source_url"] is None and metadata["retrieved_at"] is None
        captured.raw.append(raw)
        return SimpleNamespace(snapshot_id=declared_sha256)
    def revision(_self, document, *, expected_head, operation_id):
        captured.order.append("revision")
        assert expected_head is None and operation_id
        captured.documents.append(json.loads(json.dumps(document)))
        return dict(lineage_id=document["lineage_id"], report_sha256=digest(document), sequence=1)
    monkeypatch.setattr(RetainedReportSession, "retain_artifact", artifact)
    monkeypatch.setattr(RetainedReportSession, "retain_revision", revision)
    observer = RetainedNewsReportLane(session, (dict(event_index=0,
        event_sha256="a" * 64 if mismatch else digest(result.events[0]), lineage_id="fixture:news",
        expected_head=None, operation_id=str(uuid4())),), NOW_TEXT)
    return observer, captured


def test_actual_lane_snapshots_metadata_without_copying_lock_or_budget_authority(monkeypatch):
    result = returned_result()
    setattr(result, "undeclared_transport_extra", object())
    allowance = result.allowance
    assert type(allowance) is OperationAllowance
    with pytest.raises(TypeError):
        deepcopy(result)  # Control: live authority still cannot be cloned.
    observer, captured = lane(monkeypatch, result)
    before = allowance.summary()
    retained = observer(result)
    assert retained["status"] == "retained_metadata_only"
    archived = json.loads(captured.raw[0])
    assert "undeclared_transport_extra" not in archived
    assert archived["allowance"] == before and result.allowance is allowance
    assert allowance.summary() == before and captured.order == ["artifact", "revision"]
    assert archived["events"] == result.events and archived["verify_calls"] == 1
    assert retained["generation_available"] is False and retained["publication_enabled"] is False


def test_retained_metadata_and_counts_stay_detached_after_callback(monkeypatch):
    result = returned_result()
    original_event = deepcopy(result.events[0])
    observer, captured = lane(monkeypatch, result)
    before = result.allowance.summary()
    observer(result)
    raw, document = captured.raw[0], deepcopy(captured.documents[0])
    result.events[0]["impact"][0]["value"] = 999
    result.notes.append("later invented metadata")
    assert result.allowance.reserve("newsworthiness_verify")
    result.allowance.attempt("newsworthiness_verify")
    result.allowance.settle("newsworthiness_verify", "unknown")
    assert captured.raw[0] == raw and captured.documents[0] == document
    assert json.loads(raw)["events"] == [original_event] and json.loads(raw)["allowance"] == before
    assert captured.documents[0]["legacy_metadata"]["event"] == original_event


def test_snapshot_precedes_session_validation_and_retention_callbacks(monkeypatch):
    result = returned_result()
    event = deepcopy(result.events[0])
    observer, captured = lane(monkeypatch, result)
    original = RetainedReportSession._validate
    def validate(session):
        result.events[0]["headline"] = "Later invented metadata changed by a validation callback"
        original(session)
    monkeypatch.setattr(RetainedReportSession, "_validate", validate)
    observer(result)
    assert json.loads(captured.raw[0])["events"] == [event]
    assert captured.documents[0]["legacy_metadata"]["event"] == event


@pytest.mark.parametrize("mode", ["retained", "mismatch", "observer_failure"])
def test_actual_runner_returns_observer_result_with_legacy_health_and_calls_unchanged(monkeypatch, mode):
    result = returned_result()
    observer, captured = lane(monkeypatch, result, mismatch=mode == "mismatch", outage=mode == "observer_failure")
    calls = []
    def fetch():
        calls.append("fetch")
        return result
    monkeypatch.setattr(runner, "fetch_news_events", fetch)
    baseline: BotState = {}
    observed: BotState = {}
    baseline_run: dict = {"id": "fixture", "mode": "alerts", "sources": []}
    observed_run = deepcopy(baseline_run)
    before = result.allowance.summary()
    assert runner.run_newsworthiness(baseline, baseline_run) is None
    retained = runner.run_newsworthiness(observed, observed_run, retention_observer=observer)
    assert retained is not None
    assert calls == ["fetch", "fetch"] and observed == baseline and observed_run == baseline_run
    assert result.allowance.summary() == before
    assert retained["status"] == ("retained_metadata_only" if mode == "retained" else "retention_unavailable")
    assert captured.order == ({"retained": ["artifact", "revision"], "mismatch": [], "observer_failure": ["artifact"]}[mode])


def test_flag_off_does_not_fetch_or_invoke_the_observer(monkeypatch):
    result = returned_result()
    observer, captured = lane(monkeypatch, result)
    monkeypatch.delenv("THEHEAT_NEWSWORTHINESS_ENABLED")
    def forbidden():
        raise AssertionError("disabled discovery must not fetch")
    monkeypatch.setattr(runner, "fetch_news_events", forbidden)
    before = result.allowance.summary()
    run: dict = {"sources": []}
    assert runner.run_newsworthiness({}, run, retention_observer=observer) is None
    assert run["sources"][0]["status"] == "skipped" and captured.order == []
    assert result.allowance.summary() == before
