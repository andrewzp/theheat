"""Invented urgent source through the one existing spend/check/draft authority."""
from datetime import timedelta
import hashlib
import json

import pytest

from src.commands import postgres_synchronous_generation as sync, postgres_sourced_generation as generation
from src.commands.schema import canonical_json, utc_text
from src.editorial.revisions import fingerprint
from src.editorial.policy import current_editorial_policy
from src.two_bot import check_requests
from src.two_bot.check_origin import spending_job
from src.two_bot.provider_http import anthropic_httpx
from src.voice import safety
from tests import test_postgres_sourced_generation as sourced, test_postgres_candidate_admission as candidate
from tests import test_postgres_editor_media as editor, test_check_executor as executor
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.test_postgres_editor_media import offline_connections as offline_connections


@pytest.fixture
def urgent(store, core, monkeypatch):
    from tests.fire_graphic_helpers import graphic_bundle
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "invented-offline-key")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-offline-key")
    core[2].initialize_synchronous_checks(now=sourced.NOW)
    bundle = graphic_bundle()
    value = dict(schema_version=1, source_key="firms", source_revision="invented-urgent", captured_at=utc_text(sourced.NOW),
        useful_until=utc_text(sourced.NOW+timedelta(hours=8)), urgent=True, bundle=bundle.to_dict(),
        save=dict(legacy_type=bundle.signal_kind, event_id=bundle.event_id, score=None, city="", tweet_date="",
            cooldown_exempt=False, review_context=None, evaluator_metadata=None))
    refs = store.retain_generation_input(value)
    reserve = store.retain_generation_reservation(sourced.allowance_document(refs["brief_id"], schema_version=2,
        execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180))
    config = dict(schema_version=2, current_inputs=[refs["brief_id"]], reservations=dict(batch=None, synchronous=reserve))
    store.configure_sourced_generation(lambda:config)
    return dict(store=store, refs=refs, value=value, config=config, bundle=bundle,
        text="MODIS detected a 500 MW thermal signal in an invented region.")


def transport(case, *, raw=None, after=None, output=None):
    http = anthropic_httpx()
    sent = []
    def handle(request):
        sent.append(request.content)
        assert request.method == "POST" and str(request.url) == "https://api.anthropic.com/v1/messages"
        if after:
            after()
        if isinstance(raw, Exception):
            raise raw
        response = raw if raw is not None else canonical_json(dict(id="msg_invented", type="message", role="assistant",
            model=current_editorial_policy()["models"]["writer"], content=[dict(type="text", text=json.dumps(dict(dict(tweet=case["text"],
                kill_reason=None, angle_chosen="plain_number", era_anchor_used=None, peer_comparison_used=None, reasoning="invented fixture"), **(output or {}))))],
            stop_reason="end_turn", usage=dict(input_tokens=11, output_tokens=7))).encode()
        return http.Response(200, stream=http.ByteStream(response))
    return sent, lambda:dict(api_key="invented-offline-key", http_transport=http.MockTransport(handle))


def checked(case, monkeypatch):
    captured = sourced.run(case, "capture")
    assert captured["outcome"] == "candidate_ready", captured
    test_case = dict(store=case["store"], refs=captured["candidate"])
    candidate.request(test_case)
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO"), executor.envelope(editor.fact_pass(case["text"])), executor.envelope(executor.CRITIC_PASS)])
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        packet = case["store"].check_execution("read", {"check_set_id":test_case["check_set_id"]}, now=utc_text(candidate.AT))["packet"]
        request = canonical_json(check_requests.prepare_request(packet, stage)).encode()
        reserve = None if stage == "deterministic" else dict(intent_id="sync-check-"+stage, job_id=spending_job(packet),
            request_sha256=hashlib.sha256(request).hexdigest(), provider="google", role=stage,
            model=packet["policy"]["models"][stage], estimate_sha256="e"*64, reserve_micro_usd=5)
        result = case["store"].execute_candidate_check_once(test_case["request"].command_id, candidate.resolve,
            clock=lambda:utc_text(candidate.AT), reservation=reserve, enabled=True)
        assert result["outcome"] == "completed" and result["checks"]["stages"][stage] == "passed", result
    assert len(sent) == 3
    view = case["store"].candidate_projection((captured["candidate"]["admission_input_id"],), now=candidate.AT, resolve_principal=candidate.resolve)[0]
    result = candidate.consume(test_case, candidate.command(test_case, "admit_checked_candidate", changes={k:view[k] for k in ("check_set_id", "expected_completion_sha256")}))
    assert result["status"] == "applied", result
    case["draft_id"] = result["candidate"]["draft_id"]
    return test_case


