"""Single-attempt Google check transport with bounded raw response capture.

Only the local OFF-by-default executor calls this adapter. Raw bytes survive SDK
or model parsing failures. They are evidence, never an automatically passing check.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import time

import httpx

from src.commands.check_execution_journal import MAX_RESPONSE_BYTES

SOCKET_TIMEOUT_SECONDS = 15
READ_BUDGET_SECONDS = 90
LEASE_SECONDS = 180
_monotonic = time.monotonic


@dataclass(frozen=True)
class CheckObservation:
    raw: bytes
    http_status: int | None
    complete: bool
    reason: str


class _CaptureClient(httpx.Client):
    def __init__(self, model: str, *, transport=None):
        super().__init__(
            transport=transport or httpx.HTTPTransport(retries=0, trust_env=False),
            follow_redirects=False,
            trust_env=False,
            timeout=SOCKET_TIMEOUT_SECONDS,
        )
        self.expected_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        )
        self.used = False
        self.observation = CheckObservation(b"", None, False, "transport_unavailable")

    def send(self, request, **kwargs):
        if self.used or request.method != "POST" or str(request.url) != self.expected_url:
            raise ValueError("check_transport_request_not_allowed")
        self.used = True
        request.headers["accept-encoding"] = "identity"
        request.extensions["timeout"] = dict.fromkeys(
            ("connect", "read", "write", "pool"), SOCKET_TIMEOUT_SECONDS
        )
        started, data = _monotonic(), bytearray()
        response = None
        status = None
        complete, reason = False, "transport_unavailable"
        try:
            response = super().send(request, stream=True, follow_redirects=False)
            status = response.status_code
            # Do not let an ignored Accept-Encoding header become an unbounded
            # decompression allocation before the byte-count check can run.
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("unsupported_check_content_encoding")
            for chunk in response.iter_raw(chunk_size=4096):
                remaining = MAX_RESPONSE_BYTES - len(data)
                data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    reason = "size_exceeded"
                    break
                if _monotonic() - started >= READ_BUDGET_SECONDS:
                    reason = "time_exceeded"
                    break
            else:
                complete = _monotonic() - started < READ_BUDGET_SECONDS
                reason = "received" if complete else "time_exceeded"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    complete, reason = False, "cleanup_failed"
            self.observation = CheckObservation(bytes(data), status, complete, reason)
        if not complete:
            raise ValueError("incomplete_check_response")
        return httpx.Response(
            status,
            content=bytes(data),
            request=request,
            headers={"content-type": "application/json"},
        )


class GoogleCheckTransport:
    """No SDK/network retries, redirects, ambient routing or second POST.

    Optional HTTP transport is an offline fixture boundary, not a checker callback.
    Socket operations time out at15s; the read loop stops at its90s budget, with
    at most one socket wait beyond it. A separate lease/deadline check gates use.
    """

    def __init__(self, *, api_key: str, model: str, http_transport=None):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("missing_check_credential")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", model):
            raise ValueError("invalid_check_model")
        from google import genai
        from google.genai import types

        self._http = _CaptureClient(model, transport=http_transport)
        self._used = False
        try:
            self._client = genai.Client(
                vertexai=False,
                api_key=api_key,
                http_options=types.HttpOptions(
                    base_url="https://generativelanguage.googleapis.com",
                    api_version="v1beta",
                    timeout=SOCKET_TIMEOUT_SECONDS * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                    httpx_client=self._http,
                ),
            )
        except Exception:
            self._http.close()
            raise ValueError("check_client_unavailable") from None

    def execute(self, request: dict) -> CheckObservation:
        if self._used:
            raise ValueError("check_transport_already_used")
        self._used = True
        try:
            self._client.models.generate_content(**request)
        except Exception:
            # Provider/SDK errors can contain candidate text or credentials.
            # The captured bounded observation is the only diagnostic returned.
            pass
        return self._http.observation

    def close(self) -> None:
        try:
            self._client.close()
        finally:
            # google-genai deliberately does not close caller-owned HTTP clients.
            self._http.close()
