from dataclasses import replace
import importlib
from unittest.mock import MagicMock

import pytest

from src.two_bot.fact_check import fact_check as real_fact_check
from src.two_bot.pipeline import (
    generate_draft,
    generate_fire_draft,
    generate_shadow_draft,
)
from src.two_bot.types import CriticResult, ExtractedClaim, FactCheckResult, StoryBundle, WriterResult

from tests.two_bot.conftest import _bundle, _fire_event, _state_with_memory


@pytest.fixture(autouse=True)
def _critic_passes_in_pipeline_tests(monkeypatch, request):
    """Module-scoped autouse: pre-existing pipeline tests written before
    the F3 critic landed don't take ``mock_critic``, but their writer
    outputs now hit the critic stage. Default it to PASS so those tests
    stay green without modification.

    Tests that explicitly take ``mock_critic`` as a parameter override
    this default (fixture order: this autouse runs first, then
    ``mock_critic`` re-patches — last writer wins).
    """
    # Skip if the test is explicitly opting into ``mock_critic`` — its
    # patch will fire after this fixture's setUp and replace the mock.
    if "mock_critic" in request.fixturenames:
        return
    from src.two_bot import pipeline
    mock = MagicMock(return_value=CriticResult(
        passed=True, kill_reason=None, raw_response="module-autouse-pass"
    ))
    monkeypatch.setattr(pipeline.critic, "critic_review", mock)


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


def test_pipeline_fact_check_raises_records_stage(mock_writer, mock_extract, mock_fact_check):
    mock_writer.return_value = WriterResult(
        tweet="Mali fire is 361 MW.",
        kill_reason=None,
        angle_chosen="plain_number",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_fact_check.return_value = FactCheckResult(
        passed=False,
        failures=["fact-checker returned invalid JSON across 2 attempts"],
        raw_response="(json-parse retry exhausted)",
        extracted_claims=[],
    )
    state = _state_with_memory()
    result_out = {}

    draft = generate_fire_draft(_fire_event(), state, result_out=result_out)

    assert draft is None
    assert result_out["kill_stage"] == "fact_check"
    assert "invalid JSON across" in result_out["kill_reason"]
    assert state["memory"]["shipped_tweets"] == []
    assert mock_fact_check.called


def test_pipeline_budget_exhausted_records_distinct_stage(
    mock_writer, mock_extract, mock_fact_check
):
    """When an LLM stage raises BudgetExhaustedError (provider billing
    out of credits), the pipeline must record kill_stage=
    "budget_exhausted" so the dashboard surfaces a billing outage
    distinctly from a model/code bug. Otherwise operators read retry
    stack traces to figure out the fix is "top up the key", which is
    exactly the failure mode the 2026-05-15 → 2026-05-17 silent outage
    surfaced (182 of 200 suppressions were generic pipeline_error rows
    with identical "credit balance is too low" text)."""
    from src.two_bot.retry import BudgetExhaustedError

    mock_writer.side_effect = BudgetExhaustedError(
        "anthropic writer: provider billing exhausted: BadRequestError: "
        "Your credit balance is too low to access the Anthropic API."
    )
    state = _state_with_memory()
    result_out: dict = {}

    draft = generate_fire_draft(_fire_event(), state, result_out=result_out)

    assert draft is None
    assert result_out["kill_stage"] == "budget_exhausted"
    assert "billing exhausted" in result_out["kill_reason"]
    # Downstream stages must NOT have been called — the writer is dead.
    assert not mock_extract.called
    assert not mock_fact_check.called
    assert state["memory"]["shipped_tweets"] == []


def test_pipeline_evidence_contract_blocks_writer_before_token_spend(
    mock_writer, mock_extract, mock_fact_check
):
    state = _state_with_memory()
    result_out: dict = {}
    bad_bundle = replace(_bundle(), event_id="")

    draft = generate_draft(bad_bundle, state, result_out=result_out)

    assert draft is None
    assert result_out["kill_stage"] == "evidence_contract"
    assert result_out["kill_reason"] == "missing_event_id"
    assert not mock_writer.called
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
    mock_fact_check.side_effect = lambda tweet, extracted, bundle, state: real_fact_check(
        tweet,
        [ExtractedClaim(text="Spider-Man 2002", kind="era_anchor")],
        bundle,
        state,
    )

    draft2 = generate_fire_draft(_fire_event(event_id="fire_second"), state)

    assert draft2 is None


def test_samples_1_is_byte_identical_to_legacy_path(
    monkeypatch,
    mock_writer,
    mock_fact_check,
    mock_safety,
    mock_critic,
):
    from src.two_bot import pipeline

    monkeypatch.delenv("THEHEAT_WRITER_SAMPLES", raising=False)
    monkeypatch.delenv("THEHEAT_CRITIC_REVISE_ENABLED", raising=False)
    calls: list[tuple[str, str]] = []

    def write_once(bundle, memory):
        calls.append(("writer", bundle.event_id))
        return WriterResult(
            tweet="Mali fire is 1.4x a 250 MW gas plant.",
            kill_reason=None,
            angle_chosen="plain_number",
            era_anchor_used=None,
            peer_comparison_used=None,
            reasoning="test",
        )

    def safety_once(tweet):
        calls.append(("safety", tweet))
        return True, None

    def fact_once(tweet, extracted, bundle, state):
        calls.append(("fact_check", tweet))
        return FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])

    def critic_once(tweet, bundle, state, **kwargs):
        calls.append(("critic", tweet))
        assert kwargs.get("allow_revise") in (None, False)
        return CriticResult(passed=True, kill_reason=None, raw_response="ok")

    mock_writer.side_effect = write_once
    mock_safety.side_effect = safety_once
    mock_fact_check.side_effect = fact_once
    mock_critic.side_effect = critic_once
    slate_mock = MagicMock(side_effect=AssertionError("slate critic should be off"))
    monkeypatch.setattr(pipeline.critic, "critic_select_slate", slate_mock, raising=False)

    draft = generate_draft(_bundle(), _state_with_memory())

    assert draft is not None
    assert [name for name, _ in calls] == ["writer", "safety", "fact_check", "critic"]
    assert mock_writer.call_count == 1
    assert mock_writer.call_args.kwargs == {}
    assert not slate_mock.called


