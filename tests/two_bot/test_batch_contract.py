"""Bounded offline batches with independently supplied input/result identities."""

from copy import deepcopy
import hashlib
import json
from unittest.mock import MagicMock

import pytest

from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.two_bot import batch_contract as batch, writer
from tests.two_bot.conftest import _bundle, _memory


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def inputs(monkeypatch):
    monkeypatch.setattr(writer, "WRITER_PROVIDER", "anthropic")
    monkeypatch.setattr(writer, "WRITER_MODEL", "claude-synthetic")
    bundle, memory = _bundle(), _memory()
    policy = current_editorial_policy()
    policy["flags"]["writer_samples"] = 1
    return {
        "bundle": bundle,
        "memory": memory,
        "bundle_sha256": fingerprint(bundle.to_dict()),
        "memory_sha256": fingerprint(memory.to_dict()),
        "policy": policy,
        "job_id": "job-fixture",
        "publication_epoch": "paused-fixture",
        "created_at": "2026-09-29T12:00:00Z",
        "useful_until": "2026-09-30T12:00:00Z",
        "minimum_window_seconds": 3600,
    }


def context(plan):
    data = json.loads(plan)
    return {
        key: data[key]
        for key in ("bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch")
    }


def result(plan, index=0, **changes):
    data = json.loads(plan)
    output = {
        "tweet": "Synthetic station: 42 C.",
        "kill_reason": None,
        "angle_chosen": "plain_number",
        "era_anchor_used": None,
        "peer_comparison_used": None,
        "reasoning": "fixture",
    }
    msg = {
        "type": "message",
        "role": "assistant",
        "id": "msg_fixture",
        "model": data["policy"]["models"]["writer"],
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": json.dumps(output)}],
        "usage": {
            "input_tokens": 17,
            "output_tokens": 9,
            "cache_read_input_tokens": 120,
            "cache_creation": {"ephemeral_1h_input_tokens": 50},
        },
    }
    msg.update(changes)
    return {
        "custom_id": data["requests"][index]["custom_id"],
        "result": {"type": "succeeded", "message": msg},
    }


def raw_rows(rows):
    return b"\n".join(json.dumps(row).encode() for row in rows)


def collect(plan, rows, **changes):
    kwargs = {
        "expected_plan_sha256": digest(plan),
        "current_context": context(plan),
        "now": "2026-09-29T13:00:00Z",
    }
    kwargs.update(changes)
    return batch.collect_batch_results(plan, raw_rows(rows), **kwargs)


def test_single_sample_immutable_request_matches_shared_sync_contract(inputs):
    before = deepcopy(inputs)
    plan = batch.prepare_batch_plan(**inputs)
    assert isinstance(plan, bytes) and plan == batch.prepare_batch_plan(**inputs)
    data = json.loads(plan)
    assert data["samples"] == 1 and data["experiment_id"] is None
    requests = batch.batch_requests(plan, expected_plan_sha256=digest(plan))
    assert len(requests) == 1
    assert requests[0]["params"] == writer.anthropic_writer_request(
        writer.build_writer_user_prompt(inputs["bundle"], inputs["memory"])
    )
    assert len(requests[0]["custom_id"]) == 63
    requests[0]["params"]["system"].clear()
    assert batch.batch_requests(plan, expected_plan_sha256=digest(plan))[0]["params"]["system"]
    assert inputs == before


