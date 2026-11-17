"""Real SDK wire fixtures only; no provider, source or platform access."""
from copy import deepcopy
from datetime import UTC, datetime
import json
import socket

import httpx
import pytest

from src.data import newsworthiness
from src.two_bot import critic, fact_check, trial_budget, usage_ledger, writer
from tests.two_bot.conftest import _bundle


@pytest.fixture
def sdk(monkeypatch):
    from google import genai

    actual_client = genai.Client
    clients, sends, usage = [], [], []
    payload = {"candidates": [{"content": {"role": "model", "parts": [{"text": "invented"}]},
                                "finishReason": "STOP"}],
               "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10,
                                 "totalTokenCount": 30}}

    def handler(request):
        sends.append(bytes(request.content))
        return httpx.Response(200, json=deepcopy(payload))

    def factory(**kwargs):
        options = kwargs["http_options"]
        options.client_args = {"transport": httpx.MockTransport(handler), "trust_env": False}
        client = actual_client(**kwargs)
        clients.append(client)
        return client

    def no_socket(*args, **kwargs):
        raise AssertionError("real_network_forbidden")

    actual_record = usage_ledger.record_response

    def record(*args, **kwargs):
        usage.append(args[0])
        return actual_record(*args, **kwargs)

    monkeypatch.setenv("GEMINI_API_KEY", "invented-offline-nonfunctional")
    monkeypatch.setattr(genai, "Client", factory)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    monkeypatch.setattr(socket.socket, "connect", no_socket)
    monkeypatch.setattr(usage_ledger, "record_response", record)
    try:
        yield payload, sends, usage
    finally:
        for client in clients:
            client.close()


def call(stage):
    if stage == "fact_check":
        return fact_check._call_gemini("Invented test sentence.", _bundle())
    if stage == "critic":
        return critic._call_gemini("Invented test sentence.", _bundle(), [], [])
    if stage == "writer":
        return writer._call_google("Invented test request.")
    if stage == "newsworthiness_search":
        return newsworthiness._call_grounded_search(datetime(2026, 1, 1, tzinfo=UTC))
    return newsworthiness._call_verify_flash("Invented test claim", 1, "Invented source page.")


STAGES = ("fact_check", "critic", "writer", "newsworthiness_search", "newsworthiness_verify")


@pytest.mark.parametrize("stage", STAGES)
def test_real_ordinary_wire_has_fixed_bound_and_retains_usage(sdk, stage):
    _, sends, usage = sdk
    assert call(stage) == "invented"
    wire = json.loads(sends[0])
    assert wire["generationConfig"]["maxOutputTokens"] == (1024 if stage == "writer" else 8192)
    assert len(sends) == 1 and usage == [stage]


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("case", ("capped", "missing_finish", "blocked", "multiple", "no_candidates", "tool_part"))
def test_incomplete_valid_json_is_unavailable_without_retry_after_usage(sdk, stage, case):
    payload, sends, usage = sdk
    candidate = payload["candidates"][0]
    candidate["content"]["parts"][0]["text"] = '{"verdict":"PASS","passed":true}'
    if case == "capped":
        candidate["finishReason"] = "MAX_TOKENS"
    elif case == "missing_finish":
        del candidate["finishReason"]
    elif case == "blocked":
        payload["promptFeedback"] = {"blockReason": "SAFETY"}
    elif case == "multiple":
        payload["candidates"].append(deepcopy(candidate))
    elif case == "no_candidates":
        payload["candidates"] = []
    else:
        candidate["content"]["parts"].append({"functionCall": {"name": "invented", "args": {}}})
    with pytest.raises(RuntimeError, match="google_response_"):
        call(stage)
    assert len(sends) == 1 and usage == [stage]


