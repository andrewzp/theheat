"""Exact private factual-rejection context through the real production path."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from src.editorial.revisions import fingerprint, text_hash
from src.orchestrator import two_bot_dispatch as dispatch
from src.orchestrator.suppression import _record_downstream_suppression
from src.state import _merge_suppressions
from src.two_bot import pipeline
from src.two_bot.bundle_capture import MAX_SAFE_INTEGER
from src.two_bot.json_utils import model_response_diagnostic
from src.two_bot.rejected_candidate import MAX_REJECTION_BYTES, MAX_TEXT_BYTES, capture_fact_input, capture_fact_rejection
from src.two_bot.types import CriticResult, ExtractedClaim, FactCheckResult, WriterResult
from tests.test_draft_save_retention import round_trip
from tests.test_negative_cache import _score
from tests.two_bot.conftest import _bundle, _state_with_memory
from tests.two_bot.test_bundle_capture import complete_bundle

TEXT = "Mali thermal power is 361 MW."
RAW = '{"passed": false, "failures": ["Synthetic unsupported comparison"]}'


def rejected():
    return FactCheckResult(False, ["Synthetic unsupported comparison"], RAW,
                           [ExtractedClaim("A synthetic comparison", "comparison")])


def record(bundle=None, text=TEXT, verdict=None, **kwargs):
    bundle = bundle or complete_bundle()
    return capture_fact_rejection(text, bundle, capture_fact_input(bundle), verdict or rejected(),
                                  origin="required_checker", attempt=1, **kwargs)


@pytest.fixture
def stages(monkeypatch, configured_pipeline_providers):
    # Restore the compatibility facade after older tests that sync their mocks.
    from src import main
    main._sync_compat_globals()
    calls = [Mock(return_value=WriterResult(TEXT, None, "number", None, None, "offline fixture")),
             Mock(return_value=(True, None)), Mock(return_value=rejected()),
             Mock(return_value=CriticResult(True, None, "offline fixture"))]
    monkeypatch.setattr(pipeline.writer, "write_tweet", calls[0])
    monkeypatch.setattr(pipeline, "run_safety_pipeline", calls[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", calls[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", calls[3])
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    return calls


def dispatch_failure(monkeypatch, state, bundle, outcome):
    monkeypatch.setattr(dispatch, "_current_suppression_ctx", lambda: {
        "bot_state": state, "source": "firms", "run_id": "offline-rejection"})
    assert not dispatch._try_two_bot_draft(bundle, state, _score(), legacy_type="fire",
        event_id=bundle.event_id, review_context={}, result_out=outcome)
    return state["suppressions"][-1]


def test_actual_generation_dispatch_retention_and_private_response_correlation(stages, monkeypatch, capsys):
    state, bundle, outcome = _state_with_memory(), complete_bundle(), {}
    row = dispatch_failure(monkeypatch, state, bundle, outcome)
    packet = row["rejected_candidate"]
    assert packet["status"] == "retained" and packet["attempt"] == 1
    assert packet["text"] == TEXT and packet["text_sha256"] == text_hash(TEXT)
    assert packet["bundle"] == capture_fact_input(bundle).payload()
    assert packet["bundle_sha256"] == fingerprint(packet["bundle"])
    assert packet["verdict"] == {"check_path": "required_checker", "passed": False,
        "failures": rejected().failures, "extracted_claims": [c.to_dict() for c in rejected().extracted_claims],
        "response_diagnostic": model_response_diagnostic(RAW)}
    assert row["model_diagnostics"][0]["raw_response"] == RAW
    assert row["model_diagnostics"][0]["diagnostic"] == packet["verdict"]["response_diagnostic"]
    assert "raw_response" not in packet["verdict"]
    assert not row["model_diagnostics"][0]["truncated"]
    assert [call.call_count for call in stages] == [1, 1, 1, 0]
    assert not state["drafts"] and not state.get("writer_negative_cache")
    logs = capsys.readouterr().out
    assert all(secret not in logs for secret in (TEXT, RAW, "synthetic-firms-fixture"))
    before = deepcopy(row)
    outcome["rejected_candidate"]["bundle"]["raw_signal_dump"]["frp"] = 999
    bundle.raw_signal_dump["frp"] = 998
    stages[2].return_value.failures.append("Caller mutation")
    assert row == before
    loaded = round_trip(state, monkeypatch)
    assert loaded["suppressions"] == [before]


def test_actual_local_fact_rejection_does_not_buy_safety_or_checker(stages):
    # Real novelty rejection from private publication-memory input, not a stub pass.
    state = _state_with_memory()
    state["memory"]["shipped_tweets"] = [{"text": TEXT}]
    output = {}
    assert pipeline.generate_draft(_bundle(), state, result_out=output) is None
    assert output["kill_stage"] == "fact_check"
    assert output["rejected_candidate"]["verdict"]["check_path"] == "local_precheck"
    assert [call.call_count for call in stages] == [1, 0, 0, 0]


def test_revised_failure_records_only_second_exact_text_and_verdict(stages, monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    revised = "Mali: satellite thermal power reaches 361 MW."
    stages[0].side_effect = [stages[0].return_value, WriterResult(revised, None, "number", None, None, "offline")]
    stages[2].side_effect = [FactCheckResult(True, [], "first-pass"), rejected()]
    stages[3].return_value = CriticResult(False, None, "offline", verdict="REVISE", revise_instruction="Lead with the number")
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    packet = output["rejected_candidate"]
    assert packet["attempt"] == 2 and packet["text"] == revised and packet["text_sha256"] == text_hash(revised)
    assert packet["verdict"]["response_diagnostic"] == model_response_diagnostic(RAW)
    assert len(output["model_diagnostics"]) == 1
    assert [call.call_count for call in stages] == [2, 2, 2, 1]


def test_slate_failure_retains_selected_text_not_sample_zero(stages, monkeypatch):
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    texts = ["Synthetic first candidate.", "Synthetic second candidate.", "Synthetic selected candidate."]
    # The real slate fan-out still runs; order values are distinct and selected by result order.
    stages[0].side_effect = [WriterResult(t, None, "number", None, None, "offline") for t in texts]
    slate = Mock(return_value=CriticResult(True, None, "offline", selected_index=2))
    monkeypatch.setattr(pipeline.critic, "critic_select_slate", slate)
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["text"] == slate.call_args.args[0][2]
    assert output["rejected_candidate"]["attempt"] == 1
    assert stages[0].call_count == 3 and stages[2].call_count == 1 and not stages[3].called


@pytest.mark.parametrize("next_result", ["accepted", "writer", "safety", "critic"])
def test_reused_result_cannot_lend_old_failure_packet_to_another_candidate(next_result, stages):
    state, output = _state_with_memory(), {}
    assert pipeline.generate_draft(_bundle(), state, result_out=output) is None
    assert "rejected_candidate" in output
    stages[2].return_value = FactCheckResult(True, [], "offline")
    if next_result == "writer":
        stages[0].return_value = WriterResult(None, "Synthetic writer kill", "", None, None, "")
    elif next_result == "safety":
        stages[1].return_value = (False, "Synthetic safety kill")
    elif next_result == "critic":
        stages[3].return_value = CriticResult(False, "Synthetic critic kill", "offline")
    result = pipeline.generate_draft(_bundle(), state, result_out=output)
    assert (result is not None) == (next_result == "accepted")
    assert "rejected_candidate" not in output and not output.get("model_diagnostics")


def test_negative_cache_early_skip_clears_context_without_model_calls(stages, monkeypatch):
    from tests.test_negative_cache_boundaries import seed
    state, bundle, output = _state_with_memory(), _bundle(), {}
    dispatch_failure(monkeypatch, state, bundle, output)
    seed(state, bundle.event_id, bundle)
    for stage in stages:
        stage.reset_mock()
    row = dispatch_failure(monkeypatch, state, bundle, output)
    assert row["stage"] == "negative_cache"
    for field in ("rejected_candidate", "model_diagnostics", "evidence_readiness"):
        assert field not in output and field not in row
    assert all(not stage.called for stage in stages)


@pytest.mark.parametrize("field", ["raw_signal_dump", "historical_context"])
def test_mutation_during_fact_check_is_explicitly_unavailable(field, stages):
    bundle = _bundle()
    def mutate(*args):
        getattr(bundle, field)["changed"] = True
        return rejected()
    stages[2].side_effect = mutate
    output = {}
    assert pipeline.generate_draft(bundle, _state_with_memory(), result_out=output) is None
    assert output["kill_stage"] == "fact_check"
    assert output["rejected_candidate"]["reason"] == "bundle_changed_during_fact_check"
    assert "text" not in output["rejected_candidate"]


@pytest.mark.parametrize("extra", [0, 1])
def test_exact_entire_packet_byte_limit(extra):
    verdict = FactCheckResult(False, [""], "offline")
    initial = record(verdict=verdict)
    size = len(json.dumps(initial, sort_keys=True).encode("utf-8"))
    verdict.failures[0] = "x" * (MAX_REJECTION_BYTES - size + extra)
    result = record(verdict=verdict)
    assert (result["status"] == "retained") == (extra == 0)
    if not extra:
        assert len(json.dumps(result, sort_keys=True).encode("utf-8")) == MAX_REJECTION_BYTES
    else:
        assert result["reason"] == "packet_too_large" and "bundle" not in result


@pytest.mark.parametrize("text,reason", [(None, "invalid_text"), ("", "invalid_text"),
    ("x" * (MAX_TEXT_BYTES + 1), "text_too_large"), ("☀" * 1366, "text_too_large"),
    ("\ud800", "invalid_packet")], ids=["null", "empty", "long", "unicode-byte-bound", "surrogate"])
def test_invalid_or_large_text_is_never_truncated_and_labeled_complete(text, reason):
    result = record(text=text)
    assert result["status"] == "unavailable" and result["reason"] == reason
    assert "text" not in result and len(json.dumps(result)) < 200


@pytest.mark.parametrize("value", [b"invalid", float("nan"), MAX_SAFE_INTEGER + 1, "\ud800"])
def test_invalid_bundle_is_unavailable(value):
    bundle = _bundle()
    bundle.raw_signal_dump["invalid"] = value
    result = record(bundle=bundle)
    assert result["status"] == "unavailable" and "bundle" not in result
    assert result["reason"].startswith("bundle_capture_")


def test_unsupported_verdict_and_untrusted_capture_error_have_bounded_dispositions():
    verdict = rejected()
    verdict.failures = [object()]
    assert record(verdict=verdict)["reason"] == "invalid_verdict"
    result = capture_fact_rejection(TEXT, _bundle(), "private-error" * 10000, rejected(), origin="required_checker", attempt=1)
    assert result["reason"] == "invalid_packet" and len(json.dumps(result)) < 200


def test_large_raw_response_is_not_duplicated_in_packet(stages):
    stages[2].return_value.raw_response = "private output " * 10000
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["status"] == "retained"
    assert output["model_diagnostics"][0]["truncated"] is True
    assert len(output["model_diagnostics"][0]["raw_response"]) == 65536
    assert "private output" not in json.dumps(output["rejected_candidate"])


def test_existing_recent_retention_and_merge_preserve_packets_but_do_not_backfill_legacy(monkeypatch):
    state = _state_with_memory()
    now = datetime.now(UTC)
    legacy = {"id": "legacy", "ts": (now-timedelta(seconds=1)).isoformat(), "stage": "fact_check"}
    state["suppressions"] = [legacy]
    packet = record()
    for i in range(101):
        _record_downstream_suppression(bot_state=state, source="fixture", run_id="offline", event_id=str(i),
            score=_score(), kill_stage="fact_check", kill_reason="Synthetic rejection", summary="Synthetic",
            rejected_candidate=packet)
    assert len(state["suppressions"]) == 100
    assert all(row["rejected_candidate"] == packet for row in state["suppressions"])
    assert "rejected_candidate" not in legacy
    rows = deepcopy(state["suppressions"])
    merged = _merge_suppressions([legacy, *rows], rows)
    assert merged == rows
    packet["bundle"]["country"] = "changed"
    assert state["suppressions"] == rows
    assert round_trip(state, monkeypatch)["suppressions"] == rows


def test_python_generated_packet_survives_authenticated_actual_dashboard_api(stages, monkeypatch):
    state, outcome = _state_with_memory(), {}
    row = dispatch_failure(monkeypatch, state, complete_bundle(), outcome)
    loaded = round_trip(state, monkeypatch)
    script = r'''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GET } from "./app/api/suppressions/route.js";
import { writeStateStore, readStateStore } from "./lib/state-store.js";
let state = JSON.parse(readFileSync(0, "utf8"));
Object.assign(process.env, {NODE_ENV: "production", DASHBOARD_AUTH_DISABLED: "0", DASHBOARD_USERNAME: "fixture",
  DASHBOARD_PASSWORD: "offline-only", THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "",
  GIST_ID: "rejection_fixture", GITHUB_TOKEN: "offline-fixture"});
let reads = 0;
globalThis.fetch = async (url, options = {}) => {
  assert.equal(String(url), "https://api.github.com/gists/rejection_fixture");
  if (options.method === "PATCH") {
    state = JSON.parse(JSON.parse(options.body).files["state.json"].content);
    return {ok: true, status: 200, async json() {return {}}};
  }
  assert.ok(!options.method || options.method === "GET");
  reads++;
  return {ok: true, status: 200, async json() {return {files: {"state.json": {content: JSON.stringify(state)}}}}};
};
const before = structuredClone(state.suppressions);
const denied = await GET(new Request("http://localhost/api/suppressions"));
assert.equal(denied.status, 401);
assert.equal(reads, 0);
assert.ok(!(await denied.text()).includes(before[0].rejected_candidate.text));
await writeStateStore(await readStateStore());
const response = await GET(new Request("http://localhost/api/suppressions?source=firms", {
  headers: {authorization: `Basic ${Buffer.from("fixture:offline-only").toString("base64")}`}}));
assert.equal(response.status, 200);
const payload = await response.json();
assert.deepEqual(payload.suppressions, before);
assert.equal(payload.stats.stage_counts.fact_check, 1);
process.stdout.write(JSON.stringify(payload.suppressions));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2]/"dashboard", input=json.dumps(loaded),
        capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(result.stdout) == [row]
