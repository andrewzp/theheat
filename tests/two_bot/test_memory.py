from datetime import datetime, timedelta, timezone

from src.two_bot.memory import (
    _signal_kind_to_category,
    build_memory_slice,
    is_reuse,
    record_published_draft,
    record_shipped,
)
from src.two_bot.types import ExtractedClaim, StoryBundle, WriterResult

from tests.two_bot.conftest import (
    _bundle,
    _empty_memory_state,
    _state_with_memory,
    _state_with_shipped_tweets,
)


def _iso_hours_ago(hours: float) -> str:
    """Return an ISO-8601 UTC timestamp for ``hours`` hours before now."""
    ts = datetime.now(timezone.utc) - timedelta(hours=hours)
    return ts.isoformat().replace("+00:00", "Z")


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


def test_build_memory_slice_exposes_recent_published_tweets_for_event_base():
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
        "Hurricane Alpha hit Cat 3 in the Atlantic.",
    ]


def test_record_published_draft_writes_memory_from_persisted_two_bot_metadata():
    state = _empty_memory_state()
    draft = {
        "text": "Hurricane Alpha hit Cat 3 in the Atlantic.",
        "event_id": "gdacs_TC_1001270_tier3",
        "type": "global_disaster",
        "tweet_id": "tweet_123",
        "review_context": {
            "two_bot": {
                "signal_kind": "global_disaster",
                "angle_chosen": "named_storm_scale",
                "era_anchor_used": None,
                "peer_comparison_used": "Category 3 hurricane",
                "reasoning": "test",
                "fact_check": {
                    "extracted_claims": [
                        {"text": "Category 3 hurricane", "kind": "peer_comparison"}
                    ]
                },
                "bundle": {
                    "signal_kind": "global_disaster",
                    "where": "Atlantic",
                    "when": "2026-05-03",
                    "event_id": "gdacs_TC_1001270_tier3",
                    "current_facts": [
                        {"label": "disaster_type", "value": "Tropical Cyclone"},
                        {"label": "name", "value": "Alpha"},
                        {"label": "country", "value": "United States"},
                    ],
                },
            }
        },
    }

    assert record_published_draft(state, draft) is True

    memory = state["memory"]
    assert memory["shipped_tweets"][0]["tweet_text"] == draft["text"]
    assert memory["shipped_tweets"][0]["tweet_id"] == "tweet_123"
    assert "category 3 hurricane" in memory["used_peer_comparisons"]
    assert "named_storm_scale" in memory["used_framings"]


def test_build_memory_slice_limits_global_shipped_texts_but_keeps_same_event_context():
    rows = []
    for i in range(30):
        rows.append(
            {
                "tweet_text": f"published tweet {i}",
                "signal_kind": "fire",
                "event_id": "fire_target_a_old" if i == 25 else f"fire_other_{i}",
                "country": "ML",
                "shipped_at": _iso_hours_ago(i + 1),
            }
        )
    state = _state_with_memory(shipped_tweets=rows)
    bundle = _bundle(event_id="fire_target_a_new", country="ML")

    memory_slice = build_memory_slice(state, bundle)

    assert memory_slice.shipped_tweet_texts == [
        f"published tweet {i}" for i in range(20)
    ]
    assert memory_slice.recent_tweets_same_country == [
        f"published tweet {i}" for i in range(5)
    ]
    assert memory_slice.recent_tweets_same_event == ["published tweet 25"]


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


# ============================================================================
# Category cooldown: MemorySlice.recent_categories exposes the signal
# categories already posted in the last 24h so the writer can self-veto a
# same-category draft. The memory layer dedupes by country today; the
# category axis is the gap that lets us post two fires back-to-back. Each
# signal_kind maps to a coarser category (fire+fire_footprint → "fire",
# all temperature-record variants → "temperature_record", etc.) so the
# writer reasons about content variety, not detection-source variety.
# ============================================================================


def test_build_memory_slice_includes_recent_categories_in_last_24h():
    state = _state_with_memory(
        shipped_tweets=[
            {
                "tweet_text": "Mali fire 1",
                "signal_kind": "fire",
                "event_id": "fire_a",
                "country": "ML",
                "shipped_at": _iso_hours_ago(2),
            },
            {
                "tweet_text": "Mali fire 2",
                "signal_kind": "fire",
                "event_id": "fire_b",
                "country": "ML",
                "shipped_at": _iso_hours_ago(8),
            },
        ]
    )
    bundle = _bundle(event_id="fire_c", country="ML")

    memory_slice = build_memory_slice(state, bundle)

    # Two fires within 24h dedupe to a single category entry.
    assert memory_slice.recent_categories == ["fire"]


def test_build_memory_slice_filters_categories_older_than_24h():
    state = _state_with_memory(
        shipped_tweets=[
            {
                "tweet_text": "Old fire (25h ago)",
                "signal_kind": "fire",
                "event_id": "fire_old",
                "country": "ML",
                "shipped_at": _iso_hours_ago(25),
            }
        ]
    )
    bundle = _bundle(event_id="fire_new", country="ML")

    memory_slice = build_memory_slice(state, bundle)

    # 25h-old shipped tweet must NOT appear in the 24h cooldown window.
    assert memory_slice.recent_categories == []


def test_build_memory_slice_recent_categories_dedupes_most_recent_first():
    """Multiple categories within 24h dedupe; order is most-recent-first
    so the writer reads the freshest category first."""
    state = _state_with_memory(
        shipped_tweets=[
            {
                "tweet_text": "Fire 12h ago",
                "signal_kind": "fire",
                "event_id": "fire_a",
                "country": "ML",
                "shipped_at": _iso_hours_ago(12),
            },
            {
                "tweet_text": "Temperature record 6h ago",
                "signal_kind": "monthly_high",
                "event_id": "monthly_a",
                "country": "ES",
                "shipped_at": _iso_hours_ago(6),
            },
            {
                "tweet_text": "Another fire 2h ago",
                "signal_kind": "fire_footprint",
                "event_id": "footprint_a",
                "country": "AU",
                "shipped_at": _iso_hours_ago(2),
            },
        ]
    )
    bundle = _bundle(event_id="fire_new", country="US")

    memory_slice = build_memory_slice(state, bundle)

    # fire_footprint maps to "fire"; monthly_high maps to "temperature_record".
    # Most-recent-first: 2h fire, then 6h temperature_record. Fire dedupes.
    assert memory_slice.recent_categories == ["fire", "temperature_record"]


def test_signal_kind_to_category_handles_known_and_unknown_kinds():
    assert _signal_kind_to_category("fire") == "fire"
    assert _signal_kind_to_category("fire_footprint") == "fire"
    assert _signal_kind_to_category("monthly_high") == "temperature_record"
    assert _signal_kind_to_category("calendar_record_low") == "temperature_record"
    assert _signal_kind_to_category("anomaly_hot") == "anomaly"
    assert _signal_kind_to_category("sea_ice") == "cryosphere"
    # Unknown kind falls back to the input string so the writer still sees
    # something meaningful rather than dropping the entry silently.
    assert _signal_kind_to_category("future_signal_kind") == "future_signal_kind"