def test_urgent_source_single_grant_four_checks_to_native_parked_media(urgent, core, monkeypatch, tmp_path, native_dependencies, cluster):
    case = urgent
    assert sourced.request(case)["status"] == "applied"
    sent, factory = transport(case)
    assert sourced.run(case, "write", factory)["outcome"] == "response_retained"
    assert sourced.run(case, "write", factory)["outcome"] == "reconciliation_required"
    assert len(sent) == 1
    checked(case, monkeypatch)
    core[2].initialize_media_staging()
    core[2].initialize_media_commands()
    case["store"].configure_editor_media(**native_dependencies, scratch=tmp_path/"native")
    prepared, png = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    view = editor.view(case)
    result = editor.action(case, "approve_media_revision", dict(**{k:view[k] for k in (
        "expected_policy_sha256", "expected_renderer_profile_sha256", "expected_review_sha256", "expected_check_completion_sha256")},
        expected_packet_sha256=view["packet"]["packet_sha256"], reason="Invented synchronous media review"), actor=candidate.PUBLISHER)
    assert result[1]["status"] == "applied", result
    assert editor.view(case)["parked"] is True
    state = case["store"].read()[1]
    draft = next(d for d in state["drafts"] if d["id"] == case["draft_id"])
    assert draft["status"] == "pending" and draft["approval_binding"]["scope"] == "local_joint_media"
    assert len(sent) == 1
    # Restore this full origin -> native bytes -> review -> parked intent join.
    import psycopg
    from uuid import uuid4
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options
    rows, before = editor.all_application_rows(core[3]), case["store"].read()
    params, tool, directory = cluster
    dump = directory/("synchronous-media-"+uuid4().hex+".dump")
    args = ("-h",params["host"],"-p",str(params["port"]),"-U",params["user"],"-w")
    tool("pg_dump",*args,"-Fc","-f",str(dump),core[3]["dbname"])
    name = "restore_"+uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = dict(core[3],dbname=name)
    try:
        tool("pg_restore",*args,"--single-transaction","-d",name,str(dump))
        authority = PostgresCommandAuthority(**options(restored_params))
        authority.configure_sourced_generation(lambda:case["config"])
        authority.configure_editor_media(**case["store"].editor_media_configuration)
        restored = dict(case,store=authority)
        assert authority.read() == before and editor.all_application_rows(restored_params) == rows
        assert editor.view(restored)["parked"] is True
        assert editor.view(restored,png=prepared["preparation"]["proposal_sha256"]) == png
        assert authority.consume(candidate.resolve,command_id=result[0].command_id,now=candidate.AT) == result[1]
        assert editor.all_application_rows(restored_params) == rows
        changed = editor.action(restored,"edit_revision",dict(text="MODIS detected an invented thermal signal; edited after restore."))[1]
        assert changed["status"] == "applied" and not editor.view(restored)["parked"]
        updated = next(d for d in authority.read()[1]["drafts"] if d["id"] == case["draft_id"])
        assert "approval_binding" not in updated and "review_binding" not in updated
    finally:
        admin(params,psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def retained(case):
    with case["store"].projections._connection() as c:
        saved = sync.job(c, case["result"]["generation"]["generation_id"])
        grant, observed, raw = sync.observation(c, saved)
        return saved, grant, observed, raw


def change(case, monkeypatch, kind):
    resolver, at = candidate.resolve, sourced.NOW
    if kind == "role":
        def resolver(subject):
            return candidate.Principal(subject, "viewer", "fixture")
    elif kind == "auth":
        def resolver(subject):
            return candidate.Principal(subject, "editor", "different")
    elif kind == "source":
        case["config"]["current_inputs"].clear()
    elif kind == "policy":
        monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    elif kind == "allowance":
        case["config"]["reservations"]["synchronous"]["estimate_sha256"] = "e"*64
    elif kind == "pause":
        monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "1")
    elif kind == "time":
        at += timedelta(hours=8)
    return resolver, at


