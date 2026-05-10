"""Tests for the two-layer safety pipeline."""

from src.voice.safety import (
    check_regex,
    check_month_repetition,
    check_truncated_temperature,
    run_safety_pipeline,
)


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


class TestTruncatedTemperature:
    def test_truncated_singapore(self):
        """The exact Singapore bug from the drafts."""
        passed, reason = check_truncated_temperature(
            "1F forecast for Singapore today. The old record was 88.3F. From 2023."
        )
        assert not passed
        assert "truncated" in reason.lower()

    def test_truncated_lagos(self):
        """The exact Lagos bug."""
        passed, reason = check_truncated_temperature(
            "9F forecast for Lagos, Nigeria today. The old record was 90.5F. From 2020."
        )
        assert not passed

    def test_truncated_sydney(self):
        """The exact Sydney bug."""
        passed, reason = check_truncated_temperature(
            "2F forecast for Sydney. This would set a new record for the date."
        )
        assert not passed

    def test_truncated_mid_sentence(self):
        passed, reason = check_truncated_temperature(
            "Phoenix forecast to hit 2F today. That would break a record."
        )
        assert not passed

    def test_valid_two_digit_passes(self):
        passed, _ = check_truncated_temperature(
            "91F forecast for Singapore today. The old record was 88.3F."
        )
        assert passed

    def test_valid_three_digit_passes(self):
        passed, _ = check_truncated_temperature(
            "121F in Phoenix today. New record."
        )
        assert passed

    def test_valid_celsius_passes(self):
        passed, _ = check_truncated_temperature(
            "Delhi forecast to hit 48.2C today."
        )
        assert passed

    def test_single_digit_celsius_cold_record_passes(self):
        passed, reason = check_truncated_temperature(
            "Dayton reached 4C this morning. Coldest May reading in the station archive."
        )
        assert passed, f"Single-digit C can be valid for cold records, got: {reason}"

    def test_single_digit_celsius_opener_passes(self):
        passed, reason = check_truncated_temperature(
            "4C in Dayton this morning. Coldest May reading in the station archive."
        )
        assert passed, f"Single-digit C opener can be valid for cold records, got: {reason}"

    def test_no_temperature_passes(self):
        passed, _ = check_truncated_temperature("Arctic sea ice at record low extent.")
        assert passed


class TestMonthRepetition:
    def test_month_said_twice_rejected(self):
        # Canonical original failure mode: explicit "It's April." after the
        # date already established the month.
        tweet = "NWS issued a warning for Chuuk. April 10, 2026. It's April."
        passed, reason = check_month_repetition(tweet)
        assert not passed
        assert "april" in reason.lower()

    def test_month_said_once_passes(self):
        # "It's April." standalone with no prior date reference is still a
        # bureaucratic standalone — and we want it flagged. (Edge case
        # preserved from original test.)
        passed, reason = check_month_repetition(
            "Phoenix hit 121F today. It's April."
        )
        assert not passed
        assert "april" in (reason or "").lower()

    def test_no_month_passes(self):
        passed, reason = check_month_repetition("Phoenix hit 121F today.")
        assert passed

    def test_different_months_pass(self):
        # Mentioning two different months is fine (e.g. comparing May to April)
        passed, reason = check_month_repetition(
            "Phoenix at 121F in April. May average is only 95F."
        )
        assert passed

    def test_year_anchored_restatement_rejected(self):
        # Year-anchored restatement: "April 2026. April..." is the variant
        # where the writer prints a full date then opens the next sentence
        # with the same month for no reason.
        passed, reason = check_month_repetition(
            "Heat dome over Phoenix. April 2026. April records have already fallen."
        )
        assert not passed

    # -- Regression tests: monthly_low/high tweets that the prior rule
    #    rejected as false positives. The voice-regression cron flagged
    #    all three on 2026-05-10.

    def test_monthly_low_date_and_record_class_passes(self):
        # The Sissonville pattern: month as date AND as record class.
        passed, reason = check_month_repetition(
            "Sissonville, West Virginia hit 28°F (-2.2°C) overnight on May 4 "
            "— a new May cold record in 16 years of data, undercutting the "
            "previous mark of 29°F (-1.7°C) set in 2020. Hard frost, in spring."
        )
        assert passed, f"Should pass, got: {reason}"

    def test_monthly_low_dayton_pattern_passes(self):
        # The Dayton pattern: same date-plus-record-class shape, cleaner.
        passed, reason = check_month_repetition(
            "Dayton, Wyoming hit 15°F (-9.4°C) on May 5 — the coldest May "
            "night in 21 years of records there, snapping a mark set in 2010 "
            "by 2°F."
        )
        assert passed, f"Should pass, got: {reason}"

    def test_monthly_high_three_mentions_with_voice_flourish_passes(self):
        # The Verkhoyansk pattern: 3 April mentions, none of them
        # bureaucratic — date, record class, and a poetic "still belongs to
        # winter" framing. The safety-net threshold (≥4) allows this.
        passed, reason = check_month_repetition(
            "Verkhoyansk, Russia — one of the coldest cities on Earth — hit "
            "14.8°C (59°F) in April, smashing its previous April record of "
            "12.3°C set in 2018 by 2.5°C. That margin, in a 30-year archive "
            "for a place where April still belongs to winter, is not subtle."
        )
        assert passed, f"Should pass, got: {reason}"

    def test_four_plus_mentions_rejected_as_padding(self):
        # Safety net: any single month appearing 4+ times is padding.
        passed, reason = check_month_repetition(
            "April April April April records are falling."
        )
        assert not passed
        assert "padding" in (reason or "").lower()


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


