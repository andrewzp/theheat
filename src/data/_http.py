"""Small HTTP helpers shared by source fetchers."""

from __future__ import annotations

from collections.abc import Mapping
import random
import time
from typing import Any

import requests


_DEFAULT_USER_AGENT = "(theheat-bot, contact@theheat.app)"
_session: requests.Session | None = None
_WAF_RETRY_HOSTS = frozenset({
    "www.metoc.navy.mil",
    "coralreefwatch.noaa.gov",
    "waterservices.usgs.gov",
    "rapidmapping.emergency.copernicus.eu",
})
_waf_budget = {"remaining": 4}


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


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _session = session
    return _session


def _waf_retry_eligible(url: str, status_code: int) -> bool:
    from urllib.parse import urlparse

    return status_code in (403, 429) and urlparse(url).hostname in _WAF_RETRY_HOSTS


def _waf_sleep() -> None:
    time.sleep(random.uniform(15, 45))


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
    waf_retried = False
    for attempt_index in range(attempts):
        try:
            response = _get_session().get(
                url,
                headers=request_headers,
                timeout=timeout,
                **kwargs,
            )
            if (
                _waf_retry_eligible(url, response.status_code)
                and not waf_retried
                and attempt_index < attempts - 1
                and _waf_budget.get("remaining", 0) > 0
            ):
                _waf_budget["remaining"] = max(int(_waf_budget.get("remaining", 0)) - 1, 0)
                waf_retried = True
                _waf_sleep()
                continue
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


def fetch_with_cache_revalidation(
    url: str,
    *,
    cache: dict[str, tuple[str, str]],
    **kwargs: Any,
) -> requests.Response:
    """GET a URL, using ETag/Last-Modified validators from a process cache."""
    cached = cache.get(url)
    headers = dict(kwargs.pop("headers", None) or {})
    if cached is not None:
        validator, _body = cached
        headers[_validator_request_header(validator)] = validator

    response = fetch_with_retry(url, headers=headers, **kwargs)
    if response.status_code == 304 and cached is not None:
        validator, body = cached
        cached_response = requests.Response()
        cached_response.status_code = 200
        cached_response.url = response.url or url
        cached_response.headers.update(response.headers)
        cached_response.headers["X-TheHeat-Cache"] = "revalidated"
        cached_response._content = body.encode(response.encoding or "utf-8")
        cached_response.encoding = response.encoding or "utf-8"
        cache[url] = (validator, body)
        return cached_response

    validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
    if validator:
        cache[url] = (validator, response.text)
    return response


def _validator_request_header(validator: str) -> str:
    if validator.startswith('"') or validator.startswith("W/"):
        return "If-None-Match"
    return "If-Modified-Since"


def _sleep_before_retry(attempt_index: int, backoff_base: float) -> None:
    if backoff_base <= 0:
        return
    base = backoff_base * (2 ** attempt_index)
    time.sleep(base + random.uniform(0, backoff_base))


# Apply IPv4-only at import. The bot imports every source module at startup
# (src/main.py), and they import this module, so this runs before any fetch.
force_ipv4()
