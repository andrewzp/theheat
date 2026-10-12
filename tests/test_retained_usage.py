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


@pytest.mark.parametrize('field,changed',[
    ('promptTokenCount',99),('trafficType','DIFFERENT'),
    ('promptTokensDetails',[dict(modality='TEXT',tokenCount=99)]),
    ('promptTokensDetails',[dict(modality='IMAGE',tokenCount=10)]),
    ('promptTokenCount',True),('trafficType',17),
])
def test_google_terminal_camelcase_counts_labels_and_nested_disagreement(field,changed):
    metadata=dict(promptTokenCount=10,trafficType='ON_DEMAND',promptTokensDetails=[dict(modality='TEXT',tokenCount=10)])
    terminal=dict(metadata,**{field:changed})
    result=read(dict(usageMetadata=metadata),terminal_usage=terminal)
    assert result['status']=='invalid' and all(v is None for v in result['counts'].values())
    assert all(v is None for v in result['labels'].values()) and all(v is None for v in result['breakdowns'].values())


def test_terminal_presence_null_zero_and_equal_normalized_fields():
    assert read(dict(usageMetadata=dict(promptTokenCount=0)),terminal_usage=dict(promptTokenCount=0))['counts']['prompt_token_count']==0
    assert read(dict(usageMetadata=dict(promptTokenCount=None)),terminal_usage=dict(promptTokenCount=None))['status']=='present'
    assert read(dict(usageMetadata=dict(promptTokenCount=None)),terminal_usage=dict(promptTokenCount=0))['status']=='invalid'
    # Absent is not a fabricated zero or a field falsely reported by both sides.
    value=read(dict(usageMetadata={}),terminal_usage=dict(promptTokenCount=0))
    assert value['counts']['prompt_token_count'] is None and value['status']=='present'
    value=read(dict(usageMetadata=dict(promptTokenCount=0)),terminal_usage={})
    assert value['counts']['prompt_token_count']==0
    details=[dict(modality='TEXT',tokenCount=0),dict(modality='IMAGE',tokenCount=3)]
    assert read(dict(usageMetadata=dict(promptTokensDetails=details)),terminal_usage=dict(promptTokensDetails=list(reversed(details))))['status']=='present'
    assert read(dict(usage=dict(input_tokens=7,cache_creation=dict(ephemeral_1h_input_tokens=3))),'anthropic',
        terminal_usage=dict(counts={'input_tokens':7,'cache_creation.ephemeral_1h_input_tokens':3}))['status']=='present'
    assert read(dict(usage=dict(input_tokens=7)),'anthropic',terminal_usage=dict(counts={'input_tokens':8}))['status']=='invalid'
