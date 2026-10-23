"""Offline verification/inspection/comparison of private archives in fresh processes.

Archives come from actual pipeline journeys with INVENTED offline providers.
Tamper cases edit copies only. Nothing here sends, generates or reads live state.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable

import pytest

from src.two_bot import request_archive as archive_module
from src.two_bot import request_archive_replay as replay
from tests.test_request_archive_sdk import (
    CANARIES, FIXTURE, accepted_script, fact_json, journey_env, private_root, run_journey,
)

__all__ = ["journey_env"]
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/replay_request_archive.py"


def cli(*args: str) -> tuple[int, dict, str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-invented-home", "LC_ALL": "C", "LANG": "C",
           "NO_PROXY": "*", "no_proxy": "*", "NETRC": "/dev/null", "PYTHON_DOTENV_DISABLED": "1",
           "ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}
    result = subprocess.run([sys.executable, "-I", str(CLI), *args], env=env, capture_output=True, text=True,
                            timeout=120, cwd="/")
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else {}, result.stdout + result.stderr


def tree_digest(directory: Path) -> dict[str, str]:
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


@pytest.fixture
def archives(journey_env, tmp_path):
    accepted = run_journey(accepted_script(), root=private_root(tmp_path, "accepted"))
    factual = accepted_script()
    factual["fact_check"] = [{"text": fact_json(False, failures=[FIXTURE["factual_failure"]])}]
    del factual["critic"]
    rejected = run_journey(factual, root=private_root(tmp_path, "rejected"))
    return accepted, rejected


def copy_archive(source: Path, tmp_path: Path, name: str) -> Path:
    parent = private_root(tmp_path, name)
    target = parent / source.name
    shutil.copytree(source, target)
    for path in [target, *target.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    return target


def test_fresh_process_validate_inspect_and_lineage_are_content_free(archives):
    accepted, _ = archives
    before = tree_digest(accepted.archive)
    code, validated, _ = cli("validate", str(accepted.archive))
    assert code == 0 and validated["status"] == "complete" and validated["problems"] == []
    code, inspected, raw = cli("inspect", str(accepted.archive))
    assert code == 0 and [c["stage"] for c in inspected["calls"]] == ["writer", "safety", "fact_check", "critic"]
    assert all(c["billing"] == "unknown" for c in inspected["calls"])
    code, traced, raw_lineage = cli("lineage", str(accepted.archive))
    assert code == 0 and traced["generations"][0]["terminal"]["accepted"] is True
    for output in (raw, raw_lineage):
        assert FIXTURE["accepted_tweet"] not in output and "PRIMARY SIGNAL" not in output.upper()
        for secret in CANARIES.values():
            assert secret not in output
    assert tree_digest(accepted.archive) == before  # The read workflow never alters archive bytes.


def test_compare_reports_precise_field_and_hash_differences(archives):
    accepted, rejected = archives
    code, compared, raw = cli("compare", str(accepted.archive), str(rejected.archive), "--call-a", "3", "--call-b", "3")
    assert code == 0
    assert compared["stage_sequence"] == [["writer", "safety", "fact_check", "critic"],
                                          ["writer", "safety", "fact_check"]]
    assert compared["code_files_differing"] == [] and compared["editorial_policy_identical"] is True
    call = compared["call"]
    assert call["fields"] == [] and call["logical_request"]["identical"] is True  # Same candidate, same request.
    assert call["attempts"][0]["request_sha256"][0] == call["attempts"][0]["request_sha256"][1]
    assert call["attempts"][0]["response_sha256"][0] != call["attempts"][0]["response_sha256"][1]
    assert FIXTURE["factual_failure"] not in raw
    code, writer_compare, _ = cli("compare", str(accepted.archive), str(accepted.archive), "--call-a", "1",
                                  "--call-b", "2")
    fields = {f["field"] for f in writer_compare["call"]["fields"]}
    assert {"stage", "model", "binding.candidate_text_sha256", "binding.phase"} <= fields
    assert writer_compare["call"]["logical_request"]["differences"]
    assert all(set(d) <= {"path", "change", "a_sha256", "b_sha256", "a", "b"}
               for d in writer_compare["call"]["logical_request"]["differences"])


def test_export_writes_exact_content_only_to_a_new_private_file(archives, tmp_path):
    accepted, _ = archives
    out_dir = private_root(tmp_path, "exports")
    before = tree_digest(accepted.archive)
    code, result, raw = cli("export", str(accepted.archive), "--call", "1", "--output", str(out_dir / "call-1.json"))
    assert code == 0 and result["export"] == "written" and result["content_written_to_stdout"] is False
    exported = json.loads((out_dir / "call-1.json").read_bytes())
    assert os.stat(out_dir / "call-1.json").st_mode & 0o777 == 0o600
    loaded = replay.load_archive(accepted.archive)
    sent = loaded.artifact(loaded.calls[0].attempts[0].request.artifact)
    assert exported["attempts"][0]["request"]["text"].encode() == sent
    assert FIXTURE["accepted_tweet"] in exported["attempts"][0]["response"]["text"]
    assert FIXTURE["accepted_tweet"] not in raw
    code, again, _ = cli("export", str(accepted.archive), "--call", "1", "--output", str(out_dir / "call-1.json"))
    assert code == 0 and again["export"] == "identical_existing"
    code, conflict, _ = cli("export", str(accepted.archive), "--call", "2", "--output", str(out_dir / "call-1.json"))
    assert code == 2 and conflict["error"] == "private_file_conflict"
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    os.chmod(public, 0o755)
    code, refused, _ = cli("export", str(accepted.archive), "--call", "1", "--output", str(public / "x.json"))
    assert code == 2 and refused["error"] == "private_directory_not_owner_only"
    assert tree_digest(accepted.archive) == before


def _rewrite_manifest(target: Path, edit) -> None:
    lines = (target / "manifest.jsonl").read_bytes().splitlines()
    lines = edit(lines)
    (target / "manifest.jsonl").write_bytes(b"".join(line + b"\n" for line in lines))


def _rechain(records: list[dict]) -> list[bytes]:
    previous, out = archive_module.GENESIS, []
    for index, record in enumerate(records, start=1):
        record["seq"], record["prev"] = index, previous
        line = archive_module.canonical_json(record)
        previous = archive_module.sha256_hex(line)
        out.append(line)
    return out


TAMPERS: dict[str, tuple[str, Callable[[Any], Any], str]] = {
    "artifact_byte": ("artifact", lambda t: _flip_artifact(t), "artifact_hash_mismatch"),
    "artifact_missing": ("artifact", lambda t: os.remove(next((t / "artifacts").iterdir())), "artifact_missing"),
    "extra_artifact": ("artifact", lambda t: _extra_artifact(t), "unreferenced_artifact_in_sealed_scope"),
    "value_changed": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [ls[0], ls[1].replace(
        b'"generation_input"', b'"generation_inputX"'), *ls[2:]]), "record_"),
    "reordered": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [ls[0], ls[2], ls[1], *ls[3:]]), "record_"),
    "deleted_line": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [ls[0], *ls[2:]]), "record_"),
    "duplicated_line": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [*ls[:3], ls[2], *ls[3:]]), "record_"),
    "not_canonical": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [ls[0].replace(b'":', b'": ', 1),
                                                                              *ls[1:]]), "record_not_canonical"),
    "duplicate_key": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [ls[0][:-1] + b',"at":"x"}',
                                                                              *ls[1:]]), "record_unparseable"),
    "nan_number": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [ls[0].replace(
        b'"seq":1', b'"seq":NaN'), *ls[1:]]), "record_unparseable"),
    "float_number": ("manifest", lambda t: _rewrite_manifest(t, lambda ls: [ls[0].replace(
        b'"seq":1', b'"seq":1.0'), *ls[1:]]), "record_unparseable"),
    "forged_count": ("rechain", lambda records: _forge(records, "call_result", "wire_attempts", 2), "call_result_counts"),
    "forged_candidate": ("rechain", lambda records: _forge(records, "candidate", "candidate_text_sha256", "0" * 64),
                         "candidate_binding"),
    "forged_close": ("rechain", lambda records: _forge(records, "scope_closed", "calls", 9), "scope_closed_counts"),
    "forged_call_number": ("rechain", lambda records: _forge(records, "call_intent", "call", 7), "call_sequence"),
}


def _flip_artifact(target: Path) -> None:
    path = sorted((target / "artifacts").iterdir())[0]
    data = bytearray(path.read_bytes())
    data[0] ^= 1
    path.write_bytes(bytes(data))


def _extra_artifact(target: Path) -> None:
    data = b"invented extra"
    path = target / "artifacts" / hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    os.chmod(path, 0o600)


def _forge(records: list[dict], kind: str, key: str, value) -> list[dict]:
    for record in records:
        if record["type"] == kind:
            record["data"][key] = value
            break
    return records


@pytest.mark.parametrize("case", sorted(TAMPERS))
def test_tampered_copies_are_invalid_and_never_clean(archives, tmp_path, case):
    accepted, _ = archives
    target = copy_archive(accepted.archive, tmp_path, "tamper")
    kind, edit, expected = TAMPERS[case]
    if kind == "rechain":
        records = [json.loads(line) for line in (target / "manifest.jsonl").read_bytes().splitlines()]
        lines = _rechain(edit(records))
        (target / "manifest.jsonl").write_bytes(b"".join(line + b"\n" for line in lines))
    else:
        edit(target)
    loaded = replay.load_archive(target)
    assert loaded.status == "invalid" and loaded.problems[0].startswith(expected), loaded.problems
    code, result, _ = cli("validate", str(target))
    assert code == 2 and result["status"] == "invalid"


def test_truncated_tail_and_unsealed_copies_are_incomplete_not_upgraded(archives, tmp_path):
    accepted, _ = archives
    target = copy_archive(accepted.archive, tmp_path, "truncated")
    data = (target / "manifest.jsonl").read_bytes()
    (target / "manifest.jsonl").write_bytes(data[: data.rstrip(b"\n").rfind(b"\n") + 1] + b'{"schema":')
    loaded = replay.load_archive(target)
    assert loaded.status == "incomplete"
    assert {"truncated_manifest_tail", "scope_not_sealed"} <= set(loaded.problems)
    assert len(loaded.calls) == 4 and loaded.terminals  # Verified prefix remains inspectable.
    code, result, _ = cli("validate", str(target))
    assert code == 1 and result["status"] == "incomplete"


@pytest.mark.parametrize("change", ["file_mode", "directory_mode", "symlinked_artifact", "symlinked_scope"])
def test_unsafe_permissions_and_symlinks_are_refused(archives, tmp_path, change):
    accepted, _ = archives
    target = copy_archive(accepted.archive, tmp_path, "unsafe")
    if change == "file_mode":
        os.chmod(target / "manifest.jsonl", 0o644)
        assert replay.load_archive(target).problems == ("manifest_unreadable",)
    elif change == "directory_mode":
        os.chmod(target, 0o755)
        with pytest.raises(archive_module.RequestArchiveRefused, match="owner_only"):
            replay.load_archive(target)
    elif change == "symlinked_artifact":
        artifact = sorted((target / "artifacts").iterdir())[0]
        real = tmp_path / "outside-artifact"
        real.write_bytes(artifact.read_bytes())
        os.chmod(real, 0o600)
        artifact.unlink()
        artifact.symlink_to(real)
        loaded = replay.load_archive(target)
        assert loaded.status == "invalid"
    else:
        link_parent = private_root(tmp_path, "linked")
        link = link_parent / target.name
        link.symlink_to(target)
        with pytest.raises(archive_module.RequestArchiveRefused, match="not_canonical"):
            replay.load_archive(link)
    code, _, _ = cli("validate", str(target if change != "symlinked_scope" else link_parent / target.name))
    assert code == 2


def test_cli_rejects_send_like_flags_and_has_no_send_mode():
    for flags in (["send", "/x"], ["validate", "/x", "--force"], ["replay", "/x"], ["validate", "/x", "--send"]):
        code, _, _ = cli(*flags)
        assert code == 64
    import re
    code_lines = [line for line in (CLI.read_text() + Path(replay.__file__).read_text()).splitlines()
                  if line.strip() and not line.strip().startswith("#")]
    pattern = re.compile(r"^\s*(import|from)\s+(pickle|subprocess|requests|urllib|httpx|httpx2|anthropic|google|socket)\b"
                         r"|\b(eval|exec|urlopen|provider_call|generate_draft)\(")
    assert not [line for line in code_lines if pattern.search(line)]


def test_cli_process_never_imports_provider_or_network_clients(archives):
    accepted, _ = archives
    probe = (f"import sys; sys.argv = ['replay', 'inspect', {str(accepted.archive)!r}]; "
             f"sys.path.insert(0, {str(ROOT)!r}); import runpy; "
             "import contextlib, io\n"
             "with contextlib.redirect_stdout(io.StringIO()):\n"
             f"    try: runpy.run_path({str(CLI)!r}, run_name='__main__')\n"
             "    except SystemExit as exc: code = exc.code\n"
             "print(code, sorted({m.split('.')[0] for m in sys.modules} & "
             "{'anthropic', 'google', 'httpx', 'httpx2', 'requests', 'urllib3', 'pickle'}))")
    result = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=120,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, cwd="/")
    assert result.stdout.strip() == "0 []", result.stdout + result.stderr


def test_versioned_read_api_returns_verified_records_with_availability(archives):
    accepted, rejected = archives
    loaded = replay.load_archive(accepted.archive)
    assert loaded.api_version == replay.READ_API_VERSION == 1
    call = loaded.calls[0]
    assert call.logical_request.availability == "captured" and call.attempts[0].response.availability == "captured"
    assert call.attempts[0].provider_ids["request_id_header"].startswith(FIXTURE["anthropic_request_id"])
    assert loaded.calls[1].attempts[0].provider_ids["response_body_responseId"].startswith(FIXTURE["google_response_id"])
    with pytest.raises(replay.ArchiveInvalid, match="not_referenced"):
        loaded.artifact("0" * 64)
    other = replay.load_archive(rejected.archive)
    assert other.terminals[0]["accepted"] is False and other.terminals[0]["kill_stage"] == "fact_check"
