from src.two_bot.fact_check import fact_check as real_fact_check
from src.two_bot.pipeline import generate_fire_draft
from src.two_bot.types import ExtractedClaim, FactCheckResult, WriterResult

from tests.two_bot.conftest import _fire_event, _state_with_memory


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

    draft = generate_fire_draft(_fire_event(), state)

    assert draft is None
    assert state["memory"]["shipped_tweets"] == []
    assert not mock_extract.called
    assert not mock_fact_check.called


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

