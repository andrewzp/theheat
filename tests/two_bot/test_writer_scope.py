"""Deterministic editorial-scope guard for the two-bot writer.

@theheat is a climate-data account. Purely geophysical signals with no
climate mechanism — earthquakes — are editorially out of scope. The live
writer model already declines them, but *non-deterministically*: that whim
flaked the daily ``voice-regression`` workflow for days (it passed
2026-06-09 / 06-11 and failed every other run because the model sometimes
wrote the earthquake and sometimes killed it).

These tests pin the decision in code: an out-of-scope signal is killed
deterministically, BEFORE any (paid) model call. A normal climate signal
must still reach the model untouched.
"""

from __future__ import annotations

from src.two_bot.types import StoryBundle
from src.two_bot.writer import write_tweet

from tests.two_bot.conftest import _bundle, _fake_writer_response, _memory


def _earthquake_bundle() -> StoryBundle:
    return StoryBundle(
        signal_kind="usgs_earthquake",
        where="12 km S of Example City, Chile",
        when="2026-06-14",
        event_id="usgs_eq_test",
        headline_metric={"label": "magnitude", "value": 7.1, "unit": "M"},
        current_facts=[
            {"label": "source", "value": "USGS Earthquake Hazards Program"},
            {"label": "magnitude", "value": 7.1, "unit": "M"},
        ],
        historical_context={},
        raw_signal_dump={"magnitude": 7.1},
    )


def test_writer_declines_out_of_scope_earthquake_without_model_call(mock_anthropic):
    """An earthquake bundle is killed deterministically, with no model call."""
    # If the guard is missing, the model would be called and would return
    # this tweet — the assertions below would then fail.
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": "this tweet must never be produced for an earthquake",
            "kill_reason": None,
            "angle_chosen": "x",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "x",
        }
    )

    result = write_tweet(_earthquake_bundle(), _memory())

    assert result.tweet is None
    assert result.kill_reason is not None
    assert "scope" in result.kill_reason.lower()
    assert not mock_anthropic.called, (
        "out-of-scope earthquake must be killed deterministically, without "
        "spending a writer model call"
    )


def test_writer_still_calls_model_for_in_scope_signal(mock_anthropic):
    """The guard is narrow: a normal climate signal still reaches the model."""
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": "Mali fire test",
            "kill_reason": None,
            "angle_chosen": "rarity",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "x",
        }
    )

    result = write_tweet(_bundle(), _memory())

    assert result.tweet == "Mali fire test"
    assert result.kill_reason is None
    assert mock_anthropic.called
