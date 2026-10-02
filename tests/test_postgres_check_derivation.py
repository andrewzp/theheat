"""The same final-text/history contract through real PostgreSQL transactions."""

import pytest

from src.commands import check_journal as checks, postgres_checks as pg
from src.commands.schema import canonical_json
from tests import test_check_derivation as contract, test_postgres_checks as prior
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_worker import no_provider as no_provider
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_postgres_checks import actual_postgres_helpers as actual_postgres_helpers
from tests.test_check_derivation import (
    test_intake_preserves_raw_result_and_formats_a_separate_checked_text,
    test_current_row_candidate_must_match_even_if_raw_id_is_repeated,
    test_intake_detaches_evidence_before_sql_reuses_caller_inputs,
    test_unavailable_formatter_keeps_history_but_cannot_issue_another_grant,
    test_legacy_reads_late_bytes_and_receipts_do_not_grant_current_permission,
)

case = contract.case


@pytest.fixture
def review_module():
    return pg


@pytest.fixture
def rewrite_packet(core):
    def write(case, packet, *, terminal=True):
        import psycopg
        # Seed a literal schema1 payload and adapter history in the test database.
        # Immutable production APIs cannot perform this historical fixture import.
        with psycopg.connect(**core[3]) as c:
            old = c.execute("SELECT job_id,custom_id,recorded_at FROM theheat_checks.sets WHERE check_set_id=%s",
                            (case["identity"]["check_set_id"],)).fetchone()
            records = contract.history_records(case, packet, old[2], terminal)
            c.execute("SET session_replication_role=replica")
            c.execute("DELETE FROM theheat_checks.sets WHERE check_set_id=%s", (case["identity"]["check_set_id"],))
            c.execute("SET session_replication_role=origin")
            sha = pg._artifact(c, "packet_artifacts", records["packet"])
            c.execute("INSERT INTO theheat_checks.sets VALUES(%s,%s,%s,%s,%s)",
                      (records["identity"], old[0], old[1], sha, old[2]))
            request_sha = pg._artifact(c, "request_artifacts", records["request"])
            binding_sha = pg._artifact(c, "binding_artifacts", canonical_json(records["binding"]).encode())
            c.execute("INSERT INTO theheat_checks.attempts VALUES(%s,%s,%s,%s,%s,%s,%s)",
                      (records["grant"], records["identity"], "deterministic", binding_sha, request_sha, None, old[2]))
            if records["receipt"] is not None:
                receipt_sha = pg._artifact(c, "receipt_artifacts", canonical_json(records["receipt"]).encode())
                c.execute("INSERT INTO theheat_checks.receipts VALUES(%s,%s,%s,%s)",
                          (records["grant"], receipt_sha, "passed", old[2]))
        case["identity"]["check_set_id"] = records["identity"]
        return records
    return write


def test_new_derivation_is_atomic_with_intake_and_keeps_catalog_unchanged(case, core):
    with case["store"].projections._connection() as c:
        packet, _ = pg._packet(c, case["identity"]["check_set_id"], "local")
    assert packet["schema_version"] == 2
    assert checks.packet_verification(packet) == "verified_current_formatter"
    before = prior.snapshot(core[3])
    core[2].initialize_candidate_checks()
    assert prior.snapshot(core[3]) == before
