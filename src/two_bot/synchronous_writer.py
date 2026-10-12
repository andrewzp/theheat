"""One granted synchronous writer POST, with bounded original response evidence.

This transport does not authorize source evidence, settle spending, interpret a
candidate or approve a draft. The scoped authority supplies its acknowledged
grant at the SDK's actual request boundary. It defaults to no execution.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import hashlib
import json
import re
import time

from src.commands.schema import canonical_json
from src.two_bot import writer
from src.two_bot.provider_http import anthropic_httpx

MAX_REQUEST_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 131_072
SOCKET_TIMEOUT_SECONDS = 15
READ_BUDGET_SECONDS = 180
ENDPOINT = "https://api.anthropic.com/v1/messages"
_monotonic = time.monotonic


@dataclass(frozen=True)
class WriterDispatchGrant:
    """Only a scoped authority's acknowledged transaction supplies this value."""
    grant_id: str
    request_sha256: str
    wire_sha256: str


@dataclass(frozen=True)
class WriterObservation:
    raw: bytes = field(default=b"", repr=False)
    wire: bytes = field(default=b"", repr=False)
    http_status: int | None = None
    complete: bool = False
    reason: str = "not_requested"
    grant_status: str = "not_requested"
    grant_id: str | None = None


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_writer_request_key")
        result[key] = value
    return result


def _request_bytes(request: dict) -> bytes:
    """Pin transport input to the existing one-sample request builder."""
    try:
        messages = request["messages"]
        if (type(messages) is not list or len(messages) != 1
                or type(messages[0]) is not dict
                or set(messages[0]) != {"role", "content"}
                or type(messages[0]["content"]) is not str):
            raise ValueError("invalid_writer_request")
        raw = canonical_json(request).encode()
        expected = canonical_json(writer.anthropic_writer_request(messages[0]["content"])).encode()
        if raw != expected or not 0 < len(raw) <= MAX_REQUEST_BYTES:
            raise ValueError("invalid_writer_request")
        return raw
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid_writer_request") from None


