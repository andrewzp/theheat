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