class TestFabricatedContext:
    """Anti-fabrication banned phrases mirror the writer prompt's HARD RULES.

    The writer prompt at src/two_bot/prompts/writer_prompt.py is the primary
    defense against fabricated temporal/seasonal/biological framing — the
    "NO FABRICATED CONTEXT" bullet was added in PR #50 after two confirmed
    fact-check kills on Dayton WY (2026-05-08) for invented context like
    "January reading" and "three weeks into meteorological spring."

    safety.py mirrors the specific examples so a runaway model (swapped,
    retrained, prompt-drifted) can't ship a fabricated tweet even if the
    prompt is ignored. Tests below assert each banned phrase is caught and
    that nearby legitimate phrases (anthropomorphic flourish, genuine
    seasonal references) are NOT caught.
    """

    def test_three_weeks_into_meteorological_spring_rejected(self):
        passed, reason = check_regex(
            "Cold snap in Texas, three weeks into meteorological spring."
        )
        assert not passed
        assert reason is not None

    def test_january_reading_rejected(self):
        passed, reason = check_regex(
            "Phoenix at 121F. A January reading on a May day."
        )
        assert not passed

    def test_flowers_are_already_up_rejected(self):
        passed, reason = check_regex(
            "Hard freeze in Iowa, where flowers are already up."
        )
        assert not passed

    def test_the_ground_froze_rejected(self):
        passed, reason = check_regex(
            "Late frost in Maine; the ground froze overnight."
        )
        assert not passed

    def test_fruit_trees_blooming_early_rejected(self):
        passed, reason = check_regex(
            "Hard freeze in West Virginia with fruit trees blooming early."
        )
        assert not passed

    def test_anthropomorphic_flourish_passes(self):
        """Sissonville regression: the canonical 'Fruit trees were not
        consulted' line is voice, not fabrication. Must NOT match."""
        passed, reason = check_regex(
            "Fruit trees in the Kanawha Valley were not consulted."
        )
        assert passed, f"Legitimate flourish was rejected: {reason}"

    def test_supposed_to_be_spring_passes(self):
        """A genuine seasonal reference grounded in the calendar is voice;
        the bot ships these legitimately. Must NOT match."""
        passed, reason = check_regex(
            "Cold snap in Wyoming in a month that is supposed to be spring."
        )
        assert passed, f"Legitimate seasonal reference was rejected: {reason}"

    def test_three_springs_later_passes(self):
        """Shipped tweet about Sissonville used 'three springs later' as
        an echo of 'three years.' Must NOT match the meteorological-spring
        rule (rule targets the exact phrase, not all spring mentions)."""
        passed, reason = check_regex(
            "A hard freeze, in the Appalachian foothills, three springs later."
        )
        assert passed, f"Legitimate 'three springs later' echo was rejected: {reason}"
