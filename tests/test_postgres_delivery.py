"""Local owner-installed delivery obligations on the original P31 authority."""
from datetime import timedelta
import json
from uuid import uuid4

import pytest

from src.commands import postgres_delivery as delivery
from src.commands.preview_delivery_worker import execute_delivery_once
from src.commands.schema import utc_text
from src.storage import postgres_projection as p
from tests import test_postgres_editor_media as editor
from tests import test_postgres_candidate_admission as candidate
from tests.local_delivery_helpers import fixture_server
from tests.test_postgres_editor_media import admitted as admitted, offline_connections as offline_connections
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_command_authority import options
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies


def install(core):
    core[2].initialize_media_staging()
    core[2].initialize_delivery(now=editor.AT)


def configure(store, tmp_path, config):
    folder = tmp_path / "delivery-config"
    folder.mkdir(mode=0o700)
    path = folder / "fixture.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    store.configure_delivery(path)
    return path


def park(case):
    current = editor.view(case)
    return editor.action(case, "approve_media_revision", dict(
        **{key:current[key] for key in ("expected_policy_sha256", "expected_renderer_profile_sha256", "expected_review_sha256", "expected_check_completion_sha256")},
        expected_packet_sha256=current["packet"]["packet_sha256"],
        reason="Invented local fixture transport only."), actor=candidate.PUBLISHER)


def run(case, intent, platform, stage, *, owner="invented-local-worker", at=editor.AT, **kwargs):
    return execute_delivery_once(case["store"], intent, platform, stage, candidate.resolve,
        owner=owner, clock=lambda:utc_text(at), enabled=True, **kwargs)


def test_owner_catalog_upgrade_is_explicit_idempotent_and_runtime_cannot_install(core):
    before = admin(core[3], "SELECT * FROM theheat_commands.metadata")
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        core[0].initialize_delivery(now=editor.AT)
    install(core)
    core[2].initialize_delivery(now=editor.AT + timedelta(days=1))
    assert admin(core[3], "SELECT * FROM theheat_commands.metadata") == before
    assert admin(core[3], "SELECT count(*) FROM theheat_commands.delivery_upgrade") == [(1,)]
    assert core[0].read() == (0, core[1])
    for table in delivery.TABLES:
        assert admin(core[3], "SELECT has_table_privilege('projection_runtime',%s,'UPDATE'),has_table_privilege('projection_runtime',%s,'DELETE')", ("theheat_delivery."+table,)*2) == [(False, False)]


def test_owner_upgrade_failure_rolls_back_entire_additive_catalog(core, monkeypatch):
    core[2].initialize_media_staging()
    before = editor.all_application_rows(core[3])
    original = delivery.validate
    def fail_after_install(*args):
        original(*args)
        raise RuntimeError("invented installation failure")
    with monkeypatch.context() as patch:
        patch.setattr(delivery, "validate", fail_after_install)
        with pytest.raises(RuntimeError, match="invented installation failure"):
            core[2].initialize_delivery(now=editor.AT)
    assert admin(core[3], "SELECT to_regnamespace('theheat_delivery'),to_regclass('theheat_commands.delivery_upgrade')") == [(None, None)]
    assert editor.all_application_rows(core[3]) == before
    assert core[0].read() == (0, core[1])
    core[2].initialize_delivery(now=editor.AT)
    assert core[0].read() == (0, core[1])


def test_frozen_old_validator_refuses_approval_intake_and_consumption(core):
    from tests.legacy_delivery_authority import LegacyAuthority
    from tests.test_command_authority import command, PUBLISHER, resolver, NOW
    legacy = LegacyAuthority(**options(core[3]))
    cmd = command(core[1]["drafts"][0], "approve_revision", {"reason":"Invented old-binary approval"}, principal=PUBLISHER)
    assert legacy.read() == (0, core[1])
    install(core)
    before = editor.all_application_rows(core[3])
    for operation in (lambda:legacy.accept(cmd, PUBLISHER, now=NOW), lambda:legacy.consume(resolver, now=NOW)):
        with pytest.raises(p.ProjectionError, match="changed_command_schema"):
            operation()
    assert editor.all_application_rows(core[3]) == before


