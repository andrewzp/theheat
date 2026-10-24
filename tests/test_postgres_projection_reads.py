"""Actual PostgreSQL projection transfer counts and bounded corruption cases."""
import json

import pytest

from src.storage import postgres_projection as p
from tests import test_postgres_projection as base

cluster = base.cluster
database = base.database
repository = base.repository
admin = base.admin


class CountedRead:
    """Count only the selected _read; forward real SQL and unmodified values."""

    def __init__(self, connection, *, before_payload=None, damaged_rows=None):
        self.connection = connection
        self.queries = []
        self.fetches = []
        self.before_payload = before_payload
        self.damaged_rows = damaged_rows
        self.payload_rows = []

    def execute(self, sql, parameters=()):
        self.queries.append(sql)
        is_payload = sql.startswith("SELECT a.sha,")
        if is_payload and self.before_payload:
            self.before_payload()
        cursor = self.connection.execute(sql, parameters)
        observed = self

        class Cursor:
            def fetchone(self):
                observed.fetches.append("one")
                return cursor.fetchone()

            def fetchall(self):
                observed.fetches.append("all")
                rows = cursor.fetchall()
                if is_payload:
                    observed.payload_rows = rows
                    if observed.damaged_rows:
                        return observed.damaged_rows(rows)
                return rows

        return Cursor()


@pytest.mark.parametrize("shape", ["distinct", "shared", "empty", "maximum"])
def test_actual_read_round_trips_and_exact_values(repository, record_property, shape, monkeypatch):
    _, repo, _ = repository
    if shape == "shared":
        state = {f"field-{n}": {"invented": [None, -0.0, 1.0, "é🌡"]} for n in range(18)}
    else:
        count = {"distinct": 18, "empty": 0, "maximum": 512}[shape]
        state = {f"field-{n}": n for n in range(count)}
    original = repo.record("read-count", shape, state)
    canonical = p._canonical
    private = p._canonical_private_decoded
    canonical_calls = []
    private_calls = []
    def counted(value):
        canonical_calls.append(value)
        return canonical(value)
    def counted_private(value):
        private_calls.append(value)
        return private(value)
    with repo._connection() as connection:
        repo._validate(connection)
        observed = CountedRead(connection)
        with monkeypatch.context() as patch:
            patch.setattr(p, "_canonical", counted)
            patch.setattr(p, "_canonical_private_decoded", counted_private)
            receipt, actual = repo._read(observed, "read-count", shape)
    assert len(canonical_calls) == 1
    assert len(private_calls) == 2 * len(state)
    assert receipt == original
    assert p._canonical(actual) == p._canonical(state)
    assert len(observed.queries) == len(observed.fetches) == (3 if state else 2)
    distinct = len({p._canonical(value) for value in state.values()})
    assert len(observed.payload_rows) == distinct
    if shape == "shared":
        actual["field-0"]["invented"].append("detached")
        assert actual["field-1"] == state["field-1"]
    record_property("projection_read", json.dumps(dict(
        shape=shape, references=len(state), distinct_artifacts=distinct,
        execute_calls=len(observed.queries), fetch_calls=len(observed.fetches),
        payload_queries=sum("SELECT a.sha," in query for query in observed.queries),
        transferred_artifacts=len(observed.payload_rows),
        canonical_bytes=original.byte_count, same_runtime_connection=True,
    )))


def test_batched_payload_integrity_refuses_damaged_rows(repository):
    """Fault injection changes only returned batch rows; real SQL still runs."""
    _, repo, params = repository
    repo.record("integrity", "valid", {"a": 1, "b": 2})
    faults = {
        "missing": lambda rows: rows[:-1],
        "duplicate": lambda rows: [rows[0], rows[0]],
        "foreign": lambda rows: [("f" * 64, rows[0][1]), rows[1]],
        "malformed": lambda rows: [(rows[0][0],), rows[1]],
        "hash": lambda rows: [(rows[0][0], b"9"), rows[1]],
        "size": lambda rows: [(rows[0][0], b"99"), rows[1]],
        "null": lambda rows: [(rows[0][0], None), rows[1]],
    }
    for label, damage in faults.items():
        with repo._connection() as connection:
            repo._validate(connection)
            observed = CountedRead(connection, damaged_rows=damage)
            with pytest.raises(p.ProjectionError, match="^corrupt_projection_artifact$"):
                repo._read(observed, "integrity", "valid")
            assert len(observed.queries) == 3, label

    # Real, hash-valid but noncanonical storage must still fail after retrieval.
    payload = b"1 "
    digest = p._sha(payload)
    admin(params, "INSERT INTO theheat_projection.artifacts VALUES(%s,%s,%s)", (digest, payload, len(payload)))
    admin(params, "INSERT INTO theheat_projection.versions(namespace,snapshot_id,canonical_sha,byte_count,field_count) VALUES('integrity','noncanonical',%s,8,1)", (p._sha(b'{"a":1}'),))
    admin(params, "INSERT INTO theheat_projection.fields VALUES('integrity','noncanonical',%s,%s)", (b'"a"', digest))
    with pytest.raises(p.ProjectionError, match="^noncanonical_projection_artifact$"):
        repo.read("integrity", "noncanonical")

    # Owner corruption after reference preflight: the real SELECT must return
    # NULL, not the enlarged payload. No scientific/model result is stubbed.
    admin(params, "ALTER TABLE theheat_projection.artifacts DROP CONSTRAINT artifact_identity; ALTER TABLE theheat_projection.artifacts DISABLE TRIGGER artifacts_immutable")
    with pytest.raises(p.ProjectionError, match="^changed_projection_schema$"):
        repo.read("integrity", "valid")

    def grow():
        admin(params, "UPDATE theheat_projection.artifacts SET payload=%s,byte_count=%s WHERE sha=%s", (b"3333", 4, p._sha(b"1")))
    with repo._connection() as connection:
        # Deliberate owner-corrupt catalog: isolate _read's independent byte gate.
        observed = CountedRead(connection, before_payload=grow)
        with pytest.raises(p.ProjectionError, match="^corrupt_projection_artifact$"):
            repo._read(observed, "integrity", "valid")
        assert (p._sha(b"1"), None) in observed.payload_rows
        assert len(observed.queries) == 3


def test_repeated_size_preflight_precedes_payload_fetch(repository, record_property):
    """One valid blob referenced five times exceeds the unchanged snapshot cap."""
    _, repo, params = repository
    payload = b'"' + b"x" * (p.MAX_BYTES // 4) + b'"'
    digest = p._sha(payload)
    admin(params, "INSERT INTO theheat_projection.artifacts VALUES(%s,%s,%s)", (digest, payload, len(payload)))
    admin(params, "INSERT INTO theheat_projection.versions(namespace,snapshot_id,canonical_sha,byte_count,field_count) VALUES('size','repeated',%s,%s,5)", ("0" * 64, p.MAX_BYTES))
    for n in range(5):
        admin(params, "INSERT INTO theheat_projection.fields VALUES('size','repeated',%s,%s)", (p._canonical(str(n)), digest))
    with repo._connection() as connection:
        repo._validate(connection)
        observed = CountedRead(connection)
        with pytest.raises(p.ProjectionError, match="^corrupt_projection_identity$"):
            repo._read(observed, "size", "repeated")
    assert len(observed.queries) == len(observed.fetches) == 2
    assert observed.payload_rows == []
    record_property("projection_preflight", json.dumps(dict(
        references=5, distinct_artifacts=1, one_artifact_bytes=len(payload),
        reference_payload_bytes=5 * len(payload), limit=p.MAX_BYTES,
        execute_calls=2, payload_queries=0,
    )))
