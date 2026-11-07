"""Observed Google payment failures stop purchases through the real cycle."""

from unittest.mock import Mock

import httpx
import pytest
from google.genai.errors import ClientError

from src.data import newsworthiness as news
from src.orchestrator import common
from src.orchestrator.sources.newsworthiness import run_newsworthiness
from src.state import _fresh_state, _merge_state
from src.two_bot import pipeline
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.retry import BudgetExhaustedError, call_with_retries
from src.two_bot.types import WriterResult
from tests.test_billing_circuit_breaker import _candidate
from tests.test_newsworthiness import _event
from tests.test_newsworthiness_budget import event, fixtures
from tests.two_bot.conftest import _bundle


def _google_error(status=402, *, response_status=402):
    response = None if response_status is None else httpx.Response(response_status)
    return ClientError(
        status, {"error": {"code": status, "message": "invented-private-provider-body"}}, response,
    )


@pytest.mark.parametrize("triage,refill", [("0", "0"), ("1", "0"), ("1", "1")])
def test_discovery_payment_failure_stops_alerts_and_later_leaderboard(monkeypatch, triage, refill):
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", triage)
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", refill)
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    search = Mock(side_effect=_google_error())
    monkeypatch.setattr(news, "_grounded_leg", search)
    writer = Mock(return_value=False)
    monkeypatch.setattr(common, "_try_two_bot_draft", writer)
    bot_state = _fresh_state()
    run = {"id": "invented-run", "sources": []}

    run_newsworthiness(bot_state, run)
    for lane in ("alerts", "leaderboard"):
        bot_state["_triage_queue"] = [_candidate(event_id=lane, source=lane)]
        assert common._drain_and_write_triage_queue(bot_state, run) == 0

    search.assert_called_once()
    writer.assert_not_called()
    assert bot_state["_billing_exhausted_latch"] is True
    assert any(row["stage"] == "billing_cycle_abort" for row in bot_state["suppressions"])
    assert any(row["source"] == "generation" and row["status"] == "partial_failure"
               and row["error"] == "provider_billing_exhausted" for row in run["sources"])
    assert "invented-private" not in str(run) + str(bot_state)
    assert "_billing_exhausted_latch" not in _merge_state(bot_state, bot_state)


def test_discovery_payment_failure_keeps_structured_news_and_recovers_next_retrieval(monkeypatch):
    structured = _event(confidence="structured", retrieved_via="nifc")
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [structured])
    search = Mock(side_effect=[_google_error(), []])
    monkeypatch.setattr(news, "_grounded_leg", search)

    failed = news.fetch_news_events()
    recovered = news.fetch_news_events()

    assert failed.events == recovered.events == [structured]
    assert failed.provider_billing_exhausted is True
    assert recovered.provider_billing_exhausted is False
    assert search.call_count == 2
    assert "invented-private" not in str(failed.notes)


@pytest.mark.parametrize("error", [
    _google_error(429, response_status=429),
    _google_error(503, response_status=503),
    _google_error(response_status=None),
    _google_error(response_status=200),
    RuntimeError("invented HTTP402 prepayment credits are depleted"),
])
def test_discovery_does_not_infer_payment_failure_from_prose_or_body(monkeypatch, error):
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    monkeypatch.setattr(news, "_grounded_leg", Mock(side_effect=error))
    bot_state = _fresh_state()
    run = {"id": "invented-run", "sources": []}
    run_newsworthiness(bot_state, run)
    assert not bot_state.get("_billing_exhausted_latch")


def test_discovery_strict_mode_preserves_original_error(monkeypatch):
    error = _google_error()
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    monkeypatch.setattr(news, "_grounded_leg", Mock(side_effect=error))
    with pytest.raises(ClientError) as caught:
        news.fetch_news_events(strict=True)
    assert caught.value is error


def test_forged_response_cannot_trip_the_discovery_billing_latch(monkeypatch):
    error = RuntimeError("invented provider failure")
    error.response = httpx.Response(402)
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    monkeypatch.setattr(news, "_grounded_leg", Mock(side_effect=error))
    assert news.fetch_news_events().provider_billing_exhausted is False


def test_google_payment_error_reaches_shared_breaker_once_without_provider_body():
    error = _google_error()
    send = Mock(side_effect=error)
    with pytest.raises(BudgetExhaustedError, match="google_http_402") as caught:
        call_with_retries("invented-check", send, attempts=3, sleep_seconds=0)
    send.assert_called_once()
    assert caught.value.__cause__ is error
    assert "invented-private-provider-body" not in str(caught.value)


def test_concurrent_source_promotes_the_billing_hold_before_generation(monkeypatch):
    from src.orchestrator.scheduler import SourceRunner, run_stage1_sources

    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    monkeypatch.setattr(news, "_grounded_leg", Mock(side_effect=_google_error()))
    bot_state = _fresh_state()
    run = {"id": "invented-concurrent-run", "sources": []}
    run_stage1_sources(
        bot_state, run, serial_runners=[],
        concurrent_runners=[SourceRunner("newsworthiness", run_newsworthiness)],
        budget_seconds=10, max_workers=1,
    )
    assert bot_state["_billing_exhausted_latch"] is True
    assert any(row["source"] == "generation" and row["status"] == "partial_failure"
               for row in run["sources"])


