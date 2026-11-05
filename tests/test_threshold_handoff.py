"""Exercise the handoff against a real disposable Git baseline, without remote I/O."""

import json
from pathlib import Path
import subprocess

import pytest

from scripts.threshold_handoff import INVENTORY, MANIFEST, RECEIPT, main


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    repo = tmp_path.resolve()
    monkeypatch.chdir(repo)
    _git("init", "-q")
    _git("config", "user.name", "Fixture")
    _git("config", "user.email", "fixture@example.invalid")
    _git("config", "commit.gpgsign", "false")
    data = Path("data")
    data.mkdir()
    (data / MANIFEST).write_bytes(b"installed\n")
    _git("add", "data")
    _git("commit", "-qm", "installed baseline")
    base = _git("rev-parse", "HEAD")
    packet = repo / "packet"
    args = ["--directory", str(packet), "--repo", "example/theheat", "--run-id", "45", "--base-sha", base]
    (data / MANIFEST).write_bytes(b"candidate\n")
    (data / INVENTORY).write_bytes(b"station_id,active\r\nXY1,1\r\n")
    return args, data, packet


def test_handoff_round_trip_preserves_exact_candidate_bytes(handoff):
    args, data, packet = handoff
    assert main(["pack", *args]) == 0
    assert (packet / MANIFEST).read_bytes() == (data / MANIFEST).read_bytes()
    assert (packet / INVENTORY).read_bytes() == (data / INVENTORY).read_bytes()
    assert set(p.name for p in packet.iterdir()) == {MANIFEST, INVENTORY, RECEIPT}
    assert main(["pack", *args]) == 1
    assert main(["verify", *args]) == 1
    (data / MANIFEST).write_bytes(b"installed\n")
    _git("commit", "--allow-empty", "-qm", "unrelated release")
    assert main(["verify", *args]) == 0


@pytest.mark.parametrize("leaf", [MANIFEST, INVENTORY, RECEIPT])
def test_candidate_tampering_is_held(handoff, leaf):
    args, data, packet = handoff
    assert main(["pack", *args]) == 0
    (data / MANIFEST).write_bytes(b"installed\n")
    candidate = packet / leaf
    candidate.write_bytes(candidate.read_bytes() + b"\n")
    assert main(["verify", *args]) == 1


def test_origin_and_installed_manifest_must_match(handoff):
    args, data, packet = handoff
    assert main(["pack", *args]) == 0
    assert json.loads((packet / RECEIPT).read_bytes())["run_id"] == "45"
    _git("add", str(data / MANIFEST))
    _git("commit", "-qm", "new baseline")
    (data / MANIFEST).write_bytes(b"installed\n")
    assert main(["verify", *args]) == 1
    (data / MANIFEST).write_bytes(b"candidate\n")
    _git("checkout", "--detach", args[-1])
    changed = ["46" if part == "45" else part for part in args]
    assert main(["verify", *changed]) == 1


def test_bad_origin_and_nonregular_input_never_create_a_packet(handoff):
    args, data, packet = handoff
    _git("commit", "--allow-empty", "-qm", "unrelated release")
    assert main(["pack", *args]) == 1
    assert not packet.exists()
    _git("checkout", "--detach", args[-1])
    (data / INVENTORY).unlink()
    (data / INVENTORY).symlink_to(MANIFEST)
    assert main(["pack", *args]) == 1
    assert not packet.exists()
