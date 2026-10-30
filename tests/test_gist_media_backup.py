"""Portable private export/restore of selected retained media (invented inputs only).

Export → new private directory → verified restore into an empty store (SQLite, and
the PostgreSQL adapter over the OFFLINE protocol fixture) with identical previews.
Every refusal (missing, corrupt, conflicting, oversized, traversal, symlink, FIFO,
permissions, unexpected entries, existing output) happens before any write.
"""
import json
import os
from pathlib import Path
import socket
import stat

import pytest

from scripts import retain_gist_media as cli
from src.media import gist_assets, gist_assets_postgres as pg, gist_crw_media as crw, gist_media_export as portable
from src.media import gist_published_media as published
from tests import gist_pg_protocol_fixture as fx
from tests.gist_crw_helpers import varied_inputs
from tests.gist_store_helpers import retain


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    for name in [n for n in os.environ if n.startswith("PG")]:
        monkeypatch.delenv(name)


class Recording:
    """An insert-only writer that must never be reached by a refused restore."""

    def __init__(self):
        self.writes = []

    def put_many(self, blobs):
        self.writes.append(blobs)
        raise AssertionError("restore wrote before verification finished")


@pytest.fixture
def source(tmp_path):
    store = gist_assets.SQLiteMediaStore(tmp_path / "source.sqlite3")
    ids = {family: retain(family, store) for family in ("radar", "cone", "crw")}
    return store, ids


def _export(store, ids, target):
    return portable.export(store, [("published", ids["radar"]), ("published", ids["cone"]),
                                   ("crw_packet", ids["crw"])], target)


def _cli(argv, capsys, environ=None):
    code = cli.main(argv, environ=environ or {})
    out = capsys.readouterr()
    return code, json.loads(out.out or out.err)


def test_export_restore_round_trip_preserves_every_address_and_preview(source, tmp_path, capsys):
    store, ids = source
    target = tmp_path / "export"
    code, exported = _cli(["--store", f"sqlite:{tmp_path / 'source.sqlite3'}", "export", "--target", str(target),
                           "--manifest", ids["radar"], "--manifest", ids["cone"], "--crw-packet", ids["crw"]], capsys)
    assert code == 0 and exported["items"] == 3
    assert stat.S_IMODE(target.stat().st_mode) == 0o700 and stat.S_IMODE((target / "blobs").stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (target / "blobs").iterdir())
    index = json.loads((target / "export.json").read_text())
    for kind, sha in (("published", ids["radar"]), ("published", ids["cone"])):
        row = next(r for r in index["items"] if r["sha256"] == sha)
        manifest, _original, _png = published.read(store, sha)
        value = manifest["document"]
        required = {sha, value["original"]["sha256"], manifest["derivative"]["sha256"], value["receipt"]["sha256"],
                    value["references"]["product"]["sha256"], value["references"]["reuse"]["sha256"]}
        assert row["kind"] == kind and set(row["blobs"]) == required  # Rights/product references included.
    restored_path = tmp_path / "restored.sqlite3"
    code, restored = _cli(["--store", f"sqlite:{restored_path}", "restore", "--source", str(target)], capsys)
    assert code == 0 and restored == {"restored_items": 3, "restored_blobs": len(index["blobs"]), "verified": True}
    copy = gist_assets.SQLiteMediaStore(restored_path, writable=False)
    for family in ("radar", "cone"):
        assert published.read(copy, ids[family]) == published.read(store, ids[family])
    assert crw.load_packet(copy, ids["crw"]) == crw.load_packet(store, ids["crw"])
    bundle, _packet = varied_inputs()
    assert crw.prepare_media(bundle, copy, ids["crw"])["descriptor"] == crw.prepare_media(bundle, store, ids["crw"])["descriptor"]
    # Idempotent: a second restore of the same export changes nothing and still verifies.
    assert _cli(["--store", f"sqlite:{restored_path}", "restore", "--source", str(target)], capsys)[0] == 0


@pytest.mark.parametrize("fault,code", [(None, None), ("unavailable", "media_store_unavailable"),
                                        ("lost_commit_ack", "media_retention_unknown")])
def test_restore_through_the_insert_only_postgres_writer(source, tmp_path, fault, code):
    store, ids = source
    _export(store, ids, tmp_path / "export")
    backing = fx.create(tmp_path / "protocol.sqlite3")
    writer = pg.PostgresMediaStore(pg.parse_dsn(fx.WRITER_DSN), role="writer", driver=fx.module(backing))
    reader = pg.PostgresMediaStore(pg.parse_dsn(fx.READER_DSN), role="reader", driver=fx.module(backing))
    fx.set_fault(backing, fault or "")
    if code is None:
        assert portable.restore(writer, tmp_path / "export")["restored_items"] == 3
        assert published.read(reader, ids["cone"])[0]["product"] == "nhc_track_cone_v1"
        return
    with pytest.raises(portable.ExportError) as held:
        portable.restore(writer, tmp_path / "export")
    assert held.value.code == code  # Unknown retention is never reported as restored.
    with pytest.raises(portable.ExportError):
        portable.restore(reader, tmp_path / "export")  # The reader capability has no write path.


