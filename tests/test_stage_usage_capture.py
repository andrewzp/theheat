"""Actual stage return boundaries, with SDK/network mocked and no paid calls."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.data import newsworthiness as news
from src.two_bot import critic, fact_check, usage_ledger as ledger
from src.two_bot.usage_summary import INSTRUMENTED_STAGES, summarize_usage
from src.voice import safety
from tests.two_bot.conftest import _bundle, _state_with_memory


STAGES = ["fact_check", "critic", "critic_slate", "safety", "newsworthiness_search", "newsworthiness_verify"]
NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_buffer():
    ledger._BUFFER.clear()
    safety._SAFETY_CACHE.clear()
    yield
    ledger._BUFFER.clear()
    safety._SAFETY_CACHE.clear()


def response(text="{}", **usage):
    return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
        **{"prompt_token_count": 100, "candidates_token_count": 20,
           "cached_content_token_count": 30, **usage}))


@pytest.fixture
def sdk(monkeypatch):
    from google import genai
    generate = Mock()
    client = Mock(return_value=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-key")
    return generate, client


def invoke(stage):
    if stage == "fact_check":
        return fact_check._call_gemini("Some clean tweet.", _bundle())
    if stage in {"critic", "critic_slate"}:
        return critic._call_gemini("Some clean tweet.", _bundle(), [], [],
                                  candidate_drafts=["One candidate.", "Another candidate."] if stage == "critic_slate" else None)
    if stage == "safety":
        return safety.check_llm("Some clean tweet.")
    if stage == "newsworthiness_search":
        return news._call_grounded_search(NOW)
    return news._call_verify_flash("Synthetic claim", 10, "Synthetic source excerpt")


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("text", ["", "NO", "YES", "not json"])
def test_capture_preserves_request_and_output_even_for_empty_or_invalid_text(monkeypatch, sdk, stage, text):
    generate, client = sdk
    generate.return_value = response(text)
    observer = ledger.record_response
    monkeypatch.setattr(ledger, "record_response", lambda *args: None)
    before = invoke(stage)
    requests, clients = generate.call_args_list[:], client.call_args_list[:]
    generate.reset_mock()
    client.reset_mock()
    monkeypatch.setattr(ledger, "record_response", observer)
    safety._SAFETY_CACHE.clear()  # Compare observer behavior with identical uncached inputs.
    assert invoke(stage) == before
    assert generate.call_args_list == requests and client.call_args_list == clients
    assert generate.call_count == 1 and len(ledger._BUFFER) == 1
    row = ledger._BUFFER[0]
    assert row["stage"] == ("critic" if stage == "critic_slate" else stage)
    assert row["model"] == generate.call_args.kwargs["model"]
    assert (row["in"], row["out"], row["cached_in"]) == (100, 20, 30)
    assert row["priced_calls"] == 0 and row["unpriced_calls"] == 1
    assert row["missing_usage_calls"] == 0


@pytest.mark.parametrize("stage", STAGES)
def test_response_accounted_before_text_access_fails(sdk, stage):
    class BrokenText:
        usage_metadata = response().usage_metadata

        @property
        def text(self):
            assert len(ledger._BUFFER) == 1
            raise ValueError("text unavailable")

    generate, _ = sdk
    generate.return_value = BrokenText()
    if stage == "safety":
        assert invoke(stage)[0] is False  # Unreadable model output cannot establish completion.
    else:
        with pytest.raises(ValueError, match="text unavailable"):
            invoke(stage)
    assert generate.call_count == 1 and len(ledger._BUFFER) == 1


@pytest.mark.parametrize("stage", STAGES)
def test_metadata_or_accounting_failure_never_retries_provider(monkeypatch, sdk, stage):
    class BrokenMetadata:
        text = "NO"

        @property
        def usage_metadata(self):
            raise ValueError("metadata unavailable")

    generate, _ = sdk
    generate.return_value = BrokenMetadata()
    invoke(stage)
    assert generate.call_count == 1 and ledger._BUFFER[0]["missing_usage_calls"] == 1
    ledger._BUFFER.clear()
    generate.reset_mock()
    monkeypatch.setattr(ledger, "record_usage", Mock(side_effect=RuntimeError("accounting unavailable")))
    safety._SAFETY_CACHE.clear()
    invoke(stage)
    assert generate.call_count == 1 and ledger._BUFFER == []


@pytest.mark.parametrize("stage", ["fact_check", "critic"])
def test_transport_failures_count_only_returned_responses(sdk, stage):
    generate, _ = sdk
    generate.side_effect = [RuntimeError("transient"), response("NO")]
    assert invoke(stage) == "NO"
    assert generate.call_count == 2 and len(ledger._BUFFER) == 1
    ledger._BUFFER.clear()
    generate.reset_mock()
    generate.side_effect = RuntimeError("offline failure")
    with pytest.raises(RuntimeError, match="offline failure"):
        invoke(stage)
    assert generate.call_count == 3 and ledger._BUFFER == []


@pytest.mark.parametrize("stage", ["fact_check", "critic", "critic_slate"])
def test_json_retry_counts_each_returned_response(sdk, stage):
    generate, _ = sdk
    raw = ({"passed": True, "failures": [], "extracted_claims": [{"kind": "comparison", "text": "Some clean tweet."}]}
           if stage == "fact_check" else {"verdict": "PASS", "kill_reason": None, "selected_index": 0})
    generate.side_effect = [response("not json"), response(json.dumps(raw))]
    if stage == "fact_check":
        result = fact_check.fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())
    elif stage == "critic":
        result = critic.critic_review("Some clean tweet.", _bundle(), _state_with_memory())
    else:
        result = critic.critic_select_slate(["One candidate.", "Another candidate."], _bundle(), _state_with_memory())
    assert result.passed and generate.call_count == 2 and len(ledger._BUFFER) == 2


def test_fact_semantic_contract_failure_does_not_add_retry(sdk):
    generate, _ = sdk
    generate.return_value = response('{"passed":true,"failures":[]}')
    assert not fact_check.fact_check("Some clean tweet.", [], _bundle(), _state_with_memory()).passed
    assert generate.call_count == 1 and len(ledger._BUFFER) == 1


def test_deterministic_and_missing_key_paths_have_no_invented_response(monkeypatch, sdk):
    generate, _ = sdk
    assert not fact_check.fact_check("", [], _bundle(), _state_with_memory()).passed
    assert not safety.run_safety_pipeline("x" * 281)[0]
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    assert safety.check_llm("Some clean tweet.") == (False, "safety_unavailable: missing credential")
    for stage in ("fact_check", "critic", "newsworthiness_search", "newsworthiness_verify"):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            invoke(stage)
    assert generate.call_count == 0 and ledger._BUFFER == []


def test_each_verified_impact_is_counted_when_entries_share_one_page(monkeypatch, sdk):
    generate, _ = sdk
    generate.return_value = response('{"supported":true}')
    fetch = Mock(return_value=SimpleNamespace(text="Synthetic source", raise_for_status=lambda: None))
    monkeypatch.setattr(news, "fetch_with_retry", fetch)
    entries = [{"claim": f"Synthetic claim {i}", "value": i, "url": "https://example.org/report"} for i in range(5)]
    result = news.NewsRetrievalResult()
    actual = news._verify_grounded([{"headline": "Synthetic event", "confidence": "unverified", "impact": entries}], result)
    assert actual[0]["impact"] == entries and fetch.call_count == 1
    assert generate.call_count == 5 and len(ledger._BUFFER) == 5
    assert {r["stage"] for r in ledger._BUFFER} == {"newsworthiness_verify"}


@pytest.mark.parametrize("value", [None, True, "", float("nan"), -1])
def test_invalid_required_google_quantity_is_unpriced_and_incomplete(value):
    ledger.record_response("safety", response(prompt_token_count=value), "gemini-2.5-flash", "google")
    assert len(ledger._BUFFER) == 1 and ledger._BUFFER[0]["missing_usage_calls"] == 1


def test_google_cannot_borrow_anthropic_price_and_summary_cannot_certify_history():
    ledger.record_response("safety", response(), "claude-sonnet-4-6", "google")
    state = {}
    ledger.drain_into_state(state)
    summary = summarize_usage(state)
    assert summary["known_cost_usd"] is None and summary["recorded_estimate_usd"] is None
    assert summary["unpriced_calls"] == 1 and summary["missing_usage_calls"] == 0
    empty = summarize_usage({})
    assert empty["instrumented_stages"] == INSTRUMENTED_STAGES
    assert empty["recorded_calls"] is None and empty["coverage"] == "unavailable"


def test_mixed_stage_buffer_pressure_is_bounded_and_does_not_claim_missing_writer_spend():
    ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=10000)
    for _ in range(ledger._BUFFER_CAP):
        ledger.record_response("newsworthiness_verify", response(), "gemini-2.5-flash", "google")
    state = {}
    assert ledger.drain_into_state(state) == ledger._BUFFER_CAP
    assert ledger.drain_into_state(state) == 0
    summary = summarize_usage(state)
    assert summary["recorded_calls"] == 500 and summary["recorded_estimate_usd"] is None
    assert any("evict earlier writer" in value for value in summary["limitations"])


def test_multistage_usage_survives_real_storage_roundtrip_with_legacy_and_receipts(tmp_path):
    from src.state import DEFAULT_STATE
    from src.storage import sqlite_store
    from tests.test_persistence_contract import node_store
    from tests.test_usage_coverage import node
    for stage in INSTRUMENTED_STAGES:
        ledger.record_response(stage, response(), "gemini-2.5-flash", "google")
    day = ledger._BUFFER[0]["day"]
    state = deepcopy(DEFAULT_STATE)
    old = {"calls": 2, "usd": 1.25, "in": 10, "out": 2, "cached_in": 0, "cache_write": 0}
    state["llm_usage"] = {day: {"writer|legacy": deepcopy(old)}}
    state["drafts"] = [{"id": "fixture", "text": "Exact retained fixture", "status": "posted", "tweet_id": "receipt", "publish_outcome": "confirmed"}]
    state["publish_ledger"] = {"fixture": {"phase": "unknown", "text_sha256": "f" * 64}}
    assert ledger.drain_into_state(state) == 6
    path = tmp_path / "stages.sqlite"
    assert sqlite_store.write_state(str(path), state)
    node_store(path, "write", {"drafts": state["drafts"]})
    actual = sqlite_store.read_state(str(path), DEFAULT_STATE)
    for key in ["llm_usage", "drafts", "publish_ledger"]:
        assert actual[key] == state[key]
    assert ledger.drain_into_state(actual) == 0
    assert actual["llm_usage"][day]["writer|legacy"] == old
    expected = summarize_usage(actual)
    js = node('''import {readFileSync} from "node:fs";
      import {summarizeUsage} from "./dashboard/lib/usage-ledger.js";
      console.log(JSON.stringify(summarizeUsage(JSON.parse(readFileSync(0,"utf8")))));''', actual)
    assert expected == js and expected["unpriced_calls"] == 6
    assert expected["legacy_estimate_usd"] == 1.25 and expected["known_cost_usd"] is None
