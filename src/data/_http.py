"""Small HTTP helpers shared by source fetchers."""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any

import requests


def fetch_with_retry(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30,
    attempts: int = 3,
    backoff_base: float = 1.0,
    **kwargs: Any,
) -> requests.Response:
    """GET a URL, retrying transport failures and 5xx responses only."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_transport_error: requests.RequestException | None = None
    for attempt_index in range(attempts):
        try:
            response = requests.get(
                url,
                headers=dict(headers) if headers is not None else None,
                timeout=timeout,
                **kwargs,
            )
            if 500 <= response.status_code < 600 and attempt_index < attempts - 1:
                _sleep_before_retry(attempt_index, backoff_base)
                continue
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_transport_error = exc
            if attempt_index >= attempts - 1:
                raise
            _sleep_before_retry(attempt_index, backoff_base)

    if last_transport_error is not None:
        raise last_transport_error
    raise RuntimeError("fetch_with_retry exhausted attempts without a response")


def _sleep_before_retry(attempt_index: int, backoff_base: float) -> None:
    if backoff_base <= 0:
        return
    time.sleep(backoff_base * (2 ** attempt_index))
