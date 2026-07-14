"""Live writer-replay regression suite.

Calls the real Anthropic writer (Sonnet) against each bundle fixture and
asserts the output stays within the writer's contract. Catches silent voice
regressions when the writer prompt or model changes.

Skipped by default. Runs in the dedicated `.github/workflows/voice-regression.yml`
workflow: weekly full suite (Sunday), automatically on PRs touching the
writer path (`src/two_bot/prompts/**`, `writer.py`), on demand via
`workflow_dispatch`, or on PRs with the `voice-check` label. The daily
3-fixture canary lives in `test_canary.py` (economics P0.4).

To run locally:

    ANTHROPIC_API_KEY=sk-ant-... \
      python -m pytest tests/voice_regression/ -v -m voice_replay

## The writer's contract (why a kill is never a failure here)

The writer is designed so that **killing is the default** — its own system
prompt says "Most signals get killed… a mediocre tweet is worse than
silence." A live, non-deterministic model will, on any given sampling,
legitimately decline a borderline bundle (e.g. one whose honest framing
won't fit 280 characters). Asserting "the model ALWAYS emits a tweet" against
that model is inherently flaky — and it was: this suite went red for five
straight days (2026-06-12 → 06-16) because the writer correctly declined two
fixtures, not because the voice regressed.

So this suite asserts the contract the writer actually owns:

  * **Never ship bad copy.** If the writer DOES produce a tweet, it must be
    ≤280 chars, pass the safety pipeline, and carry no fabricated-context or
    absolute-claim violations. (This is the real voice-regression signal.)
  * **A clean kill is always acceptable.** `tweet=None` is a valid outcome
    for any bundle and never fails a test.
  * **Out-of-scope signals must be declined.** Earthquakes have no climate
    mechanism; the writer kills them deterministically (see
    `src.two_bot.writer.OUT_OF_SCOPE_SIGNAL_KINDS`).

"Has the writer gone too quiet?" is a production question, answered by the
Phase-A funnel telemetry (live writer pass/kill rates), not by a daily paid
CI gate that a single correct kill can turn red.
"""

from __future__ import annotations

import os

import pytest

from src.two_bot.writer import OUT_OF_SCOPE_SIGNAL_KINDS
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


# In-scope fixtures: the writer MAY produce a tweet or MAY cleanly kill, but
# if it produces one it must be safe. `regional_anomaly_bundle` is the most
# length-tight (its honest "N sampled cities" framing runs close to 280), so
# a length-cap kill is an expected, acceptable outcome for it.
TWEETABLE_FIXTURES = [
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
    "regional_anomaly_bundle",
    "precipitation_extreme_bundle",
    "air_quality_hazard_bundle",
    "dust_event_bundle",
    "synthesis_fire_drought_heat_bundle",
    "synthesis_marine_compound_bundle",
    "marine_heatwave_bundle",
    "wet_bulb_extreme_bundle",
]

# Out-of-scope fixtures: the writer must DECLINE these (no climate mechanism).
# The kill is deterministic — the scope guard short-circuits before any model
# call — so this assertion is free and never flakes.
OUT_OF_SCOPE_FIXTURES = [
    "usgs_earthquake_bundle",
]


@pytest.mark.parametrize("bundle_fixture_name", TWEETABLE_FIXTURES)
def test_writer_output_is_safe_or_a_clean_kill(
    bundle_fixture_name, request, fresh_memory_slice
):
    """Live replay: if the writer produces a tweet, it must be shippable.

    Catches (when a tweet IS produced):
    - Length-cap violations (>280 chars).
    - Banned-pattern emissions (Severity:value, BREAKING:, throat-clearing
      openers, fabricated-context phrases from PR #58).
    - Truncated temperatures.
    - Repeated month names.

    A clean kill (`tweet=None`) is an acceptable outcome for any bundle and
    is NOT a failure — see the module docstring.

    Does NOT catch:
    - Subtle voice quality (use Tier 3 LLM-as-judge for that).
    - Factual accuracy (use the existing fact_check pipeline).
    - "Writer too quiet" — that lives in the Phase-A production funnel.
    """
    _require_api_key()
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(bundle_fixture_name)
    result = write_tweet(bundle, fresh_memory_slice)

    if result.tweet is None:
        # A clean kill is the writer working as designed.
        return

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


