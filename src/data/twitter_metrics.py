"""X/Twitter engagement metric fetches."""

from __future__ import annotations

import os
from datetime import datetime

import tweepy
from src.data.metric_history import parse_public_metrics

API_KEY = os.environ.get("TWITTER_API_KEY", "")
API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET", "")


def credentials_available() -> bool:
    return all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET])


def _get_client() -> tweepy.Client | None:
    if not credentials_available():
        return None
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET,
    )


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
    """Fetch public engagement metrics for tweet IDs, batched at 100 IDs."""
    ids = _unique_ids(tweet_ids)
    if not ids:
        return {}

    client = _get_client()
    if client is None:
        print("[twitter_metrics] No credentials configured, skipping metrics fetch")
        return {}

    metrics_by_id: dict[str, dict] = {}
    for batch in _batches(ids):
        response = client.get_tweets(ids=batch, tweet_fields=["public_metrics", "created_at"])
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
