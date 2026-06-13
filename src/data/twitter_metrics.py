"""X/Twitter engagement metric fetches."""

from __future__ import annotations

import os

import tweepy

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


def fetch_metrics(tweet_ids: list[str]) -> dict[str, dict[str, int]]:
    """Fetch public engagement metrics for tweet IDs, batched at 100 IDs."""
    ids = _unique_ids(tweet_ids)
    if not ids:
        return {}

    client = _get_client()
    if client is None:
        print("[twitter_metrics] No credentials configured, skipping metrics fetch")
        return {}

    metrics_by_id: dict[str, dict[str, int]] = {}
    for batch in _batches(ids):
        response = client.get_tweets(ids=batch, tweet_fields=["public_metrics"])
        for tweet in response.data or []:
            tweet_id = str(_tweet_field(tweet, "id") or "")
            public_metrics = _tweet_field(tweet, "public_metrics") or {}
            if not tweet_id or not isinstance(public_metrics, dict):
                continue
            metrics_by_id[tweet_id] = {
                "likes": int(public_metrics.get("like_count") or 0),
                "retweets": int(public_metrics.get("retweet_count") or 0),
                "replies": int(public_metrics.get("reply_count") or 0),
            }
    return metrics_by_id
