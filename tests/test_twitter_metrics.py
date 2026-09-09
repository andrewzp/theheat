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
    assert all(fields == ["public_metrics", "created_at"] for _batch, fields in calls)
    expected = {"likes": 1, "retweets": 2, "replies": 3, "quotes": None,
                "impressions": None, "bookmarks": None, "created_at": None}
    assert metrics["tweet_0"] == expected
    assert metrics["tweet_204"] == expected


def test_missing_malformed_and_unrequested_metrics_are_not_invented(monkeypatch):
    from src.data import twitter_metrics
    mock_client = MagicMock()
    mock_client.get_tweets.return_value = SimpleNamespace(data=[
        {"id": "1", "public_metrics": {"like_count": 0, "impression_count": 21}},
        {"id": "2", "public_metrics": {"like_count": "bad", "reply_count": False}},
        {"id": "3"}, {"id": "unrequested", "public_metrics": {"like_count": 100}},
    ])
    monkeypatch.setattr(twitter_metrics, "_get_client", lambda: mock_client)
    result = twitter_metrics.fetch_metrics(["1", "2", "3"])
    assert set(result) == {"1", "2"}
    assert result["1"]["likes"] == 0 and result["1"]["impressions"] == 21
    assert result["1"]["bookmarks"] is None
    assert all(value is None for value in result["2"].values())
