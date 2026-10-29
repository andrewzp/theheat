"""The local retention command: private files in, immutable identities out (invented inputs)."""
import json
import socket

import pytest

from scripts import retain_gist_media as cli
from src.media import gist_assets, gist_crw_media as crw, gist_published_media as published
from tests import gist_published_helpers as h
from tests.gist_crw_helpers import varied_inputs


@pytest.fixture(autouse=False)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def _run(argv, capsys, environ=None):
    code = cli.main(argv, environ=environ or {})
    out = capsys.readouterr()
    return code, json.loads(out.out or out.err)


def test_published_crw_verify_and_backup_through_the_command(tmp_path, capsys, no_network):
    store = f"sqlite:{tmp_path / 'media.sqlite3'}"
    paths = h.write_private_inputs(tmp_path / "cone", *h.cone_inputs())
    code, result = _run(["--store", store, "published", "--product", "nhc_track_cone_v1",
                         "--metadata", str(paths["metadata"]), "--original", str(paths["original"]),
                         "--product-reference", str(paths["product"]), "--reuse-reference", str(paths["reuse"]),
                         "--receipt", str(paths["receipt"])], capsys)
    assert code == 0 and result["metadata_status"] == "unreviewed" and result["publication_approved"] is False
    manifest = result["manifest_sha256"]
    code, verified = _run(["--store", store, "verify", "--manifest", manifest], capsys)
    assert code == 0 and verified["verified"] and verified["product"] == "nhc_track_cone_v1"
    _, packet = varied_inputs("caribbean")
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet))
    packet_path.chmod(0o600)
    code, retained = _run(["--store", store, "crw-packet", "--packet", str(packet_path)], capsys)
    assert code == 0 and retained["packet_artifact_sha256"] == gist_assets.digest(gist_assets.encode_document(packet))
    code, backup = _run(["--store", store, "backup", "--target", str(tmp_path / "backup.sqlite3")], capsys)
    assert code == 0
    copy = gist_assets.SQLiteMediaStore(tmp_path / "backup.sqlite3")
    assert published.read(copy, manifest)[0]["product"] == "nhc_track_cone_v1"
    assert crw.load_packet(copy, retained["packet_artifact_sha256"]) == packet


def test_private_file_boundaries_and_unconfigured_store_refuse(tmp_path, capsys):
    paths = h.write_private_inputs(tmp_path / "cone", *h.cone_inputs())
    paths["original"].chmod(0o644)
    with pytest.raises(SystemExit, match="private"):
        cli.main(["--store", f"sqlite:{tmp_path / 'm.sqlite3'}", "published", "--product", "nhc_track_cone_v1",
                  "--metadata", str(paths["metadata"]), "--original", str(paths["original"]),
                  "--product-reference", str(paths["product"]), "--reuse-reference", str(paths["reuse"]),
                  "--receipt", str(paths["receipt"])], environ={})
    link = tmp_path / "link.json"
    link.symlink_to(paths["metadata"])
    with pytest.raises(SystemExit, match="symlinks"):
        cli.private_bytes(str(link))
    with pytest.raises(SystemExit, match="absolute"):
        cli.private_bytes("relative.json")
    code, held = _run(["verify", "--manifest", "0" * 64], capsys, environ={})
    assert code == 2 and held["held"] == "media_store_unavailable"
    code, missing = _run(["--store", f"sqlite:{tmp_path / 'm.sqlite3'}", "verify", "--manifest", "0" * 64], capsys)
    assert code == 2 and missing["held"] in ("media_store_unavailable", "media_original_missing")
