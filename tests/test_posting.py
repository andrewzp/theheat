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
    def test_post_tweet_uploads_media_when_provided(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {"id": "12345"}
        mock_client.create_tweet.return_value = mock_response
        mock_api = MagicMock()
        mock_media = MagicMock()
        mock_media.media_id = 98765
        mock_api.media_upload.return_value = mock_media
        media_png = b"\x89PNG\r\n\x1a\ncard"

        with (
            patch("src.posting.twitter.tweepy.Client", return_value=mock_client),
            patch("src.posting.twitter.tweepy.OAuth1UserHandler") as mock_auth,
            patch("src.posting.twitter.tweepy.API", return_value=mock_api),
        ):
            from src.posting.twitter import post_tweet

            result = post_tweet("test tweet", media_png=media_png, alt_text="Hot 10 alt")

        assert result is not None
        assert result["id"] == "12345"
        mock_auth.assert_called_once_with("k", "s", "t", "a")
        mock_api.media_upload.assert_called_once()
        upload_kwargs = mock_api.media_upload.call_args.kwargs
        assert upload_kwargs["filename"] == "hot10.png"
        upload_kwargs["file"].seek(0)
        assert upload_kwargs["file"].read() == media_png
        mock_api.create_media_metadata.assert_called_once_with("98765", "Hot 10 alt")
        mock_client.create_tweet.assert_called_once_with(
            text="test tweet",
            media_ids=["98765"],
        )

    @patch("src.posting.twitter.API_KEY", "k")
    @patch("src.posting.twitter.API_SECRET", "s")
    @patch("src.posting.twitter.ACCESS_TOKEN", "t")
    @patch("src.posting.twitter.ACCESS_SECRET", "a")
    def test_rate_limit_returns_sentinel(self):
        import tweepy

        mock_client = MagicMock()
        mock_client.create_tweet.side_effect = tweepy.TooManyRequests(
            MagicMock(status_code=429)
        )

        with patch("src.posting.twitter.tweepy.Client", return_value=mock_client):
            from src.posting.twitter import post_tweet

            result = post_tweet("test tweet")
            assert result == {"error": "rate_limited"}

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