def test_slate_critic_selects_one(
    monkeypatch,
    mock_writer,
    mock_fact_check,
    mock_safety,
    mock_critic,
):
    from src.two_bot import pipeline

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    mock_writer.side_effect = [
        WriterResult("first draft", None, "a", None, None, "one"),
        WriterResult(None, "writer self-kill", "", None, None, "two"),
        WriterResult("selected draft", None, "b", None, None, "three"),
    ]
    slate_mock = MagicMock(return_value=CriticResult(
        passed=True,
        kill_reason=None,
        raw_response="slate-pass",
        verdict="PASS",
        selected_index=1,
    ))
    monkeypatch.setattr(pipeline.critic, "critic_select_slate", slate_mock, raising=False)
    mock_safety.return_value = (True, None)
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    mock_critic.return_value = CriticResult(passed=True, kill_reason=None, raw_response="final-pass")

    draft = generate_draft(_bundle(), _state_with_memory())

    assert draft is not None
    assert draft["text"] == "selected draft"
    assert mock_writer.call_count == 3
    slate_arg = slate_mock.call_args.args[0]
    assert slate_arg == ["first draft", "selected draft"]
    mock_safety.assert_called_once_with("selected draft")
    mock_fact_check.assert_called_once()
    assert not mock_critic.called


def test_all_writer_kills_short_circuits(
    monkeypatch,
    mock_writer,
    mock_fact_check,
    mock_safety,
    mock_critic,
):
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "2")
    mock_writer.side_effect = [
        WriterResult(None, "not enough signal", "", None, None, "one"),
        WriterResult(None, "too similar", "", None, None, "two"),
    ]
    result_out: dict = {}

    draft = generate_draft(_bundle(), _state_with_memory(), result_out=result_out)

    assert draft is None
    assert result_out["kill_stage"] == "writer"
    assert "all writer samples killed" in result_out["kill_reason"]
    assert not mock_safety.called
    assert not mock_fact_check.called
    assert not mock_critic.called


def test_revise_single_iteration_then_terminal(
    monkeypatch,
    mock_writer,
    mock_fact_check,
    mock_safety,
    mock_critic,
):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    mock_writer.side_effect = [
        WriterResult("first draft", None, "a", None, None, "one"),
        WriterResult("revised draft", None, "b", None, None, "two"),
    ]
    mock_safety.return_value = (True, None)
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    mock_critic.side_effect = [
        CriticResult(
            passed=False,
            kill_reason=None,
            raw_response="revise",
            verdict="REVISE",
            revise_instruction="Use the fire scale, not the agency announcement.",
        ),
        CriticResult(passed=True, kill_reason=None, raw_response="pass", verdict="PASS"),
    ]

    draft = generate_draft(_bundle(), _state_with_memory())

    assert draft is not None
    assert draft["text"] == "revised draft"
    assert mock_writer.call_count == 2
    assert "Previous draft: first draft" in mock_writer.call_args_list[1].kwargs["revision_constraint"]
    assert "The critic requires: Use the fire scale" in mock_writer.call_args_list[1].kwargs["revision_constraint"]
    assert mock_critic.call_count == 2
    assert mock_critic.call_args_list[0].kwargs.get("allow_revise") is True
    assert mock_critic.call_args_list[1].kwargs.get("allow_revise") is False


