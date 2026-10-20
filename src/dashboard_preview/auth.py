"""Native Python function auth; Next middleware is not an authorization dependency."""

import base64
import binascii
import hmac
import re
from urllib.parse import urlsplit

from src.dashboard_preview.errors import PreviewError

DEPLOYMENT = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.vercel\.app")
HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::[1-9][0-9]{0,4})?")
LOCAL = re.compile(r"(?:localhost|127\.0\.0\.1)(?::[1-9][0-9]{0,4})?")
PATHS = frozenset({"/api/graphic_preview", "/api/graphic_preview.py"})


def header(headers, name):
    if hasattr(headers, "get_all"):
        values = headers.get_all(name, [])
    else:
        values = [v for k, v in headers.items() if k.lower() == name.lower()]
    if len(values) > 1 or (values and (not isinstance(values[0], str) or len(values[0]) > 8192)):
        raise PreviewError("bad_request")
    return values[0] if values else ""


def authorize(target, headers, env, *, paths=PATHS):
    host = header(headers, "Host").lower()
    if not HOST.fullmatch(host):
        raise PreviewError("authentication_required")
    deployed = env.get("VERCEL") == "1"
    if env.get("DASHBOARD_AUTH_DISABLED") == "1":
        protected = env.get("VERCEL_URL", "").lower()
        if not deployed or env.get("VERCEL_ENV") not in {"production", "preview"} or not DEPLOYMENT.fullmatch(protected):
            raise PreviewError("preview_unavailable")
        if host != protected:
            raise PreviewError("sign_in_required")
    else:
        user, password = env.get("DASHBOARD_USERNAME", ""), env.get("DASHBOARD_PASSWORD", "")
        if not user or not password or ":" in user:
            raise PreviewError("preview_unavailable")
        value = header(headers, "Authorization")
        try:
            if not value.startswith("Basic "):
                raise ValueError
            # Match the dashboard's atob contract, including passwords with colons.
            decoded = base64.b64decode(value[6:], validate=True).decode("latin-1")
            expected = user + ":" + password
            if not hmac.compare_digest(decoded.encode("utf-8"), expected.encode("utf-8")):
                raise ValueError
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise PreviewError("authentication_required") from exc
    try:
        parsed = urlsplit(target)
        scheme = "https" if deployed else "http"
        if not deployed and not LOCAL.fullmatch(host):
            raise PreviewError("preview_unavailable")
        if (len(target) > 512 or target.startswith("//") or parsed.path not in paths
                or parsed.query or parsed.fragment or parsed.username or parsed.password
                or (parsed.netloc and (parsed.netloc.lower() != host or parsed.scheme != scheme))
                or (parsed.scheme and not parsed.netloc)):
            raise PreviewError("bad_request")
        origin = header(headers, "Origin")
        if origin and origin != f"{scheme}://{host}":
            raise PreviewError("origin_mismatch")
    except (ValueError, UnicodeError) as exc:
        raise PreviewError("bad_request") from exc
