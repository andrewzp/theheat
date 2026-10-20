"""Verified, read-only Python preview; Next middleware is not the auth boundary."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import sys


def _bootstrap_event(stage):
    # Startup cannot import even a logging helper from an unverified archive.
    if type(stage) is not str or stage not in {
        "bootstrap_package", "bootstrap_integrity", "bootstrap_isolation",
        "bootstrap_timezone", "bootstrap_import", "bootstrap_ready",
    }:
        return
    try:
        sys.stderr.write(json.dumps({"component": "graphic_preview", "stage": stage},
                                    separators=(",", ":")) + "\n")
    except Exception:
        pass


def load_handler(*, reader_status=False):
    stage = "bootstrap_package"
    try:
        root = Path(__file__).resolve().parents[1]
        manifest_path = root / "lib/graphic-runtime-manifest.json"
        archive = root / "graphic-runtime.zip"
        if manifest_path.stat().st_size > 65536 or archive.stat().st_size > 2_000_000:
            raise ValueError("Invalid graphic runtime")
        manifest = json.loads(manifest_path.read_bytes())
        stage = "bootstrap_integrity"
        identity = manifest["identity"]
        actual = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if actual != manifest["runtime_sha256"] or sha256(archive.read_bytes()).hexdigest() != identity["archive_sha256"]:
            raise ValueError("Invalid graphic runtime")
        for name in ("api/graphic_preview.py", "api/graphic_reader_status.py", "pyproject.toml", "uv.lock"):
            if sha256((root / name).read_bytes()).hexdigest() != identity["deployment_files"][name]:
                raise ValueError("Invalid graphic runtime")
        # No extraction, downloads, environment-selected module or fallback source tree.
        stage = "bootstrap_isolation"
        if any(name == "src" or name.startswith("src.") for name in sys.modules):
            raise ValueError("Unexpected graphic runtime already loaded")
        # This dedicated preview process uses the locked timezone package. Do not
        # silently depend on host OS zone files or an inherited ZoneInfo cache.
        stage = "bootstrap_timezone"
        import tzdata
        from zoneinfo import ZoneInfo, reset_tzpath
        if tzdata.__version__ != "2026.5":
            raise ValueError("Unexpected graphic timezone data")
        reset_tzpath(())
        ZoneInfo.clear_cache()
        ZoneInfo("Asia/Kathmandu")  # Missing/corrupt package data must fail closed.
        stage = "bootstrap_import"
        sys.path.insert(0, str(archive))
        if reader_status:
            from src.dashboard_preview.reader_status import handler_type
        else:
            from src.dashboard_preview.http import handler_type
        result = handler_type(policy_sha=identity["policy_source_sha256"], runtime_sha=actual)
        _bootstrap_event("bootstrap_ready")
        return result
    except Exception:
        _bootstrap_event(stage)
        raise


class UnavailableHandler(BaseHTTPRequestHandler):
    """Malformed/missing package fails closed without importing unverified code."""
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
    # Only the fixed sibling entry supplies this literal in runpy's initial
    # globals. No URL, header, body or environment variable selects a handler.
    PreviewHandler = load_handler(reader_status=globals().get("_READER_STATUS_ENTRY") is True)
except Exception:
    PreviewHandler = UnavailableHandler


# The verified runtime selects a concrete HTTP handler class at import time.
class handler(PreviewHandler):  # type: ignore[valid-type,misc]
    pass