@pytest.mark.parametrize("change", [
    "CREATE TABLE theheat_delivery.extra(v int)",
    "GRANT UPDATE ON theheat_delivery.leases TO projection_runtime",
    "ALTER TABLE theheat_delivery.attempts DISABLE TRIGGER attempts_immutable",
    "DROP TABLE theheat_commands.delivery_upgrade",
])
def test_changed_or_partial_catalog_refused(core, change):
    install(core)
    admin(core[3], change)
    with pytest.raises(p.ProjectionError):
        core[0].read()


def test_atomic_approval_five_stages_and_replay_do_not_change_editorial_state(admitted, core, tmp_path, monkeypatch):
    case = admitted
    _, png = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"]) as (config, trace, accepted):
        configure(case["store"], tmp_path, config)
        cmd, result = park(case)
        assert result["status"] == "applied", result
        intent = result["delivery"]["intent_id"]
        assert set(result["delivery"]["obligations"]) == {"x", "bluesky"}
        assert case["store"].consume(candidate.resolve, command_id=cmd.command_id, now=editor.AT) == result
        version, state = case["store"].read()
        assert state["drafts"][-1]["status"] == "pending"
        assert_live_senders_refuse(next(d for d in state["drafts"] if d["id"] == case["draft_id"]), monkeypatch)
        for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        # Two real workers compete for one phase. Both use the original parked
        # authority and actual HTTP transport; only one may obtain the barrier.
        from concurrent.futures import ThreadPoolExecutor
        import threading
        gate = threading.Barrier(2)
        def competing(owner):
            gate.wait(timeout=5)
            return run(case, intent, "x", "upload", owner=owner)
        with ThreadPoolExecutor(max_workers=2) as workers:
            competing_results = list(workers.map(competing, ("worker-one", "worker-two")))
        assert sum(result["outcome"] == "confirmed" for result in competing_results) >= 1
        assert len(trace) == 1
        for platform, stages in delivery.STAGES.items():
            for stage in stages:
                receipt = run(case, intent, platform, stage)
                assert receipt["outcome"] == "confirmed", (platform, stage, receipt)
                replay = run(case, intent, platform, stage)
                assert replay["outcome"] == "confirmed" and replay["network_mutation"] is False
        assert len(trace) == len(accepted) == 5
        assert case["store"].read() == (version, state)
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.intents") == [(1,)]
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.work_items") == [(2,)]
        projection = case["store"].delivery_projection(case["draft_id"], candidate.resolve, now=editor.AT)
        assert projection["publication_approved"] is False and projection["intents"][0]["current"] is True
        draft = next(d for d in state["drafts"] if d["id"] == case["draft_id"])
        with case["store"].projections._connection() as c:
            with pytest.raises(delivery.CommandError, match="Local delivery") as held:
                delivery.hold(c, draft)
            assert held.value.code == "delivery_event_already_confirmed"
            delivery.hold(c, dict(draft, id="another-invented-draft", event_id="another-invented-event"))


