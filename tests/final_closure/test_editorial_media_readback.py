"""Final closure C4: the cross-host readback acceptance read (invented inputs, local store).

The same command, run on each host with that host's read-only configuration, is
the acceptance read in docs/MEDIA_STORE_SETUP.md. Here one local SQLite store
stands in for the writer and reader; no network, database server or credential.
"""
import json
import socket

import pytest

from scripts import retain_gist_media as cli
from tests import gist_published_helpers as h
from tests.gist_crw_helpers import varied_inputs


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def _run(argv, capsys, environ=None):
    code = cli.main(argv, environ=environ or {})
    out = capsys.readouterr()
    return code, out.out, out.err


def test_readback_verifies_each_identity_and_prints_no_location_or_bytes(tmp_path, capsys, no_network):
    path = tmp_path / "media.sqlite3"
    store = f"sqlite:{path}"
    paths = h.write_private_inputs(tmp_path / "cone", *h.cone_inputs())
    code, out, _ = _run(["--store", store, "published", "--product", "nhc_track_cone_v1",
                         "--metadata", str(paths["metadata"]), "--original", str(paths["original"]),
                         "--product-reference", str(paths["product"]), "--reuse-reference", str(paths["reuse"]),
                         "--receipt", str(paths["receipt"])], capsys)
    manifest = json.loads(out)["manifest_sha256"]
    _, packet = varied_inputs("caribbean")
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet))
    packet_path.chmod(0o600)
    code, out, _ = _run(["--store", store, "crw-packet", "--packet", str(packet_path)], capsys)
    packet_sha = json.loads(out)["packet_artifact_sha256"]

    # Reader-only configuration, as on the sender or preview host.
    code, out, err = _run(["readback", "--manifest", manifest, "--crw-packet", packet_sha], capsys,
                          environ={"THEHEAT_MEDIA_STORE": store})
    assert code == 0, err
    result = json.loads(out)
    assert result["capability"] == "reader" and result["credentials_printed"] is False
    assert [item["kind"] for item in result["items"]] == ["published", "crw_packet"]
    assert all(item["verified"] for item in result["items"]) and result["publication_approved"] is False
    assert str(path) not in out and str(tmp_path) not in out


def test_readback_of_a_missing_identity_is_a_named_hold(tmp_path, capsys, no_network):
    store = f"sqlite:{tmp_path / 'empty.sqlite3'}"
    code, out, err = _run(["--store", store, "readback", "--crw-packet", "0" * 64], capsys)
    assert code == 2 and not out
    assert json.loads(err)["held"] in {"media_source_packet_missing", "media_store_unavailable"}


def test_readback_needs_an_identity(tmp_path, capsys):
    with pytest.raises(SystemExit, match="at least one"):
        cli.main(["--store", f"sqlite:{tmp_path / 'm.sqlite3'}", "readback"], environ={})
