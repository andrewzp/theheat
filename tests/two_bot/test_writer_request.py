"""Request parity at the real synchronous boundary, without provider access."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.two_bot import writer
from src.two_bot.types import RelatedSignal
from tests.two_bot.conftest import _bundle, _memory


def response_text():
    return json.dumps({"tweet": "Synthetic station: 42 C.", "kill_reason": None,
                      "angle_chosen": "plain", "era_anchor_used": None,
                      "peer_comparison_used": None, "reasoning": "fixture"})


@pytest.mark.parametrize("related", [False, True])
@pytest.mark.parametrize("impact", [False, True])
@pytest.mark.parametrize("revision", [None, "Keep the source qualifier."])
def test_prompt_preserves_serialization_and_guidance_order(monkeypatch, related, impact, revision):
    bundle, memory = _bundle(), _memory()
    if related:
        bundle.related_signals = [RelatedSignal("other", "fire", "Other fixture", "2026-04-30",
                                              {"label": "FRP", "value": 300, "unit": "MW"})]
    if impact:
        bundle.human_impact = [{"claim": "synthetic evacuation", "value": 10,
                               "source_name": "Synthetic agency", "url": "https://example.test/source",
                               "as_of": "2026-04-30T12:00:00Z"}]
    monkeypatch.setattr(writer, "WRITER_USER_PROMPT_TEMPLATE", "BUNDLE={bundle_json}\nMEMORY={memory_json}")
    monkeypatch.setattr(writer, "MULTISIGNAL_GUIDANCE", "RELATED")
    monkeypatch.setattr(writer, "IMPACT_GUIDANCE", "IMPACT")
    expected = "BUNDLE=" + json.dumps(bundle.to_dict(), sort_keys=True, allow_nan=False)
    expected += "\nMEMORY=" + json.dumps(memory.to_dict(), sort_keys=True, allow_nan=False)
    if related:
        expected += "\n\nRELATED"
    if impact:
        expected += "\n\nIMPACT"
    if revision:
        expected += "\n\n[Revision context: Keep the source qualifier.]"
    before = deepcopy((bundle, memory))
    assert writer.build_writer_user_prompt(bundle, memory, revision_constraint=revision) == expected
    assert (bundle, memory) == before


def test_actual_anthropic_boundary_retains_kwargs_and_transport_configuration(monkeypatch):
    import anthropic
    from anthropic.types import TextBlock

    fake = MagicMock()
    fake.messages.create.return_value = SimpleNamespace(content=[TextBlock(type="text", text=response_text())],
                                                        stop_reason="end_turn", usage=None)
    factory = MagicMock(return_value=fake)
    monkeypatch.setattr(anthropic, "Anthropic", factory)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-only")
    monkeypatch.setattr(writer, "WRITER_MODEL", "claude-synthetic-fixture")
    monkeypatch.setattr(writer, "WRITER_SYSTEM_PROMPT", "CURRENT SYSTEM")
    assert writer._call_anthropic("CURRENT USER") == response_text()
    factory.assert_called_once_with(api_key="offline-only", timeout=180.0, max_retries=0)
    fake.messages.create.assert_called_once_with(
        model="claude-synthetic-fixture", max_tokens=1024,
        system=[{"type": "text", "text": "CURRENT SYSTEM", "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "CURRENT USER"}],
        output_config={"format": {"type": "json_schema", "schema": writer.WRITER_OUTPUT_SCHEMA}},
    )


def test_request_is_detached_and_reads_current_loaded_values(monkeypatch):
    schema = deepcopy(writer.WRITER_OUTPUT_SCHEMA)
    old = writer.anthropic_writer_request("original")
    old["system"][0]["text"] = "changed by caller"
    old["messages"].clear()
    old["output_config"]["format"]["schema"]["required"].clear()
    assert writer.WRITER_OUTPUT_SCHEMA == schema
    monkeypatch.setattr(writer, "WRITER_MODEL", "claude-next-fixture")
    monkeypatch.setattr(writer, "WRITER_SYSTEM_PROMPT", "NEW SYSTEM")
    schema["description"] = "new schema fixture"
    monkeypatch.setattr(writer, "WRITER_OUTPUT_SCHEMA", schema)
    fresh = writer.anthropic_writer_request("next")
    assert fresh["model"] == "claude-next-fixture"
    assert fresh["system"][0]["text"] == "NEW SYSTEM"
    assert fresh["messages"] == [{"role": "user", "content": "next"}]
    assert fresh["output_config"]["format"]["schema"] == schema
    assert fresh["output_config"]["format"]["schema"] is not schema


@pytest.mark.parametrize("provider", ["anthropic", "google"])
def test_writer_uses_shared_prompt_before_existing_provider_dispatch(monkeypatch, provider):
    monkeypatch.setattr(writer, "WRITER_PROVIDER", provider)
    prompt = MagicMock(return_value="SHARED USER")
    call = MagicMock(return_value=response_text())
    monkeypatch.setattr(writer, "build_writer_user_prompt", prompt)
    monkeypatch.setattr(writer, "_call_" + provider, call)
    bundle, memory = _bundle(), _memory()
    result = writer.write_tweet(bundle, memory, revision_constraint="Keep the date.")
    assert result.tweet == "Synthetic station: 42 C."
    prompt.assert_called_once_with(bundle, memory, revision_constraint="Keep the date.")
    call.assert_called_once_with("SHARED USER")


@pytest.mark.parametrize("invalid", ["scope", "evidence"])
def test_scope_and_evidence_reject_before_constructing_request(monkeypatch, invalid):
    bundle = _bundle()
    if invalid == "scope":
        bundle.signal_kind = "usgs_earthquake"
    else:
        bundle.raw_signal_dump = {}
    builder, provider = MagicMock(), MagicMock()
    monkeypatch.setattr(writer, "build_writer_user_prompt", builder)
    monkeypatch.setattr(writer, "_call_writer_provider", provider)
    assert writer.write_tweet(bundle, _memory()).tweet is None
    builder.assert_not_called()
    provider.assert_not_called()
