"""Small retry helper for transient LLM provider failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class BudgetExhaustedError(RuntimeError):
    """Provider billing/credit limit is exhausted. Non-retryable.

    Raised by the retry helper instead of cycling through retries on
    errors that obviously won't resolve in seconds. Pipeline callers
    surface this as a distinct ``kill_stage="budget_exhausted"`` so the
    dashboard separates a billing outage from a model/code bug.

    Observed 2026-05-15 → 2026-05-17: bot Anthropic key ran dry; 182
    of last 200 suppressions were ``pipeline_error`` with identical
    "credit balance is too low" text, each chewing through 3 retries
    + exponential backoff before bubbling. The fix is non-code (top up
    the key); the existing retry posture only obscured that.
    """


# Substring match on stringified exception. Narrow on purpose — only
# patterns we have actually observed in production. Adding patterns
# that ALSO resolve on retry would swallow transient quota dips and
# turn them into hard kills.
_BUDGET_EXHAUSTED_PATTERNS = (
    "credit balance is too low",  # Anthropic 400
)


def _is_budget_exhausted(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(pattern in message for pattern in _BUDGET_EXHAUSTED_PATTERNS)


def call_with_retries(
    label: str,
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    sleep_seconds: float = 1.0,
) -> T:
    """Run a provider call with bounded retry and preserve the final error.

    Non-retryable errors (currently: billing/credit exhaustion) short-
    circuit the loop and raise :class:`BudgetExhaustedError` on the
    FIRST failure — sleeping 4 seconds before re-confirming the bill
    is unpaid wastes runtime and floods the suppression ledger with
    duplicate retries.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except BudgetExhaustedError:
            raise
        except Exception as exc:
            if _is_budget_exhausted(exc):
                raise BudgetExhaustedError(
                    f"{label}: provider billing exhausted: {exc}"
                ) from exc
            if attempt >= attempts:
                raise
            print(
                f"[two_bot.retry] {label} attempt {attempt}/{attempts} failed: "
                f"{type(exc).__name__}: {exc}; retrying"
            )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds * (2 ** (attempt - 1)))

    raise RuntimeError("unreachable retry state")
