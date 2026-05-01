from src.two_bot.memory import build_memory_slice, is_reuse, record_shipped
from src.two_bot.types import ExtractedClaim, WriterResult

from tests.two_bot.conftest import (
    _bundle,
    _empty_memory_state,
    _state_with_memory,
    _state_with_shipped_tweets,
)


def test_build_memory_slice_filters_by_country():
    state = _state_with_shipped_tweets(
        [
            ("US fire tweet 1", "US"),
            ("Mali fire tweet 1", "ML"),
            ("Mali fire tweet 2", "ML"),
            ("Brazil tweet", "BR"),
        ]
    )
    bundle = _bundle(country="ML")

    memory_slice = build_memory_slice(state, bundle)

    assert len(memory_slice.recent_tweets_same_country) == 2


def test_record_shipped_uses_extracted_claims_not_writer_self_report():
    state = _empty_memory_state()
    writer = WriterResult(
        tweet="In 2002, Spider-Man was new. Today, Mali burned.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    extracted = [ExtractedClaim(text="2002 Spider-Man", kind="era_anchor")]

    record_shipped(state, _bundle(), writer, extracted)

    assert "2002 spider-man" in state["memory"]["used_era_anchors"]


def test_record_shipped_updates_ongoing_event():
    state = _empty_memory_state()
    writer = WriterResult(
        tweet="Mali fire is 361 MW.",
        kill_reason=None,
        angle_chosen="plain_number",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )

    record_shipped(state, _bundle(event_id="fire_1"), writer, [])

    event = state["memory"]["ongoing_events"][0]
    assert event["event_id"] == "fire_1"
    assert event["region"] == "Mali"
    assert event["days_running"] == 1


def test_is_reuse_normalized_substring():
    state = _state_with_memory(used_era_anchors=["spider-man 2002"])

    assert is_reuse(state, "Spider-Man 2002", "era_anchor")
    assert is_reuse(state, "the year Spider-Man 2002 came out", "era_anchor")


def test_is_reuse_token_subset():
    """Token-subset triggers when stored canonical anchor tokens all appear."""

    state = _state_with_memory(used_era_anchors=["spider-man 2002"])

    assert is_reuse(state, "Spider-Man 2002 movie", "era_anchor")


def test_is_reuse_no_match_when_year_differs():
    state = _state_with_memory(used_era_anchors=["spider-man 2002"])

    assert not is_reuse(state, "Spider-Man 3 was 2007", "era_anchor")


def test_is_reuse_framing_exact_match_only():
    state = _state_with_memory(used_framings=["off_season_irony"])

    assert is_reuse(state, "off_season_irony", "framing")
    assert not is_reuse(state, "off_season", "framing")