@pytest.mark.parametrize("kind", ["role", "auth", "source", "policy", "allowance", "pause", "time"])
def test_pregrant_drift_refuses_post_but_postgrant_raw_survives(urgent, monkeypatch, kind):
    case = urgent
    sourced.request(case)
    sent, factory = transport(case)
    # Same fixture is reset after its pre-grant refusal; no receipt exists yet.
    from copy import deepcopy
    config = deepcopy(case["config"])
    with monkeypatch.context() as patch:
        resolver, at = change(case, patch, kind)
        with pytest.raises(candidate.CommandError):
            sourced.run(case, "write", factory, resolver=resolver, at=at)
        assert sent == [] and retained(case)[1] is None
    case["config"].clear()
    case["config"].update(config)
    resolver, at = candidate.resolve, sourced.NOW
    def drift():
        nonlocal resolver, at
        resolver, at = change(case, monkeypatch, kind)
    sent, factory = transport(case, after=drift)
    result = case["store"].execute_sourced_generation_once(case["request"].command_id, lambda subject:resolver(subject),
        operation="write", clock=lambda:utc_text(at), transport_factory=factory, enabled=True)
    assert result["outcome"] == "response_retained" and len(sent) == 1
    saved, granted, observed, raw = retained(case)
    assert granted and observed["complete"] and json.loads(raw)["id"] == "msg_invented"
    assert observed["grant_id"] == granted["grant_id"] and observed["observed_at"] == utc_text(at)
    with pytest.raises(candidate.CommandError):
        sourced.run(case, "capture", resolver=resolver, at=at)
    assert case["store"].spending("status", {"intent_id":saved["intent_id"]}, now=utc_text(at))["intent"]["settled_micro_usd"] is None
    assert retained(case)[2:] == (observed, raw)


@pytest.mark.parametrize("kind", ["role", "auth"])
def test_original_writer_revocation_after_capture_blocks_check_promotion(urgent, monkeypatch, kind):
    sourced.request(urgent)
    sent, factory = transport(urgent)
    sourced.run(urgent, "write", factory)
    captured = sourced.run(urgent, "capture")["candidate"]
    resolver, _ = change(urgent, monkeypatch, kind)
    # A distinct current editor still cannot promote the original revoked grant.
    other = candidate.Principal("other-editor", "editor", "fixture")
    def resolve(subject):
        return other if subject == other.subject else resolver(subject)
    case = dict(store=urgent["store"], refs=captured)
    cmd = candidate.command(case, principal=other)
    urgent["store"].accept(cmd, other, now=candidate.AT)
    before = urgent["store"].read()
    result = urgent["store"].consume(resolve, command_id=cmd.command_id, now=candidate.AT)
    assert result["status"] == "rejected" and result["code"] == "forbidden"
    assert urgent["store"].read() == before
    projection = urgent["store"].candidate_projection((captured["admission_input_id"],), now=candidate.AT, resolve_principal=resolve)[0]
    assert not projection["required_checks_completed"] and projection["reason"] == "forbidden"
    assert len(sent) == 1


def test_lock_delay_refreshes_grant_clock_and_never_posts(urgent, monkeypatch):
    sourced.request(urgent)
    sent, factory = transport(urgent)
    at = sourced.NOW
    original, calls = urgent["store"]._state, 0
    def delayed(*args, **kwargs):
        nonlocal at, calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2: # context succeeds; the send-boundary lock resumes too late.
            at += timedelta(hours=8)
        return result
    monkeypatch.setattr(urgent["store"], "_state", delayed)
    result = urgent["store"].execute_sourced_generation_once(urgent["request"].command_id, candidate.resolve,
        operation="write", clock=lambda:utc_text(at), enabled=True, transport_factory=factory)
    assert result["outcome"] == "reconciliation_required" and sent == []
    saved, granted, observed, _ = retained(urgent)
    assert granted is observed is None
    assert urgent["store"].spending("status", {"intent_id":saved["intent_id"]}, now=utc_text(at))["intent"]["state"] == "reserved"


def test_unknown_response_retains_original_hold_and_never_resends(urgent, core):
    sourced.request(urgent)
    http = anthropic_httpx()
    sent, factory = transport(urgent, raw=http.ReadTimeout("invented lost response"))
    sourced.run(urgent, "write", factory)
    saved, grant, observed, raw = retained(urgent)
    assert grant and observed["complete"] is False and raw == b""
    assert sourced.run(urgent, "write", factory)["outcome"] == "reconciliation_required"
    assert sourced.run(urgent, "capture")["outcome"] == "terminal"
    assert len(sent) == 1
    status = urgent["store"].spending("status", {"intent_id":saved["intent_id"]}, now=utc_text(sourced.NOW))["intent"]
    assert status["state"] == "uncertain" and status["settled_micro_usd"] is None
    assert admin(core[3], "SELECT count(*) FROM theheat_batches.registrations") == [(0,)]