def test_full_critic_never_promotes_or_rebuys_capped_pass(sdk):
    payload, sends, usage = sdk
    payload["candidates"][0].update(finishReason="MAX_TOKENS")
    payload["candidates"][0]["content"]["parts"][0]["text"] = json.dumps({
        "verdict": "PASS", "kill_reason": None, "revise_instruction": None, "selected_index": None})
    with pytest.raises(RuntimeError, match="google_response_"):
        critic.critic_review("Invented test sentence.", _bundle(), {})
    assert len(sends) == 1 and usage == ["critic"]


def test_full_fact_checker_never_promotes_or_rebuys_capped_json(sdk):
    payload, sends, usage = sdk
    text, bundle = "A satellite detected a 361 MW thermal signal in Mali.", _bundle()
    assert fact_check.local_rejection(text, [], bundle, {}) is None
    payload["candidates"][0]["finishReason"] = "MAX_TOKENS"
    payload["candidates"][0]["content"]["parts"][0]["text"] = json.dumps({
        "passed": True, "failures": [], "extracted_claims": []})
    with pytest.raises(RuntimeError, match="google_response_"):
        fact_check.fact_check(text, [], bundle, {})
    assert len(sends) == 1 and usage == ["fact_check"]


@pytest.mark.parametrize("case", ("empty", "thought_only", "wrong_role", "missing_content",
                                  "wrong_index", "blocked_rating", "null_rating", "oversize"))
def test_malformed_typed_output_is_held_after_usage(sdk, case):
    payload, sends, usage = sdk
    candidate = payload["candidates"][0]
    part = candidate["content"]["parts"][0]
    if case == "empty":
        part["text"] = " "
    elif case == "thought_only":
        part["thought"] = True
    elif case == "wrong_role":
        candidate["content"]["role"] = "user"
    elif case == "missing_content":
        del candidate["content"]
    elif case == "wrong_index":
        candidate["index"] = 1
    elif case in {"blocked_rating", "null_rating"}:
        candidate["safetyRatings"] = [{"blocked": True if case == "blocked_rating" else None}]
    else:
        part["text"] = "x" * 65_537
    with pytest.raises(RuntimeError, match="google_response_"):
        call("critic")
    assert len(sends) == 1 and usage == ["critic"]


def test_complete_text_keeps_answer_and_omits_thoughts(sdk):
    payload, sends, usage = sdk
    payload["candidates"][0]["content"]["parts"] = [
        {"text": "unpublished reasoning", "thought": True},
        {"text": "answer", "thought": False}, {"text": " text"}]
    assert call("critic") == "answer text"
    assert len(sends) == 1 and usage == ["critic"]


def test_earlier_terminal_trial_cause_survives_response_hold(sdk, tmp_path):
    from google.genai import types

    budget = trial_budget.TrialBudget(lambda row: None, tmp_path / "STOP")
    budget.stopped = "earlier_terminal_cause"
    response = types.GenerateContentResponse(candidates=[{"finish_reason": "MAX_TOKENS"}])
    with trial_budget.trial_scope(budget), pytest.raises(RuntimeError, match="google_response_"):
        trial_budget.completed_google_text(response)
    assert budget.stopped == "earlier_terminal_cause" and not budget.calls


@pytest.mark.parametrize("stage", ("fact_check", "critic"))
def test_finite_uncertain_response_keeps_reservation_and_stops_next_purchase(sdk, tmp_path, stage):
    payload, sends, usage = sdk
    payload["candidates"][0]["finishReason"] = "MAX_TOKENS"
    rows = []
    budget = trial_budget.TrialBudget(rows.append, tmp_path / "STOP")
    budget.begin_candidate("invented")
    with trial_budget.trial_scope(budget):
        with pytest.raises(RuntimeError, match="google_response_"):
            call(stage)
        assert budget.stopped == "trial_provider_response_incomplete"
        reserve = budget.estimated_reserved
        assert reserve > 0 and len(budget.calls) == 1
        with pytest.raises(trial_budget.TrialStopped, match="response_incomplete"):
            call("critic" if stage == "fact_check" else "fact_check")
        assert budget.estimated_reserved == reserve
    assert len(sends) == 1 and usage == [stage]
    assert rows[-1]["outcome"] == "response_returned"
