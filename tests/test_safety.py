"""Tests for the two-layer safety pipeline."""

from src.voice.safety import check_regex, check_month_repetition, run_safety_pipeline


class TestRegexGate:
    def test_clean_tweet_passes(self):
        passed, reason = check_regex("Phoenix hit 119F today. New record.")
        assert passed
        assert reason is None

    def test_emoji_rejected(self):
        passed, reason = check_regex("Phoenix hit 119F today 🔥")
        assert not passed
        assert "Banned pattern" in reason

    def test_hashtag_rejected(self):
        passed, reason = check_regex("Phoenix hit 119F #ClimateChange")
        assert not passed
        assert "Banned pattern" in reason

    def test_exclamation_rejected(self):
        passed, reason = check_regex("Phoenix hit 119F! New record!")
        assert not passed

    def test_breaking_prefix_rejected(self):
        passed, reason = check_regex("BREAKING: Phoenix hit 119F")
        assert not passed

    def test_policy_opinion_rejected(self):
        passed, reason = check_regex("We need to act now on climate change")
        assert not passed

    def test_we_must_rejected(self):
        passed, reason = check_regex("We must reduce emissions before it's too late")
        assert not passed

    def test_governments_rejected(self):
        passed, reason = check_regex("Governments must take action on this")
        assert not passed

    def test_too_long_rejected(self):
        passed, reason = check_regex("x" * 281)
        assert not passed
        assert "Too long" in reason

    def test_280_chars_passes(self):
        passed, reason = check_regex("x" * 280)
        assert passed

    def test_dark_humor_passes(self):
        passed, reason = check_regex(
            "Phoenix. Again. 119F. New record. The old one was set... last year."
        )
        assert passed

    def test_wake_up_rejected(self):
        passed, reason = check_regex("Wake up people, the planet is burning")
        assert not passed


class TestPressReleaseOpeners:
    def test_nws_opener_rejected(self):
        passed, reason = check_regex("NWS issued a Flash Flood Emergency for Houston")
        assert not passed

    def test_gdacs_opener_rejected(self):
        passed, reason = check_regex("GDACS just raised Cyclone SINLAKU to Red")
        assert not passed

    def test_a_nws_opener_rejected(self):
        passed, reason = check_regex("A NWS Severe Thunderstorm Warning just went out")
        assert not passed

    def test_noaa_opener_rejected(self):
        passed, reason = check_regex("NOAA confirms Phoenix hit 121F")
        assert not passed

    def test_agency_mention_mid_tweet_allowed(self):
        """Agencies can be mentioned mid-tweet, just not at the start."""
        passed, reason = check_regex("Phoenix hit 121F. NOAA confirmed it hours later.")
        assert passed


class TestLabelValueRejection:
    def test_severity_label_rejected(self):
        passed, reason = check_regex(
            "Flash Flood Warning for Kauai. Severity: Severe. Not a light shower."
        )
        assert not passed

    def test_alert_level_rejected(self):
        passed, reason = check_regex("Cyclone SINLAKU at Guam. Alert level: Red.")
        assert not passed

    def test_confidence_label_rejected(self):
        passed, reason = check_regex(
            "New wildfire in Northern California. Confidence: HIGH. It's April."
        )
        assert not passed


class TestExplainerRejection:
    def test_explaining_red_tier_rejected(self):
        passed, reason = check_regex(
            "Cyclone SINLAKU. Guam is under a RED alert. "
            "This is the highest severity level GDACS issues for a tropical cyclone."
        )
        assert not passed

    def test_the_highest_alert_tier_rejected(self):
        passed, reason = check_regex(
            "Tropical Cyclone hitting Guam. This is the highest alert tier."
        )
        assert not passed


