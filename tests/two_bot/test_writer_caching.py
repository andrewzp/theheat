"""Prompt caching tests for the writer's Anthropic call.

These tests verify that the writer marks its (large, stable) system prompt
with ``cache_control: {type: "ephemeral"}`` so the Anthropic API caches the
prefix across repeated writer calls within the cache TTL.

Why this matters: every cron fires the writer many times per cycle with the
same ~5,700-token system prompt and a varying user prompt. Without caching,
each call pays full input-token cost on the system prompt. With caching,
calls within the 5-minute window cost ~0.1x on the cached prefix.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.two_bot import writer


def test_call_anthropic_marks_system_prompt_with_cache_control(monkeypatch):
    """The writer must wrap its system prompt as a content-block list with
    ``cache_control={"type": "ephemeral"}`` on the (last) text block.

    Passing ``system`` as a bare string skips prompt caching entirely. The
    SDK only honours cache_control on structured content blocks.
    """
    import anthropic
    from anthropic.types import TextBlock

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            response = MagicMock()
            response.content = [
                TextBlock(
                    text=(
                        '{"tweet":"x","kill_reason":null,"angle_chosen":"",'
                        '"era_anchor_used":null,"peer_comparison_used":null,'
                        '"reasoning":""}'
                    ),
                    type="text",
                )
            ]
            return response

    class _FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)

    writer._call_anthropic("test user prompt")

    assert "system" in captured, "messages.create must be called with a 'system' kwarg"
    system = captured["system"]
    assert isinstance(system, list), (
        "system must be a list of content blocks (not a bare string) so "
        f"cache_control can be placed on the last block; got {type(system).__name__}"
    )
    assert len(system) >= 1, "system must contain at least one content block"
    last_block = system[-1]
    assert isinstance(last_block, dict), (
        f"system content blocks must be dicts; got {type(last_block).__name__}"
    )
    assert last_block.get("type") == "text", (
        f"last system block must be type='text'; got type={last_block.get('type')!r}"
    )
    assert last_block.get("cache_control") == {"type": "ephemeral"}, (
        "last system block must carry cache_control={'type': 'ephemeral'} to "
        "enable Anthropic prompt caching across repeated writer calls; "
        f"got cache_control={last_block.get('cache_control')!r}"
    )


def test_call_anthropic_preserves_system_prompt_text(monkeypatch):
    """Wrapping the system prompt in a content-block list must not change
    its text. Cache hits depend on byte-identical prefixes — any drift here
    silently invalidates the cache and we burn input tokens unnecessarily.
    """
    import anthropic
    from anthropic.types import TextBlock

    from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            response = MagicMock()
            response.content = [
                TextBlock(
                    text=(
                        '{"tweet":"x","kill_reason":null,"angle_chosen":"",'
                        '"era_anchor_used":null,"peer_comparison_used":null,'
                        '"reasoning":""}'
                    ),
                    type="text",
                )
            ]
            return response

    class _FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)

    writer._call_anthropic("test user prompt")

    system = captured.get("system")
    assert isinstance(system, list)
    concatenated = "".join(
        block["text"] for block in system if isinstance(block, dict) and block.get("type") == "text"
    )
    assert concatenated == WRITER_SYSTEM_PROMPT, (
        "system content-block concatenation must equal the unmodified "
        "WRITER_SYSTEM_PROMPT — any drift invalidates the prompt cache "
        "on every subsequent call"
    )
