"""Transport/error taxonomy for source-health telemetry.

This is deliberately separate from ``scripts.source_health_sentinel.classify_error``:
that one chooses issue labels (ours/external/unknown), while this one records a
stable failure shape for liveness, dashboards, and later circuit-breaker work.
"""
from __future__ import annotations

import re

_AUTH_RE = re.compile(
    r"\b(401|404|410)\b|Unauthorized|EARTHDATA_TOKEN|invalid token|token expired|expired token|expired|credential",
    re.IGNORECASE,
)
_HTTP_403_RE = re.compile(r"\b403\b")
_HTTP_429_RE = re.compile(r"\b429\b")
_HTTP_5XX_RE = re.compile(r"\b50\d\b|Server Error|Bad Gateway|Service Unavailable", re.IGNORECASE)
_TIMEOUT_RE = re.compile(r"Timeout|timed out", re.IGNORECASE)
_DNS_RE = re.compile(r"NameResolution|getaddrinfo|NXDOMAIN", re.IGNORECASE)
_CONNECTION_RE = re.compile(
    r"ConnectionError|Connection refused|Max retries|RemoteDisconnected",
    re.IGNORECASE,
)
_PARSE_RE = re.compile(r"JSONDecodeError|ParseError|ExpatError", re.IGNORECASE)


def classify_error_class(error: str | None) -> str:
    """Return the telemetry taxonomy bucket for an error string."""
    if error is None:
        return "none"
    text = str(error).strip()
    if not text or text == "-":
        return "none"
    if _AUTH_RE.search(text):
        return "auth"
    if _HTTP_403_RE.search(text):
        return "http403"
    if _HTTP_429_RE.search(text):
        return "http429"
    if _HTTP_5XX_RE.search(text):
        return "http5xx"
    if _TIMEOUT_RE.search(text):
        return "timeout"
    if _DNS_RE.search(text):
        return "dns"
    if _CONNECTION_RE.search(text):
        return "connection"
    if _PARSE_RE.search(text):
        return "parse"
    return "other"


__all__ = ["classify_error_class"]
