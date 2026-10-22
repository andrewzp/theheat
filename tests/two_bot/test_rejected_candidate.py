"""Exact private factual-rejection context through the real production path."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.editorial.revisions import fingerprint, text_hash
from src.orchestrator import two_bot_dispatch as dispatch
from src.orchestrator.suppression import _record_downstream_suppression
from src.state import _merge_suppressions
from src.two_bot import pipeline
from src.two_bot.bundle_capture import MAX_BUNDLE_BYTES, MAX_SAFE_INTEGER
from src.two_bot.json_utils import model_response_diagnostic
from src.two_bot.rejected_candidate import (
    MAX_REJECTION_BYTES, MAX_TEXT_BYTES, capture_critic_rejection, capture_fact_input,
    capture_fact_rejection, capture_safety_rejection, capture_stage_input,
)
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


@pytest.mark.parametrize("stage", ["fact_check", "safety"])
def test_slate_failure_retains_selected_text_not_sample_zero(stages, monkeypatch, stage):
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    texts = ["Synthetic first candidate.", "Synthetic second candidate.", "Synthetic selected candidate."]
    # The real slate fan-out still runs; order values are distinct and selected by result order.
    stages[0].side_effect = [WriterResult(t, None, "number", None, None, "offline") for t in texts]
    slate = Mock(return_value=CriticResult(True, None, "offline", selected_index=2))
    monkeypatch.setattr(pipeline.critic, "critic_select_slate", slate)
    if stage == "safety":
        stages[1].return_value = (False, "Synthetic safety rejection")
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["text"] == slate.call_args.args[0][2]
    assert output["rejected_candidate"]["attempt"] == 1
    assert stages[0].call_count == 3 and stages[2].call_count == (0 if stage == "safety" else 1) and not stages[3].called


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
    if next_result in {"safety", "critic"}:
        assert output["rejected_candidate"]["schema_version"] == 2
        assert output["rejected_candidate"]["stage"] == next_result
        assert output["rejected_candidate"]["scope"] != "selected_fact_check_rejection"
    else:
        assert "rejected_candidate" not in output
    assert not output.get("model_diagnostics")


@pytest.mark.parametrize("prior_stage", ["fact_check", "safety", "critic"])
def test_negative_cache_early_skip_clears_context_without_model_calls(stages, monkeypatch, prior_stage):
    from tests.test_negative_cache_boundaries import seed
    state, bundle, output = _state_with_memory(), _bundle(), {}
    if prior_stage != "fact_check":
        stages[2].return_value = FactCheckResult(True, [], "offline")
        if prior_stage == "safety":
            stages[1].return_value = (False, "Synthetic safety rejection")
        else:
            stages[3].return_value = CriticResult(False, "Synthetic selected rejection", "offline")
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


@pytest.mark.parametrize("stage", ["fact_check", "safety", "critic"])
def test_python_generated_packet_survives_authenticated_actual_dashboard_api(stages, monkeypatch, stage):
    if stage != "fact_check":
        stages[2].return_value = FactCheckResult(True, [], "offline")
        if stage == "safety":
            stages[1].return_value = (False, "LLM flagged as potentially harmful")
        else:
            stages[3].return_value = CriticResult(False, "Synthetic selected rejection", "offline critic response")
    state, outcome = _state_with_memory(), {}
    row = dispatch_failure(monkeypatch, state, complete_bundle(), outcome)
    legacy = {"id": "legacy", "ts": (datetime.now(UTC)-timedelta(seconds=1)).isoformat(),
              "source": "firms", "stage": "legacy", "reasons": ["Synthetic legacy rejection"]}
    state["suppressions"].append(legacy)
    loaded = round_trip(state, monkeypatch)
    assert_dashboard_roundtrip(loaded)
    assert {r["id"]: r for r in loaded["suppressions"]} == {r["id"]: r for r in [row, legacy]}
    assert "rejected_candidate" not in legacy


def assert_dashboard_roundtrip(loaded):
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
const before = structuredClone(state.suppressions).sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
const denied = await GET(new Request("http://localhost/api/suppressions"));
assert.equal(denied.status, 401);
assert.equal(reads, 0);
const deniedBody = await denied.text();
for (const row of before) {
  if (row.rejected_candidate?.text) assert.ok(!deniedBody.includes(row.rejected_candidate.text));
  assert.ok(!deniedBody.includes(row.id));
}
await writeStateStore(await readStateStore());
const response = await GET(new Request("http://localhost/api/suppressions?source=firms", {
  headers: {authorization: `Basic ${Buffer.from("fixture:offline-only").toString("base64")}`}}));
assert.equal(response.status, 200);
const payload = await response.json();
assert.deepEqual(payload.suppressions, before);
assert.equal(payload.stats.stage_counts[before[0].stage], 1);
process.stdout.write(JSON.stringify(payload.suppressions));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2]/"dashboard", input=json.dumps(loaded),
        capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == sorted(loaded["suppressions"],
        key=lambda row: datetime.fromisoformat(row["ts"].replace("Z", "+00:00")), reverse=True)


def stage_record(stage, *, bundle=None, text=TEXT, reason="Synthetic selected rejection", attempt=1):
    bundle = bundle or _bundle()
    captured = capture_stage_input(bundle, capture_fact_input(bundle))
    if stage == "safety":
        return capture_safety_rejection(text, bundle, captured, False, reason, attempt=attempt)
    return capture_critic_rejection(text, bundle, captured,
        CriticResult(False, reason, "offline critic response"), attempt=attempt)


@pytest.mark.parametrize("stage", ["safety", "critic"])
@pytest.mark.parametrize("extra", [0, 1])
def test_new_stage_entire_packet_byte_bound_is_unchanged(stage, extra):
    initial = stage_record(stage, reason="x")
    size = len(json.dumps(initial, sort_keys=True).encode("utf-8"))
    packet = stage_record(stage, reason="x" * (MAX_REJECTION_BYTES - size + 1 + extra))
    assert (packet["status"] == "retained") == (extra == 0)
    if extra:
        assert packet["reason"] == "packet_too_large" and "text" not in packet
    else:
        assert len(json.dumps(packet, sort_keys=True).encode("utf-8")) == MAX_REJECTION_BYTES


@pytest.mark.parametrize("stage", ["safety", "critic"])
@pytest.mark.parametrize("invalid", ["text", "bundle", "oversize_bundle", "nonfinite_bundle", "verdict", "attempt"])
def test_new_stage_invalid_input_never_becomes_partial_complete_packet(stage, invalid):
    bundle = _bundle()
    kwargs = {}
    if invalid == "text":
        kwargs["text"] = "☀" * (MAX_TEXT_BYTES // 3 + 1)
    elif invalid == "bundle":
        bundle.raw_signal_dump["invalid"] = b"not retained"
    elif invalid == "oversize_bundle":
        bundle.raw_signal_dump["oversize"] = "x" * (MAX_BUNDLE_BYTES + 1)
    elif invalid == "nonfinite_bundle":
        bundle.raw_signal_dump["invalid"] = float("nan")
    elif invalid == "verdict":
        kwargs["reason"] = "\ud800"
    else:
        kwargs["attempt"] = float("nan")
    packet = stage_record(stage, bundle=bundle, **kwargs)
    assert packet["status"] == "unavailable" and "text" not in packet and "bundle" not in packet
    assert len(json.dumps(packet, allow_nan=False)) < 250


@pytest.mark.parametrize("stage", ["safety", "critic"])
@pytest.mark.parametrize("text", ["x" * MAX_TEXT_BYTES, "☀" * (MAX_TEXT_BYTES // 3) + "x"], ids=["ascii", "unicode"])
def test_new_stage_exact_text_byte_boundary_is_retained(stage, text):
    packet = stage_record(stage, text=text)
    assert len(text.encode("utf-8")) == MAX_TEXT_BYTES
    assert packet["status"] == "retained" and packet["text"] == text


@pytest.mark.parametrize("stage", ["safety", "critic"])
def test_stage_bundle_capture_compares_entry_and_terminal_without_mutable_aliases(stage):
    bundle = _bundle()
    entry = capture_fact_input(bundle)
    captured = capture_stage_input(bundle, entry)
    bundle.raw_signal_dump["changed"] = True
    if stage == "safety":
        packet = capture_safety_rejection(TEXT, bundle, captured, False, "Synthetic rejection", attempt=1)
    else:
        packet = capture_critic_rejection(TEXT, bundle, captured, CriticResult(False, "Synthetic", "offline"), attempt=1)
    assert packet["reason"] == f"bundle_changed_during_{stage}"
    assert capture_stage_input(bundle, entry) == "bundle_changed_after_generation_entry"
    retained_bundle = _bundle()
    retained = stage_record(stage, bundle=retained_bundle)
    before = deepcopy(retained)
    retained_bundle.raw_signal_dump["changed_after_return"] = True
    assert retained == before


@pytest.mark.parametrize("stage", ["safety", "critic"])
def test_actual_terminal_stage_mutation_and_failed_capture_are_unavailable(stage, stages, monkeypatch):
    bundle, output = _bundle(), {}
    stages[2].return_value = FactCheckResult(True, [], "offline")
    def reject(*args, **kwargs):
        bundle.historical_context["changed"] = True
        return (False, "Synthetic safety rejection") if stage == "safety" else CriticResult(False, "Synthetic", "offline")
    stages[1 if stage == "safety" else 3].side_effect = reject
    assert pipeline.generate_draft(bundle, _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["reason"] == f"bundle_changed_during_{stage}"
    assert [mock.call_count for mock in stages] == ([1, 1, 0, 0] if stage == "safety" else [1, 1, 1, 1])
    # Failure at the later capture boundary cannot reuse the valid entry packet.
    def unavailable_capture(*args):
        return "bundle_capture_invalid_json"
    monkeypatch.setattr(pipeline, "capture_stage_input", unavailable_capture)
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["reason"] == "bundle_capture_invalid_json"


@pytest.mark.parametrize("stage", ["safety", "critic"])
def test_changed_source_after_writer_does_not_become_qualified_stage_input(stage, stages):
    bundle, output = _bundle(), {}
    def writer_mutation(*args):
        bundle.historical_context["post_generation_change"] = True
        return stages[0].return_value
    stages[0].side_effect = writer_mutation
    stages[2].return_value = FactCheckResult(True, [], "offline")
    if stage == "safety":
        stages[1].return_value = (False, "Synthetic safety rejection")
    else:
        stages[3].return_value = CriticResult(False, "Synthetic", "offline")
    assert pipeline.generate_draft(bundle, _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["reason"] == "bundle_changed_after_generation_entry"


@pytest.mark.parametrize("stage", ["safety", "critic"])
def test_revised_selected_stage_failure_has_only_second_candidate_packet(stage, stages, monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    revised = "Mali: satellite thermal power reaches 361 MW."
    stages[0].side_effect = [stages[0].return_value, WriterResult(revised, None, "number", None, None, "offline")]
    stages[2].return_value = FactCheckResult(True, [], "offline")
    revise = CriticResult(False, None, "first response", verdict="REVISE", revise_instruction="Lead with the number")
    if stage == "safety":
        stages[1].side_effect = [(True, None), (False, "LLM flagged as potentially harmful")]
        stages[3].return_value = revise
    else:
        stages[3].side_effect = [revise, CriticResult(False, "Second selected rejection", "second response")]
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    packet = output["rejected_candidate"]
    assert packet["text"] == revised and packet["text_sha256"] == text_hash(revised)
    assert packet["attempt"] == 2 and packet["stage"] == stage and packet["status"] == "retained"
    if stage == "critic":
        assert packet["verdict"]["response_diagnostic"] == model_response_diagnostic("second response")
    assert [mock.call_count for mock in stages] == ([2, 2, 1, 1] if stage == "safety" else [2, 2, 2, 2])


@pytest.mark.parametrize("stage", ["safety", "critic"])
def test_new_packets_survive_existing_retention_merge_and_legacy_rows(stage, monkeypatch):
    packet = stage_record(stage)
    state = _state_with_memory()
    legacy = {"id": "legacy", "ts": datetime.now(UTC).isoformat(), "stage": stage}
    state["suppressions"] = [legacy]
    for i in range(100):
        _record_downstream_suppression(bot_state=state, source="fixture", run_id="offline", event_id=str(i),
            score=_score(), kill_stage=stage, kill_reason="Synthetic rejection", summary="Synthetic",
            rejected_candidate=packet)
    rows = deepcopy(state["suppressions"])
    assert len(rows) == 100 and all(row["rejected_candidate"] == packet for row in rows)
    assert "rejected_candidate" not in legacy
    assert _merge_suppressions([legacy, *rows], rows) == rows
    packet["bundle"]["country"] = "mutated after insertion"
    assert state["suppressions"] == rows
    assert round_trip(state, monkeypatch)["suppressions"] == rows


@pytest.mark.parametrize("unsupported", ["writer", "slate", "transport"])
def test_selected_packet_is_cleared_before_unsupported_terminal_outcome(unsupported, stages, monkeypatch):
    stages[2].return_value = FactCheckResult(True, [], "offline")
    stages[3].return_value = CriticResult(False, "Synthetic selected rejection", "offline")
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["stage"] == "critic"
    if unsupported == "writer":
        stages[0].return_value = WriterResult(None, "Synthetic writer rejection", "", None, None, "")
    elif unsupported == "slate":
        monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "2")
        monkeypatch.setattr(pipeline.critic, "critic_select_slate", Mock(return_value=CriticResult(False, "Synthetic slate rejection", "offline")))
    else:
        stages[3].side_effect = RuntimeError("Synthetic transport uncertainty")
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    assert "rejected_candidate" not in output and not output.get("model_diagnostics")


@pytest.mark.parametrize("outcome", ["safety_refusal", "safety_unavailable", "safety_invalid", "critic_kill", "critic_invalid",
    "safety_revised_refusal", "critic_revised_kill"])
def test_actual_writer_safety_fact_critic_functions_with_offline_provider_results(outcome, monkeypatch, configured_pipeline_providers, capsys):
    from google import genai
    from src import main
    from src.voice import safety
    main._sync_compat_globals()
    safety._SAFETY_CACHE.clear()
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    is_revised = "revised" in outcome
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1" if is_revised else "0")
    revised_text = "Mali satellite thermal power is 361 MW."
    writer_raw = json.dumps({"tweet": TEXT, "kill_reason": None, "angle_chosen": "number",
        "era_anchor_used": None, "peer_comparison_used": None, "reasoning": "offline fixture"})
    writer_call = Mock(return_value=writer_raw)
    if is_revised:
        revised_payload = json.loads(writer_raw)
        revised_payload["tweet"] = revised_text
        writer_call.side_effect = [writer_raw, json.dumps(revised_payload)]
    monkeypatch.setattr(pipeline.writer, "_call_anthropic", writer_call)
    safety_call = Mock(return_value=SimpleNamespace(text="YES" if outcome == "safety_refusal" else "NO",
        candidates=[SimpleNamespace(finish_reason="STOP")]))
    if outcome == "safety_unavailable":
        safety_call.side_effect = RuntimeError("private provider exception")
    elif outcome == "safety_invalid":
        safety_call.return_value.text = "ambiguous response"
    elif outcome == "safety_revised_refusal":
        safety_call.side_effect = [safety_call.return_value,
            SimpleNamespace(text="YES", candidates=[SimpleNamespace(finish_reason="STOP")])]
    monkeypatch.setattr(genai, "Client", Mock(return_value=SimpleNamespace(
        models=SimpleNamespace(generate_content=safety_call), close=Mock())))
    fact_call = Mock(side_effect=lambda tweet, *args, **kwargs: json.dumps({"passed": True, "failures": [],
        "extracted_claims": [{"text": tweet, "kind": "number"}]}))
    monkeypatch.setattr(pipeline.fact_check, "_call_gemini", fact_call)
    critic_raw = '{"verdict":"KILL","kill_reason":"Synthetic selected rejection","revise_instruction":null,"selected_index":null}'
    critic_call = Mock(return_value="invalid" if outcome == "critic_invalid" else critic_raw)
    if is_revised:
        critic_call.side_effect = [json.dumps({"verdict": "REVISE", "kill_reason": None,
            "revise_instruction": "Lead with the satellite measurement", "selected_index": None}), critic_raw]
    monkeypatch.setattr(pipeline.critic, "_call_gemini", critic_call)
    state, output = _state_with_memory(), {}
    try:
        row = dispatch_failure(monkeypatch, state, _bundle(), output)
        packet = row["rejected_candidate"]
        stage = "safety" if outcome.startswith("safety") else "critic"
        assert row["stage"] == stage and packet["scope"] == f"selected_{stage}_rejection"
        if outcome in {"safety_refusal", "critic_kill", "safety_revised_refusal", "critic_revised_kill"}:
            assert packet["status"] == "retained" and packet["text"] == (revised_text if is_revised else TEXT)
            assert packet["attempt"] == (2 if is_revised else 1)
            if stage == "safety":
                assert packet["verdict"] == {"check_path": "safety_pipeline", "passed": False,
                    "reason": "LLM flagged as potentially harmful", "response_status": "not_exposed", "response_diagnostic": None}
            else:
                assert packet["verdict"]["response_diagnostic"] == model_response_diagnostic(critic_raw)
        else:
            assert packet["status"] == "unavailable" and "text" not in packet
        expected_calls = ([2, 2, 1, 1] if stage == "safety" else [2, 2, 2, 2]) if is_revised else (
            [1, 1, 0, 0] if stage == "safety" else [1, 1, 1, 2 if outcome == "critic_invalid" else 1])
        assert [writer_call.call_count, safety_call.call_count, fact_call.call_count, critic_call.call_count] == expected_calls
        assert not state["drafts"] and not state.get("writer_negative_cache")
        loaded = round_trip(state, monkeypatch)
        assert loaded["suppressions"] == [row]
        assert_dashboard_roundtrip(loaded)
        logs = capsys.readouterr().out
        assert all(secret not in logs for secret in (TEXT, revised_text, critic_raw, "private provider exception", "Synthetic selected rejection"))
    finally:
        safety._SAFETY_CACHE.clear()


@pytest.mark.parametrize("passed,reason", [(None, "Synthetic rejection"), (0, "Synthetic rejection"),
    (False, None), (False, ""), (False, "safety_incomplete_response")])
def test_malformed_or_unavailable_safety_tuple_is_not_a_completed_refusal(passed, reason, stages):
    stages[1].return_value = (passed, reason)
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    packet = output["rejected_candidate"]
    assert packet["status"] == "unavailable" and "text" not in packet and "verdict" not in packet
    assert [mock.call_count for mock in stages] == [1, 1, 0, 0]


def test_safety_reason_containing_exact_copy_stays_out_of_public_logs(stages, capsys):
    stages[1].return_value = (False, TEXT)
    output = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=output) is None
    assert output["rejected_candidate"]["verdict"]["reason"] == TEXT
    assert TEXT not in capsys.readouterr().out


def test_critic_invalid_response_unicode_is_unavailable():
    bundle = _bundle()
    packet = capture_critic_rejection(TEXT, bundle, capture_fact_input(bundle),
        CriticResult(False, "Synthetic rejection", "\ud800"), attempt=1)
    assert packet["status"] == "unavailable" and packet["reason"] == "invalid_packet"
