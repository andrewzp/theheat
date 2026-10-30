"""The media-only PostgreSQL adapter's real query/transaction code against the OFFLINE
protocol fixture (tests/gist_pg_protocol_fixture.py). Not PostgreSQL acceptance: the
genuine database run is tests/test_postgres_gist_assets.py in required CI only.
"""
import hashlib
import threading

import pytest

from src.media import gist_assets, gist_assets_postgres as pg
from tests import gist_pg_protocol_fixture as fx


@pytest.fixture
def backing(tmp_path, monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith("PG"):
            monkeypatch.delenv(name)
    return fx.create(tmp_path / "protocol.sqlite3")


def store(backing, role="writer", dsn=None):
    return pg.PostgresMediaStore(pg.parse_dsn(dsn or (fx.WRITER_DSN if role == "writer" else fx.READER_DSN)),
                                 role=role, driver=fx.module(backing))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def test_retain_read_and_idempotent_retry_run_the_real_statements(backing):
    blobs = [b"invented original", b"invented derivative" * 50]
    writer = store(backing)
    assert writer.put_many(blobs) == [sha(b) for b in blobs]
    assert writer.put_many(blobs) == [sha(b) for b in blobs]  # Lost-ack retry: same receipt, no duplicate.
    reader = store(backing, "reader")
    assert [reader.get(sha(b), limit=10_000) for b in blobs] == blobs
    assert fx.counter(backing, "connections") == fx.counter(backing, "closed")  # Closed on every outcome.


def test_reader_has_no_write_path_and_wrong_privileges_refuse(backing, tmp_path):
    with pytest.raises(gist_assets.MediaStoreError, match="read-only"):
        store(backing, "reader").put_many([b"x"])
    assert fx.counter(backing, "connect_attempts") == 0  # Refused before any dial.
    for users, role in (({"media_reader": fx.WRITER}, "reader"),  # reader that could insert
                        ({"media_writer": {**fx.WRITER, "UPDATE": 1}}, "writer"),  # writer that could update
                        ({"media_writer": fx.READER}, "writer")):  # writer without insert
        path = fx.create(tmp_path / f"roles-{len(list(tmp_path.iterdir()))}.sqlite3", users=users)
        with pytest.raises(gist_assets.MediaStoreError, match="wrong permissions") as refused:
            store(path, role).get("0" * 64, limit=10) if role == "reader" else store(path, role).put_many([b"x"])
        assert refused.value.code == "media_store_unavailable"
        assert fx.counter(path, "connections") == fx.counter(path, "closed")
    fx.set_fault(backing, "revoked")
    with pytest.raises(gist_assets.MediaStoreError, match="wrong permissions"):
        store(backing, "reader").get("0" * 64, limit=10)


@pytest.mark.parametrize("fault,code", [("unavailable", "media_store_unavailable"), ("timeout", "media_store_unavailable"),
                                        ("disconnect_before_commit", "media_store_unavailable"),
                                        ("commit_failure", "media_retention_unknown"),
                                        ("lost_commit_ack", "media_retention_unknown")])
def test_write_failures_never_report_success_or_leak_settings(backing, fault, code):
    fx.set_fault(backing, fault)
    with pytest.raises(gist_assets.MediaStoreError) as failed:
        store(backing).put_many([b"invented payload"])
    assert failed.value.code == code
    for secret in ("invented-secret-host", "invented-pass", "invented_reader", "media.invented.test", "password"):
        assert secret not in str(failed.value)
    # Driver text never chains into a displayed traceback.
    assert failed.value.__cause__ is None and failed.value.__suppress_context__ is True
    fx.set_fault(backing, "")
    retained = fx.counter(backing, "payload_reads")
    store(backing).put_many([b"invented payload"])  # The retry either inserts or verifies the same bytes.
    assert store(backing, "reader").get(sha(b"invented payload"), limit=100) == b"invented payload"
    assert fx.counter(backing, "payload_reads") > retained
    assert fx.counter(backing, "connections") == fx.counter(backing, "closed")


@pytest.mark.parametrize("fault,retained", [("disconnect_before_commit", False), ("commit_failure", False),
                                             ("lost_commit_ack", True)])
def test_interrupted_writes_retain_all_or_nothing(backing, fault, retained):
    fx.set_fault(backing, fault)
    with pytest.raises(gist_assets.MediaStoreError):
        store(backing).put_many([b"first", b"second"])
    fx.set_fault(backing, "")
    for raw in (b"first", b"second"):
        if retained:
            assert store(backing, "reader").get(sha(raw), limit=100) == raw
        else:
            with pytest.raises(gist_assets.MediaStoreError) as missing:
                store(backing, "reader").get(sha(raw), limit=100)
            assert missing.value.code == "media_asset_missing"


@pytest.mark.parametrize("fault", ["tamper", "truncate", "wrong_length"])
def test_changed_truncated_or_mislabelled_bytes_are_refused(backing, fault):
    store(backing).put_many([b"invented immutable payload"])
    fx.set_fault(backing, fault)
    with pytest.raises(gist_assets.MediaStoreError) as changed:
        store(backing, "reader").get(sha(b"invented immutable payload"), limit=100)
    assert changed.value.code == "media_asset_changed"


def test_conflicting_same_hash_row_is_refused_never_overwritten(backing):
    key = sha(b"the real bytes")
    fx.raw_insert(backing, key, b"different bytes")  # Out-of-band corruption under the same identity.
    with pytest.raises(gist_assets.MediaStoreError, match="different asset") as conflict:
        store(backing).put_many([b"the real bytes"])
    assert conflict.value.code == "media_asset_changed"
    with pytest.raises(gist_assets.MediaStoreError) as read:
        store(backing, "reader").get(key, limit=100)
    assert read.value.code in ("media_asset_changed",)


def test_bounds_and_identity_refuse_before_dial_or_payload_read(backing):
    for value, limit in (("A" * 64, 10), ("0" * 63, 10), (None, 10), ("0" * 64, 0), ("0" * 64, "10")):
        with pytest.raises(gist_assets.MediaStoreError):
            store(backing, "reader").get(value, limit=limit)
    for blobs in ([], [b""], ["text"], [b"x" * (pg.MAX_ROW_BYTES + 1)], [b"x"] * 65):
        with pytest.raises(gist_assets.MediaStoreError):
            store(backing).put_many(blobs)
    assert fx.counter(backing, "connect_attempts") == 0
    store(backing).put_many([b"y" * 500])
    reads = fx.counter(backing, "payload_reads")
    with pytest.raises(gist_assets.MediaStoreError) as oversize:
        store(backing, "reader").get(sha(b"y" * 500), limit=499)
    assert oversize.value.code == "media_asset_invalid"
    assert fx.counter(backing, "payload_reads") == reads  # The size check ran first.
    with pytest.raises(gist_assets.MediaStoreError) as missing:
        store(backing, "reader").get("0" * 64, limit=10)
    assert missing.value.code == "media_asset_missing"


def test_concurrent_writers_retain_one_row_per_identity(backing):
    errors = []

    def write(index):
        try:
            for _ in range(10):
                store(backing).put_many([b"invented shared", f"worker-{index}".encode()])
        except Exception as exc:  # pragma: no cover - recorded for the assertion below
            errors.append(exc)
    threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert errors == []
    import sqlite3
    with sqlite3.connect(backing) as db:
        assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 5


@pytest.mark.parametrize("dsn", [
    "", "postgresql://user:pw@host/db", "host=a port=5432 dbname=m user=u password=p",
    "host=a port=5432 dbname=m user=u password=p sslmode=require sslrootcert=system",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-ca sslrootcert=system",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-full",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-full sslrootcert=relative.pem",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-full sslrootcert=system service=x",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-full sslrootcert=system passfile=/tmp/x",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-full sslrootcert=system options='-c x=1'",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-full sslrootcert=system host=b",
    "host=a port=5432 dbname=m user=u sslmode=verify-full sslrootcert=system",
    "host=a port=99999 dbname=m user=u password=p sslmode=verify-full sslrootcert=system",
    "host=a port=5432 dbname=m user=u password=p sslmode=verify-full sslrootcert=system channel_binding=disable",
    "host=/tmp/sock port=5432 dbname=m user=u",
    "host=/tmp/sock port=5432 dbname=m user=u sslmode=verify-full sslrootcert=system",
    "host=a\nport=5432", "host='unterminated",
])
def test_connection_settings_refuse_implicit_or_insecure_forms(dsn):
    with pytest.raises(gist_assets.MediaStoreError) as refused:
        pg.parse_dsn(dsn)
    assert refused.value.code == "media_store_unavailable"
    assert "pw" not in str(refused.value) and "user:" not in str(refused.value)


def test_accepted_settings_are_explicit_and_bounded():
    params = pg.parse_dsn("host=db.invented.test port=5432 dbname=media user=media_reader "
                          "password='p w\\'x' sslmode=verify-full sslrootcert=system")
    assert params["password"] == "p w'x"
    kwargs = pg.connection_kwargs(params, "reader")
    assert kwargs["passfile"].startswith("/nonexistent/") and kwargs["sslcertmode"] == "disable"
    assert kwargs["sslmode"] == "verify-full" and kwargs["gssencmode"] == "disable" and kwargs["connect_timeout"] == 5
    assert "default_transaction_read_only=on" in kwargs["options"] and "transaction_timeout=20000" in kwargs["options"]
    socket = pg.parse_dsn("host=/tmp/theheat-pg/socket port=55473 dbname=media user=media_writer sslmode=disable")
    assert "sslrootcert" not in pg.connection_kwargs(socket, "writer")
    assert "default_transaction_read_only=off" in pg.connection_kwargs(socket, "writer")["options"]
    assert repr(pg.PostgresMediaStore(params, role="reader")) == "PostgresMediaStore(role='reader')"


@pytest.mark.parametrize("host", [
    "/tmp/media-socket,db.invented.test", "/tmp/one,/tmp/two", "/tmp/media-socket,",
    "/tmp/media-socket,,db.invented.test", ",/tmp/media-socket", "db.invented.test,/tmp/media-socket",
    "/tmp/media-socket/.", "/tmp/./media-socket", "/tmp/one/../media-socket",
    "/tmp//media-socket", "/tmp/media-socket/", "//tmp/media-socket", "///tmp/media-socket",
    "/tmp/media-socket\n", "/tmp/media-socket\0", "relative/socket",
])
@pytest.mark.parametrize("entrypoint", ["dsn", "params", "connect"])
def test_multihost_or_unnormalized_socket_refuses_before_driver_connect(backing, host, entrypoint):
    params = pg.parse_dsn("host=/tmp/media-socket port=5432 dbname=media user=media_reader sslmode=disable")
    driver = fx.module(backing)
    with pytest.raises(gist_assets.MediaStoreError) as refused:
        if entrypoint == "dsn":
            params = pg.parse_dsn(f"host='{host}' port=5432 dbname=media user=media_reader sslmode=disable")
            reader = pg.PostgresMediaStore(params, role="reader", driver=driver)
        elif entrypoint == "params":
            reader = pg.PostgresMediaStore({**params, "host": host}, role="reader", driver=driver)
        else:
            reader = pg.PostgresMediaStore(params, role="reader", driver=driver)
            reader._params["host"] = host  # The last pre-dial validation must also refuse it.
        reader.get("0" * 64, limit=1)
    assert refused.value.code == "media_store_unavailable"
    assert fx.counter(backing, "connect_attempts") == 0


@pytest.mark.parametrize("host", ["/", "/tmp/media-socket", "/tmp/invented socket"])
@pytest.mark.parametrize("role", ["reader", "writer"])
def test_one_normalized_socket_directory_is_preserved_exactly(backing, host, role):
    params = pg.parse_dsn(f"host='{host}' port=5432 dbname=media user=media_{role} sslmode=disable")
    assert params["host"] == host
    assert pg.connection_kwargs(params, role)["host"] == host
    connection = pg.PostgresMediaStore(params, role=role, driver=fx.module(backing))._connect()
    try:
        assert connection.kwargs["host"] == host and connection.kwargs["sslmode"] == "disable"
    finally:
        connection.close()
    assert fx.counter(backing, "connect_attempts") == fx.counter(backing, "closed") == 1


def test_selection_is_explicit_with_no_backend_fallback(monkeypatch, backing):
    environ = {gist_assets.ENV: "postgres", gist_assets.DSN_ENV: fx.READER_DSN}
    reader = gist_assets.configured(environ)
    assert reader.backend == "postgres" and reader.role == "reader"
    for broken in ({gist_assets.ENV: "postgres"}, {gist_assets.ENV: "postgres", gist_assets.DSN_ENV: "nonsense"},
                   {gist_assets.ENV: "postgres", gist_assets.WRITER_DSN_ENV: fx.WRITER_DSN}):
        with pytest.raises(gist_assets.MediaStoreError) as held:
            gist_assets.configured(broken)
        assert held.value.code == "media_store_unavailable"
    # The reader selection never reads the writer DSN, and vice versa.
    writer = gist_assets.configured_writer({gist_assets.WRITER_ENV: "postgres", gist_assets.WRITER_DSN_ENV: fx.WRITER_DSN,
                                            gist_assets.DSN_ENV: fx.READER_DSN})
    assert writer.role == "writer"
    with pytest.raises(gist_assets.MediaStoreError):
        gist_assets.configured_writer(environ)
    monkeypatch.setenv("PGSERVICE", "invented")
    with pytest.raises(gist_assets.MediaStoreError, match="ambient"):
        store(backing, "reader").get("0" * 64, limit=10)
    with pytest.raises(gist_assets.MediaStoreError, match="database-wide backup"):
        store(backing).backup("/tmp/never")


def test_missing_driver_holds_without_importing_for_native_paths(monkeypatch, backing):
    import builtins
    real = builtins.__import__

    def no_psycopg(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("not installed")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    with pytest.raises(gist_assets.MediaStoreError, match="driver is not installed"):
        pg.PostgresMediaStore(pg.parse_dsn(fx.READER_DSN), role="reader").get("0" * 64, limit=10)


def test_the_real_driver_parses_every_setting_without_connecting():
    """Offline: libpq's own conninfo parser (no socket) must recognize every keyword sent."""
    conninfo = pytest.importorskip("psycopg.conninfo")
    for dsn, role in ((fx.READER_DSN, "reader"), (fx.WRITER_DSN, "writer"),
                      ("host=/tmp/theheat-pg/socket port=55473 dbname=media user=w sslmode=disable", "writer")):
        kwargs = pg.connection_kwargs(pg.parse_dsn(dsn), role)
        assert kwargs.pop("autocommit") is True  # A driver argument, not a libpq keyword.
        assert conninfo.conninfo_to_dict(conninfo.make_conninfo("", **kwargs)) == {k: str(v) for k, v in kwargs.items()}
