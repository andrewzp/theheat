"""Real PostgreSQL 17 contract tests. Required CI opts in; no provider calls.

THEHEAT_TEST_POSTGRES=1 requires the driver and binaries (missing means failure).
Each session owns a fresh private Unix-only cluster; never connect to a user DB.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import math
import os
import shutil
import subprocess
import tempfile
import threading
import uuid

import pytest

from src.storage import postgres_projection as p


@pytest.fixture(scope="module")
def cluster():
    if os.environ.get("THEHEAT_TEST_POSTGRES") != "1":
        pytest.skip("real PostgreSQL profile not requested; required PR CI enables it")
    assert not any(k.startswith("PG") for k in os.environ), "ambient PG configuration refused"
    import psycopg  # Deliberately fail, never importorskip, in the requested profile.

    bindir = os.environ.get("THEHEAT_POSTGRES_BINDIR")
    tools = {}
    for name in ("initdb", "pg_ctl", "pg_dump", "pg_restore"):
        executable = str(Path(bindir) / name) if bindir else shutil.which(name)
        assert executable and Path(executable).is_file(), f"PostgreSQL 17 {name} required"
        tools[name] = executable
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    with tempfile.TemporaryDirectory(prefix="theheat-pg-", dir="/tmp") as directory:
        root = Path(directory)
        root.chmod(0o700)
        socket = root / "socket"
        socket.mkdir(mode=0o700)
        data = root / "data"
        args = dict(host=str(socket), port=55473, user="projection_owner", dbname="postgres",
                    password="", passfile=str(root / "password-file-disabled"), autocommit=True)

        def command(name, *arguments):
            return subprocess.run([tools[name], *map(str, arguments)], check=True, env=env,
                                  capture_output=True, text=True, timeout=60)

        command("initdb", "-D", data, "-U", args["user"], "--auth-local=trust",
                "--auth-host=reject", "--encoding=UTF8", "--no-locale", "--data-checksums")
        try:
            command("pg_ctl", "-D", data, "-l", root / "server.log", "-o",
                    f"-c listen_addresses='' -k {socket} -p 55473", "-w", "start")
            with psycopg.connect(**args) as c:
                assert 170000 <= c.info.server_version < 180000
                assert c.execute("SHOW listen_addresses").fetchone() == ("",)
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
            yield args, command, root
        finally:
            # Even an interrupted start may have launched this task-owned server.
            if (data / "postmaster.pid").exists():
                command("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


@pytest.fixture
def database(cluster, monkeypatch):
    import psycopg
    for key in tuple(os.environ):
        if key.startswith("PG"):
            monkeypatch.delenv(key)
    args, command, root = cluster
    name = "projection_" + uuid.uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    params = {**args, "dbname": name}
    owner = p.PostgresProjectionRepository(socket_directory=args["host"], port=args["port"],
                                           database=name, user=args["user"])
    runtime = p.PostgresProjectionRepository(socket_directory=args["host"], port=args["port"],
                                             database=name, user="projection_runtime")
    yield owner, runtime, params
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


@pytest.fixture
def repository(database):
    owner, repo, params = database
    owner.initialize(runtime_role="projection_runtime")
    return owner, repo, params


def admin(params, sql, values=()):
    import psycopg
    with psycopg.connect(**params) as c:
        result = c.execute(sql, values)
        return result.fetchall() if result.description else []


def counts(params):
    return [admin(params, f"SELECT count(*) FROM {p.SCHEMA}.{table}")[0][0]
            for table in ("versions", "artifacts", "fields")]


def test_migrate_idempotent_roundtrip_reuse_and_detach(repository):
    owner, repo, params = repository
    owner.initialize(runtime_role="projection_runtime")
    state = {"drafts": [{"id": "synthetic", "text": "Synthetic fixture."}], "ledger": [],
             "unknown": {"空\u0000": [None, True, False, -0.0, 0.0, 0, 1.0, 1, 1e-200, 1e200,
                                      p.MAX_INTEGER, -p.MAX_INTEGER, "é🌡\u0000"]}}
    receipt = repo.record("test", "first", state)
    assert repo.record("test", "first", state) == receipt
    restored_receipt, restored = repo.read("test", "first")
    assert restored_receipt == receipt
    assert p._canonical(restored) == p._canonical(state)
    assert type(restored["unknown"]["空\u0000"][5]) is int
    assert math.copysign(1, restored["unknown"]["空\u0000"][3]) == -1
    repo.record("test", "second", state)
    assert counts(params) == [2, 3, 6]
    state["ledger"].append("changed by caller")
    restored["drafts"].clear()
    assert repo.read("test", "first")[1]["ledger"] == []
    assert len(repo.read("test", "first")[1]["drafts"]) == 1
    assert repo.record("test", "empty", {}).field_count == 0
    assert repo.read("test", "empty")[1] == {}


@pytest.mark.parametrize("left,right", [(1, 1.0), (0.0, -0.0), ([], {}), ("é", "e\u0301")])
def test_identity_does_not_coerce(repository, left, right):
    _, repo, _ = repository
    original = repo.record("test", "identity", {"value": left})
    with pytest.raises(p.ProjectionError, match="^projection_idempotency_conflict$"):
        repo.record("test", "identity", {"value": right})
    assert repo.read("test", "identity")[0] == original


@pytest.mark.parametrize("value,code", [
    ({"v": 2**53}, "unsafe_json_integer"), ({"v": float("nan")}, "nonfinite_json_number"),
    ({"v": float("inf")}, "nonfinite_json_number"), ({"v": (1,)}, "unsupported_json_value"),
    ({"v": b"bytes"}, "unsupported_json_value"), ({1: 1}, "invalid_json_key"),
    ({"v": "\ud800"}, "invalid_json"), ({"a" * 1023: None}, "field_name_bound"),
    ({str(n): n for n in range(513)}, "invalid_projection"),
], ids=["large-int", "nan", "infinity", "tuple", "bytes", "key", "surrogate", "key-size", "fields"])
def test_admission(value, code):
    with pytest.raises(p.ProjectionError, match=f"^{code}$"):
        p._snapshot(value)


def test_depth_nodes_size_and_duplicate_limits(monkeypatch):
    deep = {}
    for _ in range(34):
        deep = {"v": deep}
    for value in (deep,):
        with pytest.raises(p.ProjectionError, match="projection_structure_bound"):
            p._snapshot(value)
    cycle = []
    cycle.append(cycle)
    with pytest.raises(p.ProjectionError, match="projection_structure_bound"):
        p._snapshot({"v": cycle})
    with pytest.raises(p.ProjectionError, match="projection_byte_bound"):
        p._snapshot({"v": "x" * p.MAX_BYTES})
    monkeypatch.setattr(p, "MAX_NODES", 10)
    with pytest.raises(p.ProjectionError, match="projection_structure_bound"):
        p._snapshot({"v": [None] * 10})
    for invalid in (b'{"a":1,"a":2}', b'{"a":NaN}', b'"\xff"'):
        with pytest.raises(p.ProjectionError, match="invalid_stored_json"):
            p._decode(invalid)


def test_missing_and_ambient_configuration(repository, monkeypatch):
    _, repo, _ = repository
    with pytest.raises(p.ProjectionError, match="projection_not_found"):
        repo.read("test", "absent")
    with monkeypatch.context() as patch:
        patch.setenv("PGSERVICE", "private credentials must not appear")
        with pytest.raises(p.ProjectionError, match="^ambient_postgres_configuration_refused$"):
            repo.record("test", "absent", {})


@pytest.mark.parametrize("sql,code", [
    ("ALTER TABLE theheat_projection.versions ADD COLUMN unexpected text", "changed_projection_schema"),
    ("CREATE TABLE theheat_projection.unexpected(v int)", "changed_projection_schema"),
    ("ALTER TABLE theheat_projection.artifacts DISABLE TRIGGER artifacts_immutable", "changed_projection_schema"),
    ("GRANT CREATE ON SCHEMA theheat_projection TO projection_runtime", "changed_projection_schema"),
    ("GRANT EXECUTE ON FUNCTION theheat_projection.refuse_mutation() TO PUBLIC", "changed_projection_schema"),
    ("ALTER TABLE theheat_projection.metadata DISABLE TRIGGER metadata_immutable; UPDATE theheat_projection.metadata SET version=2; ALTER TABLE theheat_projection.metadata ENABLE TRIGGER metadata_immutable", "unsupported_projection_schema"),
], ids=["column", "table", "trigger", "schema-grant", "function-grant", "version"])
def test_schema_changes_refused(repository, sql, code):
    owner, repo, params = repository
    admin(params, sql)
    for operation in (lambda: repo.record("t", "v", {}), lambda: repo.read("t", "v"),
                      lambda: owner.initialize(runtime_role="projection_runtime")):
        with pytest.raises(p.ProjectionError, match=f"^{code}$"):
            operation()


def test_unrelated_schema_not_overwritten(database):
    owner, _, params = database
    admin(params, "CREATE SCHEMA theheat_projection; CREATE TABLE theheat_projection.private_table(v text)")
    with pytest.raises(p.ProjectionError):
        owner.initialize(runtime_role="projection_runtime")
    assert admin(params, "SELECT to_regclass('theheat_projection.private_table')")[0][0]


def test_role_and_environment_boundary(repository):
    owner, repo, params = repository
    with pytest.raises(p.ProjectionError, match="non_owner_runtime_role_required"):
        owner.record("t", "v", {})
    repo.environment = "preview"
    with pytest.raises(p.ProjectionError, match="projection_environment_mismatch"):
        repo.read("t", "v")
    with pytest.raises(p.ProjectionError, match="production_adapter_unavailable"):
        p.PostgresProjectionRepository(socket_directory=repo.socket_directory, database=repo.database,
                                       user=repo.user, environment="production")
    with pytest.raises(p.ProjectionError, match="explicit_local_socket_required"):
        p.PostgresProjectionRepository(socket_directory="localhost", database="d", user="u")
    for invalid in ("name'; SELECT 1", "", "x" * 161):
        with pytest.raises(p.ProjectionError, match="invalid_identifier"):
            repo.record(invalid, "v", {})


@pytest.mark.parametrize("statement", [
    "UPDATE theheat_projection.versions SET byte_count=2",
    "DELETE FROM theheat_projection.versions",
    "TRUNCATE theheat_projection.artifacts CASCADE",
    "ALTER TABLE theheat_projection.versions ADD COLUMN extra int",
    "DROP TABLE theheat_projection.fields",
    "CREATE TABLE theheat_projection.extra(v int)",
    "ALTER TABLE theheat_projection.fields DISABLE TRIGGER ALL",
    "INSERT INTO theheat_projection.metadata VALUES(1,1,'x','x','local','x','x')",
], ids=["update", "delete", "truncate", "alter", "drop", "create", "disable", "metadata"])
def test_non_owner_permissions(repository, statement):
    import psycopg
    _, repo, params = repository
    receipt = repo.record("t", "v", {"v": "synthetic"})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin({**params, "user": repo.user}, statement)
    assert repo.read("t", "v")[0] == receipt


@pytest.mark.parametrize("operation", ["UPDATE theheat_projection.versions SET byte_count=2",
                                       "DELETE FROM theheat_projection.fields",
                                       "TRUNCATE theheat_projection.artifacts CASCADE"])
def test_owner_requires_explicit_admin_bypass(repository, operation):
    import psycopg
    _, _, params = repository
    with pytest.raises(psycopg.errors.RaiseException, match="immutable projection archive"):
        admin(params, operation)


@pytest.mark.parametrize("same", [True, False])
def test_real_concurrent_same_key(repository, same):
    _, repo, params = repository
    barrier = threading.Barrier(2)
    def write(n):
        barrier.wait(timeout=10)
        try:
            return repo.record("concurrent", "same", {"value": 0 if same else n})
        except p.ProjectionError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [0, 1]))
    receipts = [r for r in results if isinstance(r, p.ProjectionReceipt)]
    assert len(receipts) == (2 if same else 1)
    if same:
        assert receipts[0] == receipts[1]
    else:
        assert "projection_idempotency_conflict" in results
    assert counts(params) == [1, 1, 1]
    assert repo.read("concurrent", "same")[0] == receipts[0]


def test_concurrent_overlapping_artifacts(repository):
    _, repo, params = repository
    barrier = threading.Barrier(2)
    def write(n):
        barrier.wait(timeout=10)
        return repo.record("concurrent", str(n), {"a": n, "b": 1 - n})
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(write, [0, 1]))
    assert len(receipts) == 2
    assert counts(params) == [2, 2, 4]


def wrap_connections(monkeypatch, *, after_execute=None, before_commit=None, lost_ack=False):
    """Inject failure around actual libpq transactions, never fake SQL results."""
    import psycopg
    connect = psycopg.connect
    class Connection:
        def __init__(self, conn):
            self.conn = conn
        def __getattr__(self, name):
            return getattr(self.conn, name)
        def __enter__(self):
            self.conn.__enter__()
            return self
        def __exit__(self, *args):
            return self.conn.__exit__(*args)
        def execute(self, query, *args, **kwargs):
            cursor = self.conn.execute(query, *args, **kwargs)
            if after_execute:
                after_execute(str(query), self.conn)
            return cursor
        @contextmanager
        def transaction(self):
            with self.conn.transaction():
                yield
                if before_commit:
                    before_commit(self.conn)
            if lost_ack:
                raise psycopg.OperationalError("synthetic private commit response lost")
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: Connection(connect(**kwargs)))
    return connect


@pytest.mark.parametrize("stage", ["versions", "artifacts", "fields"])
def test_each_partial_stage_rolls_back(repository, monkeypatch, stage):
    _, repo, params = repository
    def fail(query, _):
        if query.startswith(f"INSERT INTO {p.SCHEMA}.{stage}"):
            raise RuntimeError("synthetic injected failure")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic injected failure"):
            repo.record("t", "v", {"a": 1, "b": 2})
    assert counts(params) == [0, 0, 0]
    repo.record("t", "v", {"a": 1, "b": 2})


def test_receipt_after_commit_and_lost_ack_retry(repository, monkeypatch):
    _, repo, params = repository
    import psycopg
    connect = psycopg.connect
    seen = []
    def check_uncommitted(_):
        with connect(**params) as other:
            seen.append(other.execute("SELECT count(*) FROM theheat_projection.versions").fetchone()[0])
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=check_uncommitted, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="^write_outcome_unknown$"):
            repo.record("t", "lost", {"v": "synthetic"})
    assert seen == [0]
    receipt, value = repo.read("t", "lost")
    assert repo.record("t", "lost", value) == receipt
    assert counts(params) == [1, 1, 1]


def test_killed_connection_before_commit_has_no_receipt_or_partial_rows(repository, monkeypatch):
    _, repo, params = repository
    def terminate(connection):
        connection.execute("SELECT pg_terminate_backend(pg_backend_pid())")
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=terminate)
        with pytest.raises(p.ProjectionError, match="^write_outcome_unknown$"):
            repo.record("t", "killed", {"v": "synthetic"})
    assert counts(params) == [0, 0, 0]


def test_bad_hash_and_incomplete_packet_refused(repository):
    import psycopg
    _, repo, params = repository
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(params, "INSERT INTO theheat_projection.artifacts VALUES(%s,%s,%s)", ("0" * 64, b'1', 1))
    admin(params, "INSERT INTO theheat_projection.versions(namespace,snapshot_id,canonical_sha,byte_count,field_count) VALUES('t','partial',%s,7,1)", ("0" * 64,))
    with pytest.raises(p.ProjectionError, match="projection_reference_mismatch"):
        repo.read("t", "partial")


@pytest.mark.parametrize("corruption", ["missing", "bytes", "name", "oversize"])
def test_restore_or_admin_corruption_detected(repository, corruption, monkeypatch):
    _, repo, params = repository
    repo.record("t", "v", {"a": 1})
    if corruption == "missing":
        admin(params, "ALTER TABLE theheat_projection.fields DISABLE TRIGGER fields_immutable; DELETE FROM theheat_projection.fields; ALTER TABLE theheat_projection.fields ENABLE TRIGGER fields_immutable")
        expected = "projection_reference_mismatch"
    elif corruption == "bytes":
        # Trusted owner bypass emulates damaged restore; restore the catalog to
        # show byte verification is independent of schema fingerprint checking.
        admin(params, "ALTER TABLE theheat_projection.artifacts DROP CONSTRAINT artifact_identity; ALTER TABLE theheat_projection.artifacts DISABLE TRIGGER artifacts_immutable; UPDATE theheat_projection.artifacts SET payload='2'::bytea; ALTER TABLE theheat_projection.artifacts ENABLE TRIGGER artifacts_immutable; ALTER TABLE theheat_projection.artifacts ADD CONSTRAINT artifact_identity CHECK(sha=encode(sha256(payload),'hex')) NOT VALID")
        expected = "changed_projection_schema"  # unvalidated constraint itself fails closed
        import psycopg
        with psycopg.connect(**params) as connection:
            with pytest.raises(p.ProjectionError, match="corrupt_projection_artifact"):
                p.PostgresProjectionRepository._read(connection, "t", "v")
    elif corruption == "name":
        admin(params, "ALTER TABLE theheat_projection.fields DISABLE TRIGGER fields_immutable; UPDATE theheat_projection.fields SET name_json='123'::bytea; ALTER TABLE theheat_projection.fields ENABLE TRIGGER fields_immutable")
        expected = "corrupt_projection_field"
    else:
        admin(params, "ALTER TABLE theheat_projection.versions DISABLE TRIGGER versions_immutable; UPDATE theheat_projection.versions SET byte_count=16777216; ALTER TABLE theheat_projection.versions ENABLE TRIGGER versions_immutable")
        expected = "corrupt_projection_identity"
    with pytest.raises(p.ProjectionError, match=f"^{expected}$"):
        repo.read("t", "v")


def test_backup_restore_exact_receipt(repository, cluster):
    import psycopg
    _, repo, params = repository
    args, command, root = cluster
    receipt = repo.record("t", "v", {"未知": ["synthetic", 1.0, -0.0], "ledger": []})
    dump = root / "projection.dump"
    common = ["-h", args["host"], "-p", args["port"], "-U", args["user"], "-w"]
    command("pg_dump", *common, "-Fc", "-f", dump, params["dbname"])
    restored_name = "restore_" + uuid.uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(restored_name)))
    try:
        command("pg_restore", *common, "--single-transaction", "-d", restored_name, dump)
        restored = p.PostgresProjectionRepository(socket_directory=args["host"], port=args["port"],
                                                  database=restored_name, user=repo.user)
        actual, value = restored.read("t", "v")
        assert actual == receipt
        assert restored.record("t", "v", value) == receipt
    finally:
        with psycopg.connect(**args) as c:
            c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(restored_name)))


@pytest.mark.parametrize("grant,undo", [
    ("ALTER ROLE projection_runtime CREATEDB", "ALTER ROLE projection_runtime NOCREATEDB"),
    ("GRANT projection_owner TO projection_runtime", "REVOKE projection_owner FROM projection_runtime"),
], ids=["privileged-role", "owner-membership"])
def test_role_escalation_refused(repository, grant, undo):
    _, repo, params = repository
    try:
        admin(params, grant)
        with pytest.raises(p.ProjectionError, match="non_owner_runtime_role_required"):
            repo.record("t", "v", {})
    finally:
        admin(params, undo)
    assert counts(params) == [0, 0, 0]


def test_invalid_initial_runtime_role_leaves_no_schema(database):
    owner, _, params = database
    with pytest.raises(p.ProjectionError, match="invalid_runtime_role"):
        owner.initialize(runtime_role=owner.user)
    assert admin(params, "SELECT to_regnamespace('theheat_projection')") == [(None,)]


def test_driver_is_lazy_and_missing_profile_is_explicit(monkeypatch):
    import builtins
    original = builtins.__import__
    def without_driver(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("synthetic missing optional driver")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_driver)
    assert p._snapshot({"unknown": []})[0] == b'{"unknown":[]}'
    with pytest.raises(p.ProjectionError, match="^optional_postgres_driver_required$"):
        p._driver()


def test_broad_owner_defaults_do_not_become_runtime_permissions(database):
    owner, repo, params = database
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC, projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime")
    owner.initialize(runtime_role=repo.user)
    rights = admin(params, "SELECT has_table_privilege('projection_runtime','theheat_projection.versions','UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),has_schema_privilege('projection_runtime','theheat_projection','CREATE'),has_table_privilege('projection_runtime','theheat_projection.metadata','INSERT')")
    assert rights == [(False, False, False)]
    assert repo.record("t", "v", {}).field_count == 0
