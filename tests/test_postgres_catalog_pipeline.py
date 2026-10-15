"""Same catalog SQL/material on actual PG17, including bounded cost readers."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time

import pytest

from src.commands import postgres_cost_projection as cost
from src.storage import postgres_projection as p
from tests.test_postgres_projection import cluster as cluster, database as database


def baseline():
    raw = Path(__file__).with_name("fixtures").joinpath("old_sequential_postgres_catalog.py.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "075b06d28ea953cc5e1911094e3d82e3bf48ef589f54da808f1a43d9942d9bab"
    namespace = dict(SCHEMA=p.SCHEMA, _sha=p._sha, json=json)
    exec(compile(raw, "old_sequential_postgres_catalog.py.txt", "exec"), namespace)
    return namespace["_catalog"]


class Trace:
    """Observe the real driver; no replacement results or transaction control."""
    def __init__(self, connection):
        self.connection = connection
        self.events = []
        self.queries = []
        self.material = []

    @contextmanager
    def pipeline(self):
        self.events.append("enter")
        with self.connection.pipeline():
            yield
        self.events.append("synced")

    def execute(self, query, params=None):
        self.events.append("execute")
        self.queries.append((query, params))
        cursor = self.connection.execute(query, params)
        owner = self

        class Cursor:
            def fetchall(self):
                owner.events.append("fetch")
                rows = cursor.fetchall()
                owner.material.append(rows)
                return rows

        return Cursor()


def canonical(material):
    return json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()


@pytest.mark.parametrize("stage", ["missing", "initialized", "evolved"])
def test_same_nine_queries_rows_types_and_fingerprint(database, stage):
    owner, _, params = database
    import psycopg
    if stage != "missing":
        owner.initialize(runtime_role="projection_runtime")
    with psycopg.connect(**params) as c, c.transaction():
        if stage == "evolved":
            c.execute("""CREATE TABLE theheat_projection.pipeline_sample (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name text COLLATE "C" NOT NULL DEFAULT 'invented',
                active boolean DEFAULT true, CHECK (id > 0))""")
            c.execute("CREATE INDEX pipeline_name ON theheat_projection.pipeline_sample(name)")
            c.execute("""CREATE FUNCTION theheat_projection.pipeline_trigger() RETURNS trigger
                LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RETURN NEW; END $$""")
            c.execute("""CREATE TRIGGER pipeline_insert BEFORE INSERT ON theheat_projection.pipeline_sample
                FOR EACH ROW EXECUTE FUNCTION theheat_projection.pipeline_trigger()""")
            c.execute("GRANT SELECT(name) ON theheat_projection.pipeline_sample TO projection_runtime")
        old, new = Trace(c), Trace(c)
        old_digest, new_digest = baseline()(old), p._catalog(new)
        assert new.queries == old.queries and len(new.queries) == 9
        assert new.material == old.material
        assert canonical(new.material) == canonical(old.material)
        assert new_digest == old_digest == p._sha(canonical(old.material))
        assert old.events == [event for _ in range(9) for event in ("execute", "fetch")]
        # Same driver/transaction: every execute is queued before pipeline sync;
        # every result is fetched only after successful sync, in original order.
        assert new.events == ["enter"] + ["execute"] * 9 + ["synced"] + ["fetch"] * 9


def test_transaction_ddl_visibility_and_rollback(database):
    owner, _, params = database
    import psycopg
    owner.initialize(runtime_role="projection_runtime")
    with psycopg.connect(**params) as c:
        before = p._catalog(c)
        with pytest.raises(RuntimeError, match="rollback invented DDL"):
            with c.transaction():
                c.execute("ALTER TABLE theheat_projection.metadata ADD COLUMN pipeline_added integer DEFAULT 4")
                assert p._catalog(c) == baseline()(c) != before
                raise RuntimeError("rollback invented DDL")
        assert p._catalog(c) == baseline()(c) == before


def test_pipeline_sql_error_returns_no_fingerprint_and_rolls_back(database):
    owner, _, params = database
    import psycopg
    owner.initialize(runtime_role="projection_runtime")

    class Broken(Trace):
        def execute(self, query, params=None):
            if len(self.queries) == 4:
                query = "SELECT nonexistent_catalog_column FROM pg_namespace WHERE nspname=%s"
            return super().execute(query, params)

    with psycopg.connect(**params) as c:
        before = p._catalog(c)
        traced = Broken(c)
        with pytest.raises(psycopg.errors.UndefinedColumn):
            with c.transaction():
                c.execute("ALTER TABLE theheat_projection.metadata ADD COLUMN must_rollback integer")
                p._catalog(traced)
        assert "synced" not in traced.events and not traced.material
        assert p._catalog(c) == baseline()(c) == before


class SynchronousOnly(Trace):
    def pipeline(self):
        raise AssertionError("cost read must not enter the driver pipeline")


def test_cost_wrapper_executes_synchronously_and_fetches_all_rows(database):
    owner, _, params = database
    import psycopg
    owner.initialize(runtime_role="projection_runtime")
    with psycopg.connect(**params) as c, c.transaction():
        traced = SynchronousOnly(c)
        reader = cost.Read(traced, time.monotonic() + cost.SECONDS)
        assert p._catalog(reader) == baseline()(c)
        assert len(traced.queries) == 18 and len(traced.material) == 9
        assert all("set_config('statement_timeout'" in q for q, _ in traced.queries[::2])
        assert [q for q, _ in traced.queries[1::2]] == [q for q, _ in TraceQueries(c).queries]
        limits = [(int(v[0]), int(v[1])) for _, v in traced.queries[::2]]
        assert all(0 < statement <= 1500 and 0 < lock <= 250 for statement, lock in limits)
        assert limits == sorted(limits, reverse=True)
        assert traced.events == ["execute"] * 18 + ["fetch"] * 9


def TraceQueries(c):
    traced = Trace(c)
    baseline()(traced)
    return traced


def test_cost_pipeline_entry_and_exit_use_original_deadline(database):
    _, _, params = database
    import psycopg
    assert cost.SECONDS == 3.0
    with psycopg.connect(**params) as c, c.transaction():
        traced = SynchronousOnly(c)
        expired = cost.Read(traced, time.monotonic() - 1)
        with pytest.raises(cost.Deadline), expired.pipeline():
            pytest.fail("expired context entered")
        assert not traced.events
        started = time.monotonic()
        reader = cost.Read(traced, started + cost.SECONDS)
        with pytest.raises(cost.Deadline), reader.pipeline():
            # Real elapsed time, no clock monkeypatch or shorter product limit.
            c.execute("SELECT pg_sleep(%s)", (cost.SECONDS + 0.02,))
        assert time.monotonic() >= reader.deadline == started + 3.0
        assert not traced.events


def test_cost_catalog_cumulative_window_still_refuses_late_result(database):
    _, _, params = database
    import psycopg

    class Delayed(SynchronousOnly):
        def execute(self, query, params=None):
            if "set_config('statement_timeout'" not in query:
                self.connection.execute("SELECT pg_sleep(0.4)")
            return super().execute(query, params)

    with psycopg.connect(**params) as c, c.transaction():
        traced = Delayed(c)
        started = time.monotonic()
        reader = cost.Read(traced, started + cost.SECONDS)
        # The shrinking SQL timeout may cancel the final delay before the
        # monotonic check: either original fail-closed boundary is legitimate.
        with pytest.raises((cost.Deadline, psycopg.errors.QueryCanceled)):
            p._catalog(reader)
        assert 2.8 <= time.monotonic() - started < 4
        assert len(traced.queries) <= 18 and not traced.material
        assert reader.deadline == started + 3.0


def test_cost_catalog_statement_cancel_is_not_a_partial_fingerprint(database):
    owner, _, params = database
    import psycopg
    owner.initialize(runtime_role="projection_runtime")

    class Slow(SynchronousOnly):
        def execute(self, query, params=None):
            if "set_config('statement_timeout'" not in query:
                self.connection.execute("SELECT pg_sleep(2)")
            return super().execute(query, params)

    with psycopg.connect(**params) as c:
        before = p._catalog(c)
        traced = Slow(c)
        started = time.monotonic()
        with pytest.raises(psycopg.errors.QueryCanceled):
            with c.transaction():
                c.execute("ALTER TABLE theheat_projection.metadata ADD COLUMN must_rollback integer")
                p._catalog(cost.Read(traced, started + cost.SECONDS))
        assert 1.3 <= time.monotonic() - started < cost.SECONDS
        assert len(traced.queries) == 1 and not traced.material
        assert p._catalog(c) == before
