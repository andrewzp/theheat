"""Actual generate_draft journeys with capture OFF vs ON; INVENTED offline providers.

Each journey runs the real stages and pinned SDKs; only the HTTP transport is an
explicit invented fixture. Accepted/rejected outcomes here are fixture outcomes,
never weather truth, copy quality, approval or publication.
"""
from __future__ import annotations

import json

import pytest

from src.editorial.revisions import text_hash
from src.two_bot import request_archive_replay as replay
from tests.test_request_archive_sdk import (
    FIXTURE, accepted_script, result, critic_json, fact_json, journey_env, private_root, run_journey, writer_json,
)

__all__ = ["journey_env"]  # Re-exported fixture.
TWEET = FIXTURE["accepted_tweet"]


def both(tmp_path, script, **kwargs):
    off = run_journey(script, **kwargs)
    on = run_journey(script, root=private_root(tmp_path), **kwargs)
    # Capture is observation only: identical sends, results, stdout and state.
    assert on.providers.physical == off.providers.physical
    assert on.draft == off.draft and on.out == off.out
    assert on.stdout == off.stdout and on.state == off.state
    if on.draft is not None:
        assert "scope-" not in json.dumps(on.draft) and "request_archive" not in json.dumps(on.draft)
    return on, replay.load_archive(on.archive)


def only_generation(archive):
    generations = replay.lineage(archive)
    assert len(generations) == 1
    return generations[0]


def test_accepted_journey_binds_input_candidate_calls_and_terminal(journey_env, tmp_path):
    on, archive = both(tmp_path, accepted_script())
    generation = only_generation(archive)
    terminal = generation["terminal"]
    metadata = on.draft["two_bot_metadata"]
    assert archive.status == "complete" and terminal["accepted"] is True
    assert terminal["draft_text_sha256"] == text_hash(on.draft["text"]) == metadata["reviewed_text_sha256"]
    assert generation["bundle_sha256"] == terminal["reviewed_bundle_sha256"] == metadata["reviewed_bundle_sha256"]
    [candidate] = generation["candidates"]
    assert candidate["candidate_text_sha256"] == text_hash(TWEET) and candidate["attempt"] == 1
    assert {k: v["disposition"] for k, v in candidate["stages"].items()} == {
        "safety": "provider_called", "fact_check": "provider_called", "critic": "provider_called"}
    assert candidate["stages"]["fact_check"]["outcome"] == candidate["stages"]["critic"]["outcome"] == "pass"
    # The pipeline records no explicit safety pass; absence stays absent, not inferred.
    assert candidate["stages"]["safety"]["outcome"] is None
    inputs = archive.inputs[0]
    memory = json.loads(archive.artifact(inputs["memory_artifact"]))
    assert set(memory) >= {"recent_tweets_same_event", "shipped_tweet_texts"}
    writer_logical = json.loads(archive.artifact(archive.calls[0].logical_request.artifact))
    prompt = writer_logical["kwargs"]["messages"][0]["content"]
    assert on.state["memory"]["used_framings"] == [] and isinstance(prompt, str) and prompt
    code = archive.opened["code_identity"]
    assert code["authority"] == "local_provenance_only" and code["files"]["src/two_bot/pipeline.py"]


def test_factual_rejection_is_bound_to_the_exact_candidate(journey_env, tmp_path):
    script = accepted_script()
    script["fact_check"] = [{"text": fact_json(False, failures=[FIXTURE["factual_failure"]])}]
    del script["critic"]
    on, archive = both(tmp_path, script)
    assert on.out["kill_stage"] == "fact_check"
    [candidate] = only_generation(archive)["candidates"]
    assert candidate["stages"]["fact_check"] == {"calls": [{"call": 3, "outcome": "returned"}],
                                                 "outcome": "kill", "disposition": "provider_called"}
    assert "critic" not in candidate["stages"]
    # mark_stage records the bare kill first; record_kill then binds its exact reason.
    reason = [o for o in archive.stage_outcomes if o["outcome"] == "kill" and o["reason_artifact"]][0]["reason_artifact"]
    assert FIXTURE["factual_failure"] in archive.artifact(reason).decode()
    assert archive.terminals[0]["kill_stage"] == "fact_check" and archive.terminals[0]["accepted"] is False


