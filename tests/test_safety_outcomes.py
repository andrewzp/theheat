"""Completed content checks, explicit uncertainty and exact bounded reuse."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock
import hashlib
import re

import httpx
import pytest

from src.voice import safety
from src.two_bot import usage_ledger
from src.editorial.policy import current_editorial_policy

TEXT = "A synthetic weather observation for a safety-only fixture."


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    safety._SAFETY_CACHE.clear()
    usage_ledger._BUFFER.clear()
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "synthetic-key")
    yield
    safety._SAFETY_CACHE.clear()
    usage_ledger._BUFFER.clear()


@pytest.fixture
def sdk(monkeypatch):
    from google import genai

    response = SimpleNamespace(
        text="NO",
        usage_metadata=SimpleNamespace(
            prompt_token_count=30, candidates_token_count=1, cached_content_token_count=0
        ),
    )
    generate = Mock(return_value=response)
    factory = Mock(return_value=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(genai, "Client", factory)
    return generate, factory


@pytest.mark.parametrize(
    "answer,verdict,allowed",
    [
        ("NO", "allow", True),
        (" no\n", "allow", True),
        ("YES", "reject", False),
        ("yes", "reject", False),
    ],
)
def test_only_completed_unambiguous_answers_establish_a_verdict(sdk, answer, verdict, allowed):
    generate, _ = sdk
    generate.return_value.text = answer
    result = safety.check_llm_result(TEXT)
    assert (
        result.execution_status == "completed"
        and result.verdict == verdict
        and result.allowed is allowed
    )
    assert result.text_sha256 == hashlib.sha256(TEXT.encode()).hexdigest()
    assert result.prompt_sha256 and result.checked_at and not result.cache_hit
    with pytest.raises(FrozenInstanceError):
        result.verdict = "allow"


@pytest.mark.parametrize(
    "answer",
    [None, "", "NO but actually YES", "NO.", "YES OR NO", '{"allowed":true}', "unrelated text"],
)
def test_empty_or_ambiguous_answers_do_not_pass_or_enter_cache(sdk, answer):
    generate, _ = sdk
    generate.return_value.text = answer
    result = safety.check_llm_result(TEXT)
    assert result.execution_status == "failed" and result.verdict is None and not result.allowed
    assert safety.check_llm(TEXT)[0] is False
    assert generate.call_count == 2 and len(usage_ledger._BUFFER) == 2 and not safety._SAFETY_CACHE


def test_missing_credentials_block_even_a_previously_cached_pass(monkeypatch, sdk):
    generate, _ = sdk
    assert safety.check_llm_result(TEXT).allowed
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    result = safety.check_llm_result(TEXT)
    assert result.execution_status == "unavailable" and not result.allowed and not result.cache_hit
    assert result.reason == "safety_unavailable: missing credential"
    assert generate.call_count == 1


def test_provider_failure_is_uncertainty_not_a_tone_rejection_or_cached_pass(sdk):
    generate, _ = sdk
    generate.side_effect = RuntimeError("private provider exception body")
    for _ in range(2):
        result = safety.check_llm_result(TEXT)
        assert (
            result.execution_status == "unavailable"
            and result.verdict is None
            and not result.allowed
        )
        assert "private provider" not in result.reason
    assert generate.call_count == 2 and not usage_ledger._BUFFER and not safety._SAFETY_CACHE


def test_returned_response_is_accounted_even_if_text_access_fails(sdk):
    generate, _ = sdk

    class BrokenText:
        usage_metadata = generate.return_value.usage_metadata

        @property
        def text(self):
            raise ValueError("unreadable")

    generate.return_value = BrokenText()
    result = safety.check_llm_result(TEXT)
    assert not result.allowed and result.verdict is None
    assert generate.call_count == 1 and len(usage_ledger._BUFFER) == 1
    assert not safety._SAFETY_CACHE


def test_failed_accounting_does_not_change_a_valid_verdict(monkeypatch, sdk):
    generate, _ = sdk
    monkeypatch.setattr(
        usage_ledger, "record_response", Mock(side_effect=RuntimeError("broken observer"))
    )
    assert safety.check_llm_result(TEXT).allowed
    assert generate.call_count == 1


def test_exact_reuse_retains_original_time_and_counts_no_new_response(sdk):
    generate, _ = sdk
    first = safety.check_llm_result(TEXT)
    second = safety.check_llm_result(TEXT)
    assert second.cache_hit and second.allowed and second.checked_at == first.checked_at
    assert second.text_sha256 == first.text_sha256 and second.prompt_sha256 == first.prompt_sha256
    assert generate.call_count == 1 and len(usage_ledger._BUFFER) == 1


def test_completed_rejection_can_be_reused_but_changed_text_gets_another_check(sdk):
    generate, _ = sdk
    generate.return_value.text = "YES"
    assert not safety.check_llm_result(TEXT).allowed
    assert safety.check_llm_result(TEXT).cache_hit
    generate.return_value.text = "NO"
    changed = safety.check_llm_result(TEXT + " Changed.")
    assert changed.allowed and not changed.cache_hit and generate.call_count == 2


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("GEMINI_SAFETY_MODEL", "gemini-different-fixture"),
        ("SAFETY_PROMPT_TEMPLATE", "Updated policy: {tweet}"),
    ],
)
def test_model_or_runtime_prompt_change_invalidates_reuse_and_editorial_policy(
    monkeypatch, sdk, field, new_value
):
    generate, _ = sdk
    before = current_editorial_policy()
    assert before is not None and safety.check_llm_result(TEXT).allowed
    monkeypatch.setattr(safety, field, new_value)
    assert not safety.check_llm_result(TEXT).cache_hit
    assert current_editorial_policy() != before and generate.call_count == 2


@pytest.mark.parametrize(
    "template", ["A constant broken template", "Escaped {{tweet}}", "Wrong {text}"]
)
def test_broken_prompt_cannot_pass_without_reviewing_text(monkeypatch, sdk, template):
    generate, _ = sdk
    monkeypatch.setattr(safety, "SAFETY_PROMPT_TEMPLATE", template)
    result = safety.check_llm_result(TEXT)
    assert not result.allowed and result.reason == "safety_invalid_prompt"
    assert not safety._SAFETY_CACHE
    generate.assert_not_called()


@pytest.mark.parametrize("elapsed", [300, 301, -1])
def test_expiry_and_clock_reversal_require_another_request(monkeypatch, sdk, elapsed):
    generate, _ = sdk
    clock = [1000.0]
    monkeypatch.setattr(safety.time, "monotonic", lambda: clock[0])
    safety.check_llm_result(TEXT)
    clock[0] += elapsed
    assert not safety.check_llm_result(TEXT).cache_hit
    assert generate.call_count == 2


def test_cache_is_bounded_and_retains_recently_used_entries(monkeypatch, sdk):
    generate, _ = sdk
    monkeypatch.setattr(safety, "SAFETY_CACHE_SIZE", 2)
    safety.check_llm_result("First fixture.")
    safety.check_llm_result("Second fixture.")
    safety.check_llm_result("First fixture.")
    safety.check_llm_result("Third fixture.")
    assert len(safety._SAFETY_CACHE) == 2 and generate.call_count == 3
    assert safety.check_llm_result("First fixture.").cache_hit
    assert not safety.check_llm_result("Second fixture.").cache_hit
    assert generate.call_count == 4


def test_regex_rules_still_run_on_cached_model_pass(monkeypatch, sdk):
    generate, _ = sdk
    assert safety.run_safety_pipeline(TEXT) == (True, None)
    monkeypatch.setattr(safety, "BANNED_PATTERNS", [re.compile("synthetic")])
    assert safety.run_safety_pipeline(TEXT)[0] is False
    assert generate.call_count == 1


@pytest.mark.parametrize("text", ["", "x" * 281, "\ud800", None])
def test_invalid_direct_input_never_calls_provider(sdk, text):
    generate, _ = sdk
    result = safety.check_llm_result(text)
    assert not result.allowed and result.execution_status == "failed"
    generate.assert_not_called()


def test_real_sdk_uses_bounded_timeout_and_one_transport_attempt(monkeypatch):
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
                    "message": "synthetic temporary error",
                    "status": "UNAVAILABLE",
                }
            },
        )

    def factory(**kwargs):
        opts = kwargs["http_options"]
        assert opts.timeout == 90000 and opts.retry_options.attempts == 1
        opts.client_args = {"transport": httpx.MockTransport(handler)}
        client = real_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(genai, "Client", factory)
    try:
        result = safety.check_llm_result(TEXT)
        assert (
            not result.allowed and result.execution_status == "unavailable" and len(requests) == 1
        )
    finally:
        for client in clients:
            client.close()
