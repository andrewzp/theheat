"""Observed request-schema failure reproduced at the SDK wire, without a paid call."""

from copy import deepcopy
import json
from unittest.mock import Mock

import anthropic
import pytest

from src.two_bot import writer
from src.two_bot.json_utils import ModelOutputContractError
from tests.two_bot.conftest import _bundle, _memory

import httpx2 as httpx

# Technical API diagnostic only; no production prompt, event or receipt included.
SCHEMA_ERROR = ("output_config.format.schema: Invalid schema: Enum value 'evidence' "
                "does not match declared type '['string', 'null']'")


def _enum_union(node):
    if isinstance(node, dict):
        return ("enum" in node and isinstance(node.get("type"), list)) or any(
            _enum_union(value) for value in node.values()
        )
    return isinstance(node, list) and any(_enum_union(value) for value in node)


def _accepts_scalar(schema, value):
    """Tiny independent JSON Schema scalar/union evaluator for this equivalence test."""
    if "anyOf" in schema:
        return any(_accepts_scalar(branch, value) for branch in schema["anyOf"])
    kind = schema["type"]
    types = kind if isinstance(kind, list) else [kind]
    matches_type = (value is None and "null" in types) or (type(value) is str and "string" in types)
    return matches_type and ("enum" not in schema or value in schema["enum"])


@pytest.mark.parametrize("field,allowed", [
    ("kill_scope", [None, "evidence", "style", "context", "unknown"]),
    ("kill_code", [None, "insufficient_evidence", "conflicting_evidence"]),
])
def test_nullable_enum_preserves_exact_original_value_contract(field, allowed):
    original = {"type": ["string", "null"], "enum": allowed}
    current = writer.WRITER_OUTPUT_SCHEMA["properties"][field]
    for value in allowed + ["", "other", "EVIDENCE", 1, True, [], {}, "null"]:
        assert _accepts_scalar(current, value) == _accepts_scalar(original, value)
    assert not _enum_union(writer.WRITER_OUTPUT_SCHEMA)
    assert writer.WRITER_OUTPUT_SCHEMA["additionalProperties"] is False
    assert set(writer.WRITER_OUTPUT_SCHEMA["required"]) == set(writer.WRITER_OUTPUT_SCHEMA["properties"])


def output(*, scope=None, code=None, tweet="A synthetic thermal detection."):
    return dict(tweet=tweet, kill_reason="Synthetic refusal" if tweet is None else None,
                angle_chosen="plain_number", era_anchor_used=None, peer_comparison_used=None,
                reasoning="Offline fixture", cited_impact=None, kill_scope=scope, kill_code=code)


@pytest.mark.parametrize("scope,code", [(None,None), ("style",None), ("context",None),
                                        ("unknown",None), ("evidence",None),
                                        ("evidence","insufficient_evidence"),
                                        ("evidence","conflicting_evidence")])
def test_every_allowed_rejection_remains_parseable(scope, code):
    result = writer._parse_writer_json(json.dumps(output(scope=scope, code=code, tweet=None)))
    assert result.kill_scope == scope and result.kill_code == code and result.tweet is None


@pytest.mark.parametrize("changes", [{"kill_scope":"other"}, {"kill_code":"other"},
                                       {"kill_scope":"style","kill_code":"insufficient_evidence"},
                                       {"kill_scope":"evidence","tweet":"A usable candidate.","kill_reason":None}])
def test_output_contract_stays_strict_after_schema_encoding_change(changes):
    value = output(tweet=None)
    value.update(changes)
    with pytest.raises(ModelOutputContractError):
        writer._parse_writer_json(json.dumps(value))


def sdk_fixture(monkeypatch, handler):
    real = anthropic.Anthropic
    clients = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-fixture-key")
    monkeypatch.setattr(writer, "WRITER_PROVIDER", "anthropic")

    def factory(**kwargs):
        client = real(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        clients.append(client)
        return client

    monkeypatch.setattr(anthropic, "Anthropic", factory)
    return clients


def test_actual_writer_wire_handles_compatible_schema_and_preserves_exact_output(monkeypatch):
    requests = []
    returned = output()

    def handler(request):
        requests.append(request)
        data = json.loads(request.content)
        schema = data["output_config"]["format"]["schema"]
        # This fixture encodes the observed rejecting shape; it is not a live
        # provider compiler or proof that every supported schema is accepted.
        if _enum_union(schema):
            return httpx.Response(400, json={"error":{"type":"invalid_request_error", "message":SCHEMA_ERROR}})
        return httpx.Response(200, json={"id":"msg_fixture", "type":"message", "role":"assistant",
            "model":writer.WRITER_MODEL, "content":[{"type":"text", "text":json.dumps(returned)}],
            "stop_reason":"end_turn", "stop_sequence":None,
            "usage":{"input_tokens":10,"output_tokens":10}})

    clients = sdk_fixture(monkeypatch, handler)
    try:
        result = writer._parse_writer_json(writer._call_anthropic("Offline current user prompt"))
    finally:
        for client in clients:
            client.close()
    assert result.tweet == returned["tweet"] and len(requests) == 1
    sent = json.loads(requests[0].content)
    assert sent["output_config"]["format"]["schema"] == writer.WRITER_OUTPUT_SCHEMA
    assert sent["messages"] == [{"role":"user", "content":"Offline current user prompt"}]


def test_actual_writer_wire_reproduces_old_schema_400_once_without_repair(monkeypatch):
    requests = []
    schema = deepcopy(writer.WRITER_OUTPUT_SCHEMA)
    schema["properties"]["kill_scope"] = {
        "type":["string","null"], "enum":["evidence","style","context","unknown",None],
    }
    monkeypatch.setattr(writer, "WRITER_OUTPUT_SCHEMA", schema)

    def handler(request):
        requests.append(request)
        assert _enum_union(json.loads(request.content)["output_config"]["format"]["schema"])
        return httpx.Response(400, json={"type":"error", "error":{
            "type":"invalid_request_error", "message":SCHEMA_ERROR,
        }})

    clients = sdk_fixture(monkeypatch, handler)
    try:
        with pytest.raises(anthropic.BadRequestError, match="Invalid schema"):
            writer.write_tweet(_bundle(), _memory())
    finally:
        for client in clients:
            client.close()
    assert len(requests) == 1
