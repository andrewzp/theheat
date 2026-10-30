"""Loopback byte-level HTTP fixture for the bounded transport. Invented bodies only.

Each route holds a queue of actions; the last action repeats. Every accepted
request is recorded with its arrival time, and every action notes when it saw
the client disappear, so tests can prove that no request or egress continues
after the transport has returned.
"""
from __future__ import annotations

import gzip
import socket
import socketserver
import threading
import time
from typing import Callable

Action = Callable[["Fixture", socket.socket, str], None]


def gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), mtime=0)


def _head(status: int, headers: dict[str, str]) -> bytes:
    reason = {200: "OK", 206: "Partial Content", 302: "Found", 404: "Not Found", 403: "Forbidden", 503: "Service Unavailable"}.get(status, "X")
    lines = [f"HTTP/1.1 {status} {reason}"] + [f"{k}: {v}" for k, v in headers.items()] + ["Connection: close", "", ""]
    return "\r\n".join(lines).encode("latin-1")


def ok(body: bytes, *, chunked: bool = False, length: bool = True, extra: dict[str, str] | None = None) -> Action:
    def act(fixture, conn, path):
        headers = {"Content-Type": "application/gzip", "Last-Modified": "Thu, 01 Oct 2026 00:00:00 GMT",
                   "ETag": '"invented-%d"' % len(body), **(extra or {})}
        if chunked:
            headers["Transfer-Encoding"] = "chunked"
            payload = b"".join(b"%x\r\n%s\r\n" % (len(part), part)
                               for part in (body[i:i + 700] for i in range(0, len(body), 700))) + b"0\r\n\r\n"
        else:
            if length:
                headers["Content-Length"] = str(len(body))
            payload = body
        fixture.send(conn, path, _head(200, headers) + payload)
    return act


def status(code: int, location: str | None = None) -> Action:
    def act(fixture, conn, path):
        headers = {"Content-Length": "0"}
        if location:
            headers["Location"] = location
        fixture.send(conn, path, _head(code, headers))
    return act


def raw(data: bytes) -> Action:
    def act(fixture, conn, path):
        fixture.send(conn, path, data)
    return act


def delay_headers(seconds: float) -> Action:
    def act(fixture, conn, path):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(0.05)
        fixture.send(conn, path, _head(200, {"Content-Length": "4"}) + b"late")
    return act


def drip(total: int, interval: float, *, declared: int | None = None) -> Action:
    """Valid headers, then one body byte per interval until the client goes away."""
    def act(fixture, conn, path):
        if not fixture.send(conn, path, _head(200, {"Content-Length": str(declared or total)})):
            return
        for _ in range(total):
            time.sleep(interval)
            if not fixture.send(conn, path, b"x"):
                return
    return act


def truncated(body: bytes, cut: int, etag: str) -> Action:
    """Declares the full length, sends ``cut`` bytes, then closes (a dropped transfer)."""
    def act(fixture, conn, path):
        fixture.send(conn, path, _head(200, {"Content-Length": str(len(body)), "ETag": etag}) + body[:cut])
    return act


def ranged(body: bytes, etag: str) -> Action:
    """Honours ``Range`` only when ``If-Range`` still names this exact entity."""
    def act(fixture, conn, path):
        wanted = fixture.current_headers.get("range", "")
        if wanted.startswith("bytes=") and fixture.current_headers.get("if-range") == etag:
            start = int(wanted[6:].split("-")[0])
            part = body[start:]
            head = _head(206, {"Content-Length": str(len(part)), "ETag": etag,
                               "Content-Range": f"bytes {start}-{len(body) - 1}/{len(body)}"})
            fixture.send(conn, path, head + part)
            return
        fixture.send(conn, path, _head(200, {"Content-Length": str(len(body)), "ETag": etag}) + body)
    return act


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        fixture: Fixture = self.server.fixture  # type: ignore[attr-defined]
        conn = self.request
        conn.settimeout(10)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
        except OSError:
            return
        head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
        path = head[0].split(" ")[1]
        headers = {}
        for line in head[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        fixture.dispatch(conn, path, headers)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Fixture:
    def __init__(self) -> None:
        self.routes: dict[str, list[Action]] = {}
        self.requests: list[tuple[float, str]] = []
        self.request_headers: list[dict[str, str]] = []
        self.current_headers: dict[str, str] = {}
        self.client_gone: list[tuple[float, str]] = []
        self.lock = threading.Lock()
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.fixture = self  # type: ignore[attr-defined]
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def route(self, path: str, *actions: Action) -> None:
        self.routes[path] = list(actions)

    def dispatch(self, conn: socket.socket, path: str, headers: dict[str, str] | None = None) -> None:
        with self.lock:
            self.requests.append((time.monotonic(), path))
            self.current_headers = dict(headers or {})
            self.request_headers.append(self.current_headers)
            queue = self.routes.get(path)
            if not queue:
                action = status(404)
            elif len(queue) > 1:
                action = queue.pop(0)
            else:
                action = queue[0]
        action(self, conn, path)

    def send(self, conn: socket.socket, path: str, data: bytes) -> bool:
        try:
            conn.sendall(data)
            return True
        except OSError:
            with self.lock:
                self.client_gone.append((time.monotonic(), path))
            return False

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class SilentServer:
    """Accepts TCP connections and never answers (a TLS handshake that never completes)."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.accepted: list[socket.socket] = []
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.accepted.append(conn)

    def close(self) -> None:
        self.sock.close()
        for conn in self.accepted:
            conn.close()
