"""Prompt caching tests for the editorial evaluator's Anthropic call.

Same rationale as ``tests/two_bot/test_writer_caching.py``: the evaluator
ships a large stable system prompt and a varying user prompt on each call.
Marking the system prompt for ephemeral caching cuts the cached-prefix
input cost ~90% on repeated calls within the 5-minute TTL.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.editorial import evaluator


def test_evaluator_marks_system_prompt_with_cache_control(monkeypatch):
    """The evaluator must wrap its system prompt as a content-block list with
    ``cache_control={"type": "ephemeral"}`` on the (last) text block.
    """
    import anthropic
    from anthropic.types import TextBlock

    monkeypatch.setattr(evaluator, "ANTHROPIC_API_KEY", "test-key")
    captured: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            response = MagicMock()
            # Evaluator parses a JSON payload — give it a minimal valid response.
            response.content = [
                TextBlock(
                    text=(
                        '{"scores": {"wait_what": 80, "specificity": 80, '
                        '"system_clause": 80, "voice_fit": 80}, '
                        '"failures": [], "reasoning": "test"}'
                    ),
                    type="text",
                )
            ]
            return response

    class _FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)

    evaluator.evaluate_candidate(
        candidate_text="test tweet",
        data_description="test data",
        category="record",
    )

    assert "system" in captured, "messages.create must be called with a 'system' kwarg"
    system = captured["system"]
    assert isinstance(system, list), (
        "system must be a list of content blocks (not a bare string) so "
        f"cache_control can be placed on the last block; got {type(system).__name__}"
    )
    assert len(system) >= 1
    last_block = system[-1]
    assert isinstance(last_block, dict)
    assert last_block.get("type") == "text"
    assert last_block.get("cache_control") == {"type": "ephemeral"}, (
        "last system block must carry cache_control={'type': 'ephemeral'} to "
        "enable Anthropic prompt caching across repeated evaluator calls; "
        f"got cache_control={last_block.get('cache_control')!r}"
    )


def test_evaluator_preserves_system_prompt_text(monkeypatch):
    """Wrapping the system prompt in a content-block list must not change
    its text — byte-identical prefixes are the cache-hit prerequisite.
    """
    import anthropic
    from anthropic.types import TextBlock

    from src.editorial.evaluator import EVALUATOR_PROMPT

    monkeypatch.setattr(evaluator, "ANTHROPIC_API_KEY", "test-key")
    captured: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            response = MagicMock()
            response.content = [
                TextBlock(
                    text=(
                        '{"scores": {"wait_what": 80, "specificity": 80, '
                        '"system_clause": 80, "voice_fit": 80}, '
                        '"failures": [], "reasoning": "test"}'
                    ),
                    type="text",
                )
            ]
            return response

    class _FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)

    evaluator.evaluate_candidate(
        candidate_text="test tweet",
        data_description="test data",
        category="record",
    )

    system = captured.get("system")
    assert isinstance(system, list)
    concatenated = "".join(
        block["text"] for block in system if isinstance(block, dict) and block.get("type") == "text"
    )
    assert concatenated == EVALUATOR_PROMPT, (
        "system content-block concatenation must equal the unmodified "
        "EVALUATOR_PROMPT — any drift invalidates the prompt cache"
    )