def test_safety_rejection_stops_before_paid_factual_and_critic_calls(journey_env, tmp_path):
    on, archive = both(tmp_path, {"writer": accepted_script()["writer"], "safety": [{"text": "YES"}]})
    assert on.out["kill_stage"] == "safety"
    assert [c.stage for c in archive.calls] == ["writer", "safety"]
    [candidate] = only_generation(archive)["candidates"]
    assert candidate["stages"]["safety"]["outcome"] == "kill"


def test_terminal_critic_rejection_retains_the_original_verdict_body(journey_env, tmp_path):
    script = accepted_script()
    script["critic"] = [{"text": critic_json("KILL", kill_reason=FIXTURE["critic_kill_reason"])}]
    on, archive = both(tmp_path, script)
    assert on.out["kill_stage"] == "critic"
    critic_call = archive.calls[3]
    body = archive.artifact(critic_call.attempts[0].response.artifact)
    assert FIXTURE["critic_kill_reason"] in json.loads(body)["candidates"][0]["content"]["parts"][0]["text"]
    [candidate] = only_generation(archive)["candidates"]
    assert candidate["stages"]["critic"]["outcome"] == "kill"


def test_malformed_and_missing_responses_keep_every_attempt(journey_env, tmp_path):
    on, archive = both(tmp_path, {"writer": [{"text": FIXTURE["malformed_writer_text"]}, {"text": None}]})
    assert on.out["kill_stage"] == "writer" and "invalid JSON" in on.out["kill_reason"]
    assert [c.stage for c in archive.calls] == ["writer", "writer"]
    assert all(result(c)["archival"] == "complete" and result(c)["outcome"] == "returned" for c in archive.calls)
    empty = json.loads(archive.artifact(archive.calls[1].attempts[0].response.artifact))
    assert empty["content"] == []  # Returned-but-empty is retained, not converted to a verdict.
    assert only_generation(archive)["candidates"] == []
    assert archive.terminals[0]["kill_stage"] == "writer"


def test_incomplete_safety_response_is_a_failed_check_not_a_pass(journey_env, tmp_path):
    script = {"writer": accepted_script()["writer"], "safety": [{"text": "NO", "finish": "MAX_TOKENS"}]}
    on, archive = both(tmp_path, script)
    assert on.out["kill_stage"] == "safety"
    response = json.loads(archive.artifact(archive.calls[1].attempts[0].response.artifact))
    assert response["candidates"][0]["finishReason"] == "MAX_TOKENS"


def test_unknown_check_outcome_after_send_retains_original_unknown_labels(journey_env, tmp_path):
    script = accepted_script()
    script["fact_check"] = [{"raise": "timeout"}] * 3
    del script["critic"]
    on, archive = both(tmp_path, script)
    assert on.out["kill_stage"] == "pipeline_error"
    fact_calls = [c for c in archive.calls if c.stage == "fact_check"]
    assert len(fact_calls) == 3 and all(result(c)["provider_outcome"] == "unknown" for c in fact_calls)
    assert all(c.binding["candidate_text_sha256"] == text_hash(TWEET) for c in fact_calls)
    assert archive.terminals[0]["kill_stage"] == "pipeline_error" and archive.status == "complete"