def _capture_client(request: dict, authorize: Callable[[bytes], WriterDispatchGrant | None],
                    http_transport=None):
    http = anthropic_httpx()
    expected = _request_bytes(request)

    # SDK versions use two verified public HTTP client families at runtime.
    class CaptureClient(http.Client):  # type: ignore[name-defined]
        def __init__(self):
            super().__init__(
                transport=(http_transport if http_transport is not None
                           else http.HTTPTransport(retries=0, trust_env=False)),
                follow_redirects=False, trust_env=False, timeout=SOCKET_TIMEOUT_SECONDS,
            )
            self.used = False
            self.observation = WriterObservation()

        def send(self, request, **kwargs):
            if self.used:
                raise ValueError("writer_transport_already_used")
            self.used = True
            try:
                wire = request.content
                if (request.method != "POST" or str(request.url) != ENDPOINT
                        or not 0 < len(wire) <= MAX_REQUEST_BYTES):
                    raise ValueError("writer_request_not_allowed")
                decoded = json.loads(wire.decode("utf-8"), object_pairs_hook=_object)
                if canonical_json(decoded).encode() != expected:
                    raise ValueError("writer_request_changed")
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.observation = WriterObservation(reason="request_refused")
                raise ValueError("writer_request_refused") from None

            # A callback exception may follow a lost COMMIT acknowledgment.
            # Do not label it definitely absent, or send/retry without the grant.
            self.observation = WriterObservation(wire=wire, reason="grant_unconfirmed",
                                                  grant_status="unconfirmed")
            grant = authorize(wire)
            if grant is None:
                self.observation = WriterObservation(wire=wire, reason="grant_refused",
                                                      grant_status="refused")
                raise ValueError("writer_grant_refused")
            if (type(grant) is not WriterDispatchGrant
                    or not isinstance(grant.grant_id, str)
                    or re.fullmatch(r"[a-f0-9]{64}", grant.grant_id) is None
                    or grant.request_sha256 != _digest(expected)
                    or grant.wire_sha256 != _digest(wire)):
                raise ValueError("writer_grant_unconfirmed")

            request.headers["accept-encoding"] = "identity"
            request.extensions["timeout"] = dict.fromkeys(
                ("connect", "read", "write", "pool"), SOCKET_TIMEOUT_SECONDS
            )
            started, data = _monotonic(), bytearray()
            status, response = None, None
            complete, reason = False, "transport_unavailable"
            cleanup_failed = False

            class ObservedStream(http.SyncByteStream):  # type: ignore[name-defined]
                def __init__(self, stream):
                    self.stream = stream

                def __iter__(self):
                    nonlocal reason
                    for incoming in self.stream:
                        for offset in range(0, len(incoming), 4096):
                            chunk = incoming[offset:offset + 4096]
                            remaining = MAX_RESPONSE_BYTES - len(data)
                            data.extend(chunk[:remaining])
                            if len(chunk) > remaining:
                                reason = "size_exceeded"
                                raise ValueError("writer_response_size_exceeded")
                            if _monotonic() - started >= READ_BUDGET_SECONDS:
                                reason = "time_exceeded"
                                raise ValueError("writer_response_time_exceeded")
                            yield chunk

                def close(self):
                    nonlocal cleanup_failed
                    try:
                        self.stream.close()
                    except Exception:
                        cleanup_failed = True
                        raise

            try:
                response = super().send(request, stream=True, follow_redirects=False)
                status = response.status_code
                # iter_raw itself closes at EOF; remember a failure there even
                # when Response has already marked itself closed.
                response.stream = ObservedStream(response.stream)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    reason = "unsupported_content_encoding"
                    raise ValueError("unsupported_writer_content_encoding")
                # Capture before HTTPX's chunk buffer: a short prefix must not
                # disappear if the next socket read or EOF cleanup fails.
                for _ in response.iter_raw(chunk_size=4096):
                    pass
                complete = _monotonic() - started < READ_BUDGET_SECONDS
                reason = "received" if complete else "time_exceeded"
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        cleanup_failed = True
                if cleanup_failed:
                    complete, reason = False, "cleanup_failed"
                self.observation = WriterObservation(
                    raw=bytes(data), wire=wire, http_status=status, complete=complete,
                    reason=reason, grant_status="granted", grant_id=grant.grant_id,
                )
            if not complete:
                raise ValueError("incomplete_writer_response")
            # SDK status/model parsing may now fail. The original captured bytes
            # above survive it, and no provider envelope becomes a candidate here.
            return http.Response(status, content=bytes(data), request=request,
                                 headers={"content-type": "application/json"})

    return CaptureClient()


def execute_writer_once(request: dict, *, api_key: str,
                        authorize: Callable[[bytes], WriterDispatchGrant | None],
                        enabled: bool = False, http_transport=None) -> WriterObservation:
    """One real SDK call; no retries, ambient routes or returned approval.

    The180s response budget can include one additional15s socket wait. This is
    not a hard process/DNS/CPU deadline. The authority owns source deadlines and
    must persist a returned observation even after eligibility has changed.
    """
    if type(enabled) is not bool:
        raise ValueError("writer_enabled_requires_boolean")
    if not enabled:
        return WriterObservation(reason="disabled", grant_status="disabled")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("missing_writer_credential")
    if not callable(authorize):
        raise ValueError("writer_grant_boundary_required")
    raw = _request_bytes(request)
    detached = json.loads(raw)
    http = _capture_client(detached, authorize, http_transport)
    client = None
    result = WriterObservation(reason="client_unavailable")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key, base_url="https://api.anthropic.com",
                           max_retries=0, timeout=SOCKET_TIMEOUT_SECONDS, http_client=http)
        try:
            client.messages.create(**detached)
        except Exception:
            # Never echo provider/SDK/authority exception strings or credentials.
            pass
        result = http.observation
    except Exception:
        result = http.observation if http.used else result
    finally:
        try:
            if client is not None:
                client.close()
            if not http.is_closed:
                http.close()
        except Exception:
            result = replace(result, complete=False, reason="cleanup_failed")
    return result
