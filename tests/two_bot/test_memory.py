from src.two_bot.memory import build_memory_slice, is_reuse, record_shipped
from src.two_bot.types import ExtractedClaim, StoryBundle, WriterResult

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


def test_build_memory_slice_exposes_recent_tweets_for_event_base():
    state = _state_with_memory(
        shipped_tweets=[
            {
                "tweet_text": "Hurricane Alpha hit Cat 3 in the Atlantic.",
                "event_id": "gdacs_TC_1001270_tier3",
                "country": "US",
                "shipped_at": "2026-05-03T00:00:00Z",
            },
            {
                "tweet_text": "Unrelated cyclone tweet.",
                "event_id": "gdacs_TC_9999999_tier3",
                "country": "US",
                "shipped_at": "2026-05-03T01:00:00Z",
            },
        ]
    )
    state["drafts"] = [
        {
            "text": "Hurricane Alpha pushed higher again.",
            "event_id": "gdacs_TC_1001270_tier4",
            "created_at": "2026-05-03T02:00:00Z",
        }
    ]
    bundle = _bundle(event_id="gdacs_TC_1001270_tier5", country="US")

    memory_slice = build_memory_slice(state, bundle)

    assert memory_slice.recent_tweets_same_event == [
        "Hurricane Alpha pushed higher again.",
        "Hurricane Alpha hit Cat 3 in the Atlantic.",
    ]


def test_memory_slice_groups_severe_weather_by_event_type_and_area():
    state = _empty_memory_state()
    bundle = StoryBundle(
        signal_kind="severe_weather",
        where="Florida Keys",
        when="2026-05-04",
        event_id="nws_https://api.weather.gov/alerts/alpha",
        headline_metric={"label": "event_type", "value": "Hurricane Warning"},
        current_facts=[
            {"label": "event_type", "value": "Hurricane Warning"},
            {"label": "area", "value": "Florida Keys"},
        ],
        historical_context={},
        raw_signal_dump={},
    )
    writer = WriterResult(
        tweet="Florida Keys are under a hurricane warning.",
        kill_reason=None,
        angle_chosen="plain_warning",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    record_shipped(state, bundle, writer, [])
    next_bundle = StoryBundle(
        signal_kind="severe_weather",
        where="Florida Keys",
        when="2026-05-04",
        event_id="nws_https://api.weather.gov/alerts/beta",
        headline_metric={"label": "event_type", "value": "Hurricane Warning"},
        current_facts=[
            {"label": "event_type", "value": "Hurricane Warning"},
            {"label": "area", "value": "Florida Keys"},
        ],
        historical_context={},
        raw_signal_dump={},
    )

    memory_slice = build_memory_slice(state, next_bundle)

    assert memory_slice.recent_tweets_same_event == [
        "Florida Keys are under a hurricane warning.",
    ]


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
