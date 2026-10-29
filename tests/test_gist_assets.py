"""The durable Gist media store on the real local immutable artifact store (invented bytes)."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.commands import domain_journal
from src.media import gist_assets as assets


@pytest.fixture
def store(tmp_path):
    return assets.SQLiteMediaStore(tmp_path / "media.sqlite3")


def _rows(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT count(*) FROM domain_artifacts").fetchone()[0]


def test_retain_read_restart_and_idempotent_retry(store, tmp_path):
    first, second = b"invented original bytes", b"invented derivative bytes"
    identities = store.put_many([first, second])
    assert identities == [assets.digest(first), assets.digest(second)]
    assert stat_mode(store.path) == 0o600
    # A lost acknowledgement retried by a new process is the same receipt, no duplicate.
    restarted = assets.SQLiteMediaStore(tmp_path / "media.sqlite3")
    assert restarted.put_many([first, second]) == identities
    assert restarted.get(identities[0], limit=1000) == first
    assert restarted.get(identities[1], limit=1000) == second
    assert _rows(store.path) == 2


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


def test_documents_are_canonical_and_strict(store):
    value = {"b": [1, 2.5, "é"], "a": None}
    sha = assets.put_document(store, value)
    assert sha == assets.digest(b'{"a":null,"b":[1,2.5,"\xc3\xa9"]}')
    assert assets.get_document(store, sha) == value
    for bad in (b'{"a":1,"a":2}', b'{"a": 1}', b'{"a":NaN}', b"\xff"):
        with pytest.raises(assets.MediaStoreError):
            assets.decode_document(bad)
    with pytest.raises(assets.MediaStoreError, match="finite JSON"):
        assets.encode_document({"a": float("nan")})


def test_atomic_rollback_retains_nothing_from_a_failed_batch(store, monkeypatch):
    monkeypatch.setattr(domain_journal, "MAX_ARTIFACT_BYTES", 64)
    with pytest.raises(assets.MediaStoreError, match="refused the write"):
        store.put_many([b"small invented", b"x" * 65])
    with pytest.raises(assets.MediaStoreError) as missing:
        store.get(assets.digest(b"small invented"), limit=100)
    assert missing.value.code == "media_asset_missing"


def test_immutable_rows_and_byte_tampering_are_detected(store):
    sha = store.put_many([b"invented immutable payload " * 4])[0]
    with closing(sqlite3.connect(store.path)) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="immutable|constraint"):
            connection.execute("UPDATE domain_artifacts SET payload=? WHERE sha256=?", (b"y" * 108, sha))
        with pytest.raises(sqlite3.DatabaseError, match="immutable|constraint"):
            connection.execute("DELETE FROM domain_artifacts WHERE sha256=?", (sha,))
    raw = store.path.read_bytes()
    offset = raw.index(b"invented immutable payload")
    store.path.write_bytes(raw[:offset] + b"I" + raw[offset + 1:])
    with pytest.raises(assets.MediaStoreError) as changed:
        store.get(sha, limit=1000)
    assert changed.value.code == "media_asset_changed"


def test_bounds_and_missing_assets_refuse_before_reading(store):
    sha = store.put_many([b"z" * 500])[0]
    with pytest.raises(assets.MediaStoreError) as bound:
        store.get(sha, limit=499)
    assert bound.value.code == "media_asset_invalid"
    with pytest.raises(assets.MediaStoreError) as missing:
        store.get("0" * 64, limit=1000)
    assert missing.value.code == "media_asset_missing"
    for invalid in ("A" * 64, "0" * 63, None, "../x"):
        with pytest.raises(assets.MediaStoreError):
            store.get(invalid, limit=10)


def test_backup_restore_preserves_every_exact_byte(store, tmp_path):
    blobs = [b"invented original", b"invented derivative" * 100, b"{}"]
    identities = store.put_many(blobs)
    copy = store.backup(tmp_path / "backup.sqlite3")
    assert stat_mode(copy.path) == 0o600
    store.path.unlink()  # The original is lost; restore from the backup only.
    restored = copy.backup(tmp_path / "restored.sqlite3")
    assert [restored.get(sha, limit=10_000) for sha in identities] == blobs
    with closing(sqlite3.connect(restored.path)) as connection:
        connection.row_factory = sqlite3.Row
        assert domain_journal.validate_schema(connection, assets.NAMESPACE) == assets.NAMESPACE
    with pytest.raises(assets.MediaStoreError, match="already exists"):
        copy.backup(restored.path)


def test_file_boundaries_refuse_paths_links_and_shared_files(tmp_path):
    with pytest.raises(assets.MediaStoreError, match="absolute"):
        assets.SQLiteMediaStore(Path("relative.sqlite3"))
    real = tmp_path / "real.sqlite3"
    assets.SQLiteMediaStore(real).put_many([b"invented"])
    link = tmp_path / "link.sqlite3"
    link.symlink_to(real)
    with pytest.raises(assets.MediaStoreError, match="symlinks"):
        assets.SQLiteMediaStore(link)
    linked_dir = tmp_path / "linked-dir"
    linked_dir.symlink_to(tmp_path)
    with pytest.raises(assets.MediaStoreError, match="symlinks"):
        assets.SQLiteMediaStore(linked_dir / "real.sqlite3")
    os.chmod(real, 0o644)
    with pytest.raises(assets.MediaStoreError, match="private regular file"):
        assets.SQLiteMediaStore(real).get(assets.digest(b"invented"), limit=100)
    with pytest.raises(assets.MediaStoreError, match="does not exist"):
        assets.SQLiteMediaStore(tmp_path / "absent.sqlite3").get("0" * 64, limit=10)


def test_configuration_holds_only_the_store_lane(tmp_path):
    for environ in ({}, {assets.ENV: ""}, {assets.ENV: "postgres://invented"}, {assets.ENV: "https://invented.test/x"}):
        with pytest.raises(assets.MediaStoreError) as held:
            assets.configured(environ)
        assert held.value.code == "media_store_unavailable"
    path = tmp_path / "configured.sqlite3"
    assert assets.configured({assets.ENV: f"sqlite:{path}"}).path == path


WRITER = r'''
import sys
from src.media import gist_assets as assets
store = assets.SQLiteMediaStore(sys.argv[1])
for _ in range(20):
    store.put_many([b"invented shared blob", sys.argv[2].encode()])
'''


def test_separate_processes_retain_concurrently_without_duplicates(tmp_path):
    path = tmp_path / "shared.sqlite3"
    assets.SQLiteMediaStore(path).put_many([b"seed"])
    workers = [subprocess.Popen([sys.executable, "-c", WRITER, str(path), f"worker-{i}"],
                                cwd=Path(__file__).resolve().parents[1]) for i in range(3)]
    assert [worker.wait(timeout=60) for worker in workers] == [0, 0, 0]
    assert _rows(path) == 5
    store = assets.SQLiteMediaStore(path)
    assert store.get(assets.digest(b"invented shared blob"), limit=100) == b"invented shared blob"
