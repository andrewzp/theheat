"""E3 — real PostgreSQL delivery-reconciliation adapter (disposable cluster; CI shard).

The shared W14 vectors run through ``PostgresCommandAuthority.delivery_reconciliation``
and must produce exactly the state the pure rules produce. Invented identifiers
only; no Gist, X, provider or network. The production Gist path is untouched.
"""
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from src.commands import delivery_reconciliation as rec
from src.commands.schema import Principal, utc_text
from src.storage import postgres_projection as p
from tests.test_postgres_command_authority import make_authority as make_authority
from tests.test_postgres_projection import admin, cluster as cluster, database as database

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "w14_delivery_reconciliation_vectors.json").read_text())
PUBLISHER = Principal("pg-publisher", "publisher", "local-fixture")
EDITOR = Principal("pg-editor", "editor", "local-fixture")
NOW = datetime(2026, 10, 30, 11, 0, tzinfo=UTC)


@pytest.fixture
def pg(make_authority):
    make, _owner, params = make_authority
    return make(deepcopy(VECTORS["state"])), params


def _records(params):
    return admin(params, "SELECT snapshot_id FROM theheat_projection.versions WHERE namespace=%s ORDER BY snapshot_id",
                 (rec.PG_NAMESPACE,))


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[case["name"] for case in VECTORS["cases"]])
def test_shared_vectors_through_the_postgres_adapter_match_the_pure_rules(pg, case):
    authority, _params = pg
    expected = deepcopy(VECTORS["state"])
    for step in case["steps"]:
        before = authority.read()
        if "code" in step["expect"]:
            with pytest.raises(rec.ReconciliationError) as refused:
                authority.delivery_reconciliation(step["request"], PUBLISHER, now=NOW)
            assert refused.value.code == step["expect"]["code"] and authority.read() == before
            continue
        expected, pure = rec.decide(expected, step["request"], actor=PUBLISHER.subject, at=utc_text(NOW))
        result = authority.delivery_reconciliation(step["request"], PUBLISHER, now=NOW)
        assert result["status"] == pure["status"] == step["expect"]["status"]
        version, state = authority.read()
        assert state == expected
        assert version == before[0] + (1 if pure["status"] == "applied" else 0) == result["state_version"]


def test_applied_decision_retains_its_reconciliation_origin_and_repeats_are_unchanged(pg):
    authority, params = pg
    confirm = VECTORS["cases"][0]["steps"][0]["request"]
    applied = authority.delivery_reconciliation(confirm, PUBLISHER, now=NOW)
    assert applied["status"] == "applied"
    [(identity,)] = _records(params)
    assert identity == "sha256:" + rec._sha(confirm["reconciliation_id"])
    with authority.projections._connection() as c:
        record = p.PostgresProjectionRepository._read(c, rec.PG_NAMESPACE, identity)[1]
    assert record["origin"] == "reconciliation" and record["authority_version"] == applied["state_version"]
    assert record["actor_subject"] == PUBLISHER.subject and record["result"]["tweet_id"] == confirm["receipt"]["tweet_id"]
    again = authority.delivery_reconciliation(confirm, PUBLISHER, now=NOW)
    assert again["status"] == "unchanged" and again["state_version"] == applied["state_version"]
    with pytest.raises(rec.ReconciliationError, match="reconciliation_id_reused"):
        authority.delivery_reconciliation({**confirm, "reason": "invented different reason"}, PUBLISHER, now=NOW)
    assert len(_records(params)) == 1


def test_interruption_before_commit_leaves_neither_version_nor_record(pg):
    authority, params = pg
    cancel = next(c for c in VECTORS["cases"] if c["name"] == "cancel_unknown_keeps_evidence")["steps"][0]["request"]
    before = authority.read()

    def crash():
        raise RuntimeError("invented interruption")

    with pytest.raises(RuntimeError):
        authority.delivery_reconciliation(cancel, PUBLISHER, now=NOW, before_commit=crash)
    assert authority.read() == before and _records(params) == []
    assert authority.delivery_reconciliation(cancel, PUBLISHER, now=NOW)["status"] == "applied"
    version, state = authority.read()
    row = state["publish_ledger"][cancel["event_id"]]
    assert version == before[0] + 1 and row["operator_cancellation"]["reconciliation_id"] == cancel["reconciliation_id"]
    assert row["tweet_id"] is None and row["phase"] == "unknown"


def test_wrong_role_is_refused_before_any_read_or_write(pg):
    authority, params = pg
    before = authority.read()
    with pytest.raises(rec.ReconciliationError, match="forbidden"):
        authority.delivery_reconciliation(VECTORS["cases"][0]["steps"][0]["request"], EDITOR, now=NOW)
    assert authority.read() == before and _records(params) == []


def test_view_is_read_only(pg):
    authority, params = pg
    before = authority.read()
    view = authority.delivery_reconciliation_view()
    assert view["mutation"] == "none" and authority.read() == before and _records(params) == []
