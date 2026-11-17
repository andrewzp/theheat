"""Invented Gist bytes only; no provider, model, state or restore operation."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import shutil

import pytest

from src.storage.gist_backup import backup_gists, validate_descriptors, GistBackupError, LIMITS
from src.evaluation.file_boundary import FileBoundaryError

ID, REVISION, RAW = "a" * 32, "1" * 40, "2" * 40
BODY = b'{"zero":-0,"wide":9007199254740993,"unknown":{"value":1.000}}\r\n'


def descriptors(names=("state.json",)):
    return dict(
        schema="theheat-gist-backup-descriptors-v1",
        capture_started_at="2026-11-17T10:00:00Z",
        capture_finished_at="2026-11-17T10:00:01Z",
        metadata_requests=2,
        limits=deepcopy(LIMITS),
        scope="Configured Gist revisions only; no transaction, restore or approval authority.",
        sources=[
            dict(
                id=ID,
                owner="InventedOwner",
                revision=REVISION,
                roles=["state"],
                metadata_sha256="3" * 64,
                files=[
                    dict(
                        filename=name,
                        source_bytes=len(BODY),
                        raw_revision=RAW,
                        url=f"https://gist.githubusercontent.com/InventedOwner/{ID}/raw/{RAW}/{name}",
                    )
                    for name in names
                ],
            )
        ],
    )


def input_file(tmp_path, value=None):
    path = tmp_path / "descriptors.json"
    path.write_bytes(json.dumps(value or descriptors()).encode())
    path.chmod(0o600)
    return str(path)


def fetch_bytes(url, remaining):
    assert url.startswith(f"https://gist.githubusercontent.com/InventedOwner/{ID}/raw/{RAW}/")
    assert 0 < remaining <= LIMITS["downloadSeconds"]
    yield BODY[:7]
    yield BODY[7:]


def test_complete_copy_preserves_literal_bytes_and_inert_case_distinct_names(tmp_path):
    source = input_file(tmp_path, descriptors(("State.json", "state.json")))
    output = tmp_path / "backup"
    summary = backup_gists(source, str(output), _fetch=fetch_bytes)
    assert summary == {
        "status": "complete",
        "files": 2,
        "objects": 1,
        "bytes": len(BODY) * 2,
        "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
    }
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert {row["filename"] for row in manifest["files"]} == {"State.json", "state.json"}
    for row in manifest["files"]:
        assert (output / row["object"]).read_bytes() == BODY
        assert row["sha256"] == hashlib.sha256(BODY).hexdigest()
        assert row["raw_revision"] != row["revision"]
    assert (output / "descriptors.json").read_bytes() == Path(source).read_bytes()
    assert not (output / "INCOMPLETE.json").exists()


@pytest.mark.parametrize("short", [True, False])
def test_incomplete_or_excess_body_retains_private_attempt_without_complete_marker(tmp_path, short):
    def broken(url, remaining):
        yield BODY[:-1] if short else BODY + b"extra"

    output = tmp_path / "partial"
    with pytest.raises(GistBackupError, match="backup_byte_count"):
        backup_gists(input_file(tmp_path), str(output), _fetch=broken)
    assert (output / "INCOMPLETE.json").is_file()
    assert (output / "descriptors.json").is_file()
    assert not (output / "COMPLETE.json").exists()
    assert list(output.glob("part-*"))
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())


def test_process_deadline_stops_stalled_network_without_marking_complete(tmp_path):
    def stalled(url, remaining):
        time.sleep(30)
        yield BODY

    output = tmp_path / "timed-out"
    start = time.monotonic()
    with pytest.raises(GistBackupError, match="backup_deadline"):
        backup_gists(input_file(tmp_path), str(output), _fetch=stalled, _timeout=0.3)
    assert time.monotonic() - start < 3
    assert (output / "INCOMPLETE.json").exists() and not (output / "COMPLETE.json").exists()


def test_completion_write_failure_never_leaves_a_complete_marker(tmp_path, monkeypatch):
    from src.storage import gist_backup

    write = gist_backup._write

    def disk_failure(directory, name, body):
        write(directory, name, body)
        if name == "COMPLETE.json":
            raise OSError("invented disk failure after bytes reached the file")

    monkeypatch.setattr(gist_backup, "_write", disk_failure)
    output = tmp_path / "completion-failed"
    with pytest.raises(GistBackupError, match="backup_capture_incomplete"):
        backup_gists(input_file(tmp_path), str(output), _fetch=fetch_bytes)
    assert (output / "INCOMPLETE.json").exists()
    assert not (output / "COMPLETE.json").exists()
    assert (output / ("object-" + hashlib.sha256(BODY).hexdigest())).read_bytes() == BODY


@pytest.mark.parametrize(
    "change",
    ["host", "gist", "raw_revision", "filename", "query", "userinfo", "size", "budget", "roles"],
)
def test_invalid_descriptor_refuses_before_network_or_output(tmp_path, change):
    value = descriptors()
    file = value["sources"][0]["files"][0]
    if change == "host":
        file["url"] = file["url"].replace("gist.githubusercontent.com", "attacker.example")
    elif change == "gist":
        file["url"] = file["url"].replace(ID, "b" * 32)
    elif change == "raw_revision":
        file["raw_revision"] = "4" * 40
    elif change == "filename":
        file["filename"] = "../outside"
    elif change == "query":
        file["url"] += "?token=never-forward"
    elif change == "userinfo":
        file["url"] = file["url"].replace("https://", "https://user:password@")
    elif change == "size":
        file["source_bytes"] = True
    elif change == "budget":
        value["limits"]["totalBytes"] += 1
    else:
        value["sources"][0]["roles"] = ["unexpected"]
    with pytest.raises(GistBackupError):
        backup_gists(
            input_file(tmp_path, value), str(tmp_path / "must-not-exist"), _fetch=fetch_bytes
        )
    assert not (tmp_path / "must-not-exist").exists()


def test_exact_copies_count_once_and_conflicting_source_identity_is_never_picked():
    value = descriptors()
    value["sources"] *= 2
    plan, files = validate_descriptors(json.dumps(value).encode())
    assert len(plan["sources"]) == len(files) == 1
    value["sources"][1] = deepcopy(value["sources"][1])
    value["sources"][1]["revision"] = "5" * 40
    with pytest.raises(GistBackupError, match="backup_source_identity_conflict"):
        validate_descriptors(json.dumps(value).encode())


def test_existing_output_and_symlinked_or_special_input_are_refused(tmp_path):
    source = input_file(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep"
    sentinel.write_bytes(b"untouched")
    with pytest.raises(FileExistsError):
        backup_gists(source, str(output), _fetch=fetch_bytes)
    assert sentinel.read_bytes() == b"untouched"
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(FileBoundaryError):
        backup_gists(str(link), str(tmp_path / "not-created"), _fetch=fetch_bytes)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(FileBoundaryError, match="input_not_regular"):
        backup_gists(str(fifo), str(tmp_path / "still-not-created"), _fetch=fetch_bytes)


@pytest.mark.parametrize("status,encoding", [(302, "identity"), (200, "gzip"), (401, "identity")])
def test_raw_transport_never_follows_redirects_or_uses_ambient_credentials(
    monkeypatch, status, encoding
):
    from src.storage.gist_backup import _raw_request
    import requests

    calls = []

    class Response:
        status_code = status
        headers = {"Content-Encoding": encoding}
        history = []

        def close(self):
            calls.append("response_closed")

        def iter_content(self, **kwargs):
            raise AssertionError("rejected response body must not be read")

    class Session:
        trust_env = True

        def get(self, url, **kwargs):
            assert self.trust_env is False
            assert kwargs == dict(
                headers={"Accept-Encoding": "identity"},
                stream=True,
                allow_redirects=False,
                timeout=(5, 10),
            )
            calls.append("one_get")
            return Response()

        def close(self):
            calls.append("session_closed")

    monkeypatch.setattr(requests, "Session", Session)
    with pytest.raises(GistBackupError, match="backup_raw_unavailable"):
        list(_raw_request(descriptors()["sources"][0]["files"][0]["url"], 20))
    assert calls == ["one_get", "response_closed", "session_closed"]


def test_raw_provider_exception_is_sanitized_and_a_completed_prefix_is_kept(tmp_path):
    def fails_after_first(url, remaining):
        if url.endswith("second.json"):
            raise RuntimeError("private provider body and invented-secret")
        yield BODY

    output = tmp_path / "partial-prefix"
    with pytest.raises(GistBackupError, match="^backup_download_unavailable$"):
        backup_gists(
            input_file(tmp_path, descriptors(("first.json", "second.json"))),
            str(output),
            _fetch=fails_after_first,
        )
    assert (output / ("object-" + hashlib.sha256(BODY).hexdigest())).read_bytes() == BODY
    assert not (output / "COMPLETE.json").exists()
    assert not (output / "manifest.json").exists()
    assert b"invented-secret" not in (output / "INCOMPLETE.json").read_bytes()


def test_parent_path_swap_cannot_redirect_incremental_backup_writes(tmp_path):
    parent, moved, elsewhere = tmp_path / "parent", tmp_path / "held", tmp_path / "elsewhere"
    parent.mkdir()
    elsewhere.mkdir()

    def swapping(url, remaining):
        parent.rename(moved)
        parent.symlink_to(elsewhere, target_is_directory=True)
        yield BODY

    summary = backup_gists(input_file(tmp_path), str(parent / "backup"), _fetch=swapping)
    assert summary["status"] == "complete"
    assert (moved / "backup" / "COMPLETE.json").exists()
    assert list(elsewhere.iterdir()) == []


def test_symlinked_output_ancestor_is_refused_before_download(tmp_path):
    target, link = tmp_path / "target", tmp_path / "shortcut"
    target.mkdir()
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileBoundaryError, match="symlinked_path"):
        backup_gists(input_file(tmp_path), str(link / "backup"), _fetch=fetch_bytes)
    assert list(target.iterdir()) == []


def test_authenticated_handler_to_real_cli_preserves_exact_literal_bytes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node is not None, "Node is required for the actual handler-to-CLI journey"
    env = dict(
        PATH=os.environ.get("PATH", "/usr/bin:/bin"),
        HOME=str(tmp_path),
        LC_ALL="C",
        LANG="C",
        PYTHONDONTWRITEBYTECODE="1",
        NO_PROXY="*",
        no_proxy="*",
    )
    script = r"""
