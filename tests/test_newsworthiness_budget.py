"""Bound actual news-verifier attempts without admitting unchecked siblings."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json

import httpx
import pytest

from src.data import newsworthiness as news
from src.orchestrator.sources.newsworthiness import run_newsworthiness
from src.state import _fresh_state
from tests.test_newsworthiness import _event, _impact, NOW
from scripts import source_health_sentinel as sentinel


def fixtures(monkeypatch, answer='{"supported":true}'):
    fetch = Mock(
        return_value=SimpleNamespace(
            text="A retained source excerpt", raise_for_status=lambda: None
        )
    )
    verify = Mock(return_value=answer)
    monkeypatch.setattr(news, "fetch_with_retry", fetch)
    monkeypatch.setattr(news, "_call_verify_flash", verify)
    return fetch, verify


def event(index, *, count=1, url="https://example.org/report"):
    return _event(
        confidence="unverified",
        headline=f"Event {index}",
        impact=[_impact(claim=f"Event {index} claim {i}", value=i, url=url) for i in range(count)],
    )


def test_one_page_with_many_claims_has_six_checks_and_withholds_unchecked_siblings(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    original = event(0, count=1000)
    frozen = deepcopy(original)
    result = news.NewsRetrievalResult()
    out = news._verify_grounded([original], result)
    assert verify.call_count == news.MAX_VERIFY_CALLS == 6
    assert fetch.call_count == 1 and result.verify_fetches == 1
    assert out[0]["impact"] == original["impact"][:6] and original == frozen
    assert result.verify_budget_skips == 994 and result.dropped_unverified == 994
    assert len(result.notes) == 1 and result.verification_usage()["account_spending_cap"] is False


def test_first_claim_of_each_story_precedes_second_claim(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    events = [event(i, count=3) for i in range(6)]
    result = news.NewsRetrievalResult()
    out = news._verify_grounded(events, result)
    assert [call.args[0] for call in verify.call_args_list] == [
        f"Event {i} claim 0" for i in range(6)
    ]
    assert [row["impact"] for row in out] == [[row["impact"][0]] for row in events]
    assert fetch.call_count == 1 and result.verify_budget_skips == 12


def test_identical_impacts_reuse_one_verdict_but_do_not_promote_different_claim(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    first = event(0, count=2)
    second = deepcopy(first)
    result = news.NewsRetrievalResult()
    out = news._verify_grounded([first, second], result)
    assert len(out) == 2 and verify.call_count == 2 and fetch.call_count == 1
    assert result.verify_cache_hits == 2


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("claim", "Different claim"),
        ("value", 999),
        ("url", "https://example.org/another"),
        ("as_of", "2026-07-02"),
        ("source_name", "Different source"),
    ],
)
def test_changed_impact_provenance_cannot_reuse_verdict(monkeypatch, field, new_value):
    fetch, verify = fixtures(monkeypatch)
    first = event(0)
    second = deepcopy(first)
    second["impact"][0][field] = new_value
    result = news.NewsRetrievalResult()
    assert len(news._verify_grounded([first, second], result)) == 2
    assert verify.call_count == 2 and result.verify_cache_hits == 0
    assert fetch.call_count == (2 if field == "url" else 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("place", {"country": "A different country"}),
        ("window_start", "2026-07-01"),
        ("window_end", "2026-07-02"),
    ],
)
def test_changed_event_context_cannot_reuse_verdict(monkeypatch, field, value):
    _, verify = fixtures(monkeypatch)
    first = event(0)
    second = deepcopy(first)
    second[field] = value
    result = news.NewsRetrievalResult()
    news._verify_grounded([first, second], result)
    assert verify.call_count == 2 and result.verify_cache_hits == 0


def test_cache_is_not_shared_between_retrievals_or_changed_page_bytes(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    original = event(0)
    assert news._verify_grounded([original], news.NewsRetrievalResult())
    fetch.return_value.text = "A new source revision"
    verify.return_value = '{"supported":false}'
    assert news._verify_grounded([original], news.NewsRetrievalResult()) == []
    assert verify.call_count == 2 and fetch.call_count == 2


@pytest.mark.parametrize(
    "answer", ['{"supported":false}', '{"supported":"true"}', "{}", "not JSON", ""]
)
def test_negative_and_malformed_verdicts_never_promote_claims(monkeypatch, answer):
    _, verify = fixtures(monkeypatch, answer)
    original = event(0)
    result = news.NewsRetrievalResult()
    assert news._verify_grounded([original, deepcopy(original)], result) == []
    assert result.dropped_unverified == 2
    explicit_false = answer == '{"supported":false}'
    assert verify.call_count == (1 if explicit_false else 2)
    assert result.verify_errors == (0 if explicit_false else 2)


def test_failed_model_requests_consume_budget_without_caching_or_poisoning_page(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    verify.side_effect = RuntimeError("provider unavailable")
    result = news.NewsRetrievalResult()
    assert news._verify_grounded([event(0, count=100)], result) == []
    assert fetch.call_count == 1 and verify.call_count == 6
    assert (
        result.verify_calls == 6 and result.verify_errors == 6 and result.verify_budget_skips == 94
    )


def test_cached_verdict_can_be_reused_after_budget_exhaustion_without_extra_work(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    original = event(0, count=6)
    original["impact"].append(deepcopy(original["impact"][0]))
    original["impact"].append(
        _impact(claim="A new seventh claim", url="https://example.org/unused")
    )
    result = news.NewsRetrievalResult()
    out = news._verify_grounded([original], result)
    assert len(out[0]["impact"]) == 7 and result.verify_cache_hits == 1
    assert fetch.call_count == 1 and verify.call_count == 6 and result.verify_budget_skips == 1


def test_dead_url_is_cached_across_stories_and_preserves_remaining_fetch_budget(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    good = fetch.return_value
    fetch.side_effect = lambda url, **kwargs: (
        good if url.endswith("/good") else (_ for _ in ()).throw(RuntimeError("down"))
    )
    result = news.NewsRetrievalResult()
    out = news._verify_grounded(
        [
            event(0, url="https://example.org/dead"),
            event(1, url="https://example.org/dead"),
            event(2, url="https://example.org/good"),
        ],
        result,
    )
    assert [r["headline"] for r in out] == ["Event 2"]
    assert fetch.call_count == 2 and verify.call_count == 1 and result.verify_fetch_failures == 1


def test_distinct_page_budget_is_independent_from_model_budget(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    result = news.NewsRetrievalResult()
    out = news._verify_grounded(
        [event(i, url=f"https://example.org/{i}") for i in range(6)], result
    )
    assert len(out) == 3 and fetch.call_count == 3 and verify.call_count == 3
    assert result.verify_fetch_budget_skips == 3 and result.verify_budget_skips == 0


def test_structured_leg_uses_neither_budget_and_remains_in_original_order(monkeypatch):
    fetch, verify = fixtures(monkeypatch)
    structured = _event(confidence="structured")
    result = news.NewsRetrievalResult()
    out = news._verify_grounded([event(0, count=12), structured], result)
    assert out[1] is structured and fetch.call_count == 1 and verify.call_count == 6


def test_runner_reports_partial_verification_and_does_not_call_it_quiet_success(monkeypatch):
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    result = news.NewsRetrievalResult(events=[_event()], verify_calls=6, verify_budget_skips=4)
    monkeypatch.setattr("src.orchestrator.sources.newsworthiness.fetch_news_events", lambda: result)
    state = _fresh_state()
    run = {"id": "fixture", "sources": []}
    run_newsworthiness(state, run)
    row = run["sources"][0]
    assert row["status"] == "degraded" and row["error_class"] == "verification_budget"
    assert row["details"]["verification"]["model_calls"] == 6
    assert row["details"]["verification"]["model_budget_skips"] == 4
    assert len(state["news_events"]) == 1
    assert (
        state["source_health"]["newsworthiness"]["runs"][-1]["error_class"] == "verification_budget"
    )


def test_real_verification_error_is_not_hidden_as_intentional_budget_limit(monkeypatch):
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    result = news.NewsRetrievalResult(verify_errors=1, verify_budget_skips=1)
    monkeypatch.setattr("src.orchestrator.sources.newsworthiness.fetch_news_events", lambda: result)
    state = _fresh_state()
    run = {"id": "fixture", "sources": []}
    run_newsworthiness(state, run)
    assert run["sources"][0]["status"] == "degraded"
    assert run["sources"][0].get("error_class") != "verification_budget"


def test_budget_only_health_neither_files_repairs_nor_resolves_old_outage():
    health = {
        "runs": [
            {"status": "failed"},
            {"status": "degraded", "error_class": "verification_budget"},
        ],
        "failed": 1,
        "last_error": "verification model budget",
    }
    result = sentinel.classify_source("newsworthiness", health, now=NOW)
    assert result["category"] == "degraded" and result["issue_resolution_unknown"] is True
    # The exception is specific to this source and an intentionally limited run.
    assert sentinel.classify_source("other", health, now=NOW)["category"] == "failing"
    health["runs"][-1] = {"status": "failed", "error_class": "verification_budget"}
    assert sentinel.classify_source("newsworthiness", health, now=NOW)["category"] == "failing"


@pytest.mark.parametrize("stage", ["verify", "search"])
def test_actual_sdk_attempts_one_http_request_on_transient_failure(monkeypatch, stage):
    from google import genai

    real_client = genai.Client
    requests = []
    clients = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": 503,
                    "message": "synthetic transient failure",
                    "status": "UNAVAILABLE",
                }
            },
        )

    def client(**kwargs):
        assert kwargs["http_options"].retry_options.attempts == 1
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(handler)}
        created = real_client(**kwargs)
        clients.append(created)
        return created

    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(genai, "Client", client)
    try:
        with pytest.raises(Exception, match="503"):
            news._call_verify_flash(
                "A claim", 1, "Source bytes"
            ) if stage == "verify" else news._call_grounded_search(NOW)
        assert len(requests) == 1
    finally:
        for created in clients:
            created.close()


def test_actual_health_issue_planning_keeps_incidents_pending_until_observed_recovery():
    health = {
        "runs": [
            {"status": "failed"},
            {"status": "degraded", "error_class": "verification_budget"},
        ],
        "failed": 1,
        "last_error": "verification model budget",
    }
    report = sentinel.run_sentinel({"newsworthiness": health}, now=NOW)
    assert sentinel.plan_health_issue_actions(report, {"newsworthiness": 123}) == []
    assert sentinel.plan_health_issue_actions(report, {}) == []
    health["runs"] = [{"status": "success"}]
    report = sentinel.run_sentinel({"newsworthiness": health}, now=NOW)
    assert sentinel.plan_health_issue_actions(report, {"newsworthiness": 123}) == [
        {"action": "close", "source": "newsworthiness", "number": 123}
    ]
    health["runs"] = [{"status": "failed"}]
    report = sentinel.run_sentinel({"newsworthiness": health}, now=NOW)
    assert sentinel.plan_health_issue_actions(report, {})[0]["action"] == "create"
