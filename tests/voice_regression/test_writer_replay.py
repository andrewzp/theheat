"""Live writer-replay regression suite.

Calls the real Anthropic writer (Sonnet) against each bundle fixture and
asserts the output passes the safety pipeline. Catches silent voice
regressions when the writer prompt or model changes.

Skipped by default. Runs in the dedicated `.github/workflows/voice-regression.yml`
workflow on a daily schedule, on demand via `workflow_dispatch`, or on
PRs with the `voice-check` label.

To run locally:

    ANTHROPIC_API_KEY=sk-ant-... \
      python -m pytest tests/voice_regression/ -v -m voice_replay
"""

from __future__ import annotations

import os

import pytest

from src.voice.safety import run_safety_pipeline


# Module-level marks — every test in this file requires both:
# - `voice_replay` so the regular CI suite can deselect via `-m "not voice_replay"`
# - `allow_network` to bypass the hermeticity gate (real Anthropic call)
pytestmark = [
    pytest.mark.voice_replay,
    pytest.mark.allow_network,
]


# Skip the whole module if the API key is missing — saves a confusing
# "401 unauthorized" stack trace when run locally without setup.
def _require_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; voice-replay tests require it")


BUNDLE_FIXTURES = [
    "sissonville_monthly_low_bundle",
    "dayton_monthly_low_bundle",
    "verkhoyansk_monthly_high_bundle",
    "mali_fire_bundle",
    "co2_milestone_bundle",
    "ch4_milestone_bundle",
    "coral_bleaching_bundle",
    "cyclone_rapid_intensification_bundle",
    "cyclone_landfall_bundle",
    "cyclone_basin_record_bundle",
]


@pytest.mark.parametrize("bundle_fixture_name", BUNDLE_FIXTURES)
def test_writer_output_passes_safety_pipeline(
    bundle_fixture_name, request, fresh_memory_slice
):
    """Live replay: writer produces output that the safety pipeline accepts.

    Catches:
    - Length-cap violations (>280 chars).
    - Banned-pattern emissions (Severity:value, BREAKING:, throat-clearing
      openers, fabricated-context phrases from PR #58).
    - Truncated temperatures.
    - Repeated month names.

    Does NOT catch:
    - Subtle voice quality (use Tier 3 LLM-as-judge for that).
    - Factual accuracy (use the existing fact_check pipeline).
    """
    _require_api_key()
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(bundle_fixture_name)
    result = write_tweet(bundle, fresh_memory_slice)

    assert result.tweet is not None, (
        f"Writer killed {bundle_fixture_name} ({result.kill_reason}); "
        "voice replay must fail when the writer stops producing copy."
    )

    assert len(result.tweet) <= 280, (
        f"Tweet exceeds 280 char cap: {len(result.tweet)} chars\n"
        f"Tweet: {result.tweet!r}"
    )

    safe, reason = run_safety_pipeline(result.tweet)
    assert safe, (
        f"Safety pipeline rejected {bundle_fixture_name}:\n"
        f"  reason: {reason}\n"
        f"  tweet:  {result.tweet!r}"
    )


@pytest.mark.parametrize(
    "bundle_fixture_name",
    [
        "sissonville_monthly_low_bundle",
        "dayton_monthly_low_bundle",
    ],
)
def test_archive_window_only_no_absolute_claims(
    bundle_fixture_name, request, fresh_memory_slice
):
    """When the bundle's historical_context says archive_window_only=True,
    the writer must NOT use absolute language ("all-time", "ever", "in
    recorded history") because the data only spans the archive window.

    The prompt has an explicit rule (writer_prompt.py) — this test
    confirms the model honors it.
    """
    _require_api_key()
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(bundle_fixture_name)
    assert bundle.historical_context.get("archive_window_only") is True, (
        "Test fixture must have archive_window_only=True to exercise this rule"
    )

    result = write_tweet(bundle, fresh_memory_slice)
    assert result.tweet is not None, (
        f"Writer killed {bundle_fixture_name}: {result.kill_reason}"
    )

    lowered = result.tweet.lower()
    forbidden_absolutes = ["all-time", "all time", " ever ", "in recorded history"]
    for phrase in forbidden_absolutes:
        assert phrase not in lowered, (
            f"Writer used absolute phrasing {phrase!r} on an "
            f"archive_window_only bundle ({bundle_fixture_name}):\n"
            f"  tweet: {result.tweet!r}"
        )


@pytest.mark.parametrize("bundle_fixture_name", BUNDLE_FIXTURES)
def test_no_fabricated_context_phrases(
    bundle_fixture_name, request, fresh_memory_slice
):
    """The writer prompt's NO FABRICATED CONTEXT bullet (PR #50) names
    specific banned phrases. PR #58 mirrored them into safety regex, so
    the post-time check would catch any leaks. This test runs at write-
    time as an additional regression signal in the live workflow output.
    """
    _require_api_key()
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(bundle_fixture_name)
    result = write_tweet(bundle, fresh_memory_slice)
    assert result.tweet is not None, (
        f"Writer killed {bundle_fixture_name}: {result.kill_reason}"
    )

    lowered = result.tweet.lower()
    forbidden_phrases = [
        "three weeks into meteorological spring",
        "january reading",
        "flowers are already up",
        "the ground froze",
        "fruit trees blooming early",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in lowered, (
            f"Writer emitted fabricated-context phrase {phrase!r} on "
            f"{bundle_fixture_name}:\n"
            f"  tweet: {result.tweet!r}"
        )
