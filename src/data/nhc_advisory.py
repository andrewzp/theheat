"""Fixed-source NHC public-advisory reads for an explicitly nominated storm.

Exactly two fixed HTTPS products per current read: the CurrentStorms index and
the nominated bin's public advisory page. No caller URL, host, redirect, local
path, credential, proxy/netrc lookup or automatic retry. Each command or trial
phase gets a finite request budget; exhaustion, slow responses and any HTTP
irregularity hold rather than borrowing time or requests from another phase.
Existing NHC collection (src/data/nhc.py) is not touched or reused here.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
import time

from src.editorial.nhc_advisory import (
    INDEX_URL, MAX_INDEX_BYTES, MAX_PAGE_BYTES, AdvisoryCapture, AdvisoryEvidence, AdvisoryHold, AdvisoryNomination,
    iso, validate_capture,
)

MAX_REQUESTS_PER_PHASE = 32
REQUESTS_PER_READ = 2
CONNECT_SECONDS = 5
READ_SECONDS = 10
REQUEST_SECONDS = 20
USER_AGENT = "(theheat-bot, contact@theheat.app)"


@dataclass
class RequestBudget:
    """Finite requests for one command or trial phase; never refilled."""

    remaining: int = MAX_REQUESTS_PER_PHASE
    used: int = 0

    def consume(self) -> None:
        if self.remaining <= 0:
            raise AdvisoryHold("nhc_advisory_request_budget_exhausted")
        self.remaining -= 1
        self.used += 1


_BUDGET: ContextVar[RequestBudget | None] = ContextVar("nhc_advisory_request_budget", default=None)


@contextmanager
def request_budget_scope(limit: int = MAX_REQUESTS_PER_PHASE) -> Iterator[RequestBudget]:
    if type(limit) is not int or not REQUESTS_PER_READ <= limit <= MAX_REQUESTS_PER_PHASE:
        raise AdvisoryHold("nhc_advisory_request_budget_invalid")
    budget = RequestBudget(remaining=limit)
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def current_budget() -> RequestBudget | None:
    return _BUDGET.get()


def _session():
    import requests
    session = requests.Session()
    session.trust_env = False  # No proxy, netrc or ambient credential discovery.
    session.max_redirects = 0
    return session


def _http_get(url: str, *, limit: int) -> tuple[int, dict, bytes]:
    """One GET of a fixed URL: (status, lowercase headers, body). Network errors hold."""
    import requests
    started = time.monotonic()
    try:
        with _session() as session, session.get(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
            timeout=(CONNECT_SECONDS, READ_SECONDS), allow_redirects=False, stream=True,
        ) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            if response.status_code != 200:
                return response.status_code, headers, b""
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > limit:
                    raise AdvisoryHold("nhc_advisory_response_bound")
                if time.monotonic() - started > REQUEST_SECONDS:
                    raise AdvisoryHold("nhc_advisory_source_slow")
            return response.status_code, headers, bytes(body)
    except AdvisoryHold:
        raise
    except requests.Timeout:
        raise AdvisoryHold("nhc_advisory_source_slow") from None
    except (requests.RequestException, OSError):
        raise AdvisoryHold("nhc_advisory_source_unavailable") from None


def _get(url: str, *, limit: int) -> bytes:
    budget = current_budget()
    if budget is None:
        raise AdvisoryHold("nhc_advisory_request_budget_unscoped")
    budget.consume()
    status, headers, body = _http_get(url, limit=limit)
    if 300 <= status < 400:
        raise AdvisoryHold("nhc_advisory_redirect_refused")
    if status != 200:
        raise AdvisoryHold("nhc_advisory_source_unavailable")
    if headers.get("content-encoding", "identity").lower() != "identity":
        raise AdvisoryHold("nhc_advisory_encoding_invalid")
    declared = headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) != len(body)):
        raise AdvisoryHold("nhc_advisory_partial_response")
    if not body or len(body) > limit:
        raise AdvisoryHold("nhc_advisory_response_bound")
    return body


def read_capture(selected: AdvisoryNomination, *, clock: Callable[[], datetime]) -> AdvisoryCapture:
    """Two fixed requests: index, then the nominated bin's advisory page."""
    if type(selected) is not AdvisoryNomination:
        raise AdvisoryHold("nhc_advisory_nomination_invalid")
    index_bytes = _get(INDEX_URL, limit=MAX_INDEX_BYTES)
    page_bytes = _get(selected.advisory_url, limit=MAX_PAGE_BYTES)
    now = clock()
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise AdvisoryHold("nhc_advisory_clock_invalid")
    return AdvisoryCapture(index_bytes, page_bytes, iso(now.astimezone(UTC)))


def current_evidence(selected: AdvisoryNomination, *, clock: Callable[[], datetime]) -> AdvisoryEvidence:
    """A fresh exact capture validated against the explicit nomination at the read time."""
    capture = read_capture(selected, clock=clock)
    return validate_capture(capture, selected, now=clock())
