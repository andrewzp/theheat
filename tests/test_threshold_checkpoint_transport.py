"""Offline checkpoint privacy, committed WAL capture and frozen inventory replay."""

from contextlib import closing
from datetime import date
from io import BytesIO
import os
from pathlib import Path
import sqlite3
import zipfile

import pytest

from scripts import refresh_station_inventory as inventory
from scripts import threshold_checkpoint_transport as transport
from scripts.threshold_artifacts import ArtifactError
from src.data.ghcn_db import get_meta, open_db, set_meta

KEY = "1a" * 32


@pytest.fixture
def packed(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    (directory / "inventory.json").write_bytes(b"INVENTED_PRIVATE_INVENTORY")
    manifest = tmp_path / "station_thresholds.version"
    manifest.write_text("invented baseline manifest")
    archive = tmp_path / "checkpoint.aead"
    cipher = transport._cipher(KEY)
    context = transport._context(manifest, "example/repo", "123", 12)
    with open_db(directory / "refresh.sqlite") as conn:
        set_meta(conn, "incremental_plan", "invented-complete-plan")
        conn.commit()
        set_meta(conn, "uncommitted", "must not survive")
        assert (directory / "refresh.sqlite-wal").stat().st_size > 0
        transport.seal(directory, archive, cipher, context)
    return archive, manifest, context


def test_sealed_transport_only_restores_committed_progress_and_private_files(tmp_path, packed):
    archive, _, context = packed
    destination = tmp_path / "restored"
    body = archive.read_bytes()
    assert b"SQLite format" not in body and b"INVENTED_PRIVATE_INVENTORY" not in body
    transport.unseal(archive, destination, transport._cipher(KEY), context)
    assert destination.stat().st_mode & 0o077 == 0
    assert {file.name for file in destination.iterdir()} == {"inventory.json", "refresh.sqlite"}
    assert (destination / "inventory.json").read_bytes() == b"INVENTED_PRIVATE_INVENTORY"
    with closing(sqlite3.connect(destination / "refresh.sqlite")) as conn:
        assert get_meta(conn, "incremental_plan") == "invented-complete-plan"
        assert get_meta(conn, "uncommitted") is None


@pytest.mark.parametrize("change", ["run", "repo", "days", "manifest", "body", "key"])
def test_wrong_checkpoint_or_tampered_envelope_leaves_no_plaintext(tmp_path, packed, change):
    archive, manifest, _ = packed
    if change == "manifest":
        manifest.write_text("different baseline manifest")
    if change == "body":
        body = archive.read_bytes()
        archive.write_bytes(body[:-1] + bytes([body[-1] ^ 1]))
    context = transport._context(
        manifest, "other/repo" if change == "repo" else "example/repo",
        "124" if change == "run" else "123", 13 if change == "days" else 12,
    )
    destination = tmp_path / "restored"
    with pytest.raises(ArtifactError, match="threshold_checkpoint_authentication_failed"):
        transport.unseal(archive, destination, transport._cipher("2a" * 32 if change == "key" else KEY), context)
    assert not destination.exists()


def test_authenticated_archive_cannot_extract_unexpected_names(tmp_path, packed):
    archive, _, context = packed
    body = BytesIO()
    with zipfile.ZipFile(body, "w") as zipped:
        zipped.writestr("../escaped", "invented")
        zipped.writestr("refresh.sqlite", "invented")
    cipher = transport._cipher(KEY)
    nonce = os.urandom(transport.NONCE_BYTES)
    archive.write_bytes(transport.MAGIC + nonce + cipher.encrypt(nonce, body.getvalue(), context))
    destination = tmp_path / "restored"
    with pytest.raises(ArtifactError, match="threshold_checkpoint_members_invalid"):
        transport.unseal(archive, destination, cipher, context)
    assert not destination.exists()


@pytest.mark.parametrize("limit", ["database", "envelope"])
def test_sealing_enforces_independent_size_limits(tmp_path, packed, monkeypatch, limit):
    _, _, context = packed
    monkeypatch.setattr(transport, "MAX_CHECKPOINT_DB" if limit == "database" else "MAX_ENVELOPE_BYTES", 1)
    archive = tmp_path / "oversize.aead"
    expected = "threshold_checkpoint_database_invalid" if limit == "database" else "threshold_checkpoint_envelope_too_large"
    with pytest.raises(ArtifactError, match=expected):
        transport.seal(tmp_path / "private", archive, transport._cipher(KEY), context)
    assert not archive.exists()


def test_inventory_replay_rebuilds_identical_database_and_csv_without_fetch(tmp_path, monkeypatch):
    station = "ZZX00000001"
    fixtures = {
        inventory.STATIONS_URL: f"{station}  10.0000   20.0000  100.0    INVENTED STATION\n",
        inventory.INVENTORY_URL: f"{station} 10.0000 20.0000 TMAX 1990 2026\n",
        inventory.COUNTRIES_URL: "ZZ Invented Land\n",
    }
    monkeypatch.setattr(inventory, "_fetch_text", fixtures.__getitem__)
    csv_path = tmp_path / "stations.csv"
    monkeypatch.setattr(inventory, "STATIONS_CSV_PATH", csv_path)
    directory = tmp_path / "private"
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    assert inventory.main(["--db", str(first), "--resume-dir", str(directory)]) == 0
    first_csv = csv_path.read_bytes()
    assert station.encode() in first_csv
    monkeypatch.setattr(inventory, "_fetch_text", lambda _url: pytest.fail("resumed inventory must not fetch"))

    class NextYear(date):
        @classmethod
        def today(cls):
            return cls(2030, 1, 1)

    monkeypatch.setattr(inventory, "date", NextYear)
    assert inventory.main(["--db", str(second), "--resume-dir", str(directory)]) == 0
    assert second.read_bytes() == first.read_bytes()
    assert csv_path.read_bytes() == first_csv

    snapshot = directory / "inventory.json"
    snapshot.write_bytes(snapshot.read_bytes().replace(b"INVENTED", b"CORRUPTED"))
    untouched = tmp_path / "untouched.sqlite"
    assert inventory.main(["--db", str(untouched), "--resume-dir", str(directory)]) == 1
    assert not untouched.exists()