def assert_live_senders_refuse(draft, monkeypatch):
    from copy import deepcopy
    from unittest.mock import MagicMock
    from src.orchestrator import posting
    from src.posting import twitter
    from src.state import DEFAULT_STATE
    with monkeypatch.context() as patch:
        storage = MagicMock()
        storage.check_daily_cap.return_value = True
        storage.write_state.return_value = True
        sent = MagicMock(side_effect=AssertionError("Local parked approval reached live provider"))
        patch.setattr(posting, "state", storage)
        patch.setattr(posting, "post_tweet", sent)
        patch.setattr(posting, "post_to_bluesky", sent)
        patch.setattr(twitter, "_get_client", sent)
        patch.setattr(twitter, "_get_upload_api", sent)
        # Even an independently permitted publication epoch cannot promote the
        # local parked scope. This is an explicit offline adversarial fixture.
        patch.setattr(posting, "observe_publication_policy", lambda _:dict(enabled=True, reason="invented"))
        patch.setattr(posting, "automatic_approval_allowed", lambda *_:True)
        for path in ("direct", "manual", "automatic"):
            state = deepcopy(DEFAULT_STATE)
            item = deepcopy(draft)
            state["drafts"] = [item]
            if path == "direct":
                assert posting.post_approved(item, state) == "failed"
            elif path == "manual":
                item["status"] = "approved"
                patch.setenv("DRAFT_ID", item["id"])
                patch.setenv("TWEET_TEXT", item["text"])
                patch.setenv("PUBLISH_INTENT_ID", item["publish_intent_id"])
                posting.run_manual_tweet(state)
            else:
                item["auto_approve_at"] = "2000-01-01T00:00:00Z"
                posting.process_due_drafts(state)
        sent.assert_not_called()


