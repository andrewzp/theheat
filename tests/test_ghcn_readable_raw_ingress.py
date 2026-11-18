"""Duplicate source keys never disappear into a parsed authority or fresh-state fallback."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src import state
from src.two_bot.ghcn_readable_warrant import encode_full
from src.two_bot import usage_ledger
from tests.test_ghcn_publication_observation_set import paired_variants as paired_variants


@pytest.fixture(scope="module")
def content(paired_variants):
    full = paired_variants["high", "all_time"]["review_context"]["two_bot"]["bundle"]
    wire = encode_full(full)
    return json.dumps(
        {"drafts": [{"id": "invented-wire", "review_context": {"two_bot": {"bundle": wire}}}]}
    )


@pytest.mark.parametrize("scope", ["profile", "outside", "same_value", "erased_marker"])
def test_duplicate_wire_authority_keys_are_refused_before_last_wins(content, scope):
    if scope in ("profile", "same_value"):
        fragment = '"format": "ghcn-complete-readable-table-v1"'
        extra = '"format": "unknown", ' if scope == "profile" else fragment + ", "
        ambiguous = content.replace(fragment, extra + fragment)
    elif scope == "outside":
        ambiguous = '{"outside": 1, "outside": 2, ' + content[1:]
    else:
        ambiguous = '{"schema_version": "theheat-ghcn-unknown", "schema_version": 2, "drafts": []}'
    with pytest.raises(state.StateReadError, match="ambiguous readable station evidence"):
        state._decode_gist_state_json(ambiguous)


def test_old_full_and_unambiguous_readable_json_keep_existing_values(content):
    assert state._decode_gist_state_json(content) == json.loads(content)
    legacy = '{"legacy": 1, "legacy": 2, "drafts": []}'
    assert state._decode_gist_state_json(legacy) == json.loads(legacy)


@pytest.mark.parametrize("strict", [False, True])
def test_actual_gist_reader_never_substitutes_fresh_state_for_ambiguous_wire(
    monkeypatch, content, strict
):
    monkeypatch.setattr(state, "GIST_ID", "0123456789abcdef0123")
    monkeypatch.setattr(state, "GITHUB_TOKEN", "invented-not-a-credential")
    ambiguous = '{"outside": 1, "outside": 2, ' + content[1:]
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"files": {state.STATE_FILENAME: {"content": ambiguous}}},
    )
    calls = []
    monkeypatch.setattr(
        state.requests, "get", lambda *args, **kwargs: calls.append("get") or response
    )
    with pytest.raises(state.StateReadError, match="ambiguous readable station evidence"):
        state._read_gist_state(strict=strict)
    assert calls == ["get"]


def test_actual_write_refuses_ambiguous_latest_read_without_patch_or_state_replacement(
    monkeypatch, content
):
    # Earlier offline SDK tests can leave buffered, invented usage. Give this
    # read-refusal case its own buffer; write_state intentionally drains usage
    # before reading either backend and that contract is unchanged.
    monkeypatch.setattr(usage_ledger, "_BUFFER", [])
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "gist")
    monkeypatch.setattr(state, "GIST_ID", "0123456789abcdef0123")
    monkeypatch.setattr(state, "GITHUB_TOKEN", "invented-not-a-credential")
    ambiguous = '{"outside": 1, "outside": 2, ' + content[1:]
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"files": {state.STATE_FILENAME: {"content": ambiguous}}},
    )
    monkeypatch.setattr(state.requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        state, "_write_gist_state", lambda *_: pytest.fail("No PATCH after ambiguous read")
    )
    before = deepcopy(dict(state.DEFAULT_STATE))
    snapshot = deepcopy(before)
    assert state.write_state(snapshot) is False
    assert snapshot == before
