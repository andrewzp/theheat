from src.two_bot.fact_check import fact_check as real_fact_check
from src.two_bot.pipeline import (
    generate_draft,
    generate_fire_draft,
    generate_shadow_draft,
)
from src.two_bot.types import ExtractedClaim, FactCheckResult, StoryBundle, WriterResult

from tests.two_bot.conftest import _bundle, _fire_event, _state_with_memory


def test_pipeline_happy_path(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet="Mali fire is 1.4x a 250 MW gas plant.",
        kill_reason=None,
        angle_chosen="named_comparison_scale",
        era_anchor_used=None,
        peer_comparison_used="250 MW gas plant",
        reasoning="test",
    )
    mock_extract.return_value = [
        ExtractedClaim(text="250 MW gas plant", kind="peer_comparison"),
        ExtractedClaim(text="Mali", kind="named_entity"),
    ]
    mock_fact_check.return_value = FactCheckResult(
        passed=True,
        failures=[],
        raw_response="ok",
        extracted_claims=mock_extract.return_value,
    )
    state = _state_with_memory()

    draft = generate_fire_draft(_fire_event(), state)

    assert draft is not None
    assert draft["text"].startswith("Mali")
    assert "250 mw gas plant" in state["memory"]["used_peer_comparisons"]


def test_pipeline_writer_kills(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet=None,
        kill_reason="no historical_context available",
        angle_chosen="",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    state = _state_with_memory()

    draft = generate_fire_draft(_fire_event(), state)

    assert draft is None
    assert state["memory"]["shipped_tweets"] == []
    assert not mock_extract.called
    assert not mock_fact_check.called


def test_pipeline_fact_check_fails(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet="Mali fire is 361 MW.",
        kill_reason=None,
        angle_chosen="plain_number",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = [ExtractedClaim(text="361 MW", kind="number")]
    mock_fact_check.return_value = FactCheckResult(
        passed=False,
        failures=["unverified"],
        raw_response="fail",
        extracted_claims=mock_extract.return_value,
    )
    state = _state_with_memory()

    draft = generate_fire_draft(_fire_event(), state)

    assert draft is None
    assert state["memory"]["shipped_tweets"] == []


def test_pipeline_writer_raises(mock_writer, mock_extract, mock_fact_check):
    mock_writer.side_effect = RuntimeError("api down")
    state = _state_with_memory()
    result_out = {}

    draft = generate_fire_draft(_fire_event(), state, result_out=result_out)

    assert draft is None
    assert state["memory"]["shipped_tweets"] == []
    assert not mock_extract.called
    assert not mock_fact_check.called
    assert result_out["kill_stage"] == "pipeline_error"
    assert "api down" in result_out["kill_reason"]


def test_pipeline_memory_loop_blocks_reuse(mock_writer, mock_extract, mock_fact_check):
    state = _state_with_memory()

    mock_writer.return_value = WriterResult(
        tweet="Mali burned. Spider-Man 2002 was the era.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used="Spider-Man 2002",
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = [ExtractedClaim(text="Spider-Man 2002", kind="era_anchor")]
    mock_fact_check.return_value = FactCheckResult(
        passed=True,
        failures=[],
        raw_response="ok",
        extracted_claims=mock_extract.return_value,
    )
    draft1 = generate_fire_draft(_fire_event(event_id="fire_first"), state)

    assert draft1 is not None
    assert "spider-man 2002" in state["memory"]["used_era_anchors"]

    mock_writer.return_value = WriterResult(
        tweet="Another Mali fire. Spider-Man 2002 was new last time.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = [ExtractedClaim(text="Spider-Man 2002", kind="era_anchor")]
    mock_fact_check.side_effect = real_fact_check

    draft2 = generate_fire_draft(_fire_event(event_id="fire_second"), state)

    assert draft2 is None


# ----------------------- shadow pipeline tests -----------------------


def _monthly_high_bundle() -> StoryBundle:
    return StoryBundle(
        signal_kind="monthly_high",
        where="Conakry, Guinea",
        when="2026-05-01",
        event_id="meteo_monthly_Conakry_2026-05-01",
        headline_metric={"label": "forecast_high_c", "value": 35.4, "unit": "C"},
        current_facts=[
            {"label": "city", "value": "Conakry"},
            {"label": "country", "value": "Guinea"},
            {"label": "month", "value": "May"},
        ],
        historical_context={
            "prior_record_c": 34.3,
            "prior_record_year": 2022,
            "archive_years": 30,
            "month": "May",
            "margin_c": 1.1,
        },
        raw_signal_dump={},
    )


def test_shadow_returns_text_and_metadata(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea: hottest May in 30 years.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = []
    mock_fact_check.return_value = FactCheckResult(
        passed=True, failures=[], raw_response="ok", extracted_claims=[],
    )
    state = _state_with_memory()

    result = generate_shadow_draft(_monthly_high_bundle(), state)

    assert result is not None
    assert result["text"].startswith("Conakry")
    assert result["two_bot_metadata"]["signal_kind"] == "monthly_high"
    assert result["two_bot_metadata"]["angle_chosen"] == "rarity"


def test_shadow_does_not_record_memory(mock_writer, mock_extract, mock_fact_check):
    """The shadow MUST NOT pollute the memory layer.

    The shadow tweet is never shipped, so writing it into shipped_tweets,
    used_era_anchors, etc. would corrupt the banned-reuse list with text
    the audience never saw.
    """
    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea: hottest May since 2022.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used="some-era-anchor",
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = [
        ExtractedClaim(text="some-era-anchor", kind="era_anchor"),
    ]
    mock_fact_check.return_value = FactCheckResult(
        passed=True, failures=[], raw_response="ok",
        extracted_claims=mock_extract.return_value,
    )
    state = _state_with_memory()

    result = generate_shadow_draft(_monthly_high_bundle(), state)

    assert result is not None
    assert state["memory"]["shipped_tweets"] == []
    assert state["memory"]["used_era_anchors"] == []
    assert state["memory"]["used_framings"] == []


def test_shadow_returns_none_when_writer_kills(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet=None,
        kill_reason="not extraordinary",
        angle_chosen="",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    state = _state_with_memory()

    result = generate_shadow_draft(_monthly_high_bundle(), state)

    assert result is None
    assert not mock_extract.called


def test_shadow_returns_none_on_writer_exception(mock_writer):
    mock_writer.side_effect = RuntimeError("api down")
    state = _state_with_memory()

    result = generate_shadow_draft(_monthly_high_bundle(), state)

    assert result is None


def test_shadow_returns_none_on_fact_check_fail(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea: hottest May.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = []
    mock_fact_check.return_value = FactCheckResult(
        passed=False, failures=["unverified"], raw_response="fail",
        extracted_claims=[],
    )
    state = _state_with_memory()

    result = generate_shadow_draft(_monthly_high_bundle(), state)

    assert result is None
    assert state["memory"]["shipped_tweets"] == []


# ----------------------- generic generate_draft tests -----------------------


def test_generate_draft_records_memory(mock_writer, mock_extract, mock_fact_check):
    """Unlike generate_shadow_draft, generate_draft must write to the
    memory layer when a draft is produced. This is the live path —
    skipping memory would let the same tweet ship repeatedly."""
    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea: hottest May since 2022.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used="some-era-anchor",
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = [
        ExtractedClaim(text="some-era-anchor", kind="era_anchor"),
    ]
    mock_fact_check.return_value = FactCheckResult(
        passed=True, failures=[], raw_response="ok",
        extracted_claims=mock_extract.return_value,
    )
    state = _state_with_memory()

    result = generate_draft(_monthly_high_bundle(), state)

    assert result is not None
    assert result["text"].startswith("Conakry")
    assert result["type"] == "monthly_high"
    assert result["event_id"] == "meteo_monthly_Conakry_2026-05-01"
    # Live path DOES record memory — the shadow path is the one that doesn't.
    assert "some-era-anchor" in state["memory"]["used_era_anchors"]


def test_generate_draft_returns_none_on_writer_kill(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet=None,
        kill_reason="not extraordinary",
        angle_chosen="",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    state = _state_with_memory()

    result = generate_draft(_monthly_high_bundle(), state)

    assert result is None
    assert state["memory"]["shipped_tweets"] == []
    assert not mock_extract.called


def test_generate_draft_returns_none_on_fact_check_fail(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea: hottest May.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_extract.return_value = []
    mock_fact_check.return_value = FactCheckResult(
        passed=False, failures=["unverified"], raw_response="fail",
        extracted_claims=[],
    )
    state = _state_with_memory()

    result = generate_draft(_monthly_high_bundle(), state)

    assert result is None
    # Critically, memory is NOT written when fact-check fails — even though
    # the writer succeeded. record_shipped only fires on the full happy path.
    assert state["memory"]["shipped_tweets"] == []


def test_generate_draft_swallows_exceptions(mock_writer):
    mock_writer.side_effect = RuntimeError("upstream API down")
    state = _state_with_memory()

    result = generate_draft(_monthly_high_bundle(), state)

    assert result is None  # never raises