@pytest.mark.parametrize("activation", ["before_context", "during_sdk_construction"])
def test_reserved_job_rechecks_new_cache_before_grant(urgent, core, activation):
    from copy import deepcopy
    from src.two_bot import negative_cache
    case = urgent
    assert sourced.request(case)["status"] == "applied"
    original = {key:case[key] for key in ("refs", "request", "result")}
    original_config = deepcopy(case["config"])
    sent, factory = transport(case)
    at = sourced.NOW+timedelta(minutes=4)
    after_kills = []
    def arm_cache():
        for number in range(2):
            kill_at = sourced.NOW+timedelta(minutes=number+1)
            value = dict(case["value"], source_revision=f"independent-later-kill-{number}")
            case["refs"] = case["store"].retain_generation_input(value)
            case["config"]["current_inputs"] = [case["refs"]["brief_id"]]
            case["config"]["reservations"]["synchronous"] = case["store"].retain_generation_reservation(sourced.allowance_document(
                case["refs"]["brief_id"], now=kill_at, schema_version=2, execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180))
            assert sourced.request(case, now=kill_at)["status"] == "applied"
            killed, kill_factory = transport(case, output=dict(tweet=None, kill_reason="insufficient evidence",
                kill_scope="evidence", kill_code="insufficient_evidence"))
            assert sourced.run(case, "write", kill_factory, at=kill_at)["outcome"] == "response_retained"
            first = sourced.run(case, "interpret", at=kill_at)
            assert len(killed) == 1
            # The second kill activates cache; original usage/replay remains readable.
            before_replay = editor.all_application_rows(core[3])
            assert sourced.run(case, "interpret", at=kill_at) == first
            assert sourced.run(case, "capture", at=kill_at)["outcome"] == "terminal"
            assert editor.all_application_rows(core[3]) == before_replay
        case.update(original)
        case["config"].clear()
        case["config"].update(original_config)
        assert negative_cache.should_skip(case["store"].read()[1], case["bundle"].event_id, case["bundle"], now=at)
        after_kills.append(editor.all_application_rows(core[3]))
    if activation == "before_context":
        arm_cache()
    def construct():
        if activation == "during_sdk_construction":
            arm_cache()
        return factory()
    assert sourced.run(case, "write", construct, at=at)["outcome"] == "reconciliation_required"
    assert sent == [] and editor.all_application_rows(core[3]) == after_kills[0]
    with case["store"].projections._connection() as c:
        saved = sync.job(c, original["result"]["generation"]["generation_id"])
        assert sync.attempt(c, saved) is None
        assert sync.spend._record(c, saved["intent_id"])["state"] == "reserved"
        assert c.execute("SELECT count(*) FROM theheat_spending.events WHERE kind='dispatched'").fetchone() == (2,)


@pytest.mark.parametrize("phase", ["hold", "job", "dispatch", "attempt"])
def test_each_job_grant_write_rolls_back_without_leaked_permission(urgent, core, monkeypatch, phase):
    from tests.test_postgres_projection import wrap_connections
    if phase in {"dispatch", "attempt"}:
        sourced.request(urgent)
    statements = {"hold":"INSERT INTO theheat_spending.intents", "job":"sourced-sync-job-v1", "dispatch":"INSERT INTO theheat_spending.events", "attempt":"sourced-sync-attempt-v1"}
    hit = []
    if phase in {"job", "attempt"}:
        original = generation.record
        def fail(c, namespace, identity, value):
            result = original(c, namespace, identity, value)
            if namespace == statements[phase]:
                hit.append(namespace)
                raise RuntimeError("invented precommit crash")
            return result
        monkeypatch.setattr(generation, "record", fail)
    else:
        def fail(query, c):
            if query.startswith(statements[phase]):
                hit.append(query)
                raise RuntimeError("invented precommit crash")
        wrap_connections(monkeypatch, after_execute=fail)
    if phase in {"hold", "job"}:
        with pytest.raises(RuntimeError, match="invented precommit crash"):
            sourced.request(urgent)
    else:
        sent, factory = transport(urgent)
        assert sourced.run(urgent, "write", factory)["outcome"] == "reconciliation_required"
        assert sent == [] and retained(urgent)[1] is None
    assert hit
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(0 if phase in {"hold", "job"} else 1,)]


def test_acknowledged_grant_lost_ack_never_sends_or_retries(urgent, monkeypatch):
    from contextlib import contextmanager
    sourced.request(urgent)
    original = urgent["store"].projections._connection
    lost = False
    @contextmanager
    def connection(*, writing=False):
        nonlocal lost
        dispatched = False
        with original(writing=writing) as c:
            yield c
            dispatched = bool(c.execute("SELECT 1 FROM theheat_spending.events WHERE kind='dispatched'").fetchone())
        if writing and dispatched and not lost:
            lost = True
            raise RuntimeError("invented commit acknowledgment lost")
    monkeypatch.setattr(urgent["store"].projections, "_connection", connection)
    sent, factory = transport(urgent)
    assert sourced.run(urgent, "write", factory)["outcome"] == "reconciliation_required"
    assert sourced.run(urgent, "write", factory)["outcome"] == "reconciliation_required"
    saved, granted, observed, _ = retained(urgent)
    assert lost and granted and observed is None and sent == []
    assert urgent["store"].spending("status", {"intent_id":saved["intent_id"]}, now=utc_text(sourced.NOW))["intent"]["state"] == "uncertain"