class TestTellDontShow:
    def test_this_is_serious_rejected(self):
        passed, _ = check_regex(
            "Cyclone SINLAKU at 178 mph. THIS ONE IS SERIOUS."
        )
        assert not passed

    def test_this_is_not_a_drill_rejected(self):
        passed, _ = check_regex("178 mph winds in the Marianas. This is not a drill.")
        assert not passed

    def test_this_is_rare_rejected(self):
        passed, _ = check_regex("Flash flood emergency in Houston. This is extremely rare.")
        assert not passed

    def test_you_only_see_pattern_rejected(self):
        passed, _ = check_regex(
            "SINLAKU at 178 mph. You might see five of these a year."
        )
        assert not passed

    def test_pay_attention_rejected(self):
        passed, _ = check_regex("Category 5 cyclone forming. Pay attention to this one.")
        assert not passed

    def test_actual_sinlaku_bad_draft_rejected(self):
        """The exact draft the user flagged."""
        passed, _ = run_safety_pipeline(
            "Tropical Cyclone SINLAKU-26 is now a GDACS Red alert in the "
            "Northern Mariana Islands. 178 mph winds. Globally, you might "
            "see five of these alerts in a year. THIS ONE IS SERIOUS."
        )
        assert not passed

    def test_good_sinlaku_passes(self):
        """The rewritten version should pass."""
        passed, reason = run_safety_pipeline(
            "Tropical Cyclone SINLAKU just hit 178 mph over the Northern "
            "Mariana Islands. Category 5 starts at 157."
        )
        assert passed, f"Should pass, got: {reason}"


class TestWeatherServiceBoilerplate:
    def test_hurricane_force_rejected(self):
        passed, _ = check_regex("These are HURRICANE-FORCE conditions in Saipan.")
        assert not passed

    def test_extreme_force_rejected(self):
        passed, _ = check_regex("Winds will return with EXTREME force.")
        assert not passed

    def test_catastrophic_rejected(self):
        passed, _ = check_regex("Catastrophic flooding expected in Houston.")
        assert not passed

    def test_life_threatening_rejected(self):
        passed, _ = check_regex("Life-threatening storm surge at Guam.")
        assert not passed

    def test_dangerous_conditions_rejected(self):
        passed, _ = check_regex("Dangerous conditions developing along the coast.")
        assert not passed

    def test_extreme_wind_warning_rejected(self):
        passed, _ = check_regex("Saipan: Extreme Wind Warning. Winds are 155 mph.")
        assert not passed

    def test_bureaucratic_suffix_rejected(self):
        passed, _ = check_regex("Tropical Cyclone SINLAKU-26 is heading for Guam.")
        assert not passed

    def test_clean_storm_name_passes(self):
        passed, reason = check_regex(
            "Tropical Cyclone SINLAKU just hit 178 mph. Strongest in the western Pacific since Haiyan."
        )
        assert passed, f"Should pass, got: {reason}"


class TestMonthRepetition:
    def test_month_said_twice_rejected(self):
        tweet = "NWS issued a warning for Chuuk. April 10, 2026. It's April."
        passed, reason = check_month_repetition(tweet)
        assert not passed
        assert "april" in reason.lower()

    def test_month_said_once_passes(self):
        passed, reason = check_month_repetition(
            "Phoenix hit 121F today. It's April."
        )
        assert passed

    def test_no_month_passes(self):
        passed, reason = check_month_repetition("Phoenix hit 121F today.")
        assert passed

    def test_different_months_pass(self):
        # Mentioning two different months is fine (e.g. comparing May to April)
        passed, reason = check_month_repetition(
            "Phoenix at 121F in April. May average is only 95F."
        )
        assert passed


class TestSafetyPipeline:
    def test_clean_tweet_passes_full_pipeline(self):
        # LLM layer skipped when no API key is set
        passed, reason = run_safety_pipeline("Phoenix hit 119F. New record for April.")
        assert passed

    def test_regex_failure_short_circuits(self):
        passed, reason = run_safety_pipeline("BREAKING: Phoenix hit 119F!")
        assert not passed
        # Should fail on regex, never reaching LLM

    def test_full_pipeline_catches_month_repetition(self):
        """The exact failure mode from the bad draft the user flagged."""
        passed, reason = run_safety_pipeline(
            "NWS issued a Severe Tropical Storm Warning for Chuuk. "
            "April 10, 2026. It's April."
        )
        assert not passed

    def test_full_pipeline_catches_severity_label(self):
        """The exact failure mode from the Kauai draft."""
        passed, reason = run_safety_pipeline(
            "Flash Flood Warning for Kauai. Severity: Severe. Not a light shower."
        )
        assert not passed

    def test_good_sinlaku_tweet_passes(self):
        """The tweet I wrote for Cyclone SINLAKU should pass the pipeline."""
        passed, reason = run_safety_pipeline(
            "Tropical Cyclone SINLAKU is 80 miles from Guam at 145mph sustained. "
            "It just got bumped to the top GDACS tier."
        )
        assert passed, f"Should pass, got: {reason}"
