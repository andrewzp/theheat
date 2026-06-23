"""Tests for credential-expiry introspection (the dashboard counter source)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from src.credentials import collect_credential_expiry, decode_jwt_exp


def _make_jwt(payload: dict) -> str:
    """Build an unsigned JWT (header.payload.sig) with the given payload."""

    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{b64({'typ': 'JWT'})}.{b64(payload)}.signature"


# 1787411887 == 2026-08-22T15:18:07Z (the real Earthdata token's exp shape).
_EXP = 1787411887
_EXP_ISO = "2026-08-22T15:18:07Z"


def test_decode_jwt_exp_reads_exp_claim_as_utc():
    got = decode_jwt_exp(_make_jwt({"type": "User", "uid": "theheat", "exp": _EXP}))
    assert got == datetime(2026, 8, 22, 15, 18, 7, tzinfo=timezone.utc)


def test_decode_jwt_exp_returns_none_for_non_jwt():
    assert decode_jwt_exp("not-a-jwt") is None
    assert decode_jwt_exp("") is None
    assert decode_jwt_exp("a.b.c.d") is None  # wrong segment count


def test_decode_jwt_exp_returns_none_when_no_exp_claim():
    assert decode_jwt_exp(_make_jwt({"uid": "theheat"})) is None


def test_collect_skips_missing_credentials():
    assert collect_credential_expiry(env={}) == {}


def test_collect_decodes_present_jwt_credential():
    token = _make_jwt({"uid": "theheat", "exp": _EXP})
    out = collect_credential_expiry(env={"EARTHDATA_TOKEN": token})
    assert out == {
        "EARTHDATA_TOKEN": {
            "label": "NASA Earthdata",
            "expires_at": _EXP_ISO,
            "source": "jwt",
        }
    }


def test_collect_skips_credential_that_is_not_a_decodable_jwt():
    # A non-JWT value (e.g. a future opaque token) is skipped, never crashes.
    assert collect_credential_expiry(env={"EARTHDATA_TOKEN": "opaque-token"}) == {}