def test_racing_manual_automatic_and_writers_share_one_grant(urgent, core, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.two_bot.sourced_generation import SourcedGenerationClient
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
    first = sourced.request(urgent)
    client = SourcedGenerationClient(urgent["store"], candidate.EDITOR, candidate.resolve, lambda:sourced.NOW)
    result = {}
    assert not _try_two_bot_draft(urgent["bundle"], urgent["store"].read()[1], None,
        legacy_type="fire", event_id=urgent["bundle"].event_id, review_context=None, generation_client=client, result_out=result)
    assert result["generation_id"] == first["generation"]["generation_id"] and result["generation_status"] == "reused"
    gate = Barrier(2)
    sent, factory = transport(urgent)
    def delayed():
        gate.wait(timeout=10)
        return factory()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(sourced.run, urgent, "write", delayed) for _ in range(2)]]
    assert sorted(r["outcome"] for r in results) == ["reconciliation_required", "response_retained"]
    assert len(sent) == 1
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.events WHERE kind='dispatched'") == [(1,)]


@pytest.mark.parametrize("extra", [{"samples":3}, {"urgent":True}, {"prompt":"untrusted"}, {"generation_id":"gss_"+"a"*64}])
def test_reference_only_start_rejects_browser_overrides(urgent, extra):
    with pytest.raises(candidate.CommandError):
        sourced.request(urgent, changes=extra)


@pytest.mark.parametrize("change", [{"samples":3}, {"samples":True}, {"max_attempts":2}, {"read_budget_seconds":181}, {"execution_mode":"batch"}, {"provider":"google"}])
def test_sync_allowance_rejects_unapproved_runtime_changes(change):
    value = sourced.allowance_document("a"*64, schema_version=2, execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180)
    with pytest.raises(candidate.CommandError):
        generation.reservation_document(dict(value, **change))


def test_candidate_command_operator_session_change_is_independent_of_writer(urgent):
    sourced.request(urgent)
    sent, factory = transport(urgent)
    sourced.run(urgent, "write", factory)
    refs = sourced.run(urgent, "capture")["candidate"]
    checker = candidate.Principal("different-checker", "editor", "old-session")
    cmd = candidate.command(dict(store=urgent["store"], refs=refs), principal=checker)
    urgent["store"].accept(cmd, checker, now=candidate.AT)
    before = urgent["store"].read()
    def resolver(subject):
        return candidate.Principal(subject, "editor", "new-session") if subject == checker.subject else candidate.resolve(subject)
    result = urgent["store"].consume(resolver, command_id=cmd.command_id, now=candidate.AT)
    assert result["status"] == "rejected" and result["code"] == "forbidden"
    assert urgent["store"].read() == before and len(sent) == 1


@pytest.mark.parametrize("scope", ["evidence", "style"])
def test_fixed_resolution_kill_and_usage_replay_count_once(urgent, scope, monkeypatch):
    from copy import deepcopy
    from src.two_bot import negative_cache
    for number in range(2):
        at = sourced.NOW+timedelta(minutes=number*2)
        value = dict(urgent["value"], source_revision=f"independent-invented-{number}", captured_at=utc_text(at))
        urgent["refs"] = urgent["store"].retain_generation_input(value)
        urgent["config"]["current_inputs"] = [urgent["refs"]["brief_id"]]
        urgent["config"]["reservations"]["synchronous"] = urgent["store"].retain_generation_reservation(sourced.allowance_document(
            urgent["refs"]["brief_id"], now=at, schema_version=2, execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180))
        assert sourced.request(urgent, now=at)["status"] == "applied"
        sent, factory = transport(urgent, output=dict(tweet=None, kill_reason="insufficient evidence", kill_scope=scope,
            kill_code="insufficient_evidence" if scope == "evidence" else None))
        sourced.run(urgent, "write", factory, at=at)
        # A failure after cache + resolution writes must roll both back.
        before = urgent["store"].read()
        original = generation.record
        def stop(c, namespace, identity, value):
            receipt = original(c, namespace, identity, value)
            if namespace == sync.RESOLUTION:
                raise RuntimeError("invented resolution rollback")
            return receipt
        with monkeypatch.context() as patch:
            patch.setattr(generation, "record", stop)
            with pytest.raises(RuntimeError, match="invented resolution rollback"):
                sourced.run(urgent, "interpret", at=at)
        assert urgent["store"].read() == before
        first = sourced.run(urgent, "interpret", at=at)
        before = deepcopy(urgent["store"].read())
        for _ in range(2):
            assert sourced.run(urgent, "interpret", at=at) == first
            assert sourced.run(urgent, "capture", at=at)["outcome"] == "terminal"
        assert urgent["store"].read() == before
        assert len(sent) == 1 and first["usage"]["cost_usd"] is None
        cache = before[1].get("writer_negative_cache", {})
        assert (next(iter(cache.values()))["kills"] if cache else 0) == (number+1 if scope == "evidence" else 0)
    assert bool(negative_cache.should_skip(urgent["store"].read()[1], urgent["bundle"].event_id, urgent["bundle"], now=at)) is (scope == "evidence")
    if scope == "evidence":
        assert sourced.request(urgent, now=at)["code"] == "generation_negative_cache"


