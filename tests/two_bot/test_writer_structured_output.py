"""Structured-outputs tests for the writer's Anthropic call (economics P2.2).

The Anthropic writer call passes ``output_config.format`` with
``WRITER_OUTPUT_SCHEMA`` so decoding is constrained to the prompt's
`# OUTPUT` JSON contract — retiring the paid JSON-parse retry lane on the
Anthropic path. These tests pin three load-bearing facts:

1. The create() call actually carries the schema (a silently dropped kwarg
   would quietly reinstate the retry-lane burn).
2. The schema stays in lockstep with what ``_parse_writer_json`` reads —
   with ``additionalProperties: false``, a field parsed but missing from the
   schema (or vice versa) is a contract fork.
3. The schema shape follows the structured-outputs rules the API enforces
   (all-required + additionalProperties false), so a drifted edit fails here
   before it 400s in production.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.two_bot import writer


def test_call_anthropic_passes_output_config_schema(monkeypatch):
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
                        '"reasoning":"","cited_impact":null}'
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

    output_config = captured.get("output_config")
    assert output_config is not None, (
        "messages.create must carry output_config — without it the JSON-parse "
        "retry lane silently resumes burning paid calls"
    )
    fmt = output_config.get("format")
    assert fmt == {"type": "json_schema", "schema": writer.WRITER_OUTPUT_SCHEMA}


def test_schema_matches_parser_contract():
    """Every field the parser reads is in the schema, and the schema demands
    no field the parser would drop. cited_impact must be present: with
    additionalProperties=false, its absence would reject impact-lane drafts."""
    schema_fields = set(writer.WRITER_OUTPUT_SCHEMA["properties"])
    parser_fields = {
        "tweet",
        "kill_reason",
        "angle_chosen",
        "era_anchor_used",
        "peer_comparison_used",
        "reasoning",
        "cited_impact",
    }
    assert schema_fields == parser_fields


def test_schema_shape_is_strict():
    schema = writer.WRITER_OUTPUT_SCHEMA
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    # Nullable unions exactly where the contract allows null.
    nullable = {
        field
        for field, spec in schema["properties"].items()
        if isinstance(spec.get("type"), list) and "null" in spec["type"]
    }
    assert nullable == {
        "tweet",
        "kill_reason",
        "era_anchor_used",
        "peer_comparison_used",
        "cited_impact",
    }
    # No unsupported constraints (maxLength is not enforced server-side; the
    # 280 cap must stay in the length-retry lane, not silently assumed here).
    for spec in schema["properties"].values():
        assert "maxLength" not in spec


def test_parse_accepts_schema_shaped_kill(monkeypatch):
    """A schema-shaped KILL (tweet null, kill_reason set, cited_impact null)
    round-trips through the parser unchanged."""
    result = writer._parse_writer_json(
        '{"tweet":null,"kill_reason":"no extraordinary angle",'
        '"angle_chosen":"","era_anchor_used":null,'
        '"peer_comparison_used":null,"reasoning":"routine value",'
        '"cited_impact":null}'
    )
    assert result.tweet is None
    assert result.kill_reason == "no extraordinary angle"
    assert result.cited_impact is None


# ------------------------------------------------- refusal / empty content

from src.two_bot.types import MemorySlice, StoryBundle  # noqa: E402


def _bundle() -> StoryBundle:
    return StoryBundle(
        signal_kind="fire", where="Testville", when="2026-07-23",
        event_id="evt-refusal", headline_metric={"label": "FRP", "value": 100},
        current_facts=[],
    )


def _fake_anthropic_factory(monkeypatch, responses: list):
    """Patch anthropic.Anthropic so each create() pops the next canned
    (stop_reason, content_blocks) pair. Codex r1 P1: an empty-content
    refusal is a SUCCESSFUL response — it must route into the JSON-retry
    lane, never raise IndexError into pipeline_error."""
    import anthropic

    calls: list = []

    class _FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            stop_reason, content = responses.pop(0)
            response = MagicMock()
            response.stop_reason = stop_reason
            response.content = content
            return response

    class _FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return calls


def test_persistent_refusal_becomes_clean_writer_kill(monkeypatch):
    """Every attempt refused with empty content → clean KILL with a reason
    (tweet=None), not an exception escaping to pipeline_error."""
    _fake_anthropic_factory(
        monkeypatch,
        [("refusal", [])] * (writer.JSON_PARSE_RETRY_BUDGET + 1),
    )
    result = writer.write_tweet(_bundle(), MemorySlice())
    assert result.tweet is None
    assert result.kill_reason is not None
    assert "invalid JSON" in result.kill_reason


def test_empty_content_recovers_on_parse_retry(monkeypatch):
    """First response empty, second valid → the retry lane recovers and the
    tweet ships (no lost supply on a one-off empty response)."""
    from anthropic.types import TextBlock

    good = TextBlock(
        text=(
            '{"tweet":"Testville hit a number.","kill_reason":null,'
            '"angle_chosen":"plain_number","era_anchor_used":null,'
            '"peer_comparison_used":null,"reasoning":"fits",'
            '"cited_impact":null}'
        ),
        type="text",
    )
    calls = _fake_anthropic_factory(
        monkeypatch, [("end_turn", []), ("end_turn", [good])]
    )
    result = writer.write_tweet(_bundle(), MemorySlice())
    assert result.tweet == "Testville hit a number."
    assert len(calls) == 2
