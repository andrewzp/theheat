"""Invented offline news calls cannot escape an active finite trial."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.data import newsworthiness as news
from src.two_bot import trial_budget as limits


NOW = datetime(2026, 10, 21, tzinfo=UTC)
STATES = ("active", "unassigned", "stopped", "stop_file", "call_limit", "cost_scenario")


@pytest.fixture
def boundaries(monkeypatch):
    from google import genai
    from src.two_bot import usage_ledger

    # Replace only this module's environment reference, never read real values.
    credentials = Mock(return_value="invented-offline-key")
    monkeypatch.setattr(news, "os", SimpleNamespace(environ=SimpleNamespace(get=credentials)))
    send = Mock(return_value=SimpleNamespace(text="[]"))
    client = Mock(return_value=SimpleNamespace(models=SimpleNamespace(generate_content=send)))
    monkeypatch.setattr(genai, "Client", client)
    usage = Mock()
    monkeypatch.setattr(usage_ledger, "record_response", usage)
    # Any accidental physical send is trapped, even if the SDK fixture changes.
    import httpx
    import httpx2

    wire = Mock(side_effect=AssertionError("offline fixture forbids physical sends"))
    monkeypatch.setattr(httpx.Client, "send", wire)
    monkeypatch.setattr(httpx2.Client, "send", wire)
    return credentials, client, send, wire, usage


def _budget(tmp_path, state):
    rows = []
    budget = limits.TrialBudget(rows.append, tmp_path / "STOP")
    if state != "unassigned":
        budget.begin_candidate("invented-news-boundary")
    if state == "stopped":
        budget.stopped = "trial_provider_outcome_unknown"
    elif state == "stop_file":
        budget.stop_file.touch()
    elif state == "call_limit":
        budget.calls = [{"candidate": "prior", "stage": "writer"}] * limits.MAX_CALLS
    elif state == "cost_scenario":
        budget.estimated_reserved = limits.MAX_ESTIMATED_USD
    return budget, rows


def _call(route):
    if route == "search":
        return news._call_grounded_search(NOW)
    return news._call_verify_flash("Invented claim", 1, "Invented page")


@pytest.mark.parametrize("route", ("search", "verify"))
@pytest.mark.parametrize("state", STATES)
def test_paid_news_stops_trial_before_credentials_sdk_send_or_usage(tmp_path, boundaries, route, state):
    budget, rows = _budget(tmp_path, state)
    previous_calls, previous_reserve = budget.calls[:], budget.estimated_reserved
    reason = budget.stopped or "trial_unassigned_stage"
    with limits.trial_scope(budget), pytest.raises(limits.TrialStopped, match=f"^{reason}$"):
        _call(route)
    assert budget.stopped == reason
    assert budget.calls == previous_calls and budget.estimated_reserved == previous_reserve
    assert rows == []
    for boundary in boundaries:
        boundary.assert_not_called()


def _event():
    return {
        "kind": "fire", "headline": "Invented report", "place": {"country": "Invented"},
        "window_start": "2026-10-21", "window_end": "2026-10-21", "confidence": "unverified",
        "impact": [{"claim": "Invented claim", "value": 1, "source_name": "Invented",
                    "url": "https://example.invalid/report", "as_of": "2026-10-21"}],
    }


@pytest.mark.parametrize("containment", ("search_leg", "verification"))
@pytest.mark.parametrize("later_stage", ("writer", "safety"))
def test_outer_news_handler_cannot_buy_a_later_supported_call(
    tmp_path, monkeypatch, boundaries, containment, later_stage,
):
    budget, rows = _budget(tmp_path, "active")
    if containment == "search_leg":
        monkeypatch.setattr(news, "_fetch_nifc_events", lambda now: [])
    else:
        # This is an invented source fixture, not a fetch or a factual pass.
        monkeypatch.setattr(news, "fetch_with_retry", lambda *a, **k: SimpleNamespace(
            raise_for_status=lambda: None, text="Invented source page"))
    later_send = Mock()
    with limits.trial_scope(budget):
        if containment == "search_leg":
            result = news.fetch_news_events(NOW)
            assert result.events == [] and any("leg failed" in note for note in result.notes)
        else:
            result = news.NewsRetrievalResult()
            assert news._verify_grounded([_event()], result) == []
            assert result.verify_errors == 1 and result.dropped_unverified == 1
        assert budget.stopped == "trial_unassigned_stage"
        provider, model = limits.MODELS[later_stage]
        request = {"model": model, "contents": "Invented supported call"}
        if provider == "anthropic":
            request = {"model": model, "messages": [{"role": "user", "content": "Invented"}]}
        with pytest.raises(limits.TrialStopped, match="^trial_unassigned_stage$"):
            limits.provider_call(later_stage, provider, request, later_send)
    later_send.assert_not_called()
    assert rows == [] and budget.calls == [] and budget.estimated_reserved == Decimal(0)
    for boundary in boundaries:
        boundary.assert_not_called()


@pytest.mark.parametrize("route", ("search", "verify"))
def test_non_trial_news_retains_request_options_and_usage(boundaries, route):
    from src.config import CHEAP_MODEL

    credentials, client, send, wire, usage = boundaries
    assert limits.current_trial() is None
    assert _call(route) == "[]"
    credentials.assert_called_once_with("GEMINI_API_KEY", "")
    client.assert_called_once()
    options = client.call_args.kwargs["http_options"]
    assert options.timeout == 90000 and options.retry_options.attempts == 1
    send.assert_called_once()
    request = send.call_args.kwargs
    assert request["model"] == CHEAP_MODEL
    if route == "search":
        assert set(request) == {"model", "contents", "config"}
        assert request["contents"] == news.GROUNDED_PROMPT
        assert len(request["config"].tools) == 1
        assert request["config"].tools[0].google_search is not None
    else:
        assert set(request) == {"model", "contents"}
        assert request["contents"] == news.VERIFY_PROMPT_TEMPLATE.format(
            claim="Invented claim", value=1, page_text="Invented page")
    usage.assert_called_once_with(
        f"newsworthiness_{'search' if route == 'search' else 'verify'}",
        send.return_value, CHEAP_MODEL, "google")
    wire.assert_not_called()
