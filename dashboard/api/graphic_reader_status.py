"""Fixed reader-only entry through the same verified runtime bootstrap."""

from http.server import BaseHTTPRequestHandler
from pathlib import Path
import runpy


class UnavailableHandler(BaseHTTPRequestHandler):
    """Even a missing/unparseable sibling bootstrap has a fixed private reply."""
    def __init__(self, *args, **kwargs):
        setattr(self, "log_message", lambda *args, **kwargs: None)
        super().__init__(*args, **kwargs)

    def _unavailable(self):
        body = b'{"code":"preview_unavailable","error":"The preview is unavailable. Your draft has not changed; try again later."}'
        try:
            self.send_response_only(503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except OSError:
            pass
        self.close_connection = True

    def send_error(self, *args, **kwargs):
        self._unavailable()

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._unavailable
        raise AttributeError(name)


try:
    # One static sibling, whose bootstrap verifies both entries before importing
    # any archive source. Never select a file or mode from environment/input.
    loaded = runpy.run_path(str(Path(__file__).with_name("graphic_preview.py")),
                            init_globals={"_READER_STATUS_ENTRY": True})
    VerifiedHandler = (UnavailableHandler if issubclass(loaded["handler"], loaded["UnavailableHandler"])
                       else loaded["handler"])
except Exception:
    VerifiedHandler = UnavailableHandler


class handler(VerifiedHandler):  # type: ignore[valid-type,misc]
    pass