def _damage(target, case):
    blobs = sorted((target / "blobs").iterdir())
    first = blobs[0]
    if case == "missing":
        first.unlink()
    elif case == "corrupt":
        raw = bytearray(first.read_bytes())
        raw[0] ^= 1
        first.write_bytes(bytes(raw))
    elif case == "oversized":
        first.write_bytes(first.read_bytes() + b"x")
    elif case == "unexpected":
        extra = target / "blobs" / ("0" * 64)
        extra.write_bytes(b"unexpected")
        extra.chmod(0o600)
    elif case == "symlink_blob":
        raw = first.read_bytes()
        first.unlink()
        (target.parent / "elsewhere.bin").write_bytes(raw)
        first.symlink_to(target.parent / "elsewhere.bin")
    elif case == "fifo_blob":
        first.unlink()
        os.mkfifo(first, 0o600)
    elif case == "public_blob":
        first.chmod(0o644)
    elif case == "public_directory":
        target.chmod(0o755)
    elif case == "traversal_index":
        index = json.loads((target / "export.json").read_text())
        index["blobs"]["../" + first.name] = index["blobs"].pop(first.name)
        (target / "export.json").write_text(json.dumps(index))
    elif case == "conflicting_index":
        index = json.loads((target / "export.json").read_text())
        a, b = index["items"][0], index["items"][1]
        a["blobs"] = sorted(set(a["blobs"]) | {b["sha256"]})  # A dependency it does not have.
        (target / "export.json").write_text(json.dumps(index))
    elif case == "duplicate_key_index":
        raw = (target / "export.json").read_text()
        (target / "export.json").write_text(raw.replace('{"blobs":', '{"kind":"x","blobs":', 1))
    elif case == "extra_entry":
        (target / "notes.txt").write_text("x")
    return first


CASES = {"missing": "export_missing", "corrupt": "export_blob_changed", "oversized": "export_blob_changed",
         "unexpected": "export_entry_invalid", "symlink_blob": "export_entry_invalid",
         "fifo_blob": "export_entry_invalid", "public_blob": "export_entry_invalid",
         "public_directory": "export_entry_invalid", "traversal_index": "export_index_invalid",
         "conflicting_index": "export_index_invalid", "duplicate_key_index": "export_index_invalid",
         "extra_entry": "export_entry_invalid"}


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_damaged_export_is_refused_before_any_write(source, tmp_path, case):
    store, ids = source
    target = tmp_path / "export"
    _export(store, ids, target)
    _damage(target, case)
    writer = Recording()
    with pytest.raises(portable.ExportError) as refused:
        portable.restore(writer, target)
    assert refused.value.code == CASES[case] and writer.writes == []


def test_paths_selection_and_existing_output_are_refused(source, tmp_path):
    store, ids = source
    target = tmp_path / "export"
    _export(store, ids, target)
    for bad in (tmp_path / "export" / ".." / "export", Path("relative/export")):
        with pytest.raises(portable.ExportError) as refused:
            portable.restore(Recording(), bad)
        assert refused.value.code == "export_path_invalid"
    link = tmp_path / "linked-export"
    link.symlink_to(target)
    with pytest.raises(portable.ExportError) as linked:
        portable.restore(Recording(), link)
    assert linked.value.code == "export_path_invalid"
    before = sorted(p.name for p in tmp_path.iterdir())
    for target_path, items, code in ((target, [("published", ids["cone"])], "export_output_exists"),
                                     (tmp_path / "new", [("published", "0" * 64)], "media_original_missing"),
                                     (tmp_path / "new", [("crw_packet", ids["cone"])], "media_asset_invalid"),
                                     (tmp_path / "new", [("published", ids["cone"])] * 2, "export_selection_invalid"),
                                     (tmp_path / "missing-parent" / "new", [("published", ids["cone"])],
                                      "export_path_invalid")):
        with pytest.raises(portable.ExportError) as refused:
            portable.export(store, items, target_path)
        assert refused.value.code == code, (target_path, items)
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # A refused export creates nothing.


def test_existing_sqlite_backups_remain_usable_and_exportable(source, tmp_path, capsys):
    store, ids = source
    code, backup = _cli(["--store", f"sqlite:{tmp_path / 'source.sqlite3'}", "backup", "--target",
                         str(tmp_path / "backup.sqlite3")], capsys)
    assert code == 0
    copy = f"sqlite:{tmp_path / 'backup.sqlite3'}"
    assert _cli(["--store", copy, "verify", "--manifest", ids["cone"]], capsys)[1]["verified"] is True
    code, exported = _cli(["--store", copy, "export", "--target", str(tmp_path / "from-backup"),
                           "--manifest", ids["cone"]], capsys)
    assert code == 0 and exported["items"] == 1
    # The PostgreSQL store has no database-wide backup; export is the portable path.
    backing = fx.create(tmp_path / "protocol.sqlite3")
    reader = pg.PostgresMediaStore(pg.parse_dsn(fx.READER_DSN), role="reader", driver=fx.module(backing))
    with pytest.raises(gist_assets.MediaStoreError, match="database-wide backup"):
        reader.backup(str(tmp_path / "never"))