def test_late_source_billing_result_cannot_mutate_live_state(monkeypatch):
    from src.orchestrator import staging

    tick = [0.0]
    monkeypatch.setattr(staging, "clock", lambda: tick[0])
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])

    def late_search(now):
        tick[0] = 2.0
        raise _google_error()

    monkeypatch.setattr(news, "_grounded_leg", late_search)
    bot_state = _fresh_state()
    run = {"id": "invented-expired-run", "sources": []}
    owner = staging.Owner(bot_state, run)
    batch = owner.open_batch()
    stage = batch.stage("newsworthiness", 1.0)
    try:
        staging.execute(stage, run_newsworthiness)
        assert stage.state["_billing_exhausted_latch"] is True
        assert staging.promote(owner, stage, batch) != "promoted"
        assert "_billing_exhausted_latch" not in bot_state and run["sources"] == []
    finally:
        owner.close()
        staging.take_late_evidence(owner)


def test_verifier_payment_failure_stops_more_pages_and_calls_but_keeps_supported_claim(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    verify.side_effect = ['{"supported": true}', _google_error()]
    events = [event(index, url=f"https://example.org/report-{index}") for index in range(4)]
    result = news.NewsRetrievalResult()
    kept = news._verify_grounded(events, result)
    assert kept == [{**events[0], "confidence": "verified"}]
    assert verify.call_count == fetch.call_count == 2
    assert result.verify_calls == 2 and result.provider_billing_exhausted is True
    assert result.dropped_unverified == 3
    assert "invented-private" not in str(result.notes)


@pytest.mark.parametrize("reason,expected_billing", [
    ("safety_unavailable: google_http_402", True),
    ("safety_unavailable: google_http_429", False),
    ("safety_unavailable: google_http_503", False),
    ("safety_unavailable: ClientError", False),
    ("LLM flagged as potentially harmful", False),
])
def test_pipeline_payment_failure_reaches_billing_boundary_and_keeps_capture(
    monkeypatch, reason, expected_billing,
):
    bundle = _bundle()
    monkeypatch.setattr(pipeline.fact_check, "local_rejection", lambda *args: None)
    monkeypatch.setattr("src.two_bot.copy_gates.copy_rejection", lambda *args: None)
    monkeypatch.setattr(pipeline, "run_safety_pipeline", lambda text: (False, reason))
    fact = Mock(side_effect=AssertionError("No factual provider after unavailable safety"))
    monkeypatch.setattr(pipeline.fact_check, "fact_check", fact)
    result = {}
    kills = []
    kwargs = dict(
        record_kill=lambda stage, value: kills.append((stage, value)),
        result_out=result, generation_input=capture_bundle(bundle),
    )
    if expected_billing:
        with pytest.raises(BudgetExhaustedError, match="google_http_402"):
            pipeline._check_safety_honesty_fact("Invented weather fixture.", bundle, {}, **kwargs)
    else:
        assert pipeline._check_safety_honesty_fact("Invented weather fixture.", bundle, {}, **kwargs) is None
        assert kills == [("safety", reason)]
    fact.assert_not_called()
    assert result["rejected_candidate"]["stage"] == "safety"
    if reason.startswith("safety_"):
        assert result["rejected_candidate"]["status"] == "unavailable"


def test_real_safety_failure_is_recorded_as_billing_in_the_full_generation_path(monkeypatch):
    from collections import OrderedDict
    from types import SimpleNamespace
    from google import genai
    from src.voice import safety

    monkeypatch.setenv("ANTHROPIC_API_KEY", "invented-provider-key")
    monkeypatch.setenv("GEMINI_API_KEY", "invented-provider-key")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-provider-key")
    monkeypatch.setattr(safety, "_SAFETY_CACHE", OrderedDict())
    monkeypatch.setattr(pipeline.writer, "WRITER_PROVIDER", "anthropic")
    monkeypatch.setattr(pipeline.fact_check, "local_rejection", lambda *args: None)
    monkeypatch.setattr("src.two_bot.copy_gates.copy_rejection", lambda *args: None)
    writer = Mock(return_value=WriterResult(
        tweet="A synthetic weather observation for a safety-only fixture.",
        kill_reason=None, angle_chosen="invented-fixture", era_anchor_used=None,
        peer_comparison_used=None, reasoning="Invented regression input.",
    ))
    monkeypatch.setattr(pipeline.writer, "write_tweet", writer)
    send = Mock(side_effect=_google_error())
    client = SimpleNamespace(models=SimpleNamespace(generate_content=send), close=Mock())
    monkeypatch.setattr(genai, "Client", lambda **kwargs: client)
    fact = Mock(side_effect=AssertionError("No factual check after unavailable safety"))
    critic = Mock(side_effect=AssertionError("No critic after unavailable safety"))
    monkeypatch.setattr(pipeline.fact_check, "fact_check", fact)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    result = {}

    assert pipeline.generate_draft(_bundle(), _fresh_state(), result_out=result) is None
    assert result["kill_stage"] == "budget_exhausted"
    assert result["rejected_candidate"]["status"] == "unavailable"
    writer.assert_called_once()
    send.assert_called_once()
    client.close.assert_called_once()
    fact.assert_not_called()
    critic.assert_not_called()
