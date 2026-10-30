"""W11.2 — news discovery reserves before egress, counts physical attempts, keeps outcomes.

Invented events/pages and a fake Gemini SDK factory; DNS/connect are trapped.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests

from src.data import _http
from src.data import newsworthiness as news
from src.two_bot import call_inventory as inv
from tests import live_content_harness as h


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    h.trap_network(monkeypatch.setattr)


def _event(index, claims=1, url="https://example.invalid/report"):
    return {"kind": "fire", "headline": f"Invented event {index}", "place": {"country": "Invented"},
            "window_start": "2026-10-29", "window_end": "2026-10-29", "confidence": "unverified",
            "impact": [{"claim": f"Invented claim {index}.{i}", "value": i + 1, "source_name": "Invented",
                        "url": url, "as_of": "2026-10-29"} for i in range(claims)]}


class _Models:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def generate_content(self, **kwargs):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return SimpleNamespace(text=answer, usage_metadata=None)


@pytest.fixture
def sdk(monkeypatch):
    """The real _call_* functions run against a fake client; only its factory is replaced."""
    from google import genai
    holder = SimpleNamespace(models=_Models([]))
    monkeypatch.setattr(genai, "Client", lambda **_kwargs: SimpleNamespace(models=holder.models))
    monkeypatch.setenv("GEMINI_API_KEY", h.INVENTED_TOKEN)
    return holder


def _page_session(monkeypatch, outcomes):
    calls = []

    class Session:
        def get(self, url, **kwargs):
            calls.append(url)
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            response = requests.Response()
            response.status_code, response._content = result, b"Invented page text"
            return response

    monkeypatch.setattr(_http, "_get_session", lambda: Session())
    monkeypatch.setattr(_http, "_sleep_before_retry", lambda *_: None)
    return calls


def test_exhausted_verify_allowance_stops_before_page_fetch_and_model_call(monkeypatch, sdk):
    sdk.models = _Models(['{"supported": true}'] * 10)
    pages = _page_session(monkeypatch, [200] * 10)
    events = [_event(i, url=f"https://example.invalid/{i}") for i in range(8)]
    result = news.NewsRetrievalResult()
    out = news._verify_grounded(events, result)
    summary = result.allowance.summary()["stages"]
    # Existing limits are preserved: three distinct pages, then no page we cannot fetch.
    assert summary["news_verification_page"]["reserved"] == 3 == len(pages) == sdk.models.calls
    assert summary["news_verification_page"]["refused_before_egress"] == 5
    assert summary["newsworthiness_verify"]["reserved"] == 3 and len(out) == 3
    assert result.verify_fetch_budget_skips == 5 and result.verify_budget_skips == 0


def test_verify_calls_stop_at_the_allowance_and_never_exceed_it(monkeypatch, sdk):
    sdk.models = _Models(['{"supported": true}'] * 20)
    _page_session(monkeypatch, [200])
    result = news.NewsRetrievalResult()
    news._verify_grounded([_event(0, claims=9)], result)
    verify = result.allowance.summary()["stages"]["newsworthiness_verify"]
    assert sdk.models.calls == news.MAX_VERIFY_CALLS == verify["reserved"] == verify["physical_attempts"]
    assert verify["refused_before_egress"] == 3 and verify["remaining"] == 0
    assert verify["outcomes"]["returned"] == 6


def test_page_physical_attempts_are_counted_through_the_real_retry_loop(monkeypatch, sdk):
    sdk.models = _Models(['{"supported": true}'])
    calls = _page_session(monkeypatch, [requests.ConnectionError("invented"), 503, 200])
    result = news.NewsRetrievalResult()
    before = inv.runtime_counts().get("news_verification_page", 0)
    news._verify_grounded([_event(0)], result)
    page = result.allowance.summary()["stages"]["news_verification_page"]
    assert len(calls) == 3 and page["reserved"] == 1 and page["physical_attempts"] == 3
    assert inv.runtime_counts()["news_verification_page"] == before + 3
    assert page["outcomes"]["returned"] == 1


def test_timeout_and_malformed_outcomes_stay_spent_and_are_not_retried(monkeypatch, sdk):
    sdk.models = _Models([TimeoutError("invented lost response"), "not json", '{"supported": true}'])
    _page_session(monkeypatch, [200])
    result = news.NewsRetrievalResult()
    out = news._verify_grounded([_event(0, claims=3)], result)
    verify = result.allowance.summary()["stages"]["newsworthiness_verify"]
    assert verify["reserved"] == 3 and verify["physical_attempts"] == 3
    assert verify["outcomes"] == {"returned": 1, "malformed": 1, "unavailable": 0, "unknown": 1, "released_unstarted": 0}
    assert result.verify_errors == 2 and [i["claim"] for i in out[0]["impact"]] == ["Invented claim 0.2"]


def test_missing_credential_is_unavailable_before_egress_yet_keeps_the_existing_count(monkeypatch, sdk):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _page_session(monkeypatch, [200])
    result = news.NewsRetrievalResult()
    news._verify_grounded([_event(0, claims=2)], result)
    verify = result.allowance.summary()["stages"]["newsworthiness_verify"]
    assert sdk.models.calls == 0 and verify["physical_attempts"] == 0
    assert verify["outcomes"]["unavailable"] == 2 and verify["outcomes"]["unknown"] == 0
    assert result.verify_calls == 2  # Unchanged existing semantics: failed requests consume the allowance.


def test_one_grounded_search_per_retrieval_and_discovery_row_reaches_the_run(monkeypatch, sdk):
    from src.orchestrator.sources.newsworthiness import run_newsworthiness
    from src.state import _fresh_state

    sdk.models = _Models(['[{"kind": "fire", "headline": "Invented", "place": {"country": "Invented"}, '
                          '"impact": [{"claim": "Invented claim", "value": 3, "source_name": "Invented", '
                          '"url": "https://example.invalid/r", "as_of": "2026-10-29"}]}]', '{"supported": true}'])
    _page_session(monkeypatch, [200])
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    state = _fresh_state()
    run: dict[str, Any] = {"sources": []}
    run_newsworthiness(state, run)
    row = run["operation_costs"][-1]
    assert row["spend_class"] == "discovery" and row["source"] == "newsworthiness" and row["financial_cap"] is False
    stages = row["allowances"][0]["stages"]
    assert stages["newsworthiness_search"]["reserved"] == 1 == stages["newsworthiness_search"]["physical_attempts"]
    assert stages["newsworthiness_verify"]["outcomes"]["returned"] == 1
    assert row["another_attempt_allowed"]["newsworthiness_search"] is False
    source = next(s for s in run["sources"] if s["source"] == "newsworthiness")
    assert source["details"]["verification"]["spend_class"] == "discovery"
    assert source["details"]["verification"]["allowance"]["stages"]["news_verification_page"]["physical_attempts"] == 1


def test_search_failure_after_egress_is_unknown_and_never_released(monkeypatch, sdk):
    sdk.models = _Models([TimeoutError("invented")])
    monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    result = news.fetch_news_events()
    search = result.allowance.summary()["stages"]["newsworthiness_search"]
    assert search["reserved"] == 1 and search["physical_attempts"] == 1 and search["outcomes"]["unknown"] == 1
    assert search["remaining"] == 0 and any("grounded_search leg failed" in n for n in result.notes)


def test_discovery_and_selection_usage_are_summarized_separately():
    from src.two_bot.usage_summary import summarize_usage
    from datetime import datetime, timezone
    agg = {"in": 1, "cached_in": 0, "cache_write": 0, "out": 1, "calls": 2, "usd": 0.0, "priced_calls": 0,
           "unpriced_calls": 2, "missing_usage_calls": 0, "priced_usd": 0.0}
    state = {"llm_usage": {"2026-10-29": {"writer|invented-model": dict(agg),
                                          "newsworthiness_verify|invented-model": {**agg, "calls": 3, "unpriced_calls": 3}}}}
    summary = summarize_usage(state, now=datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    assert summary["coverage"] == "partial"
    assert summary["spend_classes"]["selection"]["recorded_calls"] == 2
    assert summary["spend_classes"]["discovery"]["recorded_calls"] == 3
    assert summary["spend_classes"]["discovery"]["unpriced_calls"] == 3
