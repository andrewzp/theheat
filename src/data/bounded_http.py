"""Owned, physically bounded HTTP/1.1 GET transport for owner-run acquisition tools.

``requests``/``urllib``/provider SDKs only offer per-operation timeouts: a
server that drips headers or body bytes, a DNS lookup that hangs, hidden SDK
subrequests and retries, redirects and decompression all escape a caller's
"request" and "byte" counters. This transport owns the socket boundary so the
limits an owner states are the limits that physically apply:

- one absolute wall-clock deadline (monotonic) covering DNS, connect, TLS
  handshake, send, header and body reads, retry backoff and every redirect hop;
- a cap on PHYSICAL requests: every connection that sends a request counts,
  including retries and each redirect hop;
- a cap on bytes received (status line, headers and body, all requests),
  enforced by never asking the socket for more than the remaining allowance
  plus one byte, and a per-response cap checked against Content-Length before
  any body byte is read. Counting is at the application layer: TLS record
  framing is excluded;
- a cap on decoded bytes produced by decompression (Content-Encoding and the
  explicit ``gunzip`` used for ``.gz`` products), checked chunk by chunk;
- cooperative cancellation (``threading.Event``) observed at least every
  ``poll_seconds`` during any read, write, handshake or backoff wait, and
  between connect attempts;
- no background work: every byte is read in the calling thread. The only
  helper thread is a DNS lookup, which writes only to its own local box; once
  the caller has stopped waiting nothing reads or publishes that result, so no
  shared state can change after a bound fires.

Bounds raise ``TransportStop`` (a ``BaseException``) so ordinary ``except
Exception`` retry code cannot swallow them. Provider answers are classified with
the existing source-incident vocabulary (``endpoint_missing``,
``access_refused``, ``rate_limited``, ``provider_error``,
``transport_failure``, ``malformed``) plus ``redirect_refused``,
``response_too_large`` and ``tls_verification_failed``. Only
``transport_failure``, ``provider_error`` and ``rate_limited`` are retried,
inside the same physical-request and deadline allowance.

Plain ``http`` is accepted only for a loopback IP literal named explicitly as
an allowed origin (offline fixtures); every other origin must be ``https``
with default certificate and hostname verification.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import re
import socket
import ssl
import threading
import time
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit
import zlib

SCHEMA = "theheat.bounded-http/v1"
USER_AGENT = "theheat-acquisition/1 (owner-run bounded fetch)"
MAX_HEADER_BYTES = 32 * 1024
MAX_HEADERS = 100
MAX_LINE_BYTES = 4096
READ_CHUNK = 64 * 1024
HEADER_CHUNK = 1024
REDIRECTS = frozenset({301, 302, 303, 307, 308})
RETRYABLE = frozenset({"transport_failure", "provider_error", "rate_limited"})
OUTCOMES = frozenset({"endpoint_missing", "access_refused", "rate_limited", "provider_error", "transport_failure",
                      "malformed", "redirect_refused", "response_too_large", "tls_verification_failed"})
STOP_REASONS = frozenset({"deadline", "cancelled", "request_limit", "transfer_limit", "decoded_limit"})
_STATUS_LINE = re.compile(rb"HTTP/1\.[01] ([1-5][0-9]{2})(?: [\x20-\x7e\x80-\xff]*)?")
_HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_KEPT_HEADERS = ("content-type", "content-length", "last-modified", "etag", "content-encoding", "location")


class TransportStop(BaseException):
    """A stated bound fired. Never retried; the caller records it and stops."""

    def __init__(self, reason: str) -> None:
        if reason not in STOP_REASONS:
            raise ValueError("bounded_http_stop_reason_unknown")
        super().__init__(reason)
        self.reason = reason


class TransportOutcome(Exception):
    """A classified provider/transport outcome for one logical GET."""

    def __init__(self, outcome: str, *, status: int | None = None) -> None:
        if outcome not in OUTCOMES:
            raise ValueError("bounded_http_outcome_unknown")
        super().__init__(outcome)
        self.outcome = outcome
        self.status = status
        self.retryable = outcome in RETRYABLE


@dataclass(frozen=True)
class Limits:
    max_requests: int
    max_transfer_bytes: int
    max_decoded_bytes: int
    deadline_seconds: float
    max_retries: int
    max_redirects: int = 2
    max_response_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        bounds = {"max_requests": (1, 100_000), "max_transfer_bytes": (1, 8 * 1024**3),
                  "max_decoded_bytes": (1, 8 * 1024**3), "deadline_seconds": (0.01, 24 * 3600),
                  "max_retries": (0, 10), "max_redirects": (0, 10), "max_response_bytes": (1, 8 * 1024**3)}
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError("bounded_http_limit_invalid")
            if name != "deadline_seconds" and not isinstance(value, int):
                raise ValueError("bounded_http_limit_invalid")


@dataclass(frozen=True)
class Response:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    transfer_bytes: int

    def receipt(self) -> dict[str, Any]:
        """Retrieval provenance for the exact bytes returned (no body text)."""
        return {"url": self.url, "final_url": self.final_url, "status": self.status,
                "sha256": hashlib.sha256(self.body).hexdigest(), "bytes": len(self.body),
                "last_modified": self.headers.get("last-modified"), "etag": self.headers.get("etag"),
                "content_type": self.headers.get("content-type")}


def _origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        raise ValueError("bounded_http_origin_invalid") from None
    if not host or parts.username or parts.password:
        raise ValueError("bounded_http_origin_invalid")
    if scheme == "http":
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("bounded_http_plain_http_refused")
    elif scheme != "https":
        raise ValueError("bounded_http_origin_invalid")
    return scheme, host, port


class _Stream:
    """Buffered reads of one response, every byte through the transport's bounded recv."""

    def __init__(self, transport: "BoundedTransport", sock: socket.socket, initial: bytes, entry: dict) -> None:
        self.transport, self.sock, self.buffer, self.entry = transport, sock, bytearray(initial), entry
        self.eof = False

    def fill(self, chunk: int = READ_CHUNK) -> bool:
        if self.eof:
            return False
        data = self.transport._recv(self.sock, self.entry, chunk)
        if not data:
            self.eof = True
            return False
        self.buffer += data
        return True

    def line(self) -> bytes:
        while b"\r\n" not in self.buffer:
            if len(self.buffer) > MAX_LINE_BYTES or not self.fill():
                raise TransportOutcome("malformed")
        line, _, rest = bytes(self.buffer).partition(b"\r\n")
        self.buffer = bytearray(rest)
        return line

    def exact(self, count: int) -> bytes:
        while len(self.buffer) < count:
            if not self.fill():
                raise TransportOutcome("transport_failure")  # short body: retryable, never accepted
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def rest(self, cap: int) -> bytes:
        while self.fill():
            if len(self.buffer) > cap:
                raise TransportOutcome("response_too_large")
        return bytes(self.buffer)


