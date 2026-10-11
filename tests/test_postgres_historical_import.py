"""Actual local transactions, process death and combined restore; invented data."""
import multiprocessing
import os
from uuid import uuid4

import pytest

from src.commands.postgres_authority import PostgresCommandAuthority
from src.storage import historical_import as h
from src.storage import postgres_projection as p
from tests.test_command_authority import EDITOR, NOW, command, resolver, story
from tests.test_historical_import import plan
from tests.test_postgres_command_authority import options
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import repository as repository, counts, wrap_connections, admin


def test_exact_second_import_and_changed_id_refusal(repository):
    _, repo, params = repository
    value = plan()
    receipt = h.record_import(repo, value)
    before = counts(params)
    assert h.record_import(repo, value) == h.verify_import(repo, value) == receipt
    assert counts(params) == before
    with pytest.raises(p.ProjectionError, match="projection_idempotency_conflict"):
        h.record_import(repo, plan(b"changed original bytes"))
    assert counts(params) == before
    assert h.verify_import(repo, value) == receipt


@pytest.mark.parametrize("stage", ["artifact", "completion", "commit"])
def test_whole_import_rollback(repository, monkeypatch, stage):
    _, repo, params = repository
    def fail(query, _):
        if stage == "artifact" and query.startswith("INSERT INTO theheat_projection.artifacts"):
            raise RuntimeError("invented failure")
    def commit(_):
        if stage == "commit":
            raise RuntimeError("invented failure")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail, before_commit=commit)
        if stage == "completion":
            original = repo._record
            def record(c, namespace, *args):
                if namespace == h.COMPLETIONS:
                    raise RuntimeError("invented failure")
                return original(c, namespace, *args)
            patch.setattr(repo, "_record", record)
        with pytest.raises(RuntimeError, match="invented failure"):
            h.record_import(repo, plan())
    assert counts(params) == [0, 0, 0]
    with pytest.raises(p.ProjectionError, match="projection_not_found"):
        h.verify_import(repo, plan())


def _die(params, stage):
    repo = p.PostgresProjectionRepository(**options(params))
    patch = pytest.MonkeyPatch()
    if stage == "before":
        wrap_connections(patch, before_commit=lambda _: os._exit(41))
    h.record_import(repo, plan())
    os._exit(42)  # Actual commit succeeded; no receipt reached parent.


@pytest.mark.parametrize("stage,exists", [("before", False), ("after", True)])
def test_child_death_original_id_reconciliation(repository, stage, exists):
    _, repo, params = repository
    child = multiprocessing.get_context("spawn").Process(target=_die, args=(params, stage))
    child.start()
    child.join(timeout=20)
    if child.is_alive():
        child.kill()
        child.join(timeout=5)
        pytest.fail("owned child deadline")
    assert child.exitcode == (42 if exists else 41)
    if exists:
        h.verify_import(repo, plan())
    else:
        assert counts(params) == [0, 0, 0]
        with pytest.raises(p.ProjectionError, match="projection_not_found"):
            h.verify_import(repo, plan())
    before = h.record_import(repo, plan())  # Explicit test replay, same original identity.
    assert h.record_import(repo, plan()) == before


def test_lost_ack_requires_read_only_exact_reconciliation(repository, monkeypatch):
    _, repo, params = repository
    with monkeypatch.context() as patch:
        wrap_connections(patch, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="^write_outcome_unknown$"):
            h.record_import(repo, plan())
    before = counts(params)
    receipt = h.verify_import(repo, plan())
    assert receipt.namespace == h.COMPLETIONS
    assert counts(params) == before


def test_missing_restored_field_is_not_repaired_by_replay(repository):
    _, repo, params = repository
    value = plan()
    h.record_import(repo, value)
    # Simulate a damaged backup as the owned fixture administrator; runtime may
    # neither bypass these immutable guards nor conceal the damaged artifact.
    admin(params, "ALTER TABLE theheat_projection.fields DISABLE TRIGGER fields_immutable")
    admin(params, "DELETE FROM theheat_projection.fields WHERE namespace=%s", ("history.artifacts.v1",))
    admin(params, "ALTER TABLE theheat_projection.fields ENABLE TRIGGER fields_immutable")
    before = counts(params)
    for operation in (h.verify_import, h.record_import):
        with pytest.raises(p.ProjectionError, match="projection_reference_mismatch"):
            operation(repo, value)
        assert counts(params) == before


def test_combined_restore_original_bytes_and_pending_command(database, cluster):
    import psycopg
    _, repo, params = database
    owner = PostgresCommandAuthority(**options(params, params["user"]))
    runtime = PostgresCommandAuthority(**options(params))
    initial = {"drafts": [story()], "publish_ledger": {}}
    owner.initialize(initial, runtime_role="projection_runtime")
    archive = plan()
    h.record_import(repo, archive)
    assert runtime.read() == (0, initial) and runtime.journal() == []
    pending = command(initial["drafts"][0])
    accepted = runtime.accept(pending, EDITOR, now=NOW)
    assert runtime.result(pending.command_id) is None
    args, run, root = cluster
    dump = root / ("history-" + uuid4().hex + ".dump")
    common = ["-h", args["host"], "-p", args["port"], "-U", args["user"], "-w"]
    run("pg_dump", *common, "-Fc", "-f", dump, params["dbname"])
    target = "restore_" + uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(target)))
    try:
        restored_params = {**params, "dbname": target}
        assert admin(restored_params, "SELECT count(*) FROM pg_namespace WHERE nspname LIKE %s", ("theheat_%",)) == [(0,)]
        run("pg_restore", *common, "--single-transaction", "-d", target, dump)
        restored_repo = p.PostgresProjectionRepository(**options(restored_params))
        restored = PostgresCommandAuthority(**options(restored_params))
        assert h.verify_import(restored_repo, archive) == h.verify_import(repo, archive)
        raw_key = next(ident for ns, ident, _ in archive.records if ns == "history.artifacts.v1")
        assert h.original_bytes(restored_repo.read("history.artifacts.v1", raw_key)[1]) == b'{"synthetic":9007199254740993}\n'
        assert restored.read() == runtime.read()
        assert restored.journal() == runtime.journal()
        assert restored.result(pending.command_id) is None
        result = restored.consume(resolver, now=NOW)
        assert result["status"] == "applied"
        assert restored.accept(pending, EDITOR, now=NOW) == accepted
        assert restored.consume(resolver, command_id=pending.command_id, now=NOW) == result
        assert restored.read()[0] == 1
        assert h.verify_import(restored_repo, archive) == h.verify_import(repo, archive)
    finally:
        with psycopg.connect(**args) as c:
            c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(target)))
