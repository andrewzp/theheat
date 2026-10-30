"""X/Twitter engagement metric fetches."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests
import tweepy
from src.data.metric_history import parse_public_metrics

API_KEY = os.environ.get("TWITTER_API_KEY", "")
API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET", "")
_METRICS_TIMEOUT = (5.0, 15.0)


class _MetricsSession(requests.Session):
    """Bound SDK inactivity and refuse redirects; no extra retry layer."""

    def request(self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any) -> requests.Response:
        kwargs["timeout"] = _METRICS_TIMEOUT
        kwargs["allow_redirects"] = False
        return super().request(method, url, *args, **kwargs)


def credentials_available() -> bool:
    return all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET])


def _get_client() -> tweepy.Client | None:
    if not credentials_available():
        return None
    client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET,
        wait_on_rate_limit=False,
    )
    client.session.close()
    client.session = _MetricsSession()
    return client


def _unique_ids(tweet_ids: list[str]) -> list[str]:
    seen = set()
    out = []
    for raw_id in tweet_ids:
        tweet_id = str(raw_id or "").strip()
        if not tweet_id or tweet_id in seen:
            continue
        seen.add(tweet_id)
        out.append(tweet_id)
    return out


def _batches(tweet_ids: list[str], size: int = 100):
    for idx in range(0, len(tweet_ids), size):
        yield tweet_ids[idx:idx + size]


def _tweet_field(tweet, field: str):
    if isinstance(tweet, dict):
        return tweet.get(field)
    return getattr(tweet, field, None)


def fetch_metrics(tweet_ids: list[str]) -> dict[str, dict]:
    """Fetch public counts with the configured OAuth1 credentials, 100 IDs/batch.

    Connect/read inactivity is bounded, redirects and rate-limit waiting are off,
    and the owned session closes on failure too. This does not grant API access
    or impose an absolute elapsed-time or billing ceiling. The orchestrator owns
    its existing 50-ID, once-per-UTC-day gate, including unsuccessful attempts.
    """
    ids = _unique_ids(tweet_ids)
    if not ids:
        return {}
    from src.two_bot.call_inventory import background_lane_enabled, consume
    if not background_lane_enabled("metrics"):
        # Exact opt-in at the real call boundary, before any client construction.
        print("[twitter_metrics] THEHEAT_METRICS_ENABLED is not 1, skipping metrics fetch")
        return {}

    client = _get_client()
    if client is None:
        print("[twitter_metrics] No credentials configured, skipping metrics fetch")
        return {}

    try:
        metrics_by_id: dict[str, dict] = {}
        for batch in _batches(ids):
            # The four configured credentials are OAuth1, not a bearer token.
            ticket = consume("x_metrics_read", provider="x")
            try:
                response = client.get_tweets(ids=batch, tweet_fields=["public_metrics", "created_at"], user_auth=True)
            except BaseException:
                ticket.settle("unknown")
                raise
            ticket.settle("returned")
            for tweet in response.data or []:
                tweet_id = str(_tweet_field(tweet, "id") or "")
                public_metrics = _tweet_field(tweet, "public_metrics")
                if tweet_id not in batch or not isinstance(public_metrics, dict):
                    continue
                created_at = _tweet_field(tweet, "created_at")
                if isinstance(created_at, datetime):
                    created_at = created_at.isoformat()
                metrics_by_id[tweet_id] = {**parse_public_metrics(public_metrics),
                                           "created_at": created_at if isinstance(created_at, str) else None}
        return metrics_by_id
    finally:
        client.session.close()
