"""Authenticated read-only HTTP with fixed-stage diagnostics, never request logs."""

from http.server import BaseHTTPRequestHandler
import json
import os
from threading import Lock

from src.dashboard_preview.auth import authorize, header
from src.dashboard_preview.errors import PreviewError, log_unavailable
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget, read_gist, strict_json

_BUSY = Lock()


def handler_type(*, policy_sha, runtime_sha):
    class GraphicHandler(BaseHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            # Vercel's IPC wrapper prepends a base class with its own logger.
            # Bind on the instance so that wrapper cannot restore request logs.
            setattr(self, "log_message", lambda *args, **kwargs: None)
            super().__init__(*args, **kwargs)

        def log_message(self, format, *args):
            pass

        def log_request(self, code="-", size="-"):
            pass

        def log_error(self, format, *args):
            pass

        def _reply(self, status, body, *, authenticate=False):
            # A disconnected browser needs no retry and must not escape into the
            # platform's exception logger with a private request in its context.
            try:
                self._write_reply(status, body, authenticate=authenticate)
            except OSError:
                self.close_connection = True

        def send_error(self, code, message=None, explain=None):
            # BaseHTTPRequestHandler otherwise generates/logs HTML containing
            # untrusted request-line details (including unsupported methods).
            exc = PreviewError("bad_request")
            self._reply(exc.status, json.dumps(exc.payload()).encode("utf-8"))

        def _write_reply(self, status, body, *, authenticate=False):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            if authenticate:
                self.send_header("WWW-Authenticate", 'Basic realm="theheat dashboard"')
            if status == 405:
                self.send_header("Allow", "POST")
            self.end_headers()
            self.close_connection = True
            if self.command != "HEAD":
                self.wfile.write(body)

        def _handle(self):
            acquired = False
            stage = "authorization"
            try:
                authorize(self.path, self.headers, os.environ)
                stage = "request"
                if self.command != "POST":
                    raise PreviewError("method_not_allowed")
                acquired = _BUSY.acquire(blocking=False)
                if not acquired:
                    raise PreviewError("preview_busy")
                budget = Budget()
                if header(self.headers, "Transfer-Encoding") or header(self.headers, "Content-Encoding"):
                    raise PreviewError("bad_request")
                if header(self.headers, "Content-Type").split(";")[0].strip().lower() != "application/json":
                    raise PreviewError("bad_request")
                length = header(self.headers, "Content-Length")
                if not 1 <= len(length) <= 4 or not length.isascii() or not length.isdecimal() or not 0 < int(length) <= 4096:
                    raise PreviewError("bad_request")
                self.connection.settimeout(min(3, budget.remaining()))
                raw = self.rfile.read(int(length))
                if len(raw) != int(length):
                    raise PreviewError("bad_request")
                request = strict_json(raw, 4096, code="bad_request")

                def current_state():
                    nonlocal stage
                    stage = "state_read"
                    state = read_gist(os.environ, budget)
                    stage = "render"
                    return state

                stage = "render"
                body = build_preview(request, policy_sha=policy_sha, runtime_sha=runtime_sha,
                                     read_state=current_state, budget=budget,
                                     synthetic=False)
                self._reply(200, body)
            except PreviewError as exc:
                if exc.status == 503:
                    log_unavailable(stage)
                self._reply(exc.status, json.dumps(exc.payload(), ensure_ascii=False).encode("utf-8"),
                            authenticate=exc.status == 401)
            except Exception:
                log_unavailable(stage)
                unavailable = PreviewError("preview_unavailable")
                self._reply(unavailable.status, json.dumps(unavailable.payload()).encode("utf-8"))
            finally:
                if acquired:
                    _BUSY.release()

        do_POST = do_GET = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _handle

        def __getattr__(self, name):
            if name.startswith("do_"):
                return self._handle
            raise AttributeError(name)

    return GraphicHandler
