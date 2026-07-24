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
