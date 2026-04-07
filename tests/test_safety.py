"""Tests for the two-layer safety pipeline."""

from src.voice.safety import check_regex, run_safety_pipeline


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


class TestSafetyPipeline:
    def test_clean_tweet_passes_full_pipeline(self):
        # LLM layer skipped when no API key is set
        passed, reason = run_safety_pipeline("Phoenix hit 119F. New record for April.")
        assert passed

    def test_regex_failure_short_circuits(self):
        passed, reason = run_safety_pipeline("BREAKING: Phoenix hit 119F!")
        assert not passed
        # Should fail on regex, never reaching LLM
