"""P16 — a source runner's cancellation token: its own deadline, its late evidence, shared budgets."""

from __future__ import annotations

import pytest
import requests

from src.data import _http
from src.two_bot import call_inventory as inv
from tests import live_content_harness as h
from tests.real_closure import p16_fixtures as fx


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.trap_network(monkeypatch.setattr)
    monkeypatch.setattr(inv, "_CANCELLED", {})


def test_a_deadline_token_allows_the_deadline_instant_and_refuses_after_it():
    now = {"t": 10.0}
    token = inv.CancelToken("invented", deadline=10.0, clock=lambda: now["t"], deadline_reason="runner_budget_exceeded")
    assert inv.run_cancellable(token, inv.consume, "source_http_get", join=False).stage == "source_http_get"
    assert token.reason is None
    now["t"] = 10.000001
    with pytest.raises(inv.OperationCancelled, match="runner_budget_exceeded"):
        inv.run_cancellable(token, inv.consume, "source_http_get", join=False)
    assert token.refused == 1 and token.reason == "runner_budget_exceeded"
    assert inv.unjoined_calls()["cancelled_before_egress"] == [{"stage": "source_http_get", "refused_calls": 1}]


def test_a_token_without_a_deadline_is_unchanged():
    token = inv.CancelToken("invented")
    assert not token.cancelled and token.deadline is None
    assert inv.run_cancellable(token, inv.consume, "source_http_get", join=False).stage == "source_http_get"


def test_a_response_returning_after_cancellation_is_counted_late_with_its_dispatch_attribution():
    token = inv.CancelToken("invented")

    def dispatch_then_late_response():
        inv.consume("writer", provider="anthropic", model="invented-model")
        token.cancel("runner_budget_exceeded")  # The deadline passes while the request is in flight.
        return inv.take_dispatch_attribution("writer")

    attribution = inv.run_cancellable(token, dispatch_then_late_response)
    assert attribution["status"] == "unjoined"  # Unchanged: no operation was open at dispatch.
    assert token.late_responses == {"writer": 1} and token.refused == 0


def test_cancelled_work_does_not_spend_the_shared_waf_retry_budget(monkeypatch):
    """Counterexample on .51: a late 403 spent a process-wide WAF unit and slept before refusal."""
    monkeypatch.setattr(_http, "_waf_budget", {"remaining": 4})
    monkeypatch.setattr(_http, "_waf_sleep", lambda: pytest.fail("cancelled work never sleeps for a WAF retry"))
    token = inv.CancelToken("invented")
    url = "https://coralreefwatch.noaa.gov/invented-p16"

    class LateWafSession:
        def get(self, request_url, **_):
            token.cancel("runner_budget_exceeded")  # The 403 arrives after the deadline.
            return fx.response(request_url, "invented block page", 403)

    monkeypatch.setattr(_http, "_session", LateWafSession())
    with pytest.raises(requests.HTTPError):
        inv.run_cancellable(token, _http.fetch_with_retry, url, attempts=3)
    assert _http._waf_budget == {"remaining": 4} and token.refused == 0


def test_uncancelled_work_keeps_the_existing_waf_retry(monkeypatch):
    monkeypatch.setattr(_http, "_waf_budget", {"remaining": 4})
    monkeypatch.setattr(_http, "_waf_sleep", lambda: None)
    answers = iter([403, 200])

    class WafThenOk:
        def get(self, request_url, **_):
            return fx.response(request_url, "invented body", next(answers))

    monkeypatch.setattr(_http, "_session", WafThenOk())
    token = inv.CancelToken("invented")
    response = inv.run_cancellable(token, _http.fetch_with_retry, "https://coralreefwatch.noaa.gov/invented-p16",
                                   attempts=3)
    assert response.status_code == 200 and _http._waf_budget == {"remaining": 3}
