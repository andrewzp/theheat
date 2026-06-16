"""Phase A: generate_draft records per-candidate stage outcomes in result_out.

These pin the codex must-fix #1 denominator rules: writer / fact_check / critic
each get an explicit terminal pass|kill outcome (or no entry when not reached),
so the funnel's critic_pass_rate denominator can never lie.
"""

from __future__ import annotations

from src.two_bot.pipeline import generate_fire_draft
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult

from tests.two_bot.conftest import _fire_event, _state_with_memory


def _writer(tweet="Mali fire burned an area larger than a major city this week."):
    return WriterResult(
        tweet=tweet, kill_reason=None, angle_chosen="plain_number",
        era_anchor_used=None, peer_comparison_used=None, reasoning="test",
    )


def test_happy_path_marks_all_three_pass(mock_writer, mock_fact_check, mock_critic, mock_safety):
    mock_writer.return_value = _writer()
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    mock_critic.return_value = CriticResult(passed=True, kill_reason=None, raw_response="pass")
    ro: dict = {}
    draft = generate_fire_draft(_fire_event(), _state_with_memory(), result_out=ro)
    assert draft is not None
    assert ro["stage_outcomes"] == {"writer": "pass", "fact_check": "pass", "critic": "pass"}


def test_writer_kill_marks_writer_only(mock_writer, mock_fact_check, mock_critic, mock_safety):
    mock_writer.return_value = WriterResult(
        tweet=None, kill_reason="no anchor", angle_chosen="", era_anchor_used=None,
        peer_comparison_used=None, reasoning="test",
    )
    ro: dict = {}
    draft = generate_fire_draft(_fire_event(), _state_with_memory(), result_out=ro)
    assert draft is None
    assert ro["stage_outcomes"] == {"writer": "kill"}
    assert ro["kill_stage"] == "writer"


def test_fact_check_fail_marks_writer_pass_fact_check_kill_no_critic(
    mock_writer, mock_fact_check, mock_critic, mock_safety
):
    mock_writer.return_value = _writer()
    mock_fact_check.return_value = FactCheckResult(
        passed=False, failures=["unverified"], raw_response="fail", extracted_claims=[]
    )
    ro: dict = {}
    draft = generate_fire_draft(_fire_event(), _state_with_memory(), result_out=ro)
    assert draft is None
    assert ro["stage_outcomes"] == {"writer": "pass", "fact_check": "kill"}
    assert "critic" not in ro["stage_outcomes"]
    assert not mock_critic.called


def test_critic_kill_marks_writer_fact_check_pass_critic_kill(
    mock_writer, mock_fact_check, mock_critic, mock_safety
):
    mock_writer.return_value = _writer()
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    mock_critic.return_value = CriticResult(passed=False, kill_reason="template convergence", raw_response="kill")
    ro: dict = {}
    draft = generate_fire_draft(_fire_event(), _state_with_memory(), result_out=ro)
    assert draft is None
    assert ro["stage_outcomes"] == {"writer": "pass", "fact_check": "pass", "critic": "kill"}
    assert ro["kill_stage"] == "critic"


def test_critic_disabled_has_no_critic_outcome(
    monkeypatch, mock_writer, mock_fact_check, mock_safety
):
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    mock_writer.return_value = _writer()
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    ro: dict = {}
    draft = generate_fire_draft(_fire_event(), _state_with_memory(), result_out=ro)
    assert draft is not None
    assert ro["stage_outcomes"] == {"writer": "pass", "fact_check": "pass"}


def test_revise_writer_kill_overwrites_writer_pass(
    monkeypatch, mock_writer, mock_fact_check, mock_critic, mock_safety
):
    """REVISE re-writer kill must overwrite the earlier writer pass so the
    candidate isn't counted as both a writer pass and a writer kill (codex P1)."""
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    # First writer attempt is viable; the revision writer kills.
    mock_writer.side_effect = [
        _writer(),
        WriterResult(tweet=None, kill_reason="no anchor for revision", angle_chosen="",
                     era_anchor_used=None, peer_comparison_used=None, reasoning="test"),
    ]
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    mock_critic.return_value = CriticResult(
        passed=False, kill_reason=None, raw_response="revise",
        verdict="REVISE", revise_instruction="tighten the lede",
    )
    ro: dict = {}
    draft = generate_fire_draft(_fire_event(), _state_with_memory(), result_out=ro)
    assert draft is None
    assert ro["stage_outcomes"]["writer"] == "kill"  # NOT "pass"
    assert ro["kill_stage"] == "writer"


def test_safety_kill_does_not_mark_fact_check_pass(mock_writer, mock_fact_check, mock_critic, mock_safety):
    mock_writer.return_value = _writer()
    mock_safety.return_value = (False, "banned pattern")
    ro: dict = {}
    draft = generate_fire_draft(_fire_event(), _state_with_memory(), result_out=ro)
    assert draft is None
    assert ro["stage_outcomes"].get("writer") == "pass"
    assert "fact_check" not in ro["stage_outcomes"]
    assert ro["kill_stage"] == "safety"
    assert not mock_fact_check.called
