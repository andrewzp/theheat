"""Actual required-check parsers and SDK HTTP fixtures; no paid requests."""

from contextlib import closing
from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
import sqlite3

import httpx
import pytest

from src.commands import check_journal as checks, check_execution_journal as observations
from src.commands.schema import canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.two_bot import check_executor as executor, check_requests, check_transport
from src.two_bot import critic, fact_check
from src.voice import safety
from tests import test_batch_result_journal as batches
from tests import test_batch_worker_journal as workers

store, inputs, NOW = batches.store, batches.inputs, batches.NOW
TEXT = "A satellite detected a 361 MW thermal signal in Mali."


@pytest.fixture
def case(store, inputs, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    inputs["policy"] = current_editorial_policy()
    pair, grant = batches.started(store, inputs)
    rows = batches.rows(pair)
    candidate = json.loads(rows[0]["result"]["message"]["content"][0]["text"])
    candidate["tweet"] = TEXT
    rows[0]["result"]["message"]["content"][0]["text"] = json.dumps(candidate)
    receipt = batches.retain(store, grant, batches.contract.raw_rows(rows))
    payload = dict(
        job_id=pair[1]["job_id"],
        owner="worker-one",
        fence=1,
        receipt_id=receipt["receipt_id"],
        current_context=batches.contract.context(pair[0]),
        custom_id=json.loads(pair[0])["requests"][0]["custom_id"],
        bundle=inputs["bundle"].to_dict(),
        memory=inputs["memory"].to_dict(),
        checker_state=deepcopy(store.read()[1]),
    )
    result = store.candidate_checks("intake", payload, now=NOW)
    return dict(store=store, identity=result["check_set_id"], payload=payload)


def saved(case):
    return case["store"].check_execution("read", {"check_set_id": case["identity"]}, now=NOW)


def reserve(case, stage):
    request = canonical_json(check_requests.prepare_request(saved(case)["packet"], stage)).encode()
    return dict(
        intent_id="executor-" + stage,
        job_id=case["payload"]["job_id"],
        request_sha256=hashlib.sha256(request).hexdigest(),
        provider="google",
        role=stage,
        model=saved(case)["packet"]["policy"]["models"][stage],
        estimate_sha256="e" * 64,
        reserve_micro_usd=5,
    )


def run(case, stage=None, **changes):
    args = dict(
        current_context=case["payload"]["current_context"],
        checker_state=case["payload"]["checker_state"],
        owner="worker-one",
        clock=lambda: NOW,
        enabled=True,
        reservation=None if stage in (None, "deterministic") else reserve(case, stage),
    )
    args.update(changes)
    return executor.execute_check_once(case["store"], case["identity"], **args)


def envelope(text, **changes):
    data = dict(
        candidates=[
            dict(content=dict(role="model", parts=[dict(text=text)]), finishReason="STOP", index=0)
        ],
        usageMetadata=dict(promptTokenCount=19, candidatesTokenCount=7, totalTokenCount=26),
    )
    data.update(changes)
    return json.dumps(data).encode()


FACT_PASS = json.dumps(
    dict(passed=True, extracted_claims=[dict(text=TEXT, kind="comparison")], failures=[])
)
CRITIC_PASS = json.dumps(
    dict(verdict="PASS", kill_reason=None, revise_instruction=None, selected_index=None)
)


def provider(monkeypatch, replies):
    sent, clients = [], []

    def handle(request):
        sent.append(request)
        reply = replies[min(len(sent) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        status, raw = reply if isinstance(reply, tuple) else (200, reply)
        return httpx.Response(status, stream=httpx.ByteStream(raw), request=request)

    def factory(**kwargs):
        client = check_transport.GoogleCheckTransport(
            **kwargs, http_transport=httpx.MockTransport(handle)
        )
        clients.append(client)
        return client

    monkeypatch.setattr(executor, "GoogleCheckTransport", factory)
    return sent, clients


def test_disabled_performs_zero_io(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("I/O while disabled")

    monkeypatch.setattr(executor, "current_editorial_policy", forbidden)
    monkeypatch.setattr(executor, "GoogleCheckTransport", forbidden)
    result = executor.execute_check_once(
        None, "invalid", current_context=None, checker_state=None, owner="", clock=forbidden
    )
    assert result["outcome"] == "disabled" and not result["publication_approved"]


def test_all_real_checks_run_in_order_without_draft_approval_or_cost_settlement(case, monkeypatch):
    before = case["store"].read()
    sent, clients = provider(
        monkeypatch, [envelope("NO"), envelope(FACT_PASS), envelope(CRITIC_PASS)]
    )
    for stage in checks.STAGES:
        result = run(case, stage)
        assert result["outcome"] == "completed", result
        assert result["checks"]["stages"][stage] == "passed", result
        assert not result["publication_approved"] and result["cost_usd"] is None
    assert result["required_checks_completed"]
    assert len(sent) == 3 and all(c._http.is_closed for c in clients)
    assert case["store"].read() == before
    money = case["store"].spending("status", {}, now=NOW)
    assert money["intent_count"] == 4 and money["totals"]["held_micro_usd"] == 75
    for stage in checks.STAGES:
        attempt = saved(case)["attempts"][stage]
        assert attempt["observation"]["complete"]
        raw = case["store"].read_artifact(attempt["observation"]["raw_sha256"])
        assert raw
    assert run(case)["outcome"] == "checks_completed" and len(sent) == 3


def test_exact_shared_requests_and_explicit_batch_only_output_bound(case):
    packet = saved(case)["packet"]
    bundle, memory, state = check_requests.retained_inputs(packet)
    pending = critic._collect_pending_today(
        state, exclude_event_id=bundle.event_id, today=packet["check_date"]
    )
    expected = {
        "safety": safety.prepare_request(TEXT),
        "fact_check": fact_check.prepare_request(TEXT, bundle),
        "critic": critic.prepare_request(TEXT, bundle, pending, memory.shipped_tweet_texts),
    }
    for stage, original in expected.items():
        batch = check_requests.prepare_request(packet, stage)
        config = batch.pop("config")
        assert config.pop("max_output_tokens") == 4096
        assert config == original.pop("config", {})
        assert batch == original


@pytest.mark.parametrize(
    "reply,disposition",
    [
        (envelope("YES"), "rejected"),
        (envelope("Probably safe"), "error"),
        ((429, b'{"error":{"code":429,"message":"private diagnostic"}}'), "unavailable"),
        ((500, b'{"error":{"code":500,"message":"private diagnostic"}}'), "unavailable"),
        ((307, b"{}"), "unavailable"),
        (b"not json", "error"),
        (httpx.ReadTimeout("private diagnostic"), "unavailable"),
        (envelope("NO", candidates=[]), "error"),
    ],
    ids=[
        "reject",
        "malformed",
        "rate-limit",
        "server",
        "redirect",
        "bad-json",
        "timeout",
        "missing-candidate",
    ],
)
def test_failures_never_retry_or_advance_and_keep_unknown_spend(
    case, monkeypatch, reply, disposition
):
    sent, clients = provider(monkeypatch, [reply])
    assert run(case)["checks"]["stages"]["deterministic"] == "passed"
    result = run(case, "safety")
    assert result["checks"]["stages"]["safety"] == disposition, result
    assert len(sent) == 1 and all(c._http.is_closed for c in clients)
    assert "private diagnostic" not in str(result)
    for _ in range(3):
        assert run(case, "safety")["outcome"] == "blocked"
    assert (
        len(sent) == 1
        and case["store"].spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 65
    )


def test_retained_response_recovers_after_parser_crash_without_second_post(case, monkeypatch):
    sent, _ = provider(monkeypatch, [envelope("NO")])
    run(case)
    interpret = check_requests.interpret_observation
    monkeypatch.setattr(
        check_requests,
        "interpret_observation",
        lambda *a: (_ for _ in ()).throw(RuntimeError("crash")),
    )
    assert run(case, "safety")["outcome"] == "reconciliation_required"
    assert saved(case)["attempts"]["safety"]["observation"]["complete"]
    monkeypatch.setattr(check_requests, "interpret_observation", interpret)
    assert run(case, "safety")["checks"]["stages"]["safety"] == "passed"
    assert len(sent) == 1


@pytest.mark.parametrize("action,expected_posts", [("begin", 0), ("observe", 1), ("complete", 1)])
def test_lost_commit_ack_never_rebuys(case, monkeypatch, action, expected_posts):
    sent, _ = provider(monkeypatch, [envelope("NO")])
    run(case)
    method = "check_execution" if action == "observe" else "candidate_checks"
    original = getattr(case["store"], method)

    def lost(operation, *args, **kwargs):
        result = original(operation, *args, **kwargs)
        if operation == action:
            raise RuntimeError("lost acknowledgment")
        return result

    monkeypatch.setattr(case["store"], method, lost)
    assert run(case, "safety")["outcome"] == "reconciliation_required"
    monkeypatch.setattr(case["store"], method, original)
    recovered = run(case, "safety")
    assert len(sent) == expected_posts
    if action == "begin":
        assert recovered["reason"] == "check_response_not_retained"
    elif action == "observe":
        assert recovered["checks"]["stages"]["safety"] == "passed"
    else:
        # It advances to fact_check only with its exact independent reservation.
        assert recovered["outcome"] == "reconciliation_required"


@pytest.mark.parametrize("change", ["state", "evidence", "policy", "owner", "day", "deadline"])
def test_current_context_changes_block_without_post(case, monkeypatch, change):
    sent, _ = provider(monkeypatch, [envelope("NO")])
    run(case)
    kw = {}
    if change == "state":
        kw["checker_state"] = {"memory": {}}
    elif change == "evidence":
        kw["current_context"] = dict(case["payload"]["current_context"], bundle_sha256="a" * 64)
    elif change == "policy":
        monkeypatch.setattr(safety, "GEMINI_SAFETY_MODEL", "different-model")
    elif change == "owner":
        kw["owner"] = "different-owner"
    elif change == "day":
        kw["clock"] = lambda: "2026-09-30T00:00:01Z"
    else:
        kw["clock"] = lambda: "2026-10-01T00:00:01Z"
    result = run(case, **kw)
    assert not result["required_checks_completed"] and not sent


def test_reservation_failure_and_missing_key_do_not_dispatch(case, monkeypatch):
    sent, clients = provider(monkeypatch, [envelope("NO")])
    run(case)
    assert run(case, "safety", reservation=None)["outcome"] == "reconciliation_required"
    assert not sent and all(c._http.is_closed for c in clients)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    assert not run(case)["required_checks_completed"] and not sent


def test_local_gates_reject_before_paid_checks(case, monkeypatch):
    packet = saved(case)["packet"]
    original = deepcopy(packet)
    for text in [
        TEXT + "!",
        "Mali's national average is 42 C.",
        "A satellite detected a 361 MW fire signal in Mali.",
    ]:
        packet["candidate"]["tweet"] = text
        # Directly exercise real deterministic rules with synthetic variants;
        # immutable production candidate identities are never edited here.
        result = check_requests.deterministic_result(packet)
        assert not result["passed"], result
    assert check_requests.deterministic_result(original)["passed"]


def test_scientific_rejection_keeps_material_inventory_gate(case):
    packet = saved(case)["packet"]
    raw = envelope(
        json.dumps(
            dict(
                passed=True, extracted_claims=[dict(text="Mali", kind="named_entity")], failures=[]
            )
        )
    )
    outcome = check_requests.interpret_observation(
        packet, "fact_check", dict(complete=True, http_status=200), raw
    )
    assert outcome["verdict"] == "reject"
    assert any("361" in reason for reason in outcome["result"]["failures"])


def test_observation_idempotence_conflict_and_sql_immutability(case):
    run(case)
    observation = saved(case)["attempts"]["deterministic"]["observation"]
    raw = case["store"].read_artifact(observation["raw_sha256"])
    assert case["store"].check_execution("observe", observation, raw=raw, now=NOW)["reused"]
    changed_raw = b'{"different":"retained response"}'
    with pytest.raises(checks.CheckJournalError, match="conflicting_check_observation"):
        case["store"].check_execution(
            "observe",
            dict(observation, raw_sha256=hashlib.sha256(changed_raw).hexdigest()),
            raw=changed_raw,
            now=NOW,
        )
    with pytest.raises(checks.CheckJournalError, match="inconsistent_check_observation"):
        case["store"].check_execution(
            "observe", dict(observation, complete=False), raw=raw, now=NOW
        )
    with closing(case["store"]._connect()) as conn:
        for sql in [
            "DELETE FROM check_observations",
            "UPDATE check_observations SET recorded_at=recorded_at",
            "INSERT OR REPLACE INTO check_observations SELECT * FROM check_observations",
        ]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(sql)


def test_roundtrip_drift_refused(case):
    packet = saved(case)["packet"]
    del packet["memory"]["used_framings"]
    with pytest.raises(ValueError, match="roundtrip"):
        check_requests.retained_inputs(packet)


@pytest.mark.parametrize(
    "kind", ["truncated", "multiple", "tool", "empty", "thought-only", "revise"]
)
def test_incomplete_or_unsupported_envelopes_are_never_passes(case, kind):
    data = json.loads(envelope("NO"))
    if kind == "truncated":
        data["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif kind == "multiple":
        data["candidates"] *= 2
    elif kind == "tool":
        data["candidates"][0]["content"]["parts"] = [dict(functionCall=dict(name="bypass"))]
    elif kind == "empty":
        data["candidates"][0]["content"]["parts"] = []
    elif kind == "thought-only":
        data["candidates"][0]["content"]["parts"][0]["thought"] = True
    else:
        data = json.loads(
            envelope(
                json.dumps(
                    dict(
                        verdict="REVISE",
                        kill_reason=None,
                        revise_instruction="Rewrite",
                        selected_index=None,
                    )
                )
            )
        )
    result = check_requests.interpret_observation(
        saved(case)["packet"],
        "critic" if kind == "revise" else "safety",
        dict(complete=True, http_status=200),
        json.dumps(data).encode(),
    )
    assert result["execution_status"] == "error" and result["verdict"] is None
    assert result["usage"]["promptTokenCount"] == 19


def test_actual_sdk_request_is_bounded_and_ignores_ambient_routing(monkeypatch):
    seen = []
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", "https://untrusted.invalid")

    def handle(request):
        seen.append(request)
        return httpx.Response(200, request=request, stream=httpx.ByteStream(envelope("NO")))

    client = check_transport.GoogleCheckTransport(
        api_key="offline-key", model="gemini-test", http_transport=httpx.MockTransport(handle)
    )
    try:
        got = client.execute(
            dict(model="gemini-test", contents="exact input", config=dict(max_output_tokens=4096))
        )
        assert got.complete and got.raw == envelope("NO")
        assert (
            str(seen[0].url)
            == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
        )
        assert seen[0].extensions["timeout"]["read"] == 15
        assert json.loads(seen[0].content)["generationConfig"]["maxOutputTokens"] == 4096
        with pytest.raises(ValueError, match="already_used"):
            client.execute({})
        assert len(seen) == 1
    finally:
        client.close()
    assert client._http.is_closed


def test_transport_size_bound_keeps_prefix_and_closes():
    raw = b"x" * (observations.MAX_RESPONSE_BYTES + 1)
    client = check_transport.GoogleCheckTransport(
        api_key="offline-key",
        model="gemini-test",
        http_transport=httpx.MockTransport(
            lambda r: httpx.Response(200, request=r, stream=httpx.ByteStream(raw))
        ),
    )
    try:
        result = client.execute(dict(model="gemini-test", contents="fixture"))
        assert not result.complete and result.reason == "size_exceeded"
        assert len(result.raw) == observations.MAX_RESPONSE_BYTES
    finally:
        client.close()


def test_transport_time_bound_retains_prefix(monkeypatch):
    times = iter([0, 91])
    monkeypatch.setattr(check_transport, "_monotonic", lambda: next(times))
    client = check_transport.GoogleCheckTransport(
        api_key="offline-key",
        model="gemini-test",
        http_transport=httpx.MockTransport(
            lambda r: httpx.Response(200, request=r, stream=httpx.ByteStream(envelope("NO")))
        ),
    )
    try:
        result = client.execute(dict(model="gemini-test", contents="fixture"))
        assert not result.complete and result.reason == "time_exceeded" and result.raw
    finally:
        client.close()


@pytest.mark.parametrize(
    "kind", ["feedback", "rating", "boolean-index", "duplicate-field", "nonfinite"]
)
def test_contradictory_provider_envelopes_cannot_pass(case, kind):
    data = json.loads(envelope("NO"))
    if kind == "feedback":
        data["promptFeedback"] = dict(blockReason="SAFETY")
    elif kind == "rating":
        data["candidates"][0]["safetyRatings"] = [dict(blocked=True)]
    elif kind == "boolean-index":
        data["candidates"][0]["index"] = False
    elif kind == "nonfinite":
        data["usageMetadata"]["promptTokenCount"] = float("nan")
    raw = json.dumps(data).encode()
    if kind == "duplicate-field":
        raw = raw[:-1] + b',"candidates":[]}'
    result = check_requests.interpret_observation(
        saved(case)["packet"], "safety", dict(complete=True, http_status=200), raw
    )
    assert result["execution_status"] == "error" and result["verdict"] is None


def test_compressed_response_is_not_decompressed_or_accepted():
    client = check_transport.GoogleCheckTransport(
        api_key="offline-key",
        model="gemini-test",
        http_transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                request=r,
                headers={"content-encoding": "gzip"},
                stream=httpx.ByteStream(b"compressed"),
            )
        ),
    )
    try:
        result = client.execute(dict(model="gemini-test", contents="fixture"))
        assert not result.complete and result.raw == b""
    finally:
        client.close()


def test_different_model_cannot_redirect_actual_sdk_request():
    seen = []
    client = check_transport.GoogleCheckTransport(
        api_key="offline-key",
        model="gemini-test",
        http_transport=httpx.MockTransport(lambda r: seen.append(r)),
    )
    try:
        assert not client.execute(dict(model="gemini-different", contents="fixture")).complete
        assert not seen
    finally:
        client.close()


def test_short_lease_prevents_purchase_even_when_previous_stage_passed(case, monkeypatch):
    sent, _ = provider(monkeypatch, [envelope("NO")])
    run(case)
    result = run(case, "safety", clock=lambda: workers.later(190))
    assert result["reason"] == "insufficient_check_window" and not sent
    assert "safety" not in saved(case)["attempts"]


def test_time_lost_during_grant_cannot_start_a_late_request(case, monkeypatch):
    sent, _ = provider(monkeypatch, [envelope("NO")])
    run(case)
    clock = [NOW]
    method = case["store"].candidate_checks

    def delayed(action, *a, **kw):
        result = method(action, *a, **kw)
        if action == "begin":
            clock[0] = workers.later(190)
        return result

    monkeypatch.setattr(case["store"], "candidate_checks", delayed)
    result = run(case, "safety", clock=lambda: clock[0])
    assert result["reason"] == "check_window_changed_before_execution" and not sent


def test_request_from_another_adapter_cannot_be_certified_by_recovery(case):
    packet = saved(case)["packet"]
    identity = dict(
        check_set_id=case["identity"],
        owner="worker-one",
        fence=1,
        current_context=case["payload"]["current_context"],
        checker_state_sha256=packet["checker_state_sha256"],
    )
    wrong = b'{"different":"check algorithm"}'
    grant = case["store"].candidate_checks(
        "begin", dict(identity, stage="deterministic", reservation=None), request=wrong, now=NOW
    )
    raw = canonical_json(dict(passed=True, failures=[], failure_count=0)).encode()
    case["store"].check_execution(
        "observe",
        dict(
            check_set_id=case["identity"],
            stage="deterministic",
            grant_id=grant["grant_id"],
            request_sha256=hashlib.sha256(wrong).hexdigest(),
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            http_status=None,
            complete=True,
            reason="local",
        ),
        raw=raw,
        now=NOW,
    )
    assert run(case)["reason"] == "check_request_not_exact"


def test_late_return_retains_usage_without_passing(case, monkeypatch):
    run(case)
    at = [NOW]

    def handle(request):
        at[0] = workers.later(301)
        return httpx.Response(200, request=request, stream=httpx.ByteStream(envelope("NO")))

    monkeypatch.setattr(
        executor,
        "GoogleCheckTransport",
        lambda **kw: check_transport.GoogleCheckTransport(
            **kw, http_transport=httpx.MockTransport(handle)
        ),
    )
    result = run(case, "safety", clock=lambda: at[0])
    assert result["checks"]["stages"]["safety"] == "stale"
    assert not result["required_checks_completed"]
    with closing(case["store"]._connect()) as conn:
        row = conn.execute(
            "SELECT receipt_sha256 FROM check_receipts JOIN check_attempts USING(grant_id) WHERE stage='safety'"
        ).fetchone()
    receipt = json.loads(case["store"].read_artifact(row[0]))
    assert receipt["usage"]["promptTokenCount"] == 19


def test_recovered_observation_under_new_lease_is_stale(case, monkeypatch):
    run(case)
    sent, _ = provider(monkeypatch, [envelope("NO")])
    method = case["store"].candidate_checks

    def fail_before_completion(action, *a, **kw):
        if action == "complete":
            raise RuntimeError("crash before completion")
        return method(action, *a, **kw)

    monkeypatch.setattr(case["store"], "candidate_checks", fail_before_completion)
    run(case, "safety")
    monkeypatch.setattr(case["store"], "candidate_checks", method)
    result = run(case, "safety", owner="new-owner", clock=lambda: workers.later(301))
    assert result["checks"]["stages"]["safety"] == "stale" and len(sent) == 1


def test_backup_restore_preserves_observations_and_holds(case, tmp_path):
    run(case)
    target = tmp_path / "restored.sqlite"
    with closing(case["store"]._connect()) as source, closing(sqlite3.connect(target)) as dest:
        source.backup(dest)
    restored = SQLiteAuthority(target)
    assert restored.check_execution("read", {"check_set_id": case["identity"]}, now=NOW) == saved(
        case
    )
    assert restored.read() == case["store"].read()
    assert restored.spending("status", {}, now=NOW) == case["store"].spending("status", {}, now=NOW)


def test_additive_migration_from_prior_check_schema_preserves_packet(case):
    packet = saved(case)["packet"]
    with closing(case["store"]._connect()) as conn:
        for name in observations._TABLES:
            conn.execute(f"DROP TABLE {name}")
    with pytest.raises(checks.CheckJournalError, match="migration_required"):
        saved(case)
    before = case["store"].read()
    case["store"].initialize(before[1])
    assert saved(case)["packet"] == packet and case["store"].read() == before


def _exit_after_observation(case, count, before_commit):
    original = case["store"].check_execution

    def record(action, *args, **kwargs):
        if action == "observe" and before_commit:
            kwargs["before_commit"] = lambda: os._exit(31)
        result = original(action, *args, **kwargs)
        if action == "observe":
            os._exit(31)
        return result

    case["store"].check_execution = record

    def handle(request):
        with count.get_lock():
            count.value += 1
        return httpx.Response(200, request=request, stream=httpx.ByteStream(envelope("NO")))

    executor.GoogleCheckTransport = lambda **kw: check_transport.GoogleCheckTransport(
        **kw, http_transport=httpx.MockTransport(handle)
    )
    run(case, "safety")
    os._exit(32)


@pytest.mark.parametrize("before_commit", [False, True])
def test_process_death_retention_and_recovery_never_repurchase(case, monkeypatch, before_commit):
    run(case)
    context = multiprocessing.get_context("fork")
    count = context.Value("i", 0)
    child = context.Process(target=_exit_after_observation, args=(case, count, before_commit))
    child.start()
    child.join(15)
    assert not child.is_alive() and child.exitcode == 31
    sent, _ = provider(monkeypatch, [envelope("NO")])
    result = run(case, "safety")
    assert count.value == 1 and not sent
    if before_commit:
        assert result["reason"] == "check_response_not_retained"
    else:
        assert result["checks"]["stages"]["safety"] == "passed"