@pytest.mark.parametrize(
    "change", ["evidence", "memory", "policy", "model", "prompt", "job", "epoch", "deadline"]
)
def test_every_material_change_gets_a_distinct_plan_and_custom_id(inputs, monkeypatch, change):
    before = batch.prepare_batch_plan(**inputs)
    if change == "evidence":
        inputs["bundle"] = _bundle(frp=362.0)
        inputs["bundle_sha256"] = fingerprint(inputs["bundle"].to_dict())
    elif change == "memory":
        inputs["memory"].used_framings.append("fixture-framing")
        inputs["memory_sha256"] = fingerprint(inputs["memory"].to_dict())
    elif change == "policy":
        inputs["policy"]["source_sha256"] = "a" * 64
    elif change == "model":
        monkeypatch.setattr(writer, "WRITER_MODEL", "claude-new-fixture")
        inputs["policy"]["models"]["writer"] = "claude-new-fixture"
    elif change == "prompt":
        monkeypatch.setattr(writer, "WRITER_SYSTEM_PROMPT", "new synthetic system")
    elif change == "job":
        inputs["job_id"] = "another-job"
    elif change == "epoch":
        inputs["publication_epoch"] = "next-epoch"
    else:
        inputs["useful_until"] = "2026-09-30T13:00:00Z"
    after = batch.prepare_batch_plan(**inputs)
    assert digest(after) != digest(before)
    assert (
        json.loads(after)["requests"][0]["custom_id"]
        != json.loads(before)["requests"][0]["custom_id"]
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("bundle_sha256", "b" * 64),
        ("memory_sha256", "b" * 64),
        ("urgent", True),
        ("urgent", 0),
        ("samples", True),
        ("samples", 0),
        ("samples", 4),
        ("samples", 3),
        ("job_id", ""),
        ("publication_epoch", None),
        ("created_at", "2026-09-29"),
        ("created_at", "2026-09-29T12:00:00"),
        ("useful_until", "2026-09-29T13:00:00Z"),
        ("useful_until", "2026-09-29T12:00:00Z"),
        ("useful_until", "2026-10-07T12:00:00Z"),
        ("minimum_window_seconds", 0),
        ("minimum_window_seconds", True),
        ("minimum_window_seconds", 86401),
        ("experiment_id", "x" * 129),
        ("policy", {}),
    ],
)
def test_invalid_or_urgent_plans_are_refused(inputs, key, value):
    inputs[key] = value
    with pytest.raises(batch.BatchContractError):
        batch.prepare_batch_plan(**inputs)


@pytest.mark.parametrize(
    "change",
    [
        "unsupported",
        "policy_provider",
        "policy_model",
        "policy_samples",
        "evidence",
        "scope",
        "oversized",
    ],
)
def test_planner_refuses_invalid_routing_evidence_and_size(inputs, monkeypatch, change):
    if change == "unsupported":
        monkeypatch.setattr(writer, "WRITER_PROVIDER", "google")
    elif change == "policy_provider":
        inputs["policy"]["models"]["writer_provider"] = "google"
    elif change == "policy_model":
        inputs["policy"]["models"]["writer"] = "claude-other"
    elif change == "policy_samples":
        inputs["policy"]["flags"]["writer_samples"] = 2
    else:
        if change == "evidence":
            inputs["bundle"].raw_signal_dump = {}
        elif change == "scope":
            inputs["bundle"].signal_kind = "usgs_earthquake"
        else:
            inputs["bundle"].raw_signal_dump["large"] = "x" * batch.MAX_PLAN_BYTES
        inputs["bundle_sha256"] = fingerprint(inputs["bundle"].to_dict())
    with pytest.raises(batch.BatchContractError):
        batch.prepare_batch_plan(**inputs)


def test_experimental_slate_matches_reordered_results_and_never_approves(inputs):
    inputs.update(samples=3, experiment_id="private-trial")
    inputs["policy"]["flags"]["writer_samples"] = 3
    plan = batch.prepare_batch_plan(**inputs)
    expected_ids = [r["custom_id"] for r in json.loads(plan)["requests"]]
    assert len(set(expected_ids)) == 3
    output = collect(plan, [result(plan, i) for i in (2, 0, 1)])
    assert output["complete"] and [r["custom_id"] for r in output["rows"]] == expected_ids
    assert all(r["eligible_for_checks"] and not r["publication_approved"] for r in output["rows"])
    assert not output["required_checks_completed"] and not output["publication_approved"]
    assert output["cost_usd"] is None and output["accounting_complete"] is False