def test_revise_disabled_by_default(
    monkeypatch,
    mock_writer,
    mock_fact_check,
    mock_safety,
    mock_critic,
):
    monkeypatch.delenv("THEHEAT_CRITIC_REVISE_ENABLED", raising=False)
    mock_writer.return_value = WriterResult("first draft", None, "a", None, None, "one")
    mock_safety.return_value = (True, None)
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    mock_critic.return_value = CriticResult(
        passed=False,
        kill_reason=None,
        raw_response="revise",
        verdict="REVISE",
        revise_instruction="Try a sharper system clause.",
    )

    draft = generate_draft(_bundle(), _state_with_memory())

    assert draft is None
    assert mock_writer.call_count == 1


def test_revised_draft_passes_safety_again(
    monkeypatch,
    mock_writer,
    mock_fact_check,
    mock_safety,
    mock_critic,
):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    mock_writer.side_effect = [
        WriterResult("first draft", None, "a", None, None, "one"),
        WriterResult("revised draft", None, "b", None, None, "two"),
    ]
    mock_safety.side_effect = [(True, None), (False, "Banned pattern")]
    mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
    mock_critic.return_value = CriticResult(
        passed=False,
        kill_reason=None,
        raw_response="revise",
        verdict="REVISE",
        revise_instruction="Remove the template opener.",
    )
    result_out: dict = {}

    draft = generate_draft(_bundle(), _state_with_memory(), result_out=result_out)

    assert draft is None
    assert mock_safety.call_args_list[0].args == ("first draft",)
    assert mock_safety.call_args_list[1].args == ("revised draft",)
    assert result_out["kill_stage"] == "safety"
    assert "Banned pattern" in result_out["kill_reason"]


def test_max_drafts_per_cycle_env_override(monkeypatch):
    import src.orchestrator.finalize as finalize

    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "5")
    reloaded = importlib.reload(finalize)
    assert reloaded.MAX_DRAFTS_PER_CYCLE == 5

    monkeypatch.delenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", raising=False)
    importlib.reload(finalize)


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
        raw_signal_dump={
            "source": "test",
            "event_id": "meteo_monthly_Conakry_2026-05-01",
        },
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


# ----------------------- safety stage tests --------------------------------


