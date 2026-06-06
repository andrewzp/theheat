"""Temporary AWS S3 credentials minted from a NASA Earthdata login token.

GES DISC stores its data in the controlled-access S3 bucket
``gesdisc-cumulus-prod-protected`` (us-west-2). Reading it requires *temporary*
AWS credentials minted from an Earthdata Login (EDL) bearer token via the DAAC's
``/s3credentials`` endpoint, which proxies AWS STS. The credentials are valid for
~1 hour (role chaining), so we cache them in-process and refresh a few minutes
before expiry rather than minting one per S3 request.

The endpoint accepts an EDL **Bearer token** (the same ``EARTHDATA_TOKEN`` the
OPeNDAP path already uses); unauthenticated requests are redirected to EDL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
import threading

import requests

# Per-DAAC s3credentials endpoint. GES DISC's lives under data.gesdisc; it is a
# different host from the gpm1.gesdisc OPeNDAP service the legacy path hits.
GESDISC_S3CREDENTIALS_URL = "https://data.gesdisc.earthdata.nasa.gov/s3credentials"

# Refresh this many seconds before the stated expiry so an in-flight request
# never races the 1-hour boundary.
_CRED_TTL_SAFETY_S = 300

# Fallback lifetime if the endpoint omits/garbles ``expiration``: the role is
# documented as ~1h, so assume slightly less.
_DEFAULT_TTL_S = 55 * 60

_DEFAULT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class S3Credentials:
    """Temporary AWS credentials usable for in-region S3 GetObject calls."""

    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime  # timezone-aware UTC


_cache: dict[str, S3Credentials] = {}
_lock = threading.Lock()


def get_s3_credentials(
    token: str,
    *,
    endpoint: str = GESDISC_S3CREDENTIALS_URL,
    now: Callable[[], datetime] | None = None,
    session: requests.Session | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> S3Credentials:
    """Return cached temp S3 creds for ``endpoint``, minting fresh ones if the
    cache is empty or within the safety window of expiry.

    ``now`` and ``session`` are injectable for tests; the cache is keyed by
    endpoint so distinct DAACs don't collide.
    """

    now_dt = now() if now is not None else datetime.now(timezone.utc)
    with _lock:
        cached = _cache.get(endpoint)
        if cached is not None and not _is_expiring(cached, now_dt):
            return cached

    creds = _mint(token, endpoint=endpoint, session=session, timeout=timeout, now_dt=now_dt)

    with _lock:
        _cache[endpoint] = creds
    return creds


def clear_cache() -> None:
    """Drop all cached credentials (test seam / forced refresh)."""
    with _lock:
        _cache.clear()


def _is_expiring(creds: S3Credentials, now_dt: datetime) -> bool:
    return creds.expiration - timedelta(seconds=_CRED_TTL_SAFETY_S) <= now_dt


def _mint(
    token: str,
    *,
    endpoint: str,
    session: requests.Session | None,
    timeout: float,
    now_dt: datetime,
) -> S3Credentials:
    getter = session.get if session is not None else requests.get
    resp = getter(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return S3Credentials(
            access_key_id=str(data["accessKeyId"]),
            secret_access_key=str(data["secretAccessKey"]),
            session_token=str(data["sessionToken"]),
            expiration=_parse_expiration(data.get("expiration"), now_dt=now_dt),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"s3credentials response missing expected fields: {sorted(data) if isinstance(data, dict) else type(data)}"
        ) from exc


def _parse_expiration(raw: object, *, now_dt: datetime) -> datetime:
    """Parse the endpoint's ``expiration`` string into a tz-aware UTC datetime.

    Observed format is ``"YYYY-MM-DD HH:MM:SS+00:00"``; ISO-8601 variants are
    also accepted. Anything unparseable falls back to a conservative TTL so a
    formatting drift can't wedge the source — worst case we refresh early.
    """
    if isinstance(raw, str) and raw.strip():
        text = raw.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return now_dt + timedelta(seconds=_DEFAULT_TTL_S)