@pytest.mark.parametrize(
    "change", ["params", "custom_id", "policy", "extra", "duplicate_key", "whitespace", "oversized"]
)
def test_changed_or_ambiguous_plan_never_matches_independent_root(inputs, change):
    plan = batch.prepare_batch_plan(**inputs)
    data = json.loads(plan)
    if change == "params":
        data["requests"][0]["params"]["max_tokens"] = 999
    elif change == "custom_id":
        data["requests"][0]["custom_id"] = "forged"
    elif change == "policy":
        data["policy"]["source_sha256"] = "b" * 64
    else:
        data["new_field"] = True
    changed = json.dumps(data).encode()
    if change == "duplicate_key":
        changed = b'{"schema_version":1,' + plan[1:]
    elif change == "whitespace":
        changed = plan + b" "
    elif change == "oversized":
        changed = b" " * (batch.MAX_PLAN_BYTES + 1)
    with pytest.raises(batch.BatchContractError):
        batch.batch_requests(changed, expected_plan_sha256=digest(plan))


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "unknown",
        "bad_outer",
        "extra",
        "bad_type",
        "duplicate_json_key",
        "nan",
        "oversized",
    ],
)
def test_invalid_result_protocol_is_refused_without_echoing_private_text(inputs, change):
    inputs.update(samples=2, experiment_id="test")
    inputs["policy"]["flags"]["writer_samples"] = 2
    plan = batch.prepare_batch_plan(**inputs)
    r = result(plan)
    if change == "duplicate":
        raw = raw_rows([r, r])
    elif change == "unknown":
        r["custom_id"] = "unknown"
        raw = raw_rows([r])
    elif change == "bad_outer":
        raw = b'"private unpublished payload"'
    elif change == "duplicate_json_key":
        raw = b'{"custom_id":"a","custom_id":"b","result":{}}'
    elif change == "nan":
        raw = b'{"custom_id": NaN}'
    elif change == "oversized":
        raw = b"x" * (batch.MAX_RESULTS_BYTES + 1)
    else:
        r["result"]["private_extra"] = "private unpublished payload"
        if change == "bad_type":
            r["result"]["type"] = "made_up"
        raw = raw_rows([r])
    with pytest.raises(batch.BatchContractError) as error:
        batch.collect_batch_results(
            plan,
            raw,
            expected_plan_sha256=digest(plan),
            current_context=context(plan),
            now="2026-09-29T13:00:00Z",
        )
    assert "private unpublished payload" not in str(error.value)


@pytest.mark.parametrize(
    "change,reason",
    [
        ("refusal", "incomplete_or_refused_message"),
        ("truncated", "incomplete_or_refused_message"),
        ("content", "unsupported_content"),
        ("malformed", "invalid_writer_output"),
        ("overlong", "overlong_output"),
        ("kill", "writer_kill"),
        ("model", "message_identity_mismatch"),
        ("id", "invalid_message_id"),
        ("role", "message_identity_mismatch"),
    ],
)
def test_unusable_writer_results_retain_usage_and_do_not_retry(inputs, monkeypatch, change, reason):
    plan = batch.prepare_batch_plan(**inputs)
    r = result(plan)
    msg = r["result"]["message"]
    if change in ("refusal", "truncated"):
        msg["stop_reason"] = "refusal" if change == "refusal" else "max_tokens"
    elif change == "content":
        msg["content"].append({"type": "tool_use", "input": {}})
    elif change == "model":
        msg["model"] = "claude-other"
    elif change == "id":
        msg["id"] = None
    elif change == "role":
        msg["role"] = "user"
    elif change == "malformed":
        msg["content"][0]["text"] = "not json"
    else:
        text = json.loads(msg["content"][0]["text"])
        if change == "overlong":
            text["tweet"] = "x" * 281
        else:
            text.update(tweet=None, kill_reason="no supported angle")
        msg["content"][0]["text"] = json.dumps(text)
    call = MagicMock(side_effect=AssertionError("No provider in collector"))
    monkeypatch.setattr(writer, "_call_writer_provider", call)
    row = collect(plan, [r])["rows"][0]
    assert reason in row["blocked_reasons"] and row["candidate"] is None
    assert row["usage"] == msg["usage"] and row["usage_status"] == "reported_unpriced"
    assert row["cost_usd"] is None and not row["eligible_for_checks"]
    call.assert_not_called()


