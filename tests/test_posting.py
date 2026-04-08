"""Tests for X/Twitter posting."""

from unittest.mock import patch, MagicMock


class TestPostTweet:
    @patch("src.posting.twitter.API_KEY", "")
    @patch("src.posting.twitter.API_SECRET", "")
    @patch("src.posting.twitter.ACCESS_TOKEN", "")
    @patch("src.posting.twitter.ACCESS_SECRET", "")
    def test_no_credentials_returns_none(self):
        from src.posting.twitter import post_tweet

        result = post_tweet("test tweet")
        assert result is None

    @patch("src.posting.twitter.API_KEY", "k")
    @patch("src.posting.twitter.API_SECRET", "s")
    @patch("src.posting.twitter.ACCESS_TOKEN", "t")
    @patch("src.posting.twitter.ACCESS_SECRET", "a")
    def test_success_returns_dict_with_id(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {"id": "12345"}
        mock_client.create_tweet.return_value = mock_response

        with patch("src.posting.twitter.tweepy.Client", return_value=mock_client):
            from src.posting.twitter import post_tweet

            result = post_tweet("test tweet")
            assert result is not None
            assert result["id"] == "12345"
            assert result["text"] == "test tweet"

    @patch("src.posting.twitter.API_KEY", "k")
    @patch("src.posting.twitter.API_SECRET", "s")
    @patch("src.posting.twitter.ACCESS_TOKEN", "t")
    @patch("src.posting.twitter.ACCESS_SECRET", "a")
    def test_rate_limit_returns_none(self):
        import tweepy

        mock_client = MagicMock()
        mock_client.create_tweet.side_effect = tweepy.TooManyRequests(
            MagicMock(status_code=429)
        )

        with patch("src.posting.twitter.tweepy.Client", return_value=mock_client):
            from src.posting.twitter import post_tweet

            result = post_tweet("test tweet")
            assert result is None

    @patch("src.posting.twitter.API_KEY", "k")
    @patch("src.posting.twitter.API_SECRET", "s")
    @patch("src.posting.twitter.ACCESS_TOKEN", "t")
    @patch("src.posting.twitter.ACCESS_SECRET", "a")
    def test_auth_failure_returns_none(self):
        import tweepy

        mock_client = MagicMock()
        mock_client.create_tweet.side_effect = tweepy.Unauthorized(
            MagicMock(status_code=401)
        )

        with patch("src.posting.twitter.tweepy.Client", return_value=mock_client):
            from src.posting.twitter import post_tweet

            result = post_tweet("test tweet")
            assert result is None