@pytest.mark.parametrize("phase", ["registered", "grant_unknown", "raw", "interpreted"])
def test_fresh_owned_cluster_restore_preserves_exact_writer_identity(urgent, core, cluster, phase):
    import tempfile
    from pathlib import Path
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    initial = sourced.request(urgent)
    sent, factory = transport(urgent, raw=anthropic_httpx().ReadTimeout("invented loss") if phase == "grant_unknown" else None)
    if phase != "registered":
        sourced.run(urgent, "write", factory)
    if phase == "interpreted":
        sourced.run(urgent, "capture")
    before = urgent["store"].read()
    rows = editor.all_application_rows(core[3])
    params, (_, tool, _) = core[3], cluster
    with tempfile.TemporaryDirectory(prefix="theheat-sync-restore-", dir="/tmp") as directory:
        root = Path(directory)
        root.chmod(0o700)
        socket, data, dump = root/"socket", root/"data", root/"source.dump"
        socket.mkdir(mode=0o700)
        tool("pg_dump", "-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-Fc", "-f", dump, params["dbname"])
        tool("initdb", "-D", data, "-U", "projection_owner", "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--no-locale")
        try:
            tool("pg_ctl", "-D", data, "-l", root/"server.log", "-o", f"-c listen_addresses='' -k {socket} -p 55477", "-w", "start")
            with psycopg.connect(host=str(socket), port=55477, user="projection_owner", dbname="postgres", autocommit=True) as c:
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                c.execute("CREATE DATABASE restored_synchronous TEMPLATE template0")
            tool("pg_restore", "-h", socket, "-p", "55477", "-U", "projection_owner", "-d", "restored_synchronous", "--exit-on-error", "--single-transaction", dump)
            args = dict(host=str(socket), port=55477, user="projection_owner", dbname="restored_synchronous")
            restored = PostgresCommandAuthority(socket_directory=socket, port=55477, database=args["dbname"], user="projection_runtime")
            restored.configure_sourced_generation(lambda:urgent["config"])
            assert restored.read() == before and editor.all_application_rows(args) == rows
            assert restored.consume(candidate.resolve, command_id=urgent["request"].command_id, now=sourced.NOW) == initial
            case = dict(urgent, store=restored)
            new_sent, factory = transport(case)
            if phase == "registered":
                assert sourced.run(case, "write", factory)["outcome"] == "response_retained"
                assert len(new_sent) == 1
            else:
                assert sourced.run(case, "write", factory)["outcome"] == "reconciliation_required"
                assert not new_sent
            first = sourced.run(case, "interpret")
            after = restored.read()
            assert sourced.run(case, "interpret") == first == sourced.run(case, "interpret")
            assert restored.read() == after
            assert first["usage"]["cost_usd"] is None
            assert sourced.run(case, "capture")["outcome"] == ("terminal" if phase == "grant_unknown" else "candidate_ready")
            assert urgent["store"].read() == before
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


@pytest.mark.parametrize("changes", [dict(model="wrong-model"),dict(stop_reason="max_tokens"),dict(usage=None),dict(usage={"input_tokens":True})])
def test_original_envelope_and_unknown_usage_interpretation_do_not_invent_cost(urgent, changes):
    sourced.request(urgent)
    sent, factory = transport(urgent)
    sourced.run(urgent, "write", factory)
    saved, granted, observed, raw = retained(urgent)
    value = json.loads(raw)
    value.update(changes)
    altered = canonical_json(value).encode()
    result = sync.interpret(saved, granted, observed, altered)
    assert result["usage"]["cost_usd"] is None and result["usage"]["cost_status"] == "unreconciled"
    assert result["disposition"] == ("ineligible" if any(k in changes for k in ("model","stop_reason")) else "candidate")


