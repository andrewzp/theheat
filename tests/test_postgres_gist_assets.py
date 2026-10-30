"""Genuine PostgreSQL acceptance for the media-only adapter (required CI only).

Runs only with THEHEAT_TEST_POSTGRES=1 on CI's fresh disposable task-owned cluster
(tests/test_postgres_projection.cluster: Unix socket, no network listener). It
applies the repository's migration 009 to a new database, creates invented
reader/writer roles there and exercises the adapter's real statements. It never
touches an existing or hosted instance. Locally this file is deliberately not run.
"""
from hashlib import sha256
from pathlib import Path
import threading
import uuid

import pytest

from src.media import gist_assets, gist_assets_postgres as pg
from tests.test_postgres_projection import cluster as cluster

MIGRATION = Path(__file__).resolve().parents[1] / "src/storage/migrations/009_media_staging.sql"


@pytest.fixture
def media_db(cluster, monkeypatch):
    import psycopg
    for key in tuple(__import__("os").environ):
        if key.startswith("PG"):
            monkeypatch.delenv(key)
    args, _command, _root = cluster
    name = "media_" + uuid.uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    owner = {**args, "dbname": name}
    suffix = uuid.uuid4().hex[:8]
    reader, writer, broad = f"media_reader_{suffix}", f"media_writer_{suffix}", f"media_broad_{suffix}"
    with psycopg.connect(**owner) as c:
        c.execute(MIGRATION.read_text())
        for role in (reader, writer, broad):
            c.execute(psycopg.sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(
                psycopg.sql.Identifier(role)))
            c.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA theheat_media TO {}").format(psycopg.sql.Identifier(role)))
        c.execute(psycopg.sql.SQL("GRANT SELECT ON theheat_media.artifacts TO {}").format(psycopg.sql.Identifier(reader)))
        c.execute(psycopg.sql.SQL("GRANT SELECT, INSERT ON theheat_media.artifacts TO {}").format(psycopg.sql.Identifier(writer)))
        c.execute(psycopg.sql.SQL("GRANT SELECT, INSERT, UPDATE ON theheat_media.artifacts TO {}").format(psycopg.sql.Identifier(broad)))

    def dsn(role):
        return f"host={args['host']} port={args['port']} dbname={name} user={role} sslmode=disable"
    yield dict(owner=owner, reader=dsn(reader), writer=dsn(writer), broad=dsn(broad), name=name)
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
        for role in (reader, writer, broad):
            c.execute(psycopg.sql.SQL("DROP ROLE {}").format(psycopg.sql.Identifier(role)))


def _store(dsn, role):
    return pg.PostgresMediaStore(pg.parse_dsn(dsn), role=role)


def test_real_retain_read_retry_and_bounds(media_db):
    blobs = [b"invented original", b"invented derivative" * 100]
    writer = _store(media_db["writer"], "writer")
    keys = writer.put_many(blobs)
    assert keys == [sha256(b).hexdigest() for b in blobs] == writer.put_many(blobs)
    reader = _store(media_db["reader"], "reader")
    assert [reader.get(k, limit=10_000) for k in keys] == blobs
    with pytest.raises(gist_assets.MediaStoreError) as oversize:
        reader.get(keys[1], limit=100)
    assert oversize.value.code == "media_asset_invalid"
    with pytest.raises(gist_assets.MediaStoreError) as missing:
        reader.get("0" * 64, limit=10)
    assert missing.value.code == "media_asset_missing"


def test_real_capabilities_privileges_and_immutability(media_db):
    import psycopg
    with pytest.raises(gist_assets.MediaStoreError, match="read-only"):
        _store(media_db["reader"], "reader").put_many([b"x"])
    for dsn, role in ((media_db["reader"], "writer"), (media_db["broad"], "writer"), (media_db["writer"], "reader")):
        with pytest.raises(gist_assets.MediaStoreError, match="wrong permissions"):
            store = _store(dsn, role)
            store.put_many([b"x"]) if role == "writer" else store.get("0" * 64, limit=10)
    key = _store(media_db["writer"], "writer").put_many([b"invented immutable"])[0]
    with psycopg.connect(**media_db["owner"]) as c:
        for sql in ("UPDATE theheat_media.artifacts SET byte_count=byte_count WHERE sha=%s",
                    "DELETE FROM theheat_media.artifacts WHERE sha=%s"):
            with pytest.raises(psycopg.Error, match="immutable media staging"):
                with c.transaction():
                    c.execute(sql, (key,))
        with pytest.raises(psycopg.Error):  # The table's check: key must be the payload's SHA256.
            with c.transaction():
                c.execute("INSERT INTO theheat_media.artifacts VALUES(%s,%s,%s)", ("1" * 64, b"other", 5))


def test_real_reader_session_is_read_only_with_finite_budgets(media_db):
    import psycopg
    kwargs = pg.connection_kwargs(pg.parse_dsn(media_db["reader"]), "reader")
    with psycopg.connect(**kwargs) as c:
        assert c.execute("SHOW default_transaction_read_only").fetchone() == ("on",)
        for name, value in pg.TIMEOUTS.items():
            assert c.execute(f"SHOW {name}").fetchone()[0] in (f"{value}ms", f"{value // 1000}s")


def test_real_concurrent_writers_keep_one_row_per_identity(media_db):
    import psycopg
    errors = []

    def write(index):
        try:
            for _ in range(5):
                _store(media_db["writer"], "writer").put_many([b"invented shared", f"worker-{index}".encode()])
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
    threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    assert errors == []
    with psycopg.connect(**media_db["owner"]) as c:
        assert c.execute("SELECT count(*) FROM theheat_media.artifacts").fetchone() == (5,)


@pytest.mark.parametrize("family", ["crw", "radar", "cone"])
def test_real_two_consumers_share_one_retained_identity(media_db, family, tmp_path):
    """Fresh packaged-preview and actual-sender processes read one real PostgreSQL row set."""
    from tests.test_gist_two_consumer_journey import python_two_consumers
    store_env = {gist_assets.ENV: "postgres", gist_assets.DSN_ENV: media_db["reader"]}
    _preview, record, _final = python_two_consumers(family, tmp_path, _store(media_db["writer"], "writer"), store_env)
    assert record["postgres_adapter"] is True and record["psycopg"] is True