@pytest.mark.parametrize("kind", ["errored", "canceled", "expired"])
def test_terminal_non_success_is_explicit_not_zero_cost(inputs, kind):
    plan = batch.prepare_batch_plan(**inputs)
    r = result(plan)
    r["result"] = {"type": kind}
    if kind == "errored":
        r["result"]["error"] = {
            "type": "error",
            "error": {"type": "api_error", "message": "private detail"},
        }
    row = collect(plan, [r])["rows"][0]
    assert row["provider_status"] == kind and row["usage_status"] == "missing"
    assert row["cost_usd"] is None and row["candidate"] is None
    assert "private detail" not in str(row)


@pytest.mark.parametrize(
    "change",
    ["bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch", "expiry", "before"],
)
def test_stale_and_expired_results_keep_usage_but_no_candidate(inputs, change):
    plan = batch.prepare_batch_plan(**inputs)
    current = context(plan)
    now = "2026-09-29T13:00:00Z"
    if change == "expiry":
        now = inputs["useful_until"]
    elif change == "before":
        now = "2026-09-29T11:59:59Z"
    else:
        current[change] = "next-epoch" if change == "publication_epoch" else "b" * 64
    output = collect(plan, [result(plan)], current_context=current, now=now)
    assert output["context_blocked_reasons"]
    assert output["rows"][0]["usage_status"] == "reported_unpriced"
    assert not output["rows"][0]["eligible_for_checks"] and output["rows"][0]["candidate"] is None


def test_missing_results_remain_visible(inputs):
    plan = batch.prepare_batch_plan(**inputs)
    output = collect(plan, [])
    assert not output["complete"] and len(output["missing_custom_ids"]) == 1
    assert output["rows"] == [] and output["cost_usd"] is None


def test_incomplete_slate_cannot_silently_select_only_the_first_result(inputs):
    inputs.update(samples=2, experiment_id="slate-fixture")
    inputs["policy"]["flags"]["writer_samples"] = 2
    plan = batch.prepare_batch_plan(**inputs)
    output = collect(plan, [result(plan)])
    assert output["context_blocked_reasons"] == ["incomplete_results"]
    row = output["rows"][0]
    assert not row["eligible_for_checks"] and row["candidate"] is None
    assert row["usage_status"] == "reported_unpriced"


def test_planning_and_collection_have_no_external_side_effects(inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Pure batch contract attempted external I/O")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("pathlib.Path.read_bytes", forbidden)
    monkeypatch.setattr("pathlib.Path.read_text", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr(writer, "_call_writer_provider", forbidden)
    plan = batch.prepare_batch_plan(**inputs)
    assert collect(plan, [result(plan)])["rows"][0]["eligible_for_checks"]


@pytest.mark.parametrize(
    "usage,status",
    [
        (None, "missing"),
        ({}, "invalid_unpriced"),
        ({"input_tokens": True, "output_tokens": 2}, "invalid_unpriced"),
    ],
)
def test_unknown_or_invalid_usage_is_not_silently_free(inputs, usage, status):
    plan = batch.prepare_batch_plan(**inputs)
    row = collect(plan, [result(plan, usage=usage)])["rows"][0]
    assert row["usage_status"] == status and row["cost_usd"] is None
    assert row["usage"] == usage