def checked_stage(case, stage, *, resolver=candidate.resolve, clock=lambda:utc_text(candidate.AT)):
    packet = case["store"].check_execution("read", {"check_set_id":case["check_set_id"]}, now=clock())["packet"]
    raw = canonical_json(check_requests.prepare_request(packet, stage)).encode()
    reserve = None if stage == "deterministic" else dict(intent_id="boundary-"+stage, job_id=spending_job(packet),
        request_sha256=hashlib.sha256(raw).hexdigest(), provider="google", role=stage, model=packet["policy"]["models"][stage], estimate_sha256="e"*64, reserve_micro_usd=5)
    return case["store"].execute_candidate_check_once(case["request"].command_id, resolver, clock=clock, reservation=reserve, enabled=True)


@pytest.mark.parametrize("kind", ["source", "role", "policy", "allowance", "time"])
def test_sync_check_postgrant_drift_keeps_exact_raw_without_promotion(urgent, monkeypatch, kind):
    from src.two_bot.check_transport import GoogleCheckTransport
    sourced.request(urgent)
    _, factory = transport(urgent)
    sourced.run(urgent, "write", factory)
    case = dict(store=urgent["store"], refs=sourced.run(urgent, "capture")["candidate"])
    candidate.request(case)
    assert checked_stage(case, "deterministic")["outcome"] == "completed"
    raw = executor.envelope("NO")
    sent, _ = executor.provider(monkeypatch, [raw])
    original = GoogleCheckTransport.execute
    resolver, at = candidate.resolve, candidate.AT
    def execute(transport, request):
        nonlocal resolver, at
        resolver, changed_at = change(urgent, monkeypatch, kind)
        if kind == "time":
            at = changed_at
        return original(transport, request)
    monkeypatch.setattr(GoogleCheckTransport, "execute", execute)
    result = checked_stage(case, "safety", resolver=lambda subject:resolver(subject), clock=lambda:utc_text(at))
    assert result["outcome"] == "reconciliation_required", result
    saved = case["store"].check_execution("read", {"check_set_id":case["check_set_id"]}, now=utc_text(at))
    attempt = saved["attempts"]["safety"]
    assert attempt["observation"]["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert case["store"].read_check_response(case["check_set_id"], "safety", attempt["grant_id"]) == raw
    with case["store"].projections._connection() as connection:
        from src.commands import postgres_checks
        assert postgres_checks._terminal(connection, attempt) is None
    assert len(sent) == 1


def test_missing_checks_and_forged_completion_cannot_change_drafts(urgent):
    sourced.request(urgent)
    _, factory = transport(urgent)
    sourced.run(urgent, "write", factory)
    refs = sourced.run(urgent, "capture")["candidate"]
    case = dict(store=urgent["store"], refs=refs)
    candidate.request(case)
    before = urgent["store"].read()
    cmd = candidate.command(case, "admit_checked_candidate", changes=dict(check_set_id=case["check_set_id"], expected_completion_sha256="f"*64))
    result = candidate.consume(case, cmd)
    assert result["status"] == "rejected" and urgent["store"].read() == before
    assert result["code"] == "required_checks_incomplete"


def test_null_safe_origin_projection_fk_and_lease_origin_enforced(urgent, core):
    import psycopg
    sourced.request(urgent)
    _, factory = transport(urgent)
    sourced.run(urgent, "write", factory)
    case = dict(store=urgent["store"], refs=sourced.run(urgent, "capture")["candidate"])
    candidate.request(case)
    with urgent["store"].projections._connection() as c:
        row = c.execute("SELECT packet_sha256,recorded_at,sync_namespace,sync_enrollment_id FROM theheat_checks.sets WHERE check_set_id=%s", (case["check_set_id"],)).fetchone()
    for columns, values, constraint in [
        ("origin_kind,sync_namespace,sync_enrollment_id", ("synchronous_writer_v1",None,None), "sets_origin"),
        ("origin_kind,sync_namespace,sync_enrollment_id", ("synchronous_writer_v1",row[2],None), "sets_origin"),
        ("origin_kind,sync_namespace,sync_enrollment_id", ("synchronous_writer_v1","wrong",row[3]), "sets_origin"),
        ("origin_kind,sync_namespace,sync_enrollment_id", ("synchronous_writer_v1",row[2],"a"*64), "sets_sync_projection"),
        ("origin_kind,sync_namespace,sync_enrollment_id", ("synchronous_writer_v1",row[2],row[3]), "sets_sync_unique"),
        ("origin_kind,draft_namespace,draft_enrollment_id,sync_namespace,sync_enrollment_id", ("synchronous_writer_v1","draft-check-enrollment-v1","a"*64,row[2],row[3]), "sets_origin"),
    ]:
        with pytest.raises(psycopg.Error) as exc:
            admin(core[3], f"INSERT INTO theheat_checks.sets(check_set_id,packet_sha256,recorded_at,{columns}) VALUES(%s,%s,%s,{','.join(['%s']*len(values))})", ("e"*64,*row[:2],*values))
        assert exc.value.diag.constraint_name == constraint
    with pytest.raises(psycopg.Error):
        admin(core[3], "INSERT INTO theheat_checks.draft_leases(check_set_id,origin_kind,fence,owner,expires_at,recorded_at) VALUES(%s,'saved_draft_revision_v1',2,'wrong',%s,%s)",
            (case["check_set_id"], sync.spend._time(utc_text(candidate.AT+timedelta(minutes=10))),sync.spend._time(utc_text(candidate.AT+timedelta(minutes=5)))))


@pytest.mark.parametrize("seconds", [600,601])
def test_urgent_window_threshold_is_conservative_preflight_only(urgent, seconds, core):
    value = dict(urgent["value"], useful_until=utc_text(sourced.NOW+timedelta(seconds=seconds)))
    urgent["refs"] = urgent["store"].retain_generation_input(value)
    urgent["config"]["current_inputs"] = [urgent["refs"]["brief_id"]]
    urgent["config"]["reservations"]["synchronous"] = urgent["store"].retain_generation_reservation(sourced.allowance_document(
        urgent["refs"]["brief_id"], schema_version=2, execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180))
    result = sourced.request(urgent)
    assert result["status"] == ("applied" if seconds>600 else "rejected")
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1 if seconds>600 else 0,)]


