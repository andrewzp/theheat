"""Private request-archive store: real filesystem durability, bounds and scope rules.

All requests are invented; ``send`` callables are explicit offline stand-ins
used only to drive the existing provider_call seam (no SDK or network here).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
import threading
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from src.two_bot import request_archive as archive
from src.two_bot import request_archive_replay as replay
from src.two_bot.trial_budget import provider_call

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def explicit_offline_store_senders(monkeypatch):
    # This store-only module deliberately uses stand-ins, never SDK transports.
    # Production has no no-hook sender path. Missing wire evidence stays incomplete.
    monkeypatch.setattr(archive.RequestArchiveScope, "require_supported_sender", lambda self, provider, send: None)


def private_root(base: Path, name: str = "private-archive") -> Path:
    root = base / name
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    return root


def request(text: str = "Invented offline request.", **extra) -> dict:
    return {"model": "gemini-flash-latest", "contents": text, **extra}


def records(scope_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (scope_dir / "manifest.jsonl").read_bytes().splitlines()]


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


# ------------------------------------------------------------ location rules

@pytest.mark.parametrize("bad", ["relative/archive", "/tmp/../tmp/x", "/a//b", ""])
def test_location_must_be_explicit_absolute_and_normalized(bad):
    with pytest.raises(archive.RequestArchiveRefused):
        archive.require_private_directory(bad, create=True)


def test_symlinked_component_and_non_private_directory_are_refused(tmp_path):
    real = private_root(tmp_path, "real")
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(archive.RequestArchiveRefused, match="not_canonical"):
        archive.require_private_directory(link, create=False)
    with pytest.raises(archive.RequestArchiveRefused, match="not_canonical"):
        archive.require_private_directory(link / "child", create=True)
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    os.chmod(loose, 0o755)
    with pytest.raises(archive.RequestArchiveRefused, match="owner_only"):
        archive.require_private_directory(loose, create=False)
    regular = tmp_path / "file"
    regular.write_text("invented")
    with pytest.raises(archive.RequestArchiveRefused, match="not_directory"):
        archive.require_private_directory(regular, create=False)
    with pytest.raises(archive.RequestArchiveRefused, match="missing"):
        archive.require_private_directory(tmp_path / "absent", create=False)


def test_scope_layout_is_owner_only_content_addressed_and_generated(tmp_path):
    root = tmp_path / "created-by-capture"
    with archive.capture(root, operation="layout probe") as scope:
        provider_call("safety", "google", request(), MagicMock(return_value="offline"))
    assert mode(root) == 0o700 and mode(scope.directory) == 0o700
    assert mode(scope.directory / "artifacts") == 0o700 and mode(scope.directory / "manifest.jsonl") == 0o600
    assert scope.directory.name.startswith("scope-") and len(scope.directory.name) == 38
    for path in (scope.directory / "artifacts").iterdir():
        assert mode(path) == 0o600 and archive.sha256_hex(path.read_bytes()) == path.name
    assert sorted(os.listdir(scope.directory)) == ["artifacts", "manifest.jsonl"]
    kinds = [r["type"] for r in records(scope.directory)]
    assert kinds == ["scope_opened", "call_intent", "call_result", "scope_closed"]
    result = records(scope.directory)[2]["data"]
    assert result["archival"] == "no_physical_send_observed" and result["billing"] == "unknown"


def test_manifest_lines_are_canonical_hash_chained_and_reject_floats(tmp_path):
    with archive.capture(private_root(tmp_path), operation="chain probe") as scope:
        provider_call("safety", "google", request(), MagicMock(return_value="offline"))
        with pytest.raises(ValueError):
            scope._record("stage_outcome", {"value": 0.5})
    previous = archive.GENESIS
    for line in (scope.directory / "manifest.jsonl").read_bytes().splitlines():
        parsed = archive.strict_json_loads(line)
        assert archive.canonical_json(parsed) == line and parsed["prev"] == previous
        previous = archive.sha256_hex(line)


# --------------------------------------------------------- scope ownership

def test_nested_concurrent_closed_and_reused_scopes_refuse(tmp_path):
    root = private_root(tmp_path)
    with archive.capture(root, operation="outer") as scope:
        with pytest.raises(archive.RequestArchiveRefused, match="nested"):
            with archive.capture(root, operation="inner"):
                pass
        errors = []

        def other_thread():
            try:
                with archive.capture(root, operation="concurrent"):
                    pass
            except archive.RequestArchiveRefused as exc:
                errors.append(exc.code)
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        assert errors == ["archive_scope_already_open"]
    assert archive.active_scope() is None
    with pytest.raises(archive.RequestArchiveRefused, match="closed"):
        scope.begin_call("safety", "google", request())


def test_foreign_thread_calls_are_refused_before_send_and_recorded(tmp_path):
    send = MagicMock(return_value="offline")
    outcome = []
    with archive.capture(private_root(tmp_path), operation="foreign probe") as scope:
        def worker():
            try:
                provider_call("safety", "google", request(), send)
            except archive.RequestArchiveRefused as exc:
                outcome.append(exc.code)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    assert outcome == ["archive_foreign_context"] and not send.called
    assert "foreign_call_refused" in [r["type"] for r in records(scope.directory)]


def test_context_is_reset_on_exception_and_close_records_the_exit(tmp_path):
    with pytest.raises(KeyError):
        with archive.capture(private_root(tmp_path), operation="exception probe") as scope:
            raise KeyError("invented")
    assert archive.active_scope() is None and archive._OPEN_SCOPE is None
    closed = records(scope.directory)[-1]
    assert closed["type"] == "scope_closed" and closed["data"]["exit"] == "exception"
    assert closed["data"]["exception_type"] == "KeyError"


def test_operation_label_is_bounded_and_certifies_nothing(tmp_path):
    for label in ("", "x" * 201, "bad\nlabel", 7):
        with pytest.raises(archive.RequestArchiveRefused, match="label"):
            with archive.capture(private_root(tmp_path, f"r{abs(hash(str(label)))}"), operation=cast(Any, label)):
                pass
    with archive.capture(private_root(tmp_path), operation="complete and verified") as scope:
        pass
    assert records(scope.directory)[0]["data"]["operation"]["authority"] == "caller_label_only"


# ---------------------------------------------------------------- bounds

def test_call_limit_refuses_the_129th_call_before_send(tmp_path):
    send = MagicMock(return_value="offline")
    with archive.capture(private_root(tmp_path), operation="call limit") as scope:
        for _ in range(archive.MAX_CALLS):
            provider_call("safety", "google", request(), send)
        with pytest.raises(archive.RequestArchiveRefused, match="call_limit"):
            provider_call("safety", "google", request(), send)
    assert send.call_count == archive.MAX_CALLS
    loaded = replay.load_archive(scope.directory)
    assert loaded.status == "incomplete" and len(loaded.calls) == archive.MAX_CALLS
    assert [r["reason"] for r in loaded.refusals] == ["archive_call_limit"]


def test_logical_request_over_two_mib_is_refused_not_truncated(tmp_path):
    send = MagicMock(return_value="offline")
    with archive.capture(private_root(tmp_path), operation="logical limit") as scope:
        with pytest.raises(archive.RequestArchiveRefused, match="logical_request_limit"):
            provider_call("safety", "google", request("x" * archive.MAX_LOGICAL_REQUEST_BYTES), send)
        provider_call("safety", "google", request(), send)  # Not held: nothing was purchased.
    assert send.call_count == 1 and scope.held is None


def test_scope_content_limit_refuses_new_capture_without_truncation(tmp_path):
    send = MagicMock(return_value="offline")
    size = archive.MAX_LOGICAL_REQUEST_BYTES - 200
    accepted = 0
    with archive.capture(private_root(tmp_path), operation="content limit") as scope:
        with pytest.raises(archive.RequestArchiveRefused, match="scope_content_limit"):
            for index in range(20):
                provider_call("safety", "google", request(f"{index:02d}" + "x" * size), send)
                accepted += 1
    assert accepted == send.call_count == 16 and scope.held is None
    loaded = replay.load_archive(scope.directory)
    assert loaded.status == "incomplete" and sum(loaded.artifact_sizes.values()) <= archive.MAX_SCOPE_CONTENT_BYTES


def test_record_limit_is_enforced(tmp_path):
    with archive.capture(private_root(tmp_path), operation="record limit") as scope:
        with pytest.raises(archive.RequestArchiveError, match="record_limit"):
            scope._record("stage_outcome", {"padding": "x" * archive.MAX_RECORD_BYTES})


def test_exact_duplicate_content_is_stored_once(tmp_path):
    send = MagicMock(return_value="offline")
    with archive.capture(private_root(tmp_path), operation="dedupe") as scope:
        provider_call("safety", "google", request(), send)
        provider_call("safety", "google", request(), send)
    intents = [r["data"] for r in records(scope.directory) if r["type"] == "call_intent"]
    assert intents[0]["logical_request"]["artifact"] == intents[1]["logical_request"]["artifact"]
    assert len(list((scope.directory / "artifacts").iterdir())) == 1


# -------------------------------------------- canonical numbers and Unicode

def test_logical_values_are_type_tagged_and_ambiguous_values_marked_unavailable(tmp_path):
    from google.genai import types
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
    send = MagicMock(return_value="offline")
    with archive.capture(private_root(tmp_path), operation="tagging") as scope:
        provider_call("safety", "google", {"model": "m", "contents": "é é", "config": config,
                                           "pairs": ("a", 1), "raw": b"\x00\xff", "extra": {"$k": 1}}, send)
        provider_call("safety", "google", {"model": "m", "contents": float("nan")}, send)
        provider_call("safety", "google", {"model": "m", "contents": "bad \ud800"}, send)
        provider_call("safety", "google", {"model": "m", "contents": object()}, send)
    intents = [r["data"] for r in records(scope.directory) if r["type"] == "call_intent"]
    tree = json.loads((scope.directory / "artifacts" / intents[0]["logical_request"]["artifact"]).read_bytes())
    kwargs = tree["kwargs"]
    assert kwargs["contents"] == "é é"  # Unicode retained exactly, not normalized.
    assert kwargs["config"]["$tagged"] == "model" and kwargs["config"]["value"]["temperature"] == {
        "$tagged": "float", "value": "0.1"}
    assert kwargs["pairs"] == {"$tagged": "tuple", "value": ["a", 1]}
    assert kwargs["raw"] == {"$tagged": "bytes", "value": "AP8="}
    assert kwargs["extra"] == {"$tagged": "dict", "value": [["$k", 1]]}  # No collision with tags.
    assert [i["logical_request"]["availability"] for i in intents[1:]] == ["unavailable"] * 3
    assert [i["logical_request"]["reason"] for i in intents[1:]] == [
        "unrepresentable_nonfinite_float", "unrepresentable_value", "unrepresentable_unsupported_type"]
    assert send.call_count == 4  # Logical unavailability is labeled; physical evidence decides completeness.


def test_mutation_after_capture_cannot_change_retained_evidence(tmp_path):
    payload = request(nested={"items": ["original"]})

    def mutating_send(**kwargs):
        kwargs["nested"]["items"].append("mutated during send")
        return {"returned": ["original"]}
    with archive.capture(private_root(tmp_path), operation="mutation") as scope:
        returned = provider_call("safety", "google", payload, mutating_send)
        returned["returned"].append("mutated after return")
        payload["contents"] = "changed after capture"
    intent = [r["data"] for r in records(scope.directory) if r["type"] == "call_intent"][0]
    tree = json.loads((scope.directory / "artifacts" / intent["logical_request"]["artifact"]).read_bytes())
    assert tree["kwargs"]["nested"] == {"items": ["original"]} and tree["kwargs"]["contents"] == request()["contents"]
    assert replay.load_archive(scope.directory).status == "incomplete"


# ----------------------------------------------- write failures and crashes

def test_manifest_write_failure_before_send_refuses_and_holds(tmp_path, monkeypatch):
    send = MagicMock(return_value="offline")
    real_write = archive._write_all
    with archive.capture(private_root(tmp_path), operation="write failure") as scope:
        def failing(fd, data):
            if fd == scope._manifest and b'"call_intent"' in data:
                raise OSError(28, "No space left on device (invented)")
            return real_write(fd, data)
        monkeypatch.setattr(archive, "_write_all", failing)
        with pytest.raises(archive.RequestArchiveRefused, match="write_failed_before_dispatch"):
            provider_call("safety", "google", request(), send)
        monkeypatch.setattr(archive, "_write_all", real_write)
        with pytest.raises(archive.RequestArchiveRefused, match="held"):
            provider_call("safety", "google", request(), send)
    assert not send.called and scope.held == "archive_write_failed_before_dispatch"
    loaded = replay.load_archive(scope.directory)
    assert loaded.status == "incomplete" and any(p.startswith("scope_held") for p in loaded.problems)


def test_real_readonly_artifact_directory_refuses_before_send(tmp_path):
    send = MagicMock(return_value="offline")
    with archive.capture(private_root(tmp_path), operation="readonly") as scope:
        os.chmod(scope.directory / "artifacts", 0o500)
        try:
            with pytest.raises(archive.RequestArchiveRefused, match="private_directory_not_owner_only"):
                provider_call("safety", "google", request(), send)
        finally:
            os.chmod(scope.directory / "artifacts", 0o700)
    assert not send.called and scope.held is not None


def _child(code: str, root: Path) -> subprocess.CompletedProcess:
    script = textwrap.dedent(f"""
        import os, sys, signal, resource
        sys.path.insert(0, {str(ROOT)!r})
        from pathlib import Path
        from unittest.mock import MagicMock
        from src.two_bot import request_archive as archive
        from src.two_bot.trial_budget import provider_call
        archive.RequestArchiveScope.require_supported_sender = lambda self, provider, send: None
        root = Path({str(root)!r})
        request = {{"model": "gemini-flash-latest", "contents": "Invented crash probe."}}
    """) + textwrap.dedent(code)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root.parent), "LC_ALL": "C", "LANG": "C",
           "NO_PROXY": "*", "no_proxy": "*", "PYTHON_DOTENV_DISABLED": "1", "NETRC": "/dev/null"}
    return subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120)


def test_process_killed_during_send_leaves_durable_intent_and_an_incomplete_archive(tmp_path):
    root = private_root(tmp_path)
    result = _child("""
        def dies(**kwargs):
            os._exit(9)  # Interrupted after durable intent, before any outcome.
        with archive.capture(root, operation="crash probe"):
            provider_call("safety", "google", request, MagicMock(return_value="ok"))
            provider_call("safety", "google", request, dies)
    """, root)
    assert result.returncode == 9
    scope_dir = next(root.iterdir())
    loaded = replay.load_archive(scope_dir)
    assert loaded.status == "incomplete"
    assert "scope_not_sealed" in loaded.problems and "call_without_result:2" in loaded.problems
    assert loaded.calls[1].result is None and loaded.calls[1].logical_request.availability == "captured"


def test_crash_between_temporary_write_and_publication_is_reported_not_adopted(tmp_path):
    root = private_root(tmp_path)
    result = _child("""
        os.link = lambda *a, **k: os._exit(7)
        with archive.capture(root, operation="publication crash"):
            provider_call("safety", "google", request, MagicMock(return_value="ok"))
    """, root)
    assert result.returncode == 7
    loaded = replay.load_archive(next(root.iterdir()))
    assert loaded.status == "incomplete" and "stray_temporary_file" in loaded.problems


def test_real_file_size_limit_write_failure_is_never_labeled_complete(tmp_path):
    root = private_root(tmp_path)
    result = _child("""
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        with archive.capture(root, operation="file size limit") as scope:
            resource.setrlimit(resource.RLIMIT_FSIZE, (4096, resource.RLIM_INFINITY))
            try:
                provider_call("safety", "google", {"model": "m", "contents": "x" * 8192},
                              MagicMock(return_value="ok"))
            except archive.RequestArchiveRefused as exc:
                print(exc.code)
            print("held", scope.held)
    """, root)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "archive_write_failed_before_dispatch" in result.stdout and "held archive_" in result.stdout
    loaded = replay.load_archive(next(root.iterdir()))
    assert loaded.status in {"incomplete", "invalid"} and loaded.status != "complete"


def test_private_exclusive_write_is_idempotent_and_refuses_conflicts(tmp_path):
    directory = private_root(tmp_path)
    assert archive.write_private_file_exclusive(directory, "report.json", b"same") is True
    assert archive.write_private_file_exclusive(directory, "report.json", b"same") is False
    with pytest.raises(archive.RequestArchiveRefused, match="conflict"):
        archive.write_private_file_exclusive(directory, "report.json", b"different")
    for bad in ("../escape", ".tmp-x", "a/b", ""):
        with pytest.raises(archive.RequestArchiveRefused, match="name_invalid"):
            archive.write_private_file_exclusive(directory, bad, b"x")
    assert mode(directory / "report.json") == 0o600 and (directory / "report.json").read_bytes() == b"same"


def test_code_identity_is_measured_at_entry_and_observed_drift_is_recorded(tmp_path, monkeypatch):
    import hashlib
    import shutil
    copy = tmp_path / "source-copy"
    for relative in archive.CODE_IDENTITY_FILES:
        (copy / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, copy / relative)
    monkeypatch.setattr(archive, "_ROOT", copy)
    send = MagicMock(return_value="offline")
    with archive.capture(private_root(tmp_path), operation="drift probe") as scope:
        provider_call("safety", "google", request(), send)
        with open(copy / "src/two_bot/prompts/critic_prompt.py", "a") as handle:
            handle.write("\n# invented local edit during a rehearsal\n")
        provider_call("safety", "google", request(), send)
        provider_call("safety", "google", request(), send)
    opened = records(scope.directory)[0]["data"]["code_identity"]
    expected = hashlib.sha256((ROOT / "src/two_bot/writer.py").read_bytes()).hexdigest()
    assert opened["files"]["src/two_bot/writer.py"] == expected and opened["authority"] == "local_provenance_only"
    drift = [r["data"] for r in records(scope.directory) if r["type"] == "code_drift_observed"]
    assert [d["path"] for d in drift] == ["src/two_bot/prompts/critic_prompt.py"]  # Reported once.
    assert drift[0]["at_entry"] != drift[0]["observed"]
    loaded = replay.load_archive(scope.directory)
    assert replay.summary(loaded)["code_drift"] == ["src/two_bot/prompts/critic_prompt.py"]
    assert loaded.status == "incomplete"  # Drift is provenance, not an integrity failure or authority.