class BoundedTransport:
    """GETs under one owner-stated allowance. Create one per acquisition run."""

    def __init__(self, limits: Limits, *, allowed_origins: Iterable[str], cancel: threading.Event | None = None,
                 deadline_at: float | None = None, clock: Callable[[], float] = time.monotonic,
                 poll_seconds: float = 0.25, connect_wait: float = 10.0, backoff_seconds: float = 0.5,
                 tls_context: ssl.SSLContext | None = None) -> None:
        self.limits = limits
        self._origins = frozenset(_origin(origin) for origin in allowed_origins)
        if not self._origins:
            raise ValueError("bounded_http_origin_invalid")
        self._cancel = cancel if cancel is not None else threading.Event()
        self._clock = clock
        self._deadline = deadline_at if deadline_at is not None else clock() + limits.deadline_seconds
        self._poll = max(min(poll_seconds, 1.0), 0.01)
        self._connect_wait = max(connect_wait, self._poll)
        self._backoff = max(backoff_seconds, 0.0)
        self._tls_context = tls_context
        self.counters = {"physical_requests": 0, "retries": 0, "redirects": 0, "transfer_bytes": 0,
                         "decoded_bytes": 0, "responses": 0}
        self.log: list[dict[str, Any]] = []

    # -- bounds ---------------------------------------------------------------

    def remaining(self) -> float:
        return self._deadline - self._clock()

    def check(self) -> None:
        if self._cancel.is_set():
            raise TransportStop("cancelled")
        if self.remaining() <= 0:
            raise TransportStop("deadline")

    def _wait(self, cap: float) -> float:
        self.check()
        return max(min(self.remaining(), cap), 0.001)

    def snapshot(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **self.counters,
                "limits": {"max_requests": self.limits.max_requests,
                           "max_transfer_bytes": self.limits.max_transfer_bytes,
                           "max_decoded_bytes": self.limits.max_decoded_bytes,
                           "deadline_seconds": self.limits.deadline_seconds,
                           "max_retries": self.limits.max_retries, "max_redirects": self.limits.max_redirects,
                           "max_response_bytes": self.limits.max_response_bytes},
                "transfer_counting": "application_bytes_after_tls"}

    def allowed(self, url: str) -> bool:
        try:
            return _origin(url) in self._origins
        except ValueError:
            return False

    # -- public GET -----------------------------------------------------------

    def get(self, url: str) -> Response:
        """One logical GET: bounded retries and redirects, all counted physically."""
        if not self.allowed(url):
            raise ValueError("bounded_http_origin_refused")
        retries = 0
        while True:
            try:
                return self._follow(url)
            except TransportOutcome as outcome:
                if not outcome.retryable or retries >= self.limits.max_retries:
                    raise
                retries += 1
                self.counters["retries"] += 1
                self._sleep(min(self._backoff * (2 ** (retries - 1)), 8.0))

    def gunzip(self, data: bytes) -> bytes:
        """Decode a gzip product (one or more members) inside the decoded-byte allowance."""
        out = bytearray()
        view = memoryview(data)
        position = 0
        while True:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            while not decoder.eof:
                self.check()
                if decoder.unconsumed_tail:
                    piece = decoder.unconsumed_tail
                elif position < len(view):
                    piece = bytes(view[position:position + READ_CHUNK])
                    position += len(piece)
                else:
                    raise TransportOutcome("malformed")  # truncated gzip stream
                allowance = self.limits.max_decoded_bytes - self.counters["decoded_bytes"]
                try:
                    produced = decoder.decompress(piece, allowance + 1)
                except zlib.error:
                    raise TransportOutcome("malformed") from None
                self.counters["decoded_bytes"] += len(produced)
                if self.counters["decoded_bytes"] > self.limits.max_decoded_bytes:
                    raise TransportStop("decoded_limit")
                out += produced
            trailing = decoder.unused_data + bytes(view[position:])
            if trailing[:2] == b"\x1f\x8b":
                view, position = memoryview(trailing), 0
                continue
            if trailing.strip(b"\x00"):
                raise TransportOutcome("malformed")
            return bytes(out)

    # -- internals ------------------------------------------------------------

    def _sleep(self, seconds: float) -> None:
        end = self._clock() + seconds
        while True:
            self.check()
            left = min(end - self._clock(), self.remaining())
            if left <= 0:
                self.check()
                return
            if self._cancel.wait(min(left, self._poll)):
                raise TransportStop("cancelled")

    def _follow(self, url: str) -> Response:
        current, hops = url, 0
        while True:
            status, headers, body, transfer = self._exchange(current)
            if status in REDIRECTS:
                location = headers.get("location")
                hops += 1
                if not location or hops > self.limits.max_redirects:
                    raise TransportOutcome("redirect_refused", status=status)
                target = urljoin(current, location)
                if not self.allowed(target):
                    raise TransportOutcome("redirect_refused", status=status)
                self.counters["redirects"] += 1
                current = target
                continue
            if 200 <= status < 300:
                self.counters["responses"] += 1
                return Response(url, current, status, headers, body, transfer)
            if status in (404, 410):
                raise TransportOutcome("endpoint_missing", status=status)
            if status in (401, 403):
                raise TransportOutcome("access_refused", status=status)
            if status == 429:
                raise TransportOutcome("rate_limited", status=status)
            if status >= 500:
                raise TransportOutcome("provider_error", status=status)
            raise TransportOutcome("malformed", status=status)

    def _exchange(self, url: str) -> tuple[int, dict[str, str], bytes, int]:
        """Exactly one physical request on its own connection."""
        if self.counters["physical_requests"] >= self.limits.max_requests:
            raise TransportStop("request_limit")
        self.check()
        scheme, host, port = _origin(url)
        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        authority = host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"
        request = (f"GET {target} HTTP/1.1\r\nHost: {authority}\r\nUser-Agent: {USER_AGENT}\r\n"
                   "Accept: */*\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n").encode("ascii")
        self.counters["physical_requests"] += 1
        entry: dict[str, Any] = {"url": url, "status": None, "transfer_bytes": 0}
        self.log.append(entry)
        sock: socket.socket | None = None
        try:
            sock = self._connect(self._resolve(host, port))
            if scheme == "https":
                sock = self._handshake(sock, host)
            self._send(sock, request)
            stream = _Stream(self, sock, b"", entry)
            while b"\r\n\r\n" not in stream.buffer:
                if len(stream.buffer) > MAX_HEADER_BYTES:
                    raise TransportOutcome("malformed")
                if not stream.fill(HEADER_CHUNK):  # small reads: the length check runs before the body
                    raise TransportOutcome("transport_failure")  # closed before a complete header
            head, _, rest = bytes(stream.buffer).partition(b"\r\n\r\n")
            stream.buffer = bytearray(rest)
            status, headers = _parse_head(head)
            entry["status"] = status
            body = self._body(stream, headers) if 200 <= status < 300 and status != 204 else b""
            return status, {k: v for k, v in headers.items() if k in _KEPT_HEADERS}, body, entry["transfer_bytes"]
        except ssl.SSLCertVerificationError:
            raise TransportOutcome("tls_verification_failed") from None
        except (ssl.SSLError, OSError):
            raise TransportOutcome("transport_failure") from None
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _resolve(self, host: str, port: int) -> list[tuple[Any, Any]]:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
            return [(family, (host, port))]
        box: list[Any] = []  # written only by the helper; never read once the caller stops waiting

        def lookup() -> None:
            try:
                box.append(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except OSError as error:
                box.append(error)

        helper = threading.Thread(target=lookup, name="theheat-bounded-dns", daemon=True)
        helper.start()
        while helper.is_alive():
            helper.join(self._wait(self._poll))
        self.check()
        if not box or isinstance(box[0], OSError) or not box[0]:
            raise TransportOutcome("transport_failure")
        rows = sorted(box[0], key=lambda row: row[0] != socket.AF_INET)  # IPv4 first; no IPv6 on CI runners
        return [(row[0], row[4]) for row in rows]

    def _connect(self, addresses: list[tuple[Any, Any]]) -> socket.socket:
        for family, address in addresses:
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(self._wait(self._connect_wait))
                sock.connect(address)
                return sock
            except (TimeoutError, OSError):
                sock.close()
        raise TransportOutcome("transport_failure")

    def _handshake(self, sock: socket.socket, host: str) -> socket.socket:
        context = self._tls_context or ssl.create_default_context()
        wrapped = context.wrap_socket(sock, server_hostname=host, do_handshake_on_connect=False)
        while True:
            wrapped.settimeout(self._wait(self._poll))
            try:
                wrapped.do_handshake()
                return wrapped
            except (TimeoutError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
                continue

    def _send(self, sock: socket.socket, data: bytes) -> None:
        view = memoryview(data)
        while view:
            sock.settimeout(self._wait(self._poll))
            try:
                sent = sock.send(view)
            except (TimeoutError, ssl.SSLWantWriteError, ssl.SSLWantReadError):
                continue
            view = view[sent:]

    def _recv(self, sock: socket.socket, entry: dict[str, Any], chunk: int = READ_CHUNK) -> bytes:
        allowance = self.limits.max_transfer_bytes - self.counters["transfer_bytes"]
        while True:
            sock.settimeout(self._wait(self._poll))
            try:
                data = sock.recv(min(chunk, allowance + 1))
                break
            except (TimeoutError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
                continue
        self.counters["transfer_bytes"] += len(data)
        entry["transfer_bytes"] += len(data)
        if self.counters["transfer_bytes"] > self.limits.max_transfer_bytes:
            raise TransportStop("transfer_limit")
        return data

    def _body(self, stream: _Stream, headers: dict[str, str]) -> bytes:
        cap = self.limits.max_response_bytes
        transfer = headers.get("transfer-encoding", "").lower()
        if transfer and transfer != "chunked":
            raise TransportOutcome("malformed")
        if transfer == "chunked":
            body = bytearray()
            while True:
                size_text = stream.line().split(b";", 1)[0].strip()
                if not size_text or len(size_text) > 16 or not all(c in b"0123456789abcdefABCDEF" for c in size_text):
                    raise TransportOutcome("malformed")
                size = int(size_text, 16)
                if size == 0:
                    break
                if len(body) + size > cap:
                    raise TransportOutcome("response_too_large")
                if size > self.limits.max_transfer_bytes - self.counters["transfer_bytes"] + len(stream.buffer):
                    raise TransportStop("transfer_limit")
                body += stream.exact(size)
                if stream.exact(2) != b"\r\n":
                    raise TransportOutcome("malformed")
            for _ in range(MAX_HEADERS):  # trailers end with an empty line
                if not stream.line():
                    break
            else:
                raise TransportOutcome("malformed")
            data = bytes(body)
        elif "content-length" in headers:
            text = headers["content-length"]
            if not text.isdigit() or len(text) > 15:
                raise TransportOutcome("malformed")
            length = int(text)
            if length > cap:
                raise TransportOutcome("response_too_large")
            if length - len(stream.buffer) > self.limits.max_transfer_bytes - self.counters["transfer_bytes"]:
                raise TransportStop("transfer_limit")  # refused before reading a body byte
            data = stream.exact(length)
        else:
            data = stream.rest(cap)
        encoding = headers.get("content-encoding", "identity").lower()
        if encoding == "gzip":
            return self.gunzip(data)
        if encoding not in ("identity", ""):
            raise TransportOutcome("malformed")
        return data


def _parse_head(head: bytes) -> tuple[int, dict[str, str]]:
    lines = head.split(b"\r\n")
    match = _STATUS_LINE.fullmatch(lines[0])
    if not match or len(lines) - 1 > MAX_HEADERS:
        raise TransportOutcome("malformed")
    headers: dict[str, str] = {}
    for raw in lines[1:]:
        name, sep, value = raw.partition(b":")
        if not sep or not _HEADER_NAME.fullmatch(name):
            raise TransportOutcome("malformed")  # also refuses obsolete folded lines
        key, text = name.decode("ascii").lower(), value.strip().decode("latin-1")
        if key in headers:
            if key in ("content-length", "transfer-encoding", "location", "content-encoding"):
                if headers[key] != text:
                    raise TransportOutcome("malformed")
                continue
            headers[key] = f"{headers[key]}, {text}"
        else:
            headers[key] = text
    if "transfer-encoding" in headers and "content-length" in headers:
        raise TransportOutcome("malformed")
    return int(match.group(1)), headers


__all__ = ["BoundedTransport", "Limits", "OUTCOMES", "Response", "SCHEMA", "STOP_REASONS", "TransportOutcome",
           "TransportStop"]
