"""Tests for tweet generation via Gemini Flash with fallback."""

from unittest.mock import patch, MagicMock

from src.voice.generator import (
    generate_tweet,
    generate_tweet_bundle,
    generate_record_tweet,
    generate_record_low_tweet,
    generate_fire_tweet,
    generate_co2_milestone_tweet,
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
        mock_response = MagicMock()
        mock_response.text = "Phoenix hit 119F. New record for April."

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_genai_mod = MagicMock()
        mock_genai_mod.Client.return_value = mock_client

        with patch.dict("sys.modules", {"google.genai": mock_genai_mod, "google": MagicMock(genai=mock_genai_mod)}):
            with patch("src.voice.safety.run_safety_pipeline", return_value=(True, None)):
                result = generate_tweet("test data")
                assert result == "Phoenix hit 119F. New record for April."

    @patch("src.voice.generator.GEMINI_API_KEY", "fake_key")
    def test_gemini_failure_retries_then_falls_back(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")

        mock_genai_mod = MagicMock()
        mock_genai_mod.Client.return_value = mock_client

        fallback = MagicMock(return_value="fallback tweet")

        with patch.dict("sys.modules", {"google.genai": mock_genai_mod, "google": MagicMock(genai=mock_genai_mod)}):
            result = generate_tweet(
                "test data",
                fallback_fn=fallback,
                fallback_args={"key": "val"},
            )
            assert result == "fallback tweet"
            # 3 generator retries + 1 evaluator call (which also fails gracefully)
            assert mock_client.models.generate_content.call_count >= 3

    @patch("src.voice.generator.GEMINI_API_KEY", "fake_key")
    def test_safety_rejection_triggers_retry(self):
        mock_response = MagicMock()
        mock_response.text = "BREAKING: fire everywhere!"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_genai_mod = MagicMock()
        mock_genai_mod.Client.return_value = mock_client

        fallback = MagicMock(return_value="safe fallback")

        with patch.dict("sys.modules", {"google.genai": mock_genai_mod, "google": MagicMock(genai=mock_genai_mod)}):
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
                # 3 generator retries + 1 evaluator call (which also fails gracefully)
                assert mock_client.models.generate_content.call_count >= 3

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_bundle_generation_uses_multiple_fallback_variants(self):
        fallback = MagicMock(
            side_effect=[
                "Phoenix just hit 121F. NEW RECORD. The old one was from 1998.",
                "Phoenix with 121F today. That broke a 27-year record.",
                "Phoenix, Arizona: 121F. New record for this date.",
            ]
        )

        bundle = generate_tweet_bundle(
            "Phoenix record heat",
            category="record",
            fallback_fn=fallback,
            fallback_args={},
            candidate_count=3,
        )

        assert bundle is not None
        assert len(bundle.candidates) == 3
        assert bundle.candidates[0].source == "template"

    @patch("src.voice.generator.GEMINI_API_KEY", "fake_key")
    def test_return_bundle_ranks_gemini_candidates(self):
        mock_response = MagicMock()
        mock_response.text = (
            "1. Phoenix is hot today.\n"
            "2. Phoenix just hit 121F. NEW RECORD. The old one was from 1998.\n"
            "3. Phoenix reached 121F."
        )

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_genai_mod = MagicMock()
        mock_genai_mod.Client.return_value = mock_client

        with patch.dict("sys.modules", {"google.genai": mock_genai_mod, "google": MagicMock(genai=mock_genai_mod)}):
            with patch("src.voice.generator.run_safety_pipeline", return_value=(True, None)):
                bundle = generate_tweet(
                    "Phoenix record heat",
                    category="record",
                    return_bundle=True,
                )
                assert bundle is not None
                assert "NEW RECORD" in bundle.text


class TestGenerateRecordTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_produces_output_via_fallback(self):
        result = generate_record_tweet(
            city="Phoenix",
            country="US",
            new_temp_c=48.3,
            old_record_c=47.0,
            old_record_year=2020,
        )
        assert result is not None
        assert "Phoenix" in result
        # All template variants include the year or the years-ago count
        assert "2020" in result or "6" in result

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

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_uses_provisional_language(self):
        result = generate_record_tweet(
            city="Phoenix",
            country="US",
            new_temp_c=48.3,
            old_record_c=47.0,
            old_record_year=2020,
        )
        assert result is not None
        assert "forecast" in result.lower() or "if it" in result.lower()
        assert "just recorded" not in result.lower()


class TestGenerateRecordLowTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_uses_provisional_language(self):
        result = generate_record_low_tweet(
            city="Denver",
            country="US",
            new_temp_c=-8.0,
            old_record_c=-6.0,
            old_record_year=1985,
        )
        assert result is not None
        assert "forecast" in result.lower() or "if that verifies" in result.lower()
        assert "recorded a low" not in result.lower()


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


def test_marine_heatwave_template_first_kind_contains_required_facts():
    from src.voice.templates import marine_heatwave_template
    text = marine_heatwave_template(
        kind="first", days=5, today_c=20.52, archive_max_c=20.31,
        archive_max_year=2023, years_of_data=44,
    )
    assert "5" in text
    assert "20.52" in text or "20.5" in text
    assert "20.31" in text or "20.3" in text
    assert "2023" in text
    assert "44 years" in text or "44-year" in text


def test_marine_heatwave_template_milestone_kind_uses_streak_day():
    from src.voice.templates import marine_heatwave_template
    text = marine_heatwave_template(
        kind="milestone", days=100, today_c=20.52, archive_max_c=20.31,
        archive_max_year=2023, years_of_data=44,
    )
    assert "100" in text
    assert "consecutive" in text.lower() or "th" in text


@patch("src.voice.generator.GEMINI_API_KEY", "")
def test_generate_marine_heatwave_tweet_falls_back_to_template():
    """When Gemini has no API key, the fallback template is used."""
    from src.voice.generator import generate_marine_heatwave_tweet
    result = generate_marine_heatwave_tweet(
        kind="first", days=5,
        today_c=20.52, archive_max_c=20.31,
        archive_max_year=2023, years_of_data=44,
    )
    assert isinstance(result, str)
    assert "5" in result
    assert "20.52" in result or "20.5" in result
