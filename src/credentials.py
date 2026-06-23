"""Credential-expiry introspection for the dashboard counter.

Decodes the ``exp`` claim from JWT credentials (no signature verification, no
network) so the dashboard can warn BEFORE a token silently expires — the class
of failure that took precipitation down on 2026-06-23 when the 60-day NASA
Earthdata token aged out unnoticed.

Only the derived expiry DATE is written to state; the token itself never leaves
the bot's environment. Add a credential by appending one row to
``TRACKED_CREDENTIALS`` — that is the entire cost of tracking the next token.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import datetime, timezone
from typing import Any

from src.state_schema import CredentialExpiry

# method "jwt": decode the token's own ``exp`` claim (works for any JWT, e.g.
# NASA EDL bearer tokens). Future non-JWT credentials can grow a different method
# (e.g. a manually-set expiry variable) without changing consumers.
TRACKED_CREDENTIALS: tuple[dict[str, str], ...] = (
    {"env": "EARTHDATA_TOKEN", "label": "NASA Earthdata", "method": "jwt"},
)


def decode_jwt_exp(token: str | None) -> datetime | None:
    """Return the UTC expiry from a JWT's ``exp`` claim, or None.

    Returns None when ``token`` is empty, is not a three-segment JWT, has a
    non-decodable payload, or carries no numeric ``exp``. No signature
    verification is performed — we only read the expiry, never trust the token.
    """
    if not token or token.count(".") != 2:
        return None
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)  # restore base64url padding
    try:
        payload: Any = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, binascii.Error, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return None
    try:
        return datetime.fromtimestamp(exp, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def collect_credential_expiry(env: dict[str, str] | None = None) -> dict[str, CredentialExpiry]:
    """Map ``{env_name: {label, expires_at, source}}`` for tracked credentials.

    Credentials absent from the environment are skipped (no row). For the ``jwt``
    method, a value that is not a decodable JWT-with-exp is skipped quietly —
    introspection must never crash a run.
    """
    environ = env if env is not None else os.environ
    out: dict[str, CredentialExpiry] = {}
    for cred in TRACKED_CREDENTIALS:
        token = (environ.get(cred["env"]) or "").strip()
        if not token:
            continue
        if cred["method"] == "jwt":
            exp = decode_jwt_exp(token)
            if exp is None:
                continue
            entry: CredentialExpiry = {
                "label": cred["label"],
                "expires_at": exp.isoformat().replace("+00:00", "Z"),
                "source": "jwt",
            }
            out[cred["env"]] = entry
    return out
