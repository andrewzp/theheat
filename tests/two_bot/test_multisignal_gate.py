"""Phase D — deterministic cross-signal honesty gate + writer-prompt wiring.

The gate is the load-bearing protection (codex must-fix #1): the fact-checker is
deliberately permissive, so causal / shared-system framing of related_signals is
rejected in CODE, not just the prompt.
"""

from __future__ import annotations

from src.two_bot.intern import build_fire_bundle
from src.two_bot.pipeline import _cross_signal_violation, generate_draft
from src.two_bot.types import CriticResult, FactCheckResult, RelatedSignal, WriterResult

from tests.two_bot.conftest import _fire_event, _state_with_memory


def _related():
    return [RelatedSignal(
        event_id="drought_ml_1", signal_kind="drought", where="Mali", when="2026-04-29",
        headline_metric={"label": "severity", "value": "extreme"}, country="ML")]


def _writer(tweet):
    return WriterResult(tweet=tweet, kill_reason=None, angle_chosen="plain_number",
                        era_anchor_used=None, peer_comparison_used=None, reasoning="t")


class TestCrossSignalViolation:
    def test_none_when_no_related_signals(self):
        bundle = build_fire_bundle(_fire_event())
        assert _cross_signal_violation("These are all part of a global pattern.", bundle) is None

    def test_none_when_bare_enumeration(self):
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        clean = "Mali's largest fire this week. The same week, a drought also hit the region."
        assert _cross_signal_violation(clean, bundle) is None

    def test_flags_causal_framing(self):
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        assert _cross_signal_violation("This fire is fueled by the same drought.", bundle) is not None

    def test_flags_global_pattern(self):
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        assert _cross_signal_violation("Part of a global pattern of collapse.", bundle) == "global pattern"

    def test_normalizes_curly_apostrophe(self):
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        # curly apostrophe shouldn't let "not a coincidence" evade — straightforward phrase
        assert _cross_signal_violation("This is no coincidence.", bundle) == "no coincidence"

    def test_catches_paraphrased_causal_claims(self):
        """codex evasion probes (two rounds): paraphrases that dodge literal phrases
        must still be caught by the causal/synthesis word-stems."""
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        for text in (
            "Two expressions of a drying Sahel.",
            "The same heat is amplifying both.",
            "Together they show a regional trend.",
            "The drought is feeding the fire.",
            "These are connected by a warming climate.",
            "Part of a broader collapse.",
            "The drought fuels the fire.",
            "The same heat made both disasters worse.",
            "They share a common driver.",
            "The same conditions are behind both events.",
            "The drought stoked the fire.",
        ):
            assert _cross_signal_violation(text, bundle) is not None, text

    def test_bare_enumeration_variants_pass(self):
        """The broadened denylist must NOT kill legitimate bare enumeration."""
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        for text in (
            "Mali's largest fire this week. The same week, a drought also hit the region.",
            "The same week in Mali: record heat and a major fire.",
            "Alongside the fire, a drought also gripped the country this week.",
            "Mali's worst fire on record. A drought struck the same week.",
        ):
            assert _cross_signal_violation(text, bundle) is None, text


class TestPipelineIntegration:
    def test_cross_signal_claim_killed(self, mock_writer, mock_fact_check, mock_critic, mock_safety):
        mock_writer.return_value = _writer("This Mali fire is driven by the regional drought.")
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        ro: dict = {}
        draft = generate_draft(bundle, _state_with_memory(), result_out=ro)
        assert draft is None
        assert ro["kill_stage"] == "cross_signal"
        assert not mock_fact_check.called  # gate runs before fact-check

    def test_bare_enumeration_passes_gate(self, mock_writer, mock_fact_check, mock_critic, mock_safety):
        mock_writer.return_value = _writer(
            "Mali's biggest fire this week. The same week, a drought also struck.")
        mock_fact_check.return_value = FactCheckResult(passed=True, failures=[], raw_response="ok", extracted_claims=[])
        mock_critic.return_value = CriticResult(passed=True, kill_reason=None, raw_response="pass")
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        ro: dict = {}
        draft = generate_draft(bundle, _state_with_memory(), result_out=ro)
        assert draft is not None  # bare enumeration is allowed


class TestWriterPromptWiring:
    def test_guidance_in_user_prompt_when_related_present(self, monkeypatch):
        from src.two_bot import writer
        from src.two_bot.prompts.writer_prompt import MULTISIGNAL_GUIDANCE

        captured = {}

        def fake_call(user_prompt):
            captured["prompt"] = user_prompt
            return '{"tweet":"ok","kill_reason":null,"angle_chosen":"a","era_anchor_used":null,"peer_comparison_used":null,"reasoning":"r"}'

        monkeypatch.setattr(writer, "_call_anthropic", fake_call)
        bundle = build_fire_bundle(_fire_event())
        bundle.related_signals = _related()
        from tests.two_bot.conftest import _memory
        writer.write_tweet(bundle, _memory())
        assert MULTISIGNAL_GUIDANCE.strip() in captured["prompt"]
        assert "related_signals" in captured["prompt"]  # the data rides the user prompt

    def test_no_guidance_when_no_related(self, monkeypatch):
        from src.two_bot import writer
        from src.two_bot.prompts.writer_prompt import MULTISIGNAL_GUIDANCE

        captured = {}

        def fake_call(user_prompt):
            captured["prompt"] = user_prompt
            return '{"tweet":"ok","kill_reason":null,"angle_chosen":"a","era_anchor_used":null,"peer_comparison_used":null,"reasoning":"r"}'

        monkeypatch.setattr(writer, "_call_anthropic", fake_call)
        bundle = build_fire_bundle(_fire_event())
        from tests.two_bot.conftest import _memory
        writer.write_tweet(bundle, _memory())
        assert MULTISIGNAL_GUIDANCE.strip() not in captured["prompt"]
