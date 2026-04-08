"""Tests for tweet generation via Gemini Flash with fallback."""

from unittest.mock import patch, MagicMock

from src.voice.generator import (
    generate_tweet,
    generate_record_tweet,
    generate_fire_tweet,
    generate_co2_milestone_tweet,
    generate_co2_weekly_tweet,
)


class TestGenerateTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_no_api_key_falls_back_to_template(self):
        fallback = MagicMock(return_value="fallback tweet")
        result = generate_tweet(
            "test data",
            fallback_fn=fallback,
            fallback_args={"key": "val"},
        )
        assert result == "fallback tweet"
        fallback.assert_called_once_with(key="val")

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_no_api_key_no_fallback_returns_none(self):
        result = generate_tweet("test data")
        assert result is None

    @patch("src.voice.generator.GEMINI_API_KEY", "fake_key")
    def test_gemini_success_returns_tweet(self):
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Phoenix hit 119F. New record for April."
        mock_model.generate_content.return_value = mock_response

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            with patch("src.voice.safety.run_safety_pipeline", return_value=(True, None)):
                result = generate_tweet("test data")
                assert result == "Phoenix hit 119F. New record for April."

    @patch("src.voice.generator.GEMINI_API_KEY", "fake_key")
    def test_gemini_failure_retries_then_falls_back(self):
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API error")

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        fallback = MagicMock(return_value="fallback tweet")

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            result = generate_tweet(
                "test data",
                fallback_fn=fallback,
                fallback_args={"key": "val"},
            )
            assert result == "fallback tweet"
            # generate_content called MAX_RETRIES times
            assert mock_model.generate_content.call_count == 3

    @patch("src.voice.generator.GEMINI_API_KEY", "fake_key")
    def test_safety_rejection_triggers_retry(self):
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "BREAKING: fire everywhere!"
        mock_model.generate_content.return_value = mock_response

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        fallback = MagicMock(return_value="safe fallback")

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            with patch(
                "src.voice.safety.run_safety_pipeline",
                return_value=(False, "Banned pattern"),
            ):
                result = generate_tweet(
                    "test data",
                    fallback_fn=fallback,
                    fallback_args={"key": "val"},
                )
                assert result == "safe fallback"
                assert mock_model.generate_content.call_count == 3


class TestGenerateRecordTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_produces_output_via_fallback(self):
        result = generate_record_tweet(
            city="Phoenix",
            country="US",
            new_temp_c=48.3,
            old_record_c=47.0,
            old_record_year=2023,
        )
        assert result is not None
        assert "Phoenix" in result
        assert "2023" in result

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_contains_temperature(self):
        result = generate_record_tweet(
            city="Miami",
            country="US",
            new_temp_c=40.0,
            old_record_c=39.0,
            old_record_year=2022,
        )
        assert result is not None
        # Template uses Fahrenheit
        assert "F" in result


class TestGenerateFireTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_produces_output_via_fallback(self):
        result = generate_fire_tweet(
            region="Southwestern US",
            country="US",
            confidence=95,
            frp=250.0,
        )
        assert result is not None
        assert "Southwestern US" in result
        assert "95" in result

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_includes_frp(self):
        result = generate_fire_tweet(
            region="Australia",
            country="Australia",
            confidence=90,
            frp=500.0,
        )
        assert result is not None
        assert "500" in result


class TestGenerateCO2MilestoneTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_produces_output_via_fallback(self):
        result = generate_co2_milestone_tweet(ppm_crossed=430, actual_ppm=430.2)
        assert result is not None
        assert "430" in result

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_contains_actual_ppm(self):
        result = generate_co2_milestone_tweet(ppm_crossed=429, actual_ppm=429.5)
        assert result is not None
        assert "429.5" in result


class TestGenerateCO2WeeklyTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_produces_output_via_fallback(self):
        result = generate_co2_weekly_tweet(
            current=429.0,
            last_year=426.0,
            diff=3.0,
        )
        assert result is not None
        assert "429" in result
        assert "426" in result

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_contains_diff(self):
        result = generate_co2_weekly_tweet(
            current=430.5,
            last_year=427.5,
            diff=3.0,
        )
        assert result is not None
        assert "3.0" in result
