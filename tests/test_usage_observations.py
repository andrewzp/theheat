"""Offline SDK observations, concurrent capture and real Python/JS persistence."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from src.two_bot import usage_ledger as ledger
from src.two_bot import usage_observations as observations
from src.two_bot.usage_summary import summarize_usage

ROOT = Path(__file__).resolve().parents[1]
SECRET = "DO_NOT_CAPTURE_PROMPT_OR_RESPONSE_CONTENT"


@pytest.fixture(autouse=True)
def buffer():
    ledger._BUFFER.clear()
    yield
    ledger._BUFFER.clear()


def google_response():
    from google.genai.types import GenerateContentResponse
    return GenerateContentResponse.model_validate({
        "modelVersion": "gemini-fixture-resolved", "responseId": "fixture-response-id",
        "usageMetadata": {
            "promptTokenCount": 100, "candidatesTokenCount": 20, "cachedContentTokenCount": 30,
            "thoughtsTokenCount": 40, "toolUsePromptTokenCount": 5, "totalTokenCount": 165,
            "trafficType": "ON_DEMAND",
            "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 90}, {"modality": "IMAGE", "tokenCount": 10}],
            "candidatesTokensDetails": [{"modality": "TEXT", "tokenCount": 20}],
            "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": 30}],
            "toolUsePromptTokensDetails": [{"modality": "TEXT", "tokenCount": 5}],
        },
        "candidates": [{"content": {"parts": [{"text": SECRET}]}}],
    })


def anthropic_response():
    from anthropic.types import Message
    return Message.model_validate({
        "id": "msg-fixture", "type": "message", "role": "assistant", "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "text", "text": SECRET}],
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 40,
                  "cache_read_input_tokens": 30, "cache_creation": {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 30},
                  "output_tokens_details": {"thinking_tokens": 15},
                  "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 1},
                  "service_tier": "batch", "inference_geo": "us"},
    })


def record(number=1):
    result = observations.observe_response("writer", google_response(), "gemini-fixture-alias", "google")
    result["id"] = f"{number:032x}"
    result["observed_at"] = "2026-10-01T12:00:00.000Z"
    return result


def window(*rows, **flags):
    return {"schema_version": 1, "observations": list(rows), "truncated": False, "invalid": False, **flags}


def node(values, *, operation="merge"):
    script = '''
      import {readFileSync} from "node:fs";
      import {mergeUsageObservations, summarizeUsageObservations} from "./dashboard/lib/usage-observations.js";
      const {values, operation} = JSON.parse(readFileSync(0, "utf8"));
      let result;
      if (operation === "merge") result = values.reduce((a,b) => mergeUsageObservations(a,b), {});
      else if (operation === "summary") result = summarizeUsageObservations(values);
      console.log(JSON.stringify(result));
    '''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                            input=json.dumps({"values": values, "operation": operation}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_actual_google_sdk_keeps_reported_dimensions_without_inventing_token_arithmetic():
    row = record()
    assert observations.valid_record(row)
    assert row["requested_model"] == "gemini-fixture-alias"
    assert row["resolved_model"] == "gemini-fixture-resolved"
    assert row["response_id"] == "fixture-response-id"
    assert row["counts"] == {"prompt_token_count": 100, "candidates_token_count": 20, "cached_content_token_count": 30,
                             "thoughts_token_count": 40, "tool_use_prompt_token_count": 5, "total_token_count": 165}
    assert row["labels"] == {"traffic_type": "ON_DEMAND"}
    assert row["breakdowns"]["prompt_tokens_details"] == [{"modality": "IMAGE", "token_count": 10}, {"modality": "TEXT", "token_count": 90}]
    assert not row["unsupported_fields"] and not row["invalid_fields"]
    assert SECRET not in observations.canonical(row)


def test_actual_anthropic_sdk_keeps_cache_duration_thinking_tools_and_tier():
    row = observations.observe_response("writer", anthropic_response(), "claude-haiku-4-5", "anthropic")
    assert observations.valid_record(row)
    assert row["resolved_model"] == "claude-haiku-4-5-20251001"
    assert row["counts"] == {
        "input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 40, "cache_read_input_tokens": 30,
        "cache_creation.ephemeral_5m_input_tokens": 10, "cache_creation.ephemeral_1h_input_tokens": 30,
        "output_tokens_details.thinking_tokens": 15, "server_tool_use.web_search_requests": 2,
        "server_tool_use.web_fetch_requests": 1,
    }
    assert row["labels"] == {"service_tier": "batch", "inference_geo": "us"}
    assert not row["unsupported_fields"] and not row["invalid_fields"]
    assert SECRET not in observations.canonical(row)


@pytest.mark.parametrize("value", [None, 0, False, -1, 1.5, "4", float("inf"), float("nan"), 10**13])
def test_absent_zero_and_invalid_usage_are_distinct(value):
    row = observations.observe_response("safety", SimpleNamespace(usage_metadata=SimpleNamespace(thoughts_token_count=value)), "fixture", "google")
    assert observations.valid_record(row)
    valid = value is None or type(value) is int and value == 0
    assert row["counts"]["thoughts_token_count"] == (value if valid else None)
    assert ("thoughts_token_count" in row["invalid_fields"]) is not valid
    assert row["counts"]["prompt_token_count"] is None
    assert row["resolved_model"] is None


def test_raising_metadata_and_content_do_not_escape_or_trigger_content_access():
    class Response:
        @property
        def usage_metadata(self):
            raise ValueError(SECRET)

        @property
        def text(self):
            pytest.fail("content must not be read by usage capture")

    ledger.record_response("safety", Response(), "fixture", "google")
    assert len(ledger._BUFFER) == 1
    state = {}
    assert ledger.drain_into_state(state) == 1
    row = state["llm_usage_observations"]["observations"][0]
    assert row["usage_status"] == "invalid" and row["invalid_fields"] == ["usage"]
    assert SECRET not in json.dumps(state)
    assert summarize_usage(state)["known_cost_usd"] is None


def test_unknown_usage_fields_are_flagged_without_copying_names_or_values():
    response = google_response()
    response.usage_metadata = response.usage_metadata.model_copy(update={SECRET: SECRET})
    row = observations.observe_response("safety", response, "fixture", "google")
    assert row["unsupported_fields"]
    assert SECRET not in observations.canonical(row)


def test_unknown_nested_fields_and_raising_model_identity_are_explicit():
    class Response:
        usage_metadata = SimpleNamespace(prompt_tokens_details=[{"modality": "TEXT", "token_count": 1, SECRET: SECRET}])

        @property
        def model_version(self):
            raise RuntimeError(SECRET)

    row = observations.observe_response("safety", Response(), "fixture", "google")
    assert row["unsupported_fields"] and "resolved_model" in row["invalid_fields"]
    assert row["resolved_model"] is None
    assert row["breakdowns"]["prompt_tokens_details"] == [{"modality": "TEXT", "token_count": 1}]
    assert SECRET not in observations.canonical(row)


@pytest.mark.parametrize("rows", [
    [{"modality": "TEXT", "token_count": 1}, {"modality": "TEXT", "token_count": 2}],
    [{"modality": "UNKNOWN", "token_count": 1}],
    [{"modality": "TEXT", "token_count": True}],
    [{"modality": "TEXT", "token_count": 1}]*9,
    SECRET,
])
def test_invalid_breakdown_is_explicit_and_never_summed_or_truncated_silently(rows):
    row = observations.observe_response("writer", SimpleNamespace(usage_metadata=SimpleNamespace(prompt_tokens_details=rows)), "fixture", "google")
    assert row["breakdowns"]["prompt_tokens_details"] is None
    assert "prompt_tokens_details" in row["invalid_fields"]
    assert observations.valid_record(row)


def test_schema_is_bounded_even_with_all_modalities_max_counts_and_identifiers():
    row = record()
    for key in ("stage", "requested_model", "resolved_model", "response_id"):
        row[key] = "x"*160
    row["labels"] = {k: "x"*160 for k in row["labels"]}
    row["counts"] = {k: 10**12 for k in row["counts"]}
    row["breakdowns"] = {k: [{"modality": m, "token_count": 10**12} for m in sorted(observations.CONTRACT["modalities"])] for k in row["breakdowns"]}
    row["invalid_fields"] = sorted(observations._paths("google"))
    assert observations.valid_record(row)
    rows = [{**row, "id": f"{i:032x}"} for i in range(32)]
    merged = observations.merge_observations(window(*rows))
    assert len(observations.canonical(merged).encode()) < 132*1024
    assert merged == node([window(*rows)])


def test_exact_union_is_associative_and_stale_saves_preserve_competing_observations():
    a, b, c = record(1), record(2), record(1)
    c["counts"]["thoughts_token_count"] = 41
    expected = observations.merge_observations(window(a,b,c))
    for order in permutations([window(a),window(b),window(c)]):
        left = observations.merge_observations(observations.merge_observations(*order[:2]), order[2])
        right = observations.merge_observations(order[0], observations.merge_observations(*order[1:]))
        assert left == right == expected == node(order)
    assert observations.merge_observations(expected, expected) == expected
    assert observations.summarize_observations(expected)["retained_conflicting_ids"] == [a["id"]]
    assert observations.summarize_observations(expected) == node(expected, operation="summary")


def test_retention_keeps_latest32_and_loss_evidence_survives_stale_merges():
    rows = [record(i) for i in range(38)]
    expected = observations.merge_observations(window(*rows))
    assert expected["truncated"] and len(expected["observations"]) == 32
    assert expected["observations"][0]["id"] == f"{37:032x}"
    for order in [rows, list(reversed(rows)), rows[::2]+rows[1::2]]:
        parts = [window(r) for r in order]
        result = {}
        for p in parts:
            result = observations.merge_observations(result,p)
        assert result == expected == node(parts)
    assert observations.merge_observations(expected, window(rows[0])) == expected


@pytest.mark.parametrize("bad", [[], "corrupt", {"schema_version": 2},
                                {"schema_version": 1, "observations": [], "truncated": "false", "invalid": False}])
def test_unknown_window_cannot_erase_current_observations_or_clear_invalid_flag(bad):
    good = window(record())
    merged = observations.merge_observations(good,bad)
    assert merged["invalid"] and merged["observations"] == good["observations"]
    assert merged == node([bad,good])
    assert observations.merge_observations(merged,{}) == merged


def test_persisted_integral_numbers_and_missing_empty_breakdowns_have_runtime_parity():
    row = record()
    row["schema_version"] = 1.0
    row["counts"]["thoughts_token_count"] = 40.0
    row["breakdowns"]["cache_tokens_details"] = []
    row["breakdowns"]["tool_use_prompt_tokens_details"] = None
    result = observations.merge_observations(window(row))
    assert not result["invalid"] and result == node([window(row)])
    assert result["observations"][0]["breakdowns"]["cache_tokens_details"] == []
    assert result["observations"][0]["breakdowns"]["tool_use_prompt_tokens_details"] is None


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("id", "x"), ("observed_at", "2026-02-30T00:00:00.000Z"),
    ("observed_at", "0000-01-01T00:00:00.000Z"), ("stage", "writer\n"),
    ("provider", "__proto__"), ("counts", {"__proto__": {"polluted": True}}),
    ("unsupported_fields", "false"), ("invalid_fields", [SECRET]),
    ("requested_model", "x"*161), ("usage_status", "trusted"),
])
def test_malformed_state_is_quarantined_with_python_js_parity(field,value):
    good, bad = record(), record(2)
    bad[field] = value
    raw = window(good,bad)
    before = deepcopy(raw)
    result = observations.merge_observations(raw)
    assert result["invalid"] and result["observations"] == [good]
    assert result == node([raw]) and raw == before


def test_capture_threads_then_failed_drain_preserve_every_observation_without_rebuy(monkeypatch):
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: ledger.record_response("safety", google_response(), "fixture", "google"), range(20)))
    ids = {row["usage_observation"]["id"] for row in ledger._BUFFER}
    assert len(ids) == 20
    state = {"drafts": [{"text": "Private fixture"}], "publish_ledger": {"fixture": {"status": "sent"}}}
    before = deepcopy(state)
    with monkeypatch.context() as patch:
        patch.setattr(ledger, "merge_observations", lambda *args: (_ for _ in ()).throw(ValueError("fixture")))
        assert ledger.drain_into_state(state) == 0
    assert state == before and len(ledger._BUFFER) == 20
    assert ledger.drain_into_state(state) == 20
    assert {r["id"] for r in state["llm_usage_observations"]["observations"]} == ids
    assert ledger.drain_into_state(state) == 0
    assert state["drafts"] == before["drafts"] and state["publish_ledger"] == before["publish_ledger"]


def test_buffer_overflow_and_failed_extractor_remain_visible(monkeypatch):
    monkeypatch.setattr(ledger, "_BUFFER_CAP", 3)
    for _ in range(4):
        ledger.record_response("safety", google_response(), "fixture", "google")
    state = {}
    assert ledger.drain_into_state(state) == 3
    assert state["llm_usage_observations"]["truncated"]
    monkeypatch.setattr(ledger, "observe_response", lambda *args: (_ for _ in ()).throw(ValueError(SECRET)))
    ledger.record_response("safety", google_response(), "fixture", "google")
    assert ledger.drain_into_state(state) == 1
    assert state["llm_usage_observations"]["invalid"]
    assert SECRET not in json.dumps(state)


def test_sqlite_roundtrip_and_dashboard_edit_preserve_exact_observations(tmp_path):
    from src.state import DEFAULT_STATE, _merge_state
    from src.storage import sqlite_store
    from tests.test_persistence_contract import node_store
    state = deepcopy(DEFAULT_STATE)
    ledger.record_response("safety", google_response(), "fixture", "google")
    ledger.drain_into_state(state)
    expected = deepcopy(state["llm_usage_observations"])
    # Use the real store adapter, not a mocked persistence callback.
    path = tmp_path / "state.sqlite3"
    assert sqlite_store.write_state(str(path), state)
    restored = sqlite_store.read_state(str(path), DEFAULT_STATE)
    assert restored["llm_usage_observations"] == expected
    stale = {"llm_usage_observations": window()}
    assert _merge_state(restored, stale)["llm_usage_observations"] == expected
    node_store(path, "write", stale)
    assert sqlite_store.read_state(str(path), DEFAULT_STATE)["llm_usage_observations"] == expected
