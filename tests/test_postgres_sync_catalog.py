"""Actual additive catalog3, original-row parity and failed-owner upgrades."""
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.commands import postgres_checks as pg, postgres_revision_checks as revisions, postgres_sync_checks as sync
from src.storage import postgres_projection as p
from tests import test_postgres_revision_checks as prior
from tests.test_postgres_projection import cluster as cluster, database as database, admin, wrap_connections
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_postgres_editor_media import all_application_rows, admitted as admitted
from tests.native_profile_helpers import native_dependencies as native_dependencies


def test_catalog3_preserves_original_metadata_receipt_and_repeated_owner_init(store, core):
    core[2].initialize_revision_checks(now=prior.NOW)
    before = prior.catalogs(store)
    receipt = admin(core[3], "SELECT * FROM theheat_checks.schema_upgrades WHERE upgrade_version=2")
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(core[2].initialize_synchronous_checks, now=prior.NOW) for _ in range(2)]:
            future.result()
    after = prior.catalogs(store)
    assert before["theheat_checks"][0] == after["theheat_checks"][0]
    assert before["theheat_check_executions"] == after["theheat_check_executions"]
    assert before["theheat_checks"][1] != after["theheat_checks"][1]
    assert admin(core[3], "SELECT * FROM theheat_checks.schema_upgrades WHERE upgrade_version=2") == receipt
    assert admin(core[3], "SELECT upgrade_version FROM theheat_checks.schema_upgrades ORDER BY 1") == [(2,), (3,)]
    rows = all_application_rows(core[3])
    core[2].initialize_synchronous_checks(now=prior.NOW)
    core[2].initialize_revision_checks(now=prior.NOW)
    assert all_application_rows(core[3]) == rows
    with pytest.raises(p.ProjectionError):
        store.initialize_synchronous_checks(now=prior.NOW)


@pytest.mark.parametrize("statements", [1,2,3,4])
def test_each_partial_ddl_or_receipt_rolls_back_exact_catalog2(store, core, monkeypatch, statements):
    core[2].initialize_revision_checks(now=prior.NOW)
    before, rows = prior.catalogs(store), all_application_rows(core[3])
    if statements < 4:
        original = sync.MIGRATION
        partial = ";".join(original.read_text().split(";")[:statements])+";SELECT 1/0"
        monkeypatch.setattr(sync, "MIGRATION", SimpleNamespace(read_bytes=original.read_bytes, read_text=lambda:partial))
        error = p.ProjectionError
    else:
        def stop(query, c):
            if query.startswith("INSERT INTO theheat_checks.schema_upgrades VALUES(3,"):
                raise RuntimeError("invented receipt crash")
        wrap_connections(monkeypatch, after_execute=stop)
        error = RuntimeError
    with pytest.raises(error):
        core[2].initialize_synchronous_checks(now=prior.NOW)
    assert prior.catalogs(store) == before and all_application_rows(core[3]) == rows


def test_exact_previous_binary_validator_refuses_catalog3(store, core):
    core[2].initialize_revision_checks(now=prior.NOW)
    raw = Path(__file__).with_name("fixtures").joinpath("old_revision_catalog_validate.py.txt").read_bytes()
    assert p._sha(raw) == "286fbf81a69368c61ccf79e69726b241ba6efcb658b3c1d6298c4ea4f592c1c0"
    namespace = dict(vars(revisions))
    exec(compile(raw, "old_revision_catalog_validate.py.txt", "exec"), namespace)
    def previous():
        with store.projections._connection() as c:
            original = revisions.metadata(c, "theheat_checks")
            namespace["validate_catalog"](c, original, "local", (original["owner_role"], original["runtime_role"]))
    previous()
    core[2].initialize_synchronous_checks(now=prior.NOW)
    with pytest.raises(pg.checks.CheckJournalError, match="revision_check_upgrade_receipt_required"):
        previous()


def test_populated_batch_receipts_survive_catalog3_and_continue_real_checks(store, core, inputs, monkeypatch):
    from tests import test_postgres_check_observations as obs, test_postgres_checks as batch
    case = batch.legacy.case.__wrapped__(store, inputs, monkeypatch)
    started = batch.start(case, "deterministic")
    raw = b"invented retained original batch evidence"
    obs.record(case, obs.observation(case, started, raw), raw)
    batch.finish(case, started)
    core[2].initialize_revision_checks(now=prior.NOW)
    before = all_application_rows(core[3])
    core[2].initialize_synchronous_checks(now=prior.NOW)
    after = all_application_rows(core[3])
    for key, rows in before.items():
        if key == ("theheat_checks", "sets"):
            assert rows == [row[:-2] for row in after[key]]
        elif key == ("theheat_checks", "schema_upgrades"):
            assert rows == after[key][:1]
        else:
            assert rows == after[key]
    assert batch.start(case, "safety")[0]["dispatch_granted"]
    assert obs.response(case, obs.observation(case, started, raw)) == raw


@pytest.mark.parametrize("statement", [
    "ALTER TABLE theheat_checks.sets DROP CONSTRAINT sets_origin",
    "ALTER TABLE theheat_checks.sets DROP CONSTRAINT sets_sync_projection",
    "ALTER TABLE theheat_checks.draft_leases DISABLE TRIGGER draft_leases_progress",
    "GRANT INSERT ON theheat_checks.schema_upgrades TO projection_runtime",
])
def test_changed_catalog3_refuses_without_repair(store, core, statement):
    core[2].initialize_synchronous_checks(now=prior.NOW)
    admin(core[3], statement)
    with pytest.raises(pg.checks.CheckJournalError):
        with store.projections._connection() as c:
            pg.validate(c, "local")


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.revision_check_protocol(1)
def test_populated_saved_media_receipts_survive_catalog3_and_continue(admitted, core, monkeypatch):
    from tests import test_postgres_editor_media as editor, test_check_executor as executor
    editor.prepare_and_attach(admitted)
    command, identity, packet = editor.request_revision(admitted)
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO"), executor.envelope(editor.fact_pass(admitted["text"]))])
    for stage in ("deterministic", "safety"):
        assert editor.run_revision(admitted, command, packet, stage)["outcome"] == "completed"
    assert packet["origin_kind"] == "saved_draft_revision_v1" and len(sent) == 1
    assert admin(core[3], "SELECT upgrade_version FROM theheat_checks.schema_upgrades") == [(2,)]
    before = all_application_rows(core[3])
    assert before[("theheat_checks", "draft_leases")]
    assert before[("theheat_check_executions", "observations")]
    core[2].initialize_synchronous_checks(now=editor.AT)
    after = all_application_rows(core[3])
    for key, rows in before.items():
        if key == ("theheat_checks", "sets"):
            assert rows == [row[:-2] for row in after[key]]
            assert all(row[-2:] == (None, None) for row in after[key])
        elif key == ("theheat_checks", "schema_upgrades"):
            assert rows == after[key][:1]
        else:
            assert rows == after[key]
    assert editor.run_revision(admitted, command, packet, "fact_check")["outcome"] == "completed"
    assert len(sent) == 2
    retained = admitted["store"].check_execution("read", {"check_set_id":identity}, now=editor.utc_text(editor.AT))
    assert retained["packet"] == packet
