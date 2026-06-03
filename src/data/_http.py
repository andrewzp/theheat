"""Small HTTP helpers shared by source fetchers."""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any

import requests


_DEFAULT_USER_AGENT = "(theheat-bot, contact@theheat.app)"


def force_ipv4() -> None:
    """Force urllib3/requests onto IPv4 for the whole process.

    GitHub-hosted runners have broken/absent IPv6, but several NASA EOSDIS hosts
    (gpm1.gesdisc, firms.modaps) publish AAAA records — so `requests` attempts
    IPv6 first and fails with '[Errno 101] Network is unreachable'. Flipping
    urllib3's HAS_IPV6 flag makes every connection use IPv4, which is strictly
    correct here (every source has an A record; the runner can't reach IPv6
    anyway). Idempotent; safe to call repeatedly.
    """
    import urllib3.util.connection as urllib3_conn

    urllib3_conn.HAS_IPV6 = False


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

    request_headers = dict(headers) if headers else {}
    if not any(key.lower() == "user-agent" for key in request_headers):
        request_headers["User-Agent"] = _DEFAULT_USER_AGENT

    last_transport_error: requests.RequestException | None = None
    for attempt_index in range(attempts):
        try:
            response = requests.get(
                url,
                headers=request_headers,
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


# Apply IPv4-only at import. The bot imports every source module at startup
# (src/main.py), and they import this module, so this runs before any fetch.
force_ipv4()