def catalogs(params):
    import psycopg
    with psycopg.connect(**params) as c:
        schemas = c.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'theheat_%' ORDER BY 1").fetchall()
        sequences = c.execute("SELECT schemaname,sequencename,sequenceowner,data_type,start_value,min_value,max_value,increment_by,cycle,cache_size,last_value FROM pg_sequences WHERE schemaname LIKE 'theheat_%' ORDER BY 1,2").fetchall()
        states = [(s[0], s[1], c.execute(psycopg.sql.SQL("SELECT last_value,is_called FROM {}.{}").format(psycopg.sql.Identifier(s[0]), psycopg.sql.Identifier(s[1]))).fetchone()) for s in sequences]
        dependencies = c.execute("""SELECT n.nspname,s.relname,tn.nspname,t.relname,a.attname,d.deptype
            FROM pg_class s JOIN pg_namespace n ON n.oid=s.relnamespace JOIN pg_depend d ON d.objid=s.oid
            JOIN pg_class t ON t.oid=d.refobjid JOIN pg_namespace tn ON tn.oid=t.relnamespace
            LEFT JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
            WHERE s.relkind='S' AND n.nspname LIKE 'theheat_%' ORDER BY 1,2,3,4,5,6""").fetchall()
        return dict(catalogs={s:p._catalog(c, s) for (s,) in schemas}, sequences=sequences, states=states, dependencies=dependencies)


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_raw_and_receipt_commit_failures_recover_without_mutation_replay(admitted, core, tmp_path, monkeypatch):
    from contextlib import contextmanager
    from src.posting.delivery_receipts import digest
    from src.commands.schema import canonical_json

    case = admitted
    _, png = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"]) as (config, trace, _):
        configure(case["store"], tmp_path, config)
        _, result = park(case)
        intent = result["delivery"]["intent_id"]
        state = case["store"].read()
        for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

        def count(table):
            return admin(core[3], f"SELECT count(*) FROM theheat_delivery.{table}")[0][0]

        # The HTTP service accepts, but raw storage rolls back. Neither an empty
        # journal nor a restart authorizes a second POST. Only a positive GET
        # witness can resolve this originally acknowledged dispatch barrier.
        original = delivery.observe
        def fail_raw(*args):
            original(*args)
            raise RuntimeError("invented raw commit failure")
        with monkeypatch.context() as patch:
            patch.setattr(delivery, "observe", fail_raw)
            assert run(case, intent, "x", "upload")["outcome"] == "unknown"
        assert count("observations") == count("receipts") == 0
        assert run(case, intent, "x", "upload")["outcome"] == "unknown" and len(trace) == 1
        assert run(case, intent, "x", "upload", reconcile=True)["outcome"] == "confirmed"
        assert len(trace) == 2 and trace[-1]["method"] == "GET"

        # Kill the worker's control flow only after the actual transaction has
        # committed, at each of the two independently durable evidence seams.
        @contextmanager
        def die_after_commit(table):
            connect = case["store"].projections._connection
            before = count(table)
            @contextmanager
            def connection(**kwargs):
                with connect(**kwargs) as c:
                    yield c
                if kwargs.get("writing") and count(table) > before:
                    raise SystemExit(73)
            with monkeypatch.context() as patch:
                patch.setattr(case["store"].projections, "_connection", connection)
                yield

        before_receipts = count("receipts")
        with die_after_commit("observations"), pytest.raises(SystemExit, match="73"):
            run(case, intent, "bluesky", "upload")
        assert count("observations") == 2 and count("receipts") == before_receipts
        assert run(case, intent, "bluesky", "upload")["outcome"] == "confirmed" and len(trace) == 3

        original_finish = delivery.finish
        def fail_receipt(*args):
            original_finish(*args)
            raise RuntimeError("invented receipt commit failure")
        before_receipts = count("receipts")
        with monkeypatch.context() as patch:
            patch.setattr(delivery, "finish", fail_receipt)
            assert run(case, intent, "x", "alt")["outcome"] == "unknown"
        assert count("observations") == 3 and count("receipts") == before_receipts
        assert run(case, intent, "x", "alt")["outcome"] == "confirmed" and len(trace) == 4

        with die_after_commit("receipts"), pytest.raises(SystemExit, match="73"):
            run(case, intent, "x", "create")
        assert count("observations") == count("receipts") == 4
        assert run(case, intent, "x", "create")["outcome"] == "confirmed" and len(trace) == 5
        assert run(case, intent, "bluesky", "create")["outcome"] == "confirmed" and len(trace) == 6

        # Append contradictory positive evidence under the same exact request.
        # Preserve both originals; do not select the latest or release the hold.
        with case["store"].projections._connection(writing=True) as c:
            value = delivery.read(c, intent)
            saved = delivery.attempt(c, value, "x", "create")
            raw = canonical_json({"data":{"id":"999999999", "text":value["text"]}}).encode()
            observation = dict(attempt_id=saved["attempt_id"], request_sha256=saved["request_sha256"],
                source="response", reason="received", http_status=201, complete=True,
                raw_sha256=digest(raw), recorded_at=utc_text(editor.AT))
            with pytest.raises(ValueError, match="delivery_observation_identity"):
                delivery.observe(c, value, saved, dict(observation, request_sha256="f"*64), raw)
            delivery.observe(c, value, saved, observation, raw)
            assert delivery.finish(c, value, saved)["reason"] == "conflicting_delivery_receipts"
            with pytest.raises(delivery.CommandError):
                delivery.hold(c, next(d for d in state[1]["drafts"] if d["id"] == case["draft_id"]))
        assert run(case, intent, "x", "create")["outcome"] == "unknown" and len(trace) == 6
        assert case["store"].read() == state
        from tests.local_delivery_readback import verify
        before_rows = editor.all_application_rows(core[3])
        verify(case, tmp_path, monkeypatch)
        assert editor.all_application_rows(core[3]) == before_rows and len(trace) == 6


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("drift", ["role", "expiry", "state"])
def test_post_barrier_recheck_preserves_original_scope_and_deadline(admitted, core, tmp_path, monkeypatch, drift):
    case = admitted
    _, png = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"]) as (config, trace, _):
        configure(case["store"], tmp_path, config)
        _, result = park(case)
        intent = result["delivery"]["intent_id"]
        for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        original = delivery.before_call
        def drift_after_barrier(authority, c, value, saved, resolve, now):
            if drift == "role":
                def resolve(_):
                    return None
            elif drift == "expiry":
                now += timedelta(seconds=40)
            else:
                # Alter the exact state in this same transaction, then verify
                # currentness. Its rejection rolls back this invented fault.
                version, state = authority._state(c, lock=True)
                state["invented_unrelated_write"] = True
                encoded, fields = p._snapshot(state)
                authority.projections._record(c, "command-core-v1", str(version+1), encoded, fields)
                c.execute("UPDATE theheat_commands.state SET version=%s,snapshot_id=%s WHERE singleton=1", (version+1,str(version+1)))
            return original(authority, c, value, saved, resolve, now)
        with monkeypatch.context() as patch:
            patch.setattr(delivery, "before_call", drift_after_barrier)
            outcome = run(case, intent, "x", "upload")
        assert outcome["outcome"] == "not_sent", outcome
        assert trace == []
        assert run(case, intent, "x", "upload")["outcome"] == "not_sent" and trace == []
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.attempts") == [(1,)]
        blocked = run(case, intent, "x", "alt")
        assert blocked["outcome"] == "withheld" and blocked["reason"] == "delivery_dependency_unconfirmed"
        assert trace == []
        if drift == "role":
            assert run(case, intent, "bluesky", "upload")["outcome"] == "confirmed" and len(trace) == 1


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_prebarrier_fence_reclaim_lost_ack_and_empty_reconciliation(admitted, core, tmp_path, monkeypatch):
    from contextlib import contextmanager
    case = admitted
    _, png = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"]) as (config, trace, _):
        configure(case["store"], tmp_path, config)
        _, result = park(case)
        intent = result["delivery"]["intent_id"]
        for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        authority = case["store"]
        def acquire(owner, at):
            with authority.projections._connection(writing=True) as c:
                authority._validate(c)
                authority._pointer(c, lock=True)
                return delivery.acquire(authority, c, delivery.read(c, intent), "x", "upload", owner, candidate.resolve, at)
        first = acquire("worker-old", editor.AT)
        later = editor.AT + timedelta(seconds=31)
        replacement = acquire("invented-local-worker", later)
        assert first["lease"]["fence"] == 1 and replacement["lease"]["fence"] == 2
        with authority.projections._connection(writing=True) as c:
            with pytest.raises(delivery.CommandError) as stale:
                delivery.begin(authority, c, delivery.read(c, intent), "x", "upload", first["lease"], {}, b"", candidate.resolve, later)
            assert stale.value.code == "delivery_lease_busy"
        with pytest.raises(delivery.CommandError) as regressed:
            acquire("invented-local-worker", editor.AT)
        assert regressed.value.code == "delivery_clock_regressed"
        original_connection = authority.projections._connection
        @contextmanager
        def lost_ack(*, writing=False):
            with original_connection(writing=writing) as c:
                before = c.execute("SELECT count(*) FROM theheat_delivery.attempts").fetchone()[0]
                yield c
                after = c.execute("SELECT count(*) FROM theheat_delivery.attempts").fetchone()[0]
            if writing and after > before:
                raise p.ProjectionError("write_outcome_unknown")
        with monkeypatch.context() as patch:
            patch.setattr(authority.projections, "_connection", lost_ack)
            assert run(case, intent, "x", "upload", at=later)["outcome"] == "unknown"
        assert trace == []
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.attempts") == [(1,)]
        assert run(case, intent, "x", "upload", at=later)["outcome"] == "unknown" and trace == []
        assert run(case, intent, "x", "upload", at=later, reconcile=True)["outcome"] == "unknown"
        assert len(trace) == 1 and trace[0]["method"] == "GET"
        draft = next(d for d in authority.read()[1]["drafts"] if d["id"] == case["draft_id"])
        with authority.projections._connection() as c:
            with pytest.raises(delivery.CommandError) as held:
                delivery.hold(c, draft)
            assert held.value.code == "delivery_prior_outcome_unknown"
        assert run(case, intent, "bluesky", "upload", at=later)["outcome"] == "confirmed"
        assert run(case, intent, "bluesky", "create", at=editor.AT+timedelta(days=1))["outcome"] == "withheld"
        assert len(trace) == 2


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_atomic_failure_unknown_restart_full_restore_and_positive_reconciliation(admitted, core, cluster, tmp_path, monkeypatch):
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    from src.commands.schema import Command
    from src.commands.reducer import _identity

    case = admitted
    prepared, png = editor.prepare_and_attach(case)
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"], mode={("x", "create"):"drop"}) as (config, trace, _):
        config_path = configure(case["store"], tmp_path, config)
        before = case["store"].read()
        original = delivery.enroll
        def fail_after_enrollment(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("invented atomic enrollment fault")
        with monkeypatch.context() as patch:
            patch.setattr(delivery, "enroll", fail_after_enrollment)
            with pytest.raises(RuntimeError, match="invented atomic enrollment fault"):
                park(case)
        assert case["store"].read() == before
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.intents") == [(0,)]
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.work_items") == [(0,)]
        cmd_id = admin(core[3], "SELECT command_id FROM theheat_commands.intents ORDER BY sequence DESC LIMIT 1")[0][0]
        assert case["store"].result(cmd_id) is None
        result = case["store"].consume(candidate.resolve, command_id=cmd_id, now=editor.AT)
        assert result["status"] == "applied", result
        intent = result["delivery"]["intent_id"]
        for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        for platform, stage in (("x","upload"),("x","alt"),("bluesky","upload")):
            assert run(case, intent, platform, stage)["outcome"] == "confirmed"
        assert run(case, intent, "x", "create")["outcome"] == "unknown"
        assert len(trace) == 4
        assert run(case, intent, "x", "create")["outcome"] == "unknown"
        assert len(trace) == 4
        state = case["store"].read()
        draft = next(d for d in state[1]["drafts"] if d["id"] == case["draft_id"])
        pending = Command.from_request(dict(command_id=str(uuid4()), action="edit_revision", requested_at=utc_text(editor.AT),
            expires_at=utc_text(editor.AT + timedelta(minutes=5)), targets=[_identity(draft)],
            payload={"text":"An invented edit after the complete delivery restore."}), candidate.EDITOR, environment="local", now=editor.AT)
        case["store"].accept(pending, candidate.EDITOR, now=editor.AT)
        before_rows, before_catalog = editor.all_application_rows(core[3]), catalogs(core[3])
        projection = case["store"].delivery_projection(case["draft_id"], candidate.resolve, now=editor.AT)
        params, binaries, folder = cluster
        archive = folder / ("delivery-" + uuid4().hex + ".dump")
        common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
        binaries("pg_dump", *common, "-Fc", "-f", str(archive), core[3]["dbname"])
        name = "restore_" + uuid4().hex
        admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
        restored_params = dict(core[3], dbname=name)
        try:
            binaries("pg_restore", *common, "--single-transaction", "-d", name, str(archive))
            authority = PostgresCommandAuthority(**options(restored_params))
            authority.configure_sourced_generation(lambda: case["config"])
            authority.configure_editor_media(**case["store"].editor_media_configuration)
            authority.configure_delivery(config_path)
            restored = dict(case, store=authority)
            assert authority.read() == state
            assert editor.all_application_rows(restored_params) == before_rows
            assert catalogs(restored_params) == before_catalog
            assert authority.delivery_projection(case["draft_id"], candidate.resolve, now=editor.AT) == projection
            assert editor.view(restored, png=prepared["preparation"]["proposal_sha256"]) == png
            assert run(restored, intent, "x", "create")["outcome"] == "unknown" and len(trace) == 4
            assert run(restored, intent, "x", "create", reconcile=True)["outcome"] == "confirmed"
            assert trace[-1]["method"] == "GET" and len(trace) == 5
            assert run(restored, intent, "bluesky", "create")["outcome"] == "confirmed"
            assert len(trace) == 6 and authority.read() == state
            resumed = authority.consume(candidate.resolve, command_id=pending.command_id, now=editor.AT)
            assert resumed["status"] == "applied" and resumed["state_version"] == state[0] + 1
            assert authority.consume(candidate.resolve, command_id=pending.command_id, now=editor.AT) == resumed
            assert not authority.delivery_projection(case["draft_id"], candidate.resolve, now=editor.AT)["intents"][0]["current"]
            assert run(restored, intent, "bluesky", "create")["outcome"] == "confirmed" and len(trace) == 6
            assert not editor.view(restored)["parked"]
        finally:
            admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