def test_pipeline_safety_rejects_writer_output(
    mock_writer, mock_extract, mock_fact_check, mock_safety
):
    """Safety gate runs between writer-success and fact-check. When safety
    rejects, fact-check is NOT called (saves an LLM cost) and the
    suppression is recorded with stage='safety' so the dashboard can
    distinguish from writer / fact_check / pipeline_error kills."""
    mock_writer.return_value = WriterResult(
        tweet="Severity: Severe. Hottest May!",
        kill_reason=None,
        angle_chosen="plain_number",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_safety.return_value = (False, "Banned pattern: 'Severity: Severe'")
    state = _state_with_memory()
    result_out = {}

    result = generate_draft(_monthly_high_bundle(), state, result_out=result_out)

    assert result is None
    assert result_out["kill_stage"] == "safety"
    assert "Severity" in result_out["kill_reason"]
    # Fact-check must NOT have been called — safety short-circuits to save cost.
    assert not mock_fact_check.called
    # Memory must not be written — only the happy path records.
    assert state["memory"]["shipped_tweets"] == []


def test_shadow_pipeline_safety_rejects(
    mock_writer, mock_extract, mock_fact_check, mock_safety
):
    """Shadow pipeline mirrors live pipeline's safety gate. Even though
    shadow doesn't post, voice regression in the shadow path is still a
    signal worth catching."""
    mock_writer.return_value = WriterResult(
        tweet="Severity: Severe.",
        kill_reason=None,
        angle_chosen="plain_number",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_safety.return_value = (False, "Banned pattern: 'Severity: Severe'")
    state = _state_with_memory()

    result = generate_shadow_draft(_monthly_high_bundle(), state)

    assert result is None
    assert not mock_fact_check.called
    assert state["memory"]["shipped_tweets"] == []


def test_pipeline_safety_passes_through_to_fact_check(
    mock_writer, mock_extract, mock_fact_check, mock_safety
):
    """Sanity: when safety passes, fact-check runs as before."""
    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea hit 39C in May. Hottest in 12 years.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )
    mock_safety.return_value = (True, None)
    mock_extract.return_value = []
    mock_fact_check.return_value = FactCheckResult(
        passed=True, failures=[], raw_response="ok", extracted_claims=[],
    )
    state = _state_with_memory()

    result = generate_draft(_monthly_high_bundle(), state)

    assert result is not None
    assert mock_safety.called
    assert mock_fact_check.called
    # Safety was called once with the writer output verbatim.
    mock_safety.assert_called_once_with("Conakry, Guinea hit 39C in May. Hottest in 12 years.")


# ----------------------- critic stage tests --------------------------------


def test_pipeline_critic_rejects_after_fact_check_pass(
    mock_writer, mock_extract, mock_fact_check, mock_critic
):
    """Critic is the final editorial gate — runs AFTER fact-check passes
    and KILLs if the draft is mid, template-convergent, or echoes
    shipped phrasing. When critic kills, suppression records
    stage='critic' so the dashboard can distinguish editorial kills
    from factual kills."""
    from src.two_bot.types import CriticResult

    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea hit 39C in May. Hottest in 12 years.",
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
    mock_critic.return_value = CriticResult(
        passed=False,
        kill_reason="interesting_but_not_memorable: 12-year archive is mid",
        raw_response='{"passed": false, "kill_reason": "..."}',
    )
    state = _state_with_memory()
    result_out: dict = {}

    result = generate_draft(_monthly_high_bundle(), state, result_out=result_out)

    assert result is None
    assert result_out["kill_stage"] == "critic"
    assert "interesting_but_not_memorable" in result_out["kill_reason"]
    # Critic ran AFTER fact-check — both should have been called.
    assert mock_fact_check.called
    assert mock_critic.called
    # Memory must NOT be written — critic kills are not shipped tweets.
    assert state["memory"]["shipped_tweets"] == []


def test_pipeline_critic_passes_and_records_metadata(
    mock_writer, mock_extract, mock_fact_check, mock_critic
):
    """When the critic passes, the draft metadata carries the critic
    verdict + model name. Dashboard reads these to surface "critic-
    approved" badge and to retro on which model caught which kills."""
    from src.two_bot.types import CriticResult

    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea hit 39C in May. Hottest in 12 years.",
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
    mock_critic.return_value = CriticResult(
        passed=True,
        kill_reason=None,
        raw_response='{"passed": true, "kill_reason": null}',
    )
    state = _state_with_memory()

    result = generate_draft(_monthly_high_bundle(), state)

    assert result is not None
    meta = result["two_bot_metadata"]
    assert meta["critic"]["passed"] is True
    assert meta["critic"]["kill_reason"] is None
    assert "critic_model" in meta


def test_pipeline_skips_critic_when_env_disabled(
    monkeypatch, mock_writer, mock_extract, mock_fact_check, mock_critic
):
    """THEHEAT_CRITIC_ENABLED=0 is the operations kill-switch. If the
    critic ever over-kills in production, ops can disable it without
    a deploy by setting this env var; the rest of the pipeline keeps
    running."""
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")

    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea hit 39C in May.",
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

    result = generate_draft(_monthly_high_bundle(), state)

    assert result is not None
    # Critic was NOT called when the env kill-switch is set.
    assert not mock_critic.called
    # When critic is skipped, metadata should NOT carry a stale verdict.
    assert "critic" not in result["two_bot_metadata"]


def test_pipeline_critic_exception_records_pipeline_error(
    mock_writer, mock_extract, mock_fact_check, mock_critic
):
    """A Gemini outage or schema-drift in the critic response surfaces
    as stage='pipeline_error' (matching the existing try/except posture
    of the pipeline). The draft is killed — never let a critic outage
    let mid drafts through unchecked. Operators can set
    THEHEAT_CRITIC_ENABLED=0 if Gemini is having a sustained bad day.
    """
    mock_writer.return_value = WriterResult(
        tweet="Conakry, Guinea hit 39C in May.",
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
    mock_critic.side_effect = RuntimeError("Gemini 500")
    state = _state_with_memory()
    result_out: dict = {}

    result = generate_draft(_monthly_high_bundle(), state, result_out=result_out)

    assert result is None
    assert result_out["kill_stage"] == "pipeline_error"
    assert "Gemini 500" in result_out["kill_reason"]
    # No memory leakage on the failure path.
    assert state["memory"]["shipped_tweets"] == []
