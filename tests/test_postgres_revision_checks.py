"""Actual immutable catalog evolution and saved-revision checks, offline only."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.commands import postgres_checks as pg, postgres_revision_checks as revisions
from src.storage import postgres_projection as p
from tests.test_postgres_projection import (
    cluster as cluster,
    database as database,
    admin,
    wrap_connections,
)
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_batch_worker import no_provider as no_provider
from tests.test_postgres_checks import store as store
from tests.two_bot.test_batch_contract import inputs as inputs

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


def catalogs(store):
    with store.projections._connection() as c:
        return {
            schema: (revisions.metadata(c, schema), p._catalog(c, schema))
            for schema in ("theheat_checks", "theheat_check_executions")
        }


def test_additive_upgrade_keeps_original_metadata_and_observation_catalog(store, core):
    core[2].initialize_check_executions()
    before = catalogs(store)
    core[2].initialize_revision_checks(now=NOW)
    after = catalogs(store)
    assert before["theheat_checks"][0] == after["theheat_checks"][0]
    assert before["theheat_checks"][1] != after["theheat_checks"][1]
    assert before["theheat_check_executions"] == after["theheat_check_executions"]
    with store.projections._connection() as c:
        pg.validate(c, "local")
        retained = c.execute("SELECT * FROM theheat_checks.schema_upgrades").fetchall()
    core[2].initialize_revision_checks(now=NOW)
    core[2].initialize_candidate_checks()
    core[2].initialize_check_executions()
    with store.projections._connection() as c:
        assert c.execute("SELECT * FROM theheat_checks.schema_upgrades").fetchall() == retained
    # Runtime cannot install or alter the owner-only immutable receipt.
    with pytest.raises(p.ProjectionError):
        store.initialize_revision_checks(now=NOW)
    for statement in (
        "DELETE FROM theheat_checks.schema_upgrades",
        "UPDATE theheat_checks.metadata SET version=2",
        "INSERT INTO theheat_checks.schema_upgrades SELECT * FROM theheat_checks.schema_upgrades",
    ):
        with pytest.raises(Exception):
            with store.projections._connection(writing=True) as c:
                c.execute(statement)


def test_upgrade_failure_rolls_back_ddl_and_acl_together(store, core, monkeypatch):
    core[2].initialize_check_executions()
    before = catalogs(store)

    def fail(c):
        raise RuntimeError("before commit")

    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=fail)
        with pytest.raises(RuntimeError, match="before commit"):
            core[2].initialize_revision_checks(now=NOW)
    assert catalogs(store) == before
    assert admin(core[3], "SELECT to_regclass('theheat_checks.schema_upgrades')") == [(None,)]
    core[2].initialize_revision_checks(now=NOW)


def test_original_catalog_validator_refuses_upgrade_before_work(store, core):
    # Exact validate() source from reviewed parent d4714c0, not a rewritten gate.
    source = (
        Path(__file__)
        .with_name("fixtures")
        .joinpath("old_candidate_checks_validate.py.txt")
        .read_bytes()
    )
    assert p._sha(source) == "0ffcd55f5671b9fd8633c3ae85c3d15436bd0c61e24ddabf9fa26453a11d4f58"
    namespace = dict(vars(pg))
    exec(compile(source, "old_candidate_checks_validate.py.txt", "exec"), namespace)
    with store.projections._connection() as c:
        namespace["validate"](c, "local")
    core[2].initialize_revision_checks(now=NOW)
    with store.projections._connection() as c:
        with pytest.raises(pg.checks.CheckJournalError, match="changed_check_schema"):
            namespace["validate"](c, "local")


@pytest.mark.parametrize("step", range(9))
def test_every_upgrade_statement_group_is_atomic(store, core, monkeypatch, step):
    core[2].initialize_check_executions()
    before = catalogs(store)
    seen = []

    def fail(query, c):
        if (
            query.startswith("-- Explicit owner-only evolution")
            or "theheat_checks.schema_upgrades" in query
            and query.startswith(("REVOKE", "Composed", "INSERT"))
            or "theheat_checks.draft_leases" in query
            and query.startswith(("REVOKE", "Composed"))
        ):
            seen.append(query)
            if len(seen) == step + 1:
                raise RuntimeError("atomic upgrade stop")

    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="atomic upgrade stop"):
            core[2].initialize_revision_checks(now=NOW)
    assert len(seen) == step + 1
    assert catalogs(store) == before
    assert admin(core[3], "SELECT to_regclass('theheat_checks.schema_upgrades')") == [(None,)]


def test_owner_upgrades_serialize_and_retain_one_receipt(store, core):
    from concurrent.futures import ThreadPoolExecutor

    core[2].initialize_check_executions()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(core[2].initialize_revision_checks, now=NOW) for _ in range(2)]
        for future in futures:
            future.result()
    with store.projections._connection() as c:
        pg.validate(c, "local")
        assert c.execute("SELECT count(*) FROM theheat_checks.schema_upgrades").fetchone() == (1,)


@pytest.mark.parametrize(
    "tamper",
    [
        "DROP TABLE theheat_checks.schema_upgrades",
        "ALTER TABLE theheat_checks.sets DROP CONSTRAINT sets_origin",
        "GRANT INSERT ON theheat_checks.schema_upgrades TO projection_runtime",
        "ALTER TABLE theheat_checks.draft_leases DISABLE TRIGGER draft_leases_progress",
    ],
)
def test_changed_upgrade_catalog_never_infers_or_repairs_receipt(store, core, tamper):
    core[2].initialize_revision_checks(now=NOW)
    admin(core[3], tamper)
    with pytest.raises(pg.checks.CheckJournalError):
        with store.projections._connection() as c:
            pg.validate(c, "local")


def test_populated_legacy_batch_rows_and_raw_observations_survive_then_continue(
    store, core, monkeypatch, inputs
):
    from tests import test_postgres_check_observations as obs, test_postgres_checks as prior

    core[2].initialize_check_executions()
    case = prior.legacy.case.__wrapped__(store, inputs, monkeypatch)
    started = prior.start(case, "deterministic")
    raw = b"invented raw bytes, including an unresolved billable-history representation"
    obs.record(case, obs.observation(case, started, raw), raw)
    prior.finish(case, started)
    before = obs.snapshot(core[3])
    core[2].initialize_revision_checks(now=NOW)
    after = obs.snapshot(core[3])
    for key, rows in before.items():
        assert rows == (
            [row[:5] for row in after[key]] if key == ("theheat_checks", "sets") else after[key]
        )
    assert prior.start(case, "safety")[0]["dispatch_granted"]
    assert obs.response(case, obs.observation(case, started, raw)) == raw
