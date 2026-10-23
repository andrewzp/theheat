"""Verified archive usage: every call/attempt/response stays a separate denominator.

Archives are produced by the actual pipeline and pinned SDKs over INVENTED offline
transports (D1 harness). Usage shapes are invented; nothing here is provider truth.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from src.evaluation import archive_usage
from src.two_bot import request_archive_replay as replay
from src.two_bot.usage_cost_scenario import SCENARIO
from tests.test_request_archive_sdk import (
    FIXTURE, accepted_script, critic_json, fact_json, journey_env, private_root, run_journey, writer_json,
)

__all__ = ["journey_env"]
FIXTURES = Path(__file__).parent / "fixtures/private_workflow"


def anthropic_item(text, *, message_id=None, request_id=None, usage="default", model="claude-sonnet-4-6"):
    """Invented Anthropic Messages body with explicit IDs/usage (absent when None)."""
    def respond(family, request):
        body = {"type": "message", "role": "assistant", "model": model,
                "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None}
        if message_id is not None:
            body["id"] = message_id
        if usage == "default":
            body["usage"] = {"input_tokens": 1100, "output_tokens": 45, "cache_creation_input_tokens": 0,
                             "cache_read_input_tokens": 900}
        elif usage is not None:
            body["usage"] = usage
        headers = {"request-id": request_id} if request_id else {}
        return family.Response(200, json=body, headers=headers)
    return respond


def google_item(text, *, response_id=None, usage="default", model_version="gemini-2.5-flash", finish="STOP"):
    def respond(family, request):
        body: dict = {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                                      "finishReason": finish}]}
        if response_id is not None:
            body["responseId"] = response_id
        if model_version is not None:
            body["modelVersion"] = model_version
        if usage == "default":
            body["usageMetadata"] = {"promptTokenCount": 100, "candidatesTokenCount": 10, "thoughtsTokenCount": 0,
                                     "totalTokenCount": 110,
                                     "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100}]}
        elif usage is not None:
            body["usageMetadata"] = usage
        return family.Response(200, json=body)
    return respond


def d2_accepted_script(prefix="accepted"):
    return {"writer": [anthropic_item(writer_json(FIXTURE["accepted_tweet"]),
                                      message_id=f"msg_invented_d2_{prefix}_writer",
                                      request_id=f"req_invented_d2_{prefix}_writer")],
            "safety": [google_item("NO", response_id=f"invented-d2-{prefix}-safety")],
            "fact_check": [google_item(fact_json(True), response_id=f"invented-d2-{prefix}-fact")],
            "critic": [google_item(critic_json("PASS"), response_id=f"invented-d2-{prefix}-critic")]}


def d2_rejected_script():
    return {"writer": [anthropic_item(writer_json(FIXTURE["accepted_tweet"]),
                                      message_id="msg_invented_d2_rejected_writer",
                                      request_id="req_invented_d2_rejected_writer")],
            "safety": [google_item("NO", response_id="invented-d2-rejected-safety")],
            "fact_check": [google_item(fact_json(False, failures=[FIXTURE["factual_failure"]]),
                                       response_id="invented-d2-rejected-fact")]}


def d2_uncertain_script():
    return {"writer": [{"raise": "timeout"}] * 3}


def load(path):
    return replay.load_archive(path)


def test_accepted_rejected_and_uncertain_denominators_stay_separate(journey_env, tmp_path):
    accepted = run_journey(d2_accepted_script(), root=private_root(tmp_path, "a"))
    rejected = run_journey(d2_rejected_script(), root=private_root(tmp_path, "r"))
    uncertain = run_journey(d2_uncertain_script(), root=private_root(tmp_path, "u"))
    usage = archive_usage.archive_usage([load(accepted.archive), load(rejected.archive), load(uncertain.archive)])
    assert usage["denominators"] == {
        "sdk_calls": 10, "refused_or_raised_before_send": 0, "physical_attempts": 10,
        "responses_received": 7, "unknown_send_outcomes": 3, "responses_with_present_usage": 7,
        "responses_with_absent_usage": 0, "responses_with_invalid_usage": 0, "http_error_responses": 0,
        "rejected_answers_with_usage": 1, "provider_id_conflicts": 0}
    rejected_fact = [r for r in usage["attempts"] if r["provider_ids"].get("response_body_responseId")
                     == "invented-d2-rejected-fact"][0]
    assert rejected_fact["candidate_stage_outcome"] == "kill" and rejected_fact["usage_status"] == "present"
    assert rejected_fact["counts"]["prompt_token_count"] == 100  # A rejected answer keeps its real usage.
    unknown = [r for r in usage["attempts"] if r["send_outcome"] == "unknown"]
    assert len(unknown) == 3 and all(r["usage_status"] == "unknown" and "counts" not in r for r in unknown)
    writer = [g for g in usage["token_totals"] if g["provider"] == "anthropic"][0]
    assert writer["responses"] == 2 and writer["counts"]["input_tokens"] == 2200
    assert writer["counts"]["cache_read_input_tokens"] == 1800 and writer["missing_counts"]["output_tokens_details.thinking_tokens"] == 2
    assert usage["billing"] == "unknown" and usage["complete_account_coverage"] is False


@pytest.mark.parametrize("case,usage_value,expected", [
    ("missing", None, "absent"),
    ("negative", {"input_tokens": -1, "output_tokens": 3}, "invalid"),
    ("float", {"input_tokens": 1.5, "output_tokens": 3}, "invalid"),
    ("bool", {"input_tokens": True, "output_tokens": 3}, "invalid"),
])
def test_missing_and_invalid_usage_are_never_zero(journey_env, tmp_path, case, usage_value, expected):
    script = {"writer": [anthropic_item(writer_json(None, "Invented kill"), usage=usage_value)]}
    run = run_journey(script, root=private_root(tmp_path))
    usage = archive_usage.archive_usage([load(run.archive)])
    [row] = usage["attempts"]
    assert row["usage_status"] == expected and row["send_outcome"] == "response_received"
    assert usage["token_totals"] == []  # Nothing missing or invalid is summed as zero.
    assert row["provider_ids"] == {}  # Absent IDs stay absent.


def test_malformed_answer_and_http_error_keep_usage_separate(journey_env, tmp_path):
    def error(family, request):
        return family.Response(529, json={"type": "error", "error": {"type": "overloaded_error",
                                                                     "message": "invented"}})
    script = {"writer": [anthropic_item(FIXTURE["malformed_writer_text"], message_id="msg_invented_d2_malformed"),
                         anthropic_item("still not json", message_id="msg_invented_d2_malformed_2")]}
    run = run_journey(script, root=private_root(tmp_path, "m"))
    errors = run_journey({"writer": [error] * 3}, root=private_root(tmp_path, "e"))
    usage = archive_usage.archive_usage([load(run.archive), load(errors.archive)])
    outcomes = [(r["outcome"], r["usage_status"], r["http_status"]) for r in usage["attempts"]]
    assert outcomes[:2] == [("response_returned", "present", 200)] * 2
    assert outcomes[2:] == [("http_error_response", "absent", 529)] * 3
    assert usage["denominators"]["http_error_responses"] == 3


def test_cache_thought_tool_and_other_modalities_are_retained_and_scenario_excluded(journey_env, tmp_path):
    rich = {"promptTokenCount": 120, "candidatesTokenCount": 8, "thoughtsTokenCount": 30,
            "cachedContentTokenCount": 40, "toolUsePromptTokenCount": 5, "totalTokenCount": 163,
            "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100}, {"modality": "IMAGE", "tokenCount": 20}]}
    thoughts = {"promptTokenCount": 100, "candidatesTokenCount": 10, "thoughtsTokenCount": 20,
                "cachedContentTokenCount": 60, "totalTokenCount": 130,
                "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 100}],
                "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": 60}]}
    script = accepted_script()
    script["safety"] = [google_item("NO", response_id="invented-d2-rich", usage=rich)]
    script["fact_check"] = [google_item(fact_json(True), response_id="invented-d2-thoughts", usage=thoughts)]
    script["critic"] = [google_item(critic_json("PASS"), response_id="invented-d2-plain")]
    run = run_journey(script, root=private_root(tmp_path))
    usage = archive_usage.archive_usage([load(run.archive)])
    by_id = {r["provider_ids"].get("response_body_responseId"): r for r in usage["attempts"]}
    assert by_id["invented-d2-rich"]["counts"]["tool_use_prompt_token_count"] == 5
    assert {i["modality"] for i in by_id["invented-d2-rich"]["breakdowns"]["prompt_tokens_details"]} == {"TEXT", "IMAGE"}
    priced = archive_usage.priced_scenario(usage, SCENARIO)
    reasons = {r.get("call"): (r["disposition"], r["reasons"]) for r in priced["rows"]}
    assert reasons[2] == ("excluded", ["tool_input_not_priced"])
    assert reasons[3] == ("eligible", ["zero_tool_tokens_derived_from_total"])  # Thoughts priced as output.
    assert reasons[4] == ("eligible", ["zero_tool_tokens_derived_from_total", "cache_count_unknown_interval"])
    assert reasons[1][1] == ["no_named_scenario_for_provider"]  # Anthropic: no invented rate table.
    # fact (100-60)*300 + 60*30 + 30*2500 = 88800 nUSD; critic cache unknown: 28000..55000 nUSD.
    assert priced["token_component_usd"] == {"min": "0.000116800", "max": "0.000143800"}
    fact_amount = [r for r in priced["rows"] if r["call"] == 3][0]["token_component_usd"]
    assert fact_amount == {"min": "0.000088800", "max": "0.000088800"}
    assert priced["actual_cost_known"] is False and priced["billed_amount"] is None
    with pytest.raises(ValueError, match="unsupported_cost_scenario"):
        archive_usage.priced_scenario(usage, "anthropic-invented-rates")


def test_every_call_is_listed_with_no_newest_window(journey_env, tmp_path):
    from google import genai
    from google.genai import types
    from src.two_bot import request_archive, trial_budget
    from tests.test_request_archive_sdk import OfflineProviders, offline_transport
    providers = OfflineProviders()
    providers.queue("safety", *[google_item("NO", response_id=f"invented-d2-many-{i}") for i in range(40)])
    with offline_transport(providers), request_archive.capture(private_root(tmp_path), operation="many") as scope:
        with genai.Client(api_key="invented-offline", http_options=types.HttpOptions(
                **trial_budget.google_trial_options())) as client:
            for _ in range(40):
                trial_budget.provider_call("safety", "google", {"model": "gemini-flash-latest", "contents": "x"},
                                           client.models.generate_content)
    usage = archive_usage.archive_usage([load(scope.directory)])
    assert usage["denominators"]["responses_received"] == 40 and len(usage["attempts"]) == 40
    assert len(archive_usage.priced_scenario(usage, SCENARIO)["rows"]) == 40


def test_duplicate_provider_ids_across_archives_are_conflicts_not_merged(journey_env, tmp_path):
    first = run_journey(d2_accepted_script("same"), root=private_root(tmp_path, "one"))
    second = run_journey(d2_accepted_script("same"), root=private_root(tmp_path, "two"))
    usage = archive_usage.archive_usage([load(first.archive), load(second.archive)])
    assert usage["denominators"]["provider_id_conflicts"] == 8 and usage["token_totals"] == []
    priced = archive_usage.priced_scenario(usage, SCENARIO)
    assert priced["eligible_rows"] == 0 and {r["disposition"] for r in priced["rows"]} == {"excluded", "conflict"}


def test_partial_archive_is_labeled_and_invalid_archive_contributes_nothing(journey_env, tmp_path):
    run = run_journey(d2_accepted_script(), root=private_root(tmp_path))
    truncated_parent = private_root(tmp_path, "truncated")
    truncated = truncated_parent / run.archive.name
    shutil.copytree(run.archive, truncated)
    for path in [truncated, *truncated.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    manifest = truncated / "manifest.jsonl"
    lines = manifest.read_bytes().splitlines(keepends=True)
    manifest.write_bytes(b"".join(lines[:10]) + lines[10][:20])
    changed_parent = private_root(tmp_path, "changed")
    changed = changed_parent / run.archive.name
    shutil.copytree(run.archive, changed)
    for path in [changed, *changed.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    response = load(run.archive).calls[0].attempts[0].response.artifact
    target = changed / "artifacts" / str(response)
    target.write_bytes(target.read_bytes().replace(b"1100", b"9100"))  # Changed raw response.
    usage = archive_usage.archive_usage([load(truncated), load(changed)])
    sources = {s["status"]: s for s in usage["sources"]}
    assert sources["incomplete"]["used"] is True and "truncated_manifest_tail" in sources["incomplete"]["problems"]
    assert sources["invalid"]["used"] is False and sources["invalid"]["problems"] == ["artifact_hash_mismatch"]
    assert usage["denominators"]["physical_attempts"] == 2  # Verified prefix only; no upgrade, no repair.
    assert all(r["counts"]["input_tokens"] != 9100 for r in usage["attempts"] if "counts" in r)


@pytest.mark.parametrize("outcomes", [(False, True), (True, False)])
def test_same_text_on_different_generation_evidence_keeps_its_own_outcome(journey_env, tmp_path, outcomes):
    from collections import OrderedDict
    from unittest.mock import patch
    from src.two_bot import request_archive
    from src.voice import safety
    from tests.test_request_archive_sdk import OfflineProviders, offline_transport
    from tests.two_bot.conftest import _bundle, _state_with_memory
    providers = OfflineProviders()
    for index, passed in enumerate(outcomes):
        providers.queue("writer", anthropic_item(writer_json(FIXTURE["accepted_tweet"]),
                                                 message_id=f"msg-multigen-{index}", request_id=f"req-multigen-{index}"))
        providers.queue("safety", google_item("NO", response_id=f"safety-multigen-{index}"))
        providers.queue("fact_check", google_item(fact_json(passed, failures=[] if passed else ["invented failure"]),
                                                  response_id=f"fact-multigen-{index}"))
        if passed:
            providers.queue("critic", google_item(critic_json("PASS"), response_id=f"critic-multigen-{index}"))
    with offline_transport(providers), request_archive.capture(private_root(tmp_path), operation="invented two generations") as scope:
        for index in range(2):
            with patch.object(safety, "_SAFETY_CACHE", OrderedDict()):
                scope.run_generation(_bundle(frp=361.0 + index), _state_with_memory())
    archive = load(scope.directory)
    assert archive.status == "complete" and len(archive.inputs) == 2
    assert archive.inputs[0]["bundle_sha256"] != archive.inputs[1]["bundle_sha256"]
    usage = archive_usage.archive_usage([archive])
    facts = [row for row in usage["attempts"] if row["stage"] == "fact_check"]
    assert len(facts) == 2 and facts[0]["candidate_text_sha256"] == facts[1]["candidate_text_sha256"]
    assert [row["candidate_stage_outcome"] for row in facts] == ["pass" if passed else "kill" for passed in outcomes]
    assert usage["denominators"]["rejected_answers_with_usage"] == 1
