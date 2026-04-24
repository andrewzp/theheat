"""Tests for tweet generation via Gemini Flash with fallback."""

from unittest.mock import patch, MagicMock

from src.voice.generator import (
    generate_tweet,
    generate_tweet_bundle,
    generate_record_tweet,
    generate_record_low_tweet,
    generate_fire_tweet,
    generate_co2_milestone_tweet,
    _detect_stock_formula,
    _prompt_for_category,
    SYSTEM_PROMPT,
    _CATEGORY_PROMPTS,
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


class TestDetectStockFormula:
    """Regex guard against Gemini template traps identified in
    docs/DRAFT_CORPUS.md 2026-04-24 section. Every pattern here is a
    specific failure mode observed in production."""

    def test_homes_count_formula_rejected(self):
        bad = [
            "A wildfire radiating 220 MW — enough to power 220,000 homes.",
            "enough to power roughly 200,000 homes",
            "enough to run 100,000 American homes",
            "That is enough to run roughly 150,000 average US homes.",
            "enough to power 130,000 electric heaters simultaneously",
        ]
        for t in bad:
            assert _detect_stock_formula(t) is not None, f"Should reject: {t}"

    def test_generic_power_plant_comparison_rejected(self):
        bad = [
            "A coal power plant produces about 1,000 MW. This is a third of that.",
            "A standard nuclear reactor runs at around 1,000 MW.",
            "A typical coal plant runs at 600 MW.",
            "A small power plant delivers about 300 MW. Except it's a forest.",
        ]
        for t in bad:
            assert _detect_stock_formula(t) is not None, f"Should reject: {t}"

    def test_no_name_yet_closer_rejected(self):
        bad = [
            "A fire in Mexico. It has no name yet.",
            "234 MW in Kazakhstan. The fire has no name yet.",
        ]
        for t in bad:
            assert _detect_stock_formula(t) is not None

    def test_continent_only_location_rejected(self):
        bad = [
            "A wildfire somewhere in Asia is radiating 161 MW.",
            "The satellite confidence is 95%. The location is unknown.",
            "Location still unknown. Satellite confidence: 95%.",
            "A fire burning somewhere in Africa at 250 MW.",
        ]
        for t in bad:
            assert _detect_stock_formula(t) is not None

    def test_legitimate_tweets_not_rejected(self):
        """Good tweets from the A/B corpus should pass through clean."""
        good = [
            "Sevilla is forecast to hit 86.4F today. The record for this date was set in 2002.",
            "Chicago hit 82F today. Average high for April is 52F. That 29-degree jump used to define an entire season.",
            "A 264 MW wildfire on Hawaii's Big Island. In APRIL. The average rainfall there this month is 2.5 inches.",
            "Kathmandu forecast 88.5F today. That would break a record from 1999. The year the world worried about Y2K.",
            # Named power-plant comparison — legit, Palo Verde is a real plant.
            "The Dixie Complex is radiating more heat than the Palo Verde reactor outputs.",
            # Seattle comparison — the one power-plant-family comparison that landed.
            "Seattle, the whole city, averages about 1,000 MW of electricity use.",
        ]
        for t in good:
            assert _detect_stock_formula(t) is None, f"Should NOT reject: {t}"

    def test_empty_and_none_safe(self):
        assert _detect_stock_formula("") is None
        assert _detect_stock_formula(None) is None


class TestPromptForCategory:
    def test_unknown_category_falls_back_to_universal(self):
        assert _prompt_for_category("unknown_type") == SYSTEM_PROMPT
        assert _prompt_for_category("") == SYSTEM_PROMPT
        assert _prompt_for_category(None) == SYSTEM_PROMPT

    def test_known_category_includes_addendum(self):
        result = _prompt_for_category("fire")
        assert SYSTEM_PROMPT in result
        assert "CATEGORY-SPECIFIC — WILDFIRE" in result
        assert len(result) > len(SYSTEM_PROMPT)

    def test_every_registered_category_prompt_loads(self):
        # Sanity: no broken keys in _CATEGORY_PROMPTS; each assembles a
        # prompt that strictly extends SYSTEM_PROMPT.
        for category, addendum in _CATEGORY_PROMPTS.items():
            result = _prompt_for_category(category)
            assert SYSTEM_PROMPT in result
            assert addendum in result

    def test_fire_prompt_bans_stock_formulas(self):
        fire_prompt = _prompt_for_category("fire")
        # The fire addendum should explicitly warn Gemini off the two
        # biggest fire-voice traps we identified.
        assert "no name yet" in fire_prompt
        assert "power-plant comparison" in fire_prompt.lower() or \
               "power plant" in fire_prompt.lower()


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


class TestGenerateIceMassTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_monthly_record_falls_back_to_template(self):
        from src.voice.generator import generate_ice_mass_tweet
        result = generate_ice_mass_tweet(
            region="greenland",
            kind="monthly_loss_record",
            month="2026-08",
            monthly_delta_gt=-423.0,
            previous_worst_gt=-350.0,
            previous_worst_month="2019-07",
            years_of_record=24,
        )
        assert result is not None
        assert "Greenland" in result
        assert "423" in result
        assert "GRACE" in result

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_cumulative_milestone_falls_back_to_template(self):
        from src.voice.generator import generate_ice_mass_tweet
        result = generate_ice_mass_tweet(
            region="antarctica",
            kind="cumulative_milestone",
            threshold_gt=-3000.0,
            current_mass_gt=-3042.0,
            years_of_record=24,
        )
        assert result is not None
        assert "Antarctica" in result
        assert "3,000" in result or "3000" in result


class TestFireFootprintTemplate:
    def test_named_fire_leads_with_name(self):
        from src.voice.templates import fire_footprint_template
        text = fire_footprint_template(
            name="Dixie Complex",
            country="US",
            region="California",
            hectares=213_000,
        )
        assert "Dixie Complex" in text
        assert "213,000" in text
        assert "hectares" in text

    def test_unnamed_fire_uses_region_fallback(self):
        from src.voice.templates import fire_footprint_template
        text = fire_footprint_template(
            name=None,
            country="Russia",
            region="Yakutia",
            hectares=300_000,
        )
        assert "Yakutia" in text
        assert "Russia" in text
        assert "300,000" in text

    def test_includes_acre_conversion(self):
        from src.voice.templates import fire_footprint_template
        # Run many times so at least one acre-bearing variant appears.
        produced = {
            fire_footprint_template(
                name="Test Fire",
                country="US",
                region="California",
                hectares=100_000,
            )
            for _ in range(50)
        }
        assert any("acres" in t for t in produced)


class TestGenerateFireFootprintTweet:
    def test_uses_fire_footprint_category(self):
        from unittest.mock import patch, MagicMock
        from src.voice import generator

        with patch.object(generator, "generate_tweet") as mock_gen:
            mock_gen.return_value = "mocked tweet"
            generator.generate_fire_footprint_tweet(
                name="Dixie Complex",
                country="US",
                region="California",
                hectares=213_000,
                tier_hectares=100_000,
            )
            args, kwargs = mock_gen.call_args
            assert kwargs["category"] == "fire_footprint"
            # fallback args must carry all four fields
            assert kwargs["fallback_args"]["name"] == "Dixie Complex"
            assert kwargs["fallback_args"]["country"] == "US"
            assert kwargs["fallback_args"]["region"] == "California"
            assert kwargs["fallback_args"]["hectares"] == 213_000

    def test_data_description_contains_key_facts(self):
        from unittest.mock import patch
        from src.voice import generator

        with patch.object(generator, "generate_tweet") as mock_gen:
            mock_gen.return_value = "mocked tweet"
            generator.generate_fire_footprint_tweet(
                name=None,
                country="Russia",
                region="Yakutia",
                hectares=300_000,
                tier_hectares=250_000,
            )
            args, kwargs = mock_gen.call_args
            data_description = args[0]
            assert "Yakutia" in data_description
            assert "Russia" in data_description
            assert "300,000" in data_description
            assert "250,000" in data_description  # the crossed threshold


class TestSynthesisGenerator:
    def test_template_fallback_no_api_key(self):
        from unittest.mock import patch
        from src.voice.generator import generate_synthesis_fire_drought_heat_tweet
        with patch("src.voice.generator.GEMINI_API_KEY", ""):
            tweet = generate_synthesis_fire_drought_heat_tweet(
                state="California",
                drought_d4_pct=10.0,
                fire_peak_frp=1200.0,
                fire_peak_region="Sacramento County",
                heat_peak_city="Sacramento",
                heat_peak_kind="calendar",
                heat_peak_value_c=40.1,
                window_days=14,
                return_bundle=False,
            )
            assert tweet is not None
            assert "California" in tweet
            # Period-separated cadence, no emojis, no hashtags.
            assert "#" not in tweet
            assert "🔥" not in tweet
