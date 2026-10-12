"""Offline retained usage extraction, independent of editorial verdicts."""
import json

import pytest

from src.two_bot.retained_usage import extract


def read(value,provider="google",**kw):
    raw=value if isinstance(value,bytes) else json.dumps(value).encode()
    return extract(raw,provider=provider,stage="safety",model="invented",observed_at="2026-10-12T00:00:00.000000Z",complete=True,**kw)


def test_closed_google_usage_dimensions_and_unknown_fields():
    value=read(dict(modelVersion="invented",usageMetadata=dict(promptTokenCount=0,candidatesTokenCount=2,thoughtsTokenCount=8,
        promptTokensDetails=[dict(modality="TEXT",tokenCount=0)],newPrivateField="DO_NOT_EXPOSE"),candidates=[dict(text="INVALID EDITORIAL OUTPUT")]))
    assert value["status"]=="present" and value["counts"]["prompt_token_count"]==0
    assert value["counts"]["cached_content_token_count"] is None and value["counts"]["thoughts_token_count"]==8
    assert value["breakdowns"]["prompt_tokens_details"]==[dict(modality="TEXT",token_count=0)]
    assert value["unsupported_fields"] and "DO_NOT_EXPOSE" not in json.dumps(value) and "EDITORIAL" not in json.dumps(value)


@pytest.mark.parametrize("raw",[b'{"usage":{},"usage":{}}',b'{"usage":{"input_tokens":NaN}}',b'{"usage":',b'[]',b'{"usage":2}'])
def test_invalid_envelopes_never_salvage(raw):
    assert read(raw,"anthropic")["status"]=="invalid"


def test_missing_zero_error_and_terminal_disagreement():
    assert read({},"anthropic")["status"]=="absent"
    response=dict(type="error",model="invented",usage=dict(input_tokens=0,output_tokens=0,cache_creation=dict(ephemeral_5m_input_tokens=5)))
    result=read(response,"anthropic")
    assert result["status"]=="present" and result["counts"]["input_tokens"]==0
    assert read(response,"anthropic",terminal_usage=dict(input_tokens=1))["status"]=="invalid"
    assert read(dict(usage=dict(input_tokens=True)),"anthropic")["status"]=="invalid"


def test_incomplete_response_not_parsed(monkeypatch):
    from src.two_bot import retained_usage
    monkeypatch.setattr(retained_usage,"decode",lambda *_:pytest.fail("partial bytes must not be parsed"))
    value=extract(b'{}',provider="google",stage="safety",model="invented",observed_at=None,complete=False)
    assert value["status"]=="unavailable" and value["reason"]=="response_incomplete"