import { GET } from "./dashboard/app/api/backup-manifest/route.js"
const [id, revision, raw, bytes] = process.argv.slice(1)
Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "invented-operator",
  DASHBOARD_PASSWORD: "invented-password", GITHUB_TOKEN: "invented-token", GIST_ID: id,
  THEHEAT_FEEDBACK_GIST_ID: id, THEHEAT_STATE_BACKEND: "gist" })
let calls = 0
globalThis.fetch = async (url, options) => {
  calls++
  if (url !== `https://api.github.com/gists/${id}${calls === 1 ? "" : "/" + revision}` ||
      options.headers.Authorization !== "Bearer invented-token") throw Error("unexpected request")
  return Response.json({ id, truncated: false, owner: { login: "InventedOwner" },
    history: [{ version: revision }], files: { "state.json": { filename: "state.json",
      size: Number(bytes), content: "do not use this incomplete API content", truncated: true,
      raw_url: `https://gist.githubusercontent.com/InventedOwner/${id}/raw/${raw}/state.json` } } })
}
const request = new Request("https://invented.example/api/backup-manifest", {
  headers: { host: "invented.example", authorization: "Basic " +
    Buffer.from("invented-operator:invented-password").toString("base64") } })
const response = await GET(request)
if (response.status !== 200 || calls !== 2) throw Error("descriptor capture failed")
process.stdout.write(await response.text())
"""
    descriptor = subprocess.run(
        [node, "--input-type=module", "-e", script, ID, REVISION, RAW, str(len(BODY))],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert descriptor.returncode == 0, descriptor.stderr.decode()[-2000:]
    source = tmp_path / "route-descriptors.json"
    source.write_bytes(descriptor.stdout)
    source.chmod(0o600)
    assert b"invented-token" not in descriptor.stdout
    assert b"incomplete API content" not in descriptor.stdout
    output = tmp_path / "cli-backup"
    # Only the raw network boundary is fake. The actual CLI, POSIX worker,
    # no-follow filesystem, parent verification and complete marker all run.
    wrapper = r"""
import sys
from src.storage import gist_backup
body = bytes.fromhex(sys.argv[1])
def transport(url, remaining):
    assert url == sys.argv[2]
    assert remaining > 0
    yield body[:3]
    yield body[3:]
gist_backup._raw_request = transport
from scripts.backup_gist import main
raise SystemExit(main(sys.argv[3:]))
"""
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            wrapper,
            BODY.hex(),
            descriptors()["sources"][0]["files"][0]["url"],
            "--descriptors",
            str(source),
            "--output",
            str(output),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert run.returncode == 0, run.stderr.decode()[-2000:]
    summary = json.loads(run.stdout)
    assert summary["status"] == "complete" and summary["files"] == summary["objects"] == 1
    manifest_bytes = (output / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert summary["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert manifest["descriptors"]["sources"][0]["roles"] == ["feedback", "state"]
    row = manifest["files"][0]
    assert (output / row["object"]).read_bytes() == BODY
    assert row["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert (output / "descriptors.json").read_bytes() == descriptor.stdout
    assert json.loads((output / "COMPLETE.json").read_bytes()) == summary