def test_exhausted_sync_allowance_is_durable_refusal_without_orphan(urgent, core):
    urgent["config"]["reservations"]["synchronous"] = urgent["store"].retain_generation_reservation(sourced.allowance_document(
        urgent["refs"]["brief_id"], schema_version=2, execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180, reserve_micro_usd=91))
    result = sourced.request(urgent)
    assert result["status"] == "rejected" and result["code"] == "spending_allowance_exhausted"
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_projection.versions WHERE namespace=%s", (sync.JOB,)) == [(0,)]


@pytest.mark.parametrize("refill", [False,True])
def test_both_actual_drains_use_same_urgent_source_without_refill_or_callback(urgent, monkeypatch, refill):
    from dataclasses import replace
    from src.orchestrator import common, funnel, triage_queue, two_bot_dispatch
    from src.two_bot.sourced_generation import SourcedGenerationClient
    from src.two_bot import pipeline
    from tests.test_triage import _candidate
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", str(int(refill)))
    monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_GLOBAL_CAP", "1")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "1")
    monkeypatch.setattr(common,"_try_two_bot_draft",two_bot_dispatch._try_two_bot_draft)
    monkeypatch.setattr(pipeline,"generate_draft",lambda *a,**k:pytest.fail("legacy writer bypass"))
    row = replace(_candidate(event_id=urgent["bundle"].event_id,total=95),bundle=urgent["bundle"],legacy_type="fire",review_context=None,tweet_date="")
    value = dict(urgent["value"],save=dict(urgent["value"]["save"],score=row.score.as_dict()))
    urgent["refs"] = urgent["store"].retain_generation_input(value)
    urgent["config"]["current_inputs"] = [urgent["refs"]["brief_id"]]
    urgent["config"]["reservations"]["synchronous"] = urgent["store"].retain_generation_reservation(sourced.allowance_document(
        urgent["refs"]["brief_id"],schema_version=2,execution_mode="synchronous",samples=1,max_attempts=1,read_budget_seconds=180))
    first = sourced.request(urgent)
    state = urgent["store"].read()[1]
    before = list(state["drafts"])
    state["_triage_queue"] = [row]
    run = {"sources":[dict(source="coral_dhw",drafted=0,writer_attempted=0)]}
    client = SourcedGenerationClient(urgent["store"],candidate.EDITOR,candidate.resolve,lambda:sourced.NOW)
    sink = funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(state,run,generation_client=client,funnel_sink=sink) == 0
    assert state["drafts"] == before and run["sources"][0]["writer_attempted"] == 0
    assert sink["_slate_terminal"][row.event_id] == "generation_queued"
    saved = retained(urgent)[0]
    assert saved["generation_id"] == first["generation"]["generation_id"]