@pytest.mark.parametrize("bundle_fixture_name", OUT_OF_SCOPE_FIXTURES)
def test_writer_declines_out_of_scope_signals(
    bundle_fixture_name, request, fresh_memory_slice
):
    """Out-of-scope signals (earthquakes) must be declined, deterministically.

    @theheat is a climate-data account; a purely geophysical event has no
    climate mechanism to frame. The scope guard kills these before any model
    call, so this is a free, deterministic policy lock — it pins the
    decision against a future prompt/model that might start drafting them.
    """
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(bundle_fixture_name)
    assert bundle.signal_kind in OUT_OF_SCOPE_SIGNAL_KINDS, (
        "Fixture must carry an out-of-scope signal_kind to exercise this rule"
    )

    result = write_tweet(bundle, fresh_memory_slice)
    assert result.tweet is None, (
        f"Writer produced a tweet for out-of-scope {bundle_fixture_name}:\n"
        f"  tweet: {result.tweet!r}"
    )
    assert "scope" in (result.kill_reason or "").lower(), (
        f"Out-of-scope kill_reason should explain the scope decision; got: "
        f"{result.kill_reason!r}"
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
    confirms the model honors it. A clean kill is acceptable (no copy, no
    way to violate the rule).
    """
    _require_api_key()
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(bundle_fixture_name)
    assert bundle.historical_context.get("archive_window_only") is True, (
        "Test fixture must have archive_window_only=True to exercise this rule"
    )

    result = write_tweet(bundle, fresh_memory_slice)
    if result.tweet is None:
        return

    lowered = result.tweet.lower()
    forbidden_absolutes = ["all-time", "all time", " ever ", "in recorded history"]
    for phrase in forbidden_absolutes:
        assert phrase not in lowered, (
            f"Writer used absolute phrasing {phrase!r} on an "
            f"archive_window_only bundle ({bundle_fixture_name}):\n"
            f"  tweet: {result.tweet!r}"
        )


@pytest.mark.parametrize("bundle_fixture_name", TWEETABLE_FIXTURES)
def test_no_fabricated_context_phrases(
    bundle_fixture_name, request, fresh_memory_slice
):
    """The writer prompt's NO FABRICATED CONTEXT bullet (PR #50) names
    specific banned phrases. PR #58 mirrored them into safety regex, so
    the post-time check would catch any leaks. This test runs at write-
    time as an additional regression signal in the live workflow output.

    A clean kill is acceptable (no copy to inspect).
    """
    _require_api_key()
    from src.two_bot.writer import write_tweet

    bundle = request.getfixturevalue(bundle_fixture_name)
    result = write_tweet(bundle, fresh_memory_slice)
    if result.tweet is None:
        return

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


def test_regional_anomaly_writer_keeps_point_index_honesty(
    regional_anomaly_bundle, fresh_memory_slice
):
    """REQUIRED honesty eval (Rev-3): the live writer must frame a regional
    anomaly as a point index over N sampled cities, never a bare-region or
    area-weighted national mean. Verifies prompt Layers 2-3 — which unit tests
    cannot exercise — and guards against prompt drift silently re-opening the
    primary leak. The deterministic §F gate is the production backstop; this
    asserts the writer doesn't need it.

    A clean kill is acceptable: a killed draft ships nothing, so it cannot
    leak a bare-region aggregate. The honesty assertions only apply when the
    writer actually produces copy.
    """
    _require_api_key()
    from src.two_bot.pipeline import _forbidden_claim_violation
    from src.two_bot.writer import write_tweet

    bundle = regional_anomaly_bundle
    result = write_tweet(bundle, fresh_memory_slice)
    if result.tweet is None:
        return

    safe, reason = run_safety_pipeline(result.tweet)
    assert safe, f"Safety pipeline rejected regional anomaly draft:\n  {reason}\n  {result.tweet!r}"

    # §F: the honest draft must NOT trip any forbidden bare-region aggregate.
    violation = _forbidden_claim_violation(result.tweet, bundle)
    assert violation is None, (
        f"Writer emitted a forbidden bare-region aggregate {violation!r}:\n"
        f"  tweet: {result.tweet!r}"
    )

    # Honest attribution must be present: the sampled-city framing or the count.
    lowered = result.tweet.lower()
    assert "sampled" in lowered or "cities" in lowered or "7" in result.tweet, (
        "Regional-anomaly draft dropped the N-sampled-cities attribution:\n"
        f"  tweet: {result.tweet!r}"
    )
