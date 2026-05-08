"""Small retry helper for transient LLM provider failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def call_with_retries(
    label: str,
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    sleep_seconds: float = 1.0,
) -> T:
    """Run a provider call with bounded retry and preserve the final error."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= attempts:
                raise
            print(
                f"[two_bot.retry] {label} attempt {attempt}/{attempts} failed: "
                f"{type(exc).__name__}: {exc}; retrying"
            )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds * (2 ** (attempt - 1)))

    raise RuntimeError("unreachable retry state")
