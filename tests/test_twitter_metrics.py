"""Tests for X/Twitter engagement metric fetches."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_fetch_metrics_batches_by_100(monkeypatch):
    from src.data import twitter_metrics

    calls = []
    mock_client = MagicMock()

    def fake_get_tweets(*, ids, tweet_fields):
        calls.append((list(ids), list(tweet_fields)))
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    id=tweet_id,
                    public_metrics={
                        "like_count": 1,
                        "retweet_count": 2,
                        "reply_count": 3,
                    },
                )
                for tweet_id in ids
            ]
        )

    mock_client.get_tweets.side_effect = fake_get_tweets
    monkeypatch.setattr(twitter_metrics, "API_KEY", "k")
    monkeypatch.setattr(twitter_metrics, "API_SECRET", "s")
    monkeypatch.setattr(twitter_metrics, "ACCESS_TOKEN", "t")
    monkeypatch.setattr(twitter_metrics, "ACCESS_SECRET", "a")
    monkeypatch.setattr(twitter_metrics.tweepy, "Client", lambda **kwargs: mock_client)

    ids = [f"tweet_{idx}" for idx in range(205)]
    metrics = twitter_metrics.fetch_metrics(ids)

    assert [len(batch) for batch, _fields in calls] == [100, 100, 5]
    assert all(fields == ["public_metrics"] for _batch, fields in calls)
    assert metrics["tweet_0"] == {"likes": 1, "retweets": 2, "replies": 3}
    assert metrics["tweet_204"] == {"likes": 1, "retweets": 2, "replies": 3}