def test_optional_revise_mode_never_lets_revised_text_inherit_earlier_verdicts(journey_env, tmp_path, monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    revised = FIXTURE["revised_tweet"]
    script = {"writer": [{"text": writer_json(TWEET)}, {"text": writer_json(revised)}],
              "safety": [{"text": "NO"}, {"text": "NO"}],
              "fact_check": [{"text": fact_json(True)}, {"text": fact_json(True, FIXTURE["revised_claims"])}],
              "critic": [{"text": critic_json("REVISE", revise_instruction=FIXTURE["critic_revise_instruction"])},
                         {"text": critic_json("PASS")}]}
    on, archive = both(tmp_path, script)
    assert on.draft["text"] == revised
    generation = only_generation(archive)
    first, second = generation["candidates"]
    assert (first["attempt"], second["attempt"]) == (1, 2)
    assert first["candidate_text_sha256"] == text_hash(TWEET) and second["candidate_text_sha256"] == text_hash(revised)
    assert first["stages"]["critic"]["outcome"] is None  # REVISE is not a pass for the first text.
    assert second["stages"]["critic"]["outcome"] == "pass" and second["stages"]["fact_check"]["outcome"] == "pass"
    assert {c["call"] for s in first["stages"].values() for c in s["calls"]}.isdisjoint(
        {c["call"] for s in second["stages"].values() for c in s["calls"]})
    revision = [w for w in generation["writer_calls"] if w["phase"] == "revision"]
    assert revision == [{"call": 5, "outcome": "returned", "phase": "revision", "revises": text_hash(TWEET)}]
    assert generation["terminal"]["draft_text_sha256"] == text_hash(revised)


def test_local_precheck_decision_records_no_invented_paid_response(journey_env, tmp_path):
    on, archive = both(tmp_path, {"writer": [{"text": writer_json(FIXTURE["local_precheck_tweet"])}]})
    assert on.out["kill_stage"] == "fact_check" and [c.stage for c in archive.calls] == ["writer"]
    [candidate] = only_generation(archive)["candidates"]
    assert candidate["stages"] == {"fact_check": {"calls": [], "outcome": "kill",
                                                  "disposition": "decided_without_provider_call"}}


def test_disabled_critic_stage_is_absent_not_passed(journey_env, tmp_path, monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    script = accepted_script()
    del script["critic"]
    on, archive = both(tmp_path, script)
    assert on.draft is not None and [c.stage for c in archive.calls] == ["writer", "safety", "fact_check"]
    assert "critic" not in only_generation(archive)["candidates"][0]["stages"]


def test_threaded_writer_slate_is_an_unsupported_route_refused_before_any_send(journey_env, tmp_path, monkeypatch):
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "2")
    on = run_journey({"writer": [{"text": writer_json(TWEET)}] * 2}, root=private_root(tmp_path))
    assert on.draft is None and on.out["kill_stage"] == "pipeline_error"
    assert on.providers.physical == []
    archive = replay.load_archive(on.archive)
    assert archive.calls == () and archive.refusals and archive.refusals[0]["type"] == "foreign_call_refused"


@pytest.mark.parametrize("journey", ["accepted", "factual"])
def test_archives_do_not_leak_into_stdout_or_retained_state(journey_env, tmp_path, journey):
    script = accepted_script()
    if journey == "factual":
        script["fact_check"] = [{"text": fact_json(False, failures=[FIXTURE["factual_failure"]])}]
        del script["critic"]
    on = run_journey(script, root=private_root(tmp_path))
    archive = replay.load_archive(on.archive)
    dumped = json.dumps(on.state, default=str) + on.stdout + json.dumps(on.out, default=str)
    # Existing code already hashes candidate text; archive-private request/response
    # identities and locations must not appear anywhere outside the archive.
    private = {call.logical_request.artifact for call in archive.calls}
    private |= {a.request.artifact for call in archive.calls for a in call.attempts}
    private |= {a.response.artifact for call in archive.calls for a in call.attempts if a.response}
    private |= {item["memory_artifact"] for item in archive.inputs} | {item["bundle_artifact"] for item in archive.inputs}
    assert private and all(digest not in dumped for digest in private)
    assert archive.scope_id not in dumped and str(on.archive) not in dumped
    prompt = json.loads(archive.artifact(archive.calls[0].logical_request.artifact))["kwargs"]["messages"][0]["content"]
    assert prompt[:120] not in on.stdout
