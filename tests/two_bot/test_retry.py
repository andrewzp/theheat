import pytest

from src.two_bot.retry import BudgetExhaustedError, call_with_retries


def test_call_with_retries_returns_after_transient_exception():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("slow provider")
        return "ok"

    assert call_with_retries("test", flaky, sleep_seconds=0) == "ok"
    assert calls["count"] == 2


def test_call_with_retries_preserves_final_error():
    def always_boom():
        raise RuntimeError("still down")

    with pytest.raises(RuntimeError, match="still down"):
        call_with_retries("test", always_boom, attempts=2, sleep_seconds=0)


def test_call_with_retries_short_circuits_on_budget_exhausted():
    """Anthropic credit-exhausted errors are 400s that will not resolve
    in 1-3 seconds. Retrying floods the suppression ledger with duplicate
    rows and wastes ~5s per draft. Short-circuit on first failure and
    raise BudgetExhaustedError so the pipeline can record kill_stage=
    "budget_exhausted" instead of generic pipeline_error.
    """
    calls = {"count": 0}

    def out_of_credit():
        calls["count"] += 1
        raise RuntimeError(
            "BadRequestError: Error code: 400 - "
            "{'error': {'message': 'Your credit balance is too low to "
            "access the Anthropic API. Please go to Plans & Billing to "
            "upgrade or purchase credits.'}}"
        )

    with pytest.raises(BudgetExhaustedError, match="billing exhausted"):
        call_with_retries("test writer", out_of_credit, attempts=3, sleep_seconds=0)
    assert calls["count"] == 1  # No retry; short-circuited on first failure


def test_call_with_retries_passes_through_normal_errors_unchanged():
    """Sanity guard: only the budget-exhausted pattern short-circuits.
    Generic RuntimeError still flows through the existing 3-attempt loop.
    """
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("slow provider")
        return "ok"

    assert call_with_retries("test", flaky, attempts=3, sleep_seconds=0) == "ok"
    assert calls["count"] == 3


def test_call_with_retries_reraises_budget_exhausted_from_callee():
    """Defensive: if a callee starts raising BudgetExhaustedError directly
    (e.g. a future SDK that pre-classifies), the retry helper must not
    re-wrap or re-classify it.
    """
    pre_classified = BudgetExhaustedError("upstream already classified")

    def already_classified():
        raise pre_classified

    with pytest.raises(BudgetExhaustedError) as exc_info:
        call_with_retries("test", already_classified, attempts=3, sleep_seconds=0)
    assert exc_info.value is pre_classified  # Not re-wrapped


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 410, 413, 415, 422])
def test_real_anthropic_client_errors_preserve_identity_without_retry(status):
    import anthropic
    import httpx
    from unittest.mock import Mock

    response = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    error = anthropic.APIStatusError("fixture rejection", response=response, body={})
    call = Mock(side_effect=error)
    with pytest.raises(anthropic.APIStatusError) as captured:
        call_with_retries("fixture", call, sleep_seconds=0)
    assert captured.value is error and call.call_count == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_real_google_client_errors_are_not_retried(status):
    from google.genai import errors
    from unittest.mock import Mock

    error = errors.ClientError(status, {"error":{"code":status, "message":"fixture", "status":"INVALID_ARGUMENT"}})
    call = Mock(side_effect=error)
    with pytest.raises(errors.ClientError) as captured:
        call_with_retries("fixture", call, sleep_seconds=0)
    assert captured.value is error and call.call_count == 1


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_retryable_statuses_keep_existing_attempt_bound(status):
    import anthropic
    import httpx
    from unittest.mock import Mock

    error = anthropic.APIStatusError("fixture", response=httpx.Response(status,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")), body={})
    call = Mock(side_effect=error)
    with pytest.raises(anthropic.APIStatusError) as captured:
        call_with_retries("fixture", call, attempts=3, sleep_seconds=0)
    assert captured.value is error and call.call_count == 3


def test_httpx_response_status_is_read_without_relying_on_exception_text():
    import httpx
    from unittest.mock import Mock

    request = httpx.Request("POST", "https://example.invalid")
    error = httpx.HTTPStatusError("no status number in text", request=request,
                                  response=httpx.Response(400, request=request))
    call = Mock(side_effect=error)
    with pytest.raises(httpx.HTTPStatusError) as captured:
        call_with_retries("fixture", call, sleep_seconds=0)
    assert captured.value is error and call.call_count == 1


def test_text_numbers_do_not_classify_unknown_error_as_nonretryable():
    from unittest.mock import Mock
    call = Mock(side_effect=RuntimeError("Network stopped while sending 400 tokens"))
    with pytest.raises(RuntimeError):
        call_with_retries("fixture", call, attempts=2, sleep_seconds=0)
    assert call.call_count == 2


def test_conflicting_or_raising_status_fields_remain_unknown():
    from unittest.mock import Mock

    class Conflicting(Exception):
        status_code = 400
        code = 503

    class Raising(Exception):
        @property
        def status_code(self):
            raise ValueError("unavailable")

    for error in (Conflicting("fixture"), Raising("fixture")):
        call = Mock(side_effect=error)
        with pytest.raises(type(error)):
            call_with_retries("fixture", call, attempts=2, sleep_seconds=0)
        assert call.call_count == 2


def test_structured_billing_400_keeps_distinct_budget_error():
    import anthropic
    import httpx
    from unittest.mock import Mock

    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    error = anthropic.BadRequestError("Your credit balance is too low", response=response, body={})
    call = Mock(side_effect=error)
    with pytest.raises(BudgetExhaustedError):
        call_with_retries("fixture", call, sleep_seconds=0)
    assert call.call_count == 1
