"""Pure tests for the local integration packet, on an invented temporary repository.

Git here only builds the invented fixture repository; the packet code itself
reads git with fixed arguments. Receipts are invented JSON and never executed.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import prepare_integration_packet as packet

ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
       "GIT_AUTHOR_NAME": "Invented", "GIT_AUTHOR_EMAIL": "invented@example.invalid", "GIT_COMMITTER_NAME": "Invented",
       "GIT_COMMITTER_EMAIL": "invented@example.invalid", "GIT_AUTHOR_DATE": "2032-01-01T00:00:00Z",
       "GIT_COMMITTER_DATE": "2032-01-01T00:00:00Z"}


def run(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], env=ENV, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, files, message):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        run(repo, "add", name)
    run(repo, "commit", "-q", "-m", message)
    return run(repo, "rev-parse", "HEAD")


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "init", "-q", "-b", "main")
    base = commit(repo, {"README": "invented\n", "dashboard/lib/state-contract.js": "export const v = 1\n"}, "base")
    run(repo, "checkout", "-q", "-b", "codex/invented")
    first = commit(repo, {"src/a.py": "A = 1\n"}, "donor one")
    second = commit(repo, {"dashboard/lib/state-contract.js": "export const v = 2\n"}, "donor two")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    return dict(repo=repo, base=base, first=first, second=second, evidence=evidence, tmp=tmp_path)


def receipt(world, name, returncode=0, seconds=1.5, log=b"invented log\n", **extra):
    (world["evidence"] / f"{name}.log").write_bytes(log)
    body = dict(label=name, returncode=returncode, seconds=seconds, log_sha256=packet.sha256(log), **extra)
    (world["evidence"] / f"{name}.json").write_text(json.dumps(body))
    return {"check": name.split("@")[0], "path": f"{name}.json", "log": f"{name}.log"}


def request(world, **line):
    value = dict(label="E9", worktree=str(world["repo"]), branch="codex/invented", base=world["base"], head=world["second"],
                 donors=[{"label": "one", "commit": world["first"]}, {"label": "two", "commit": world["second"]}],
                 required_checks=["unit", "gen_state_contract"], receipts=[], local_claims={"implemented": True})
    value.update(line)
    path = world["tmp"] / f"request-{len(list(world['tmp'].glob('request-*')))}.json"
    path.write_text(json.dumps({"schema": packet.REQUEST_SCHEMA, "evidence_root": str(world["evidence"]), "lines": [value]}))
    return path


def prepared(world, **line):
    out = world["tmp"] / f"packet-{len(list(world['tmp'].glob('packet-*')))}"
    packet.prepare(request(world, **line), out)
    return out, json.loads((out / "packet.json").read_text())


def test_clean_line_binds_commits_paths_hashes_order_and_generator_impact(world):
    receipts = [receipt(world, "unit"), receipt(world, "gen_state_contract")]
    out, value = prepared(world, receipts=receipts, local_claims={"implemented": True, "locally_tested": True})
    line = value["lines"][0]
    assert line["label"] == "E9" and line["branch"] == "codex/invented"
    assert (line["base"], line["head"]) == (world["base"], world["second"])
    assert [donor["commit"] for donor in line["donors"]] == [world["first"], world["second"]]
    assert line["donors"][0]["changed_paths"] == [{"path": "src/a.py", "status": "A", "head_sha256": packet.sha256(b"A = 1\n"), "head_bytes": 6}]
    assert {row["path"] for row in line["changed_paths"]} == {"src/a.py", "dashboard/lib/state-contract.js"}
    assert line["worktree"]["worktree_at_head"] is True and line["worktree"]["tracked_dirty_count"] == 0
    assert line["generator_impact"]["state_contract"] == {"outputs_changed": ["dashboard/lib/state-contract.js"], "check": "claimed_pass"}
    assert line["generator_impact"]["source_registry"] == {"outputs_changed": [], "check": "unperformed"}
    assert line["checks"]["unit"]["receipts"][0]["log"] == "verified"
    assert line["stages"]["locally_tested"] == "claimed" and line["contradictions"] == []
    assert all(line["stages"][stage] == "not_established_by_local_packet" for stage in packet.LATER_STAGES)
    checked = packet.validate(out, world["evidence"], {"E9": world["repo"]})
    assert (checked["status"], checked["reasons"]) == ("valid", [])
    assert checked["lines"] == [{"label": "E9", "commit_identity": "unchanged", "current_state": "clean",
                                 "worktree_head": world["second"], "tracked_dirty": [], "untracked_count": 0}]
    assert oct(out.stat().st_mode & 0o777) == "0o700" and all(oct(f.stat().st_mode & 0o777) == "0o600" for f in out.iterdir())


def test_missing_receipts_are_unperformed_never_pass(world):
    _, value = prepared(world, receipts=[receipt(world, "unit")], local_claims={"locally_tested": True})
    line = value["lines"][0]
    assert line["checks"]["gen_state_contract"] == {"required": True, "status": "unperformed", "receipts": []}
    assert line["stages"]["locally_tested"] == "partial"
    assert {"kind": "local_claim_not_supported", "check": "locally_tested"} in line["contradictions"]
    _, empty = prepared(world, receipts=[])
    assert empty["lines"][0]["stages"]["locally_tested"] == "unperformed"


def test_failures_are_preserved_and_contradictions_block_a_claim(world):
    failed, passed = receipt(world, "unit@1", returncode=1), receipt(world, "unit@2")
    _, value = prepared(world, receipts=[failed, passed, receipt(world, "gen_state_contract")])
    check = value["lines"][0]["checks"]["unit"]
    assert check["status"] == "claimed_pass_after_failure" and [r["claim"]["exit"] for r in check["receipts"]] == [1, 0]
    _, last_failed = prepared(world, receipts=[passed, failed])
    assert last_failed["lines"][0]["checks"]["unit"]["status"] == "claimed_fail"
    wrong_head = dict(receipt(world, "unit@3"), claimed_head=world["first"])
    _, value = prepared(world, receipts=[wrong_head, receipt(world, "gen_state_contract")])
    assert value["lines"][0]["checks"]["unit"]["status"] == "contradictory"
    assert value["lines"][0]["stages"]["locally_tested"] == "partial"
    tampered = receipt(world, "unit@4")
    (world["evidence"] / "unit@4.log").write_bytes(b"changed after the receipt\n")
    _, value = prepared(world, receipts=[tampered])
    assert value["lines"][0]["checks"]["unit"]["receipts"][0]["contradictions"] == ["log_hash_mismatch"]
    skipped = dict(check="unit", reason="invented skip")
    _, value = prepared(world, receipts=[receipt(world, "unit@5")], skipped_checks=[skipped])
    assert value["lines"][0]["checks"]["unit"]["status"] == "contradictory"


def test_duplicate_receipts_collapse_and_skips_are_not_passes(world):
    same = receipt(world, "unit")
    _, value = prepared(world, receipts=[same, dict(same)], skipped_checks=[{"check": "gen_state_contract", "reason": "invented: not run"}])
    line = value["lines"][0]
    assert len(line["checks"]["unit"]["receipts"]) == 1 and line["checks"]["unit"]["receipts"][0]["duplicates"] == 1
    assert line["checks"]["gen_state_contract"]["status"] == "skipped"
    assert line["stages"]["locally_tested"] == "partial"


@pytest.mark.parametrize("body", [
    '{"returncode": 0, "seconds": NaN}', '{"returncode": 0, "seconds": Infinity}', '{"returncode": true, "seconds": 1}',
    '{"returncode": "0", "seconds": 1}', '{"returncode": 0, "seconds": -1}', '{"returncode": 0, "seconds": 1e309}',
    '{"returncode": 0}', '{"returncode": 0, "returncode": 1, "seconds": 1}', '[0]', 'not json', '{"returncode": 99999, "seconds": 1}',
], ids=["nan", "infinity", "bool", "string", "negative", "overflow", "no_seconds", "duplicate_key", "list", "text", "range"])
def test_malformed_or_nonfinite_receipts_never_pass(world, body):
    (world["evidence"] / "bad.json").write_text(body)
    _, value = prepared(world, receipts=[{"check": "unit", "path": "bad.json"}])
    check = value["lines"][0]["checks"]["unit"]
    assert check["status"] == "malformed" and check["receipts"][0]["claim"]["malformed"] is True


def test_dirty_tracked_source_is_refused_unless_explicitly_allowed(world):
    (world["repo"] / "src/a.py").write_text("A = 2\n")
    with pytest.raises(packet.PacketError, match="tracked_source_dirty"):
        prepared(world)
    _, value = prepared(world, allow_dirty=True, receipts=[receipt(world, "unit"), receipt(world, "gen_state_contract")])
    state = value["lines"][0]["worktree"]
    assert state["tracked_dirty"] == ["src/a.py"] and value["lines"][0]["stages"]["locally_tested"] == "partial"
    (world["repo"] / "src/a.py").write_text("A = 1\n")
    (world["repo"] / "untracked.txt").write_text("invented\n")
    _, value = prepared(world)
    assert value["lines"][0]["worktree"]["untracked"] == ["untracked.txt"]


def test_moving_head_and_inconsistent_order_are_refused(world, monkeypatch):
    original, calls = packet.snapshot, []

    def moving(worktree, line):
        result = original(worktree, line)
        calls.append(1)
        if len(calls) == 2:
            result = dict(result, head_tree="0" * 40)
        return result
    monkeypatch.setattr(packet, "snapshot", moving)
    with pytest.raises(packet.PacketError, match="moving_snapshot"):
        prepared(world)
    monkeypatch.setattr(packet, "snapshot", original)
    with pytest.raises(packet.PacketError, match="donors_not_exact_ordered_chain"):
        prepared(world, donors=[{"label": "two", "commit": world["second"]}, {"label": "one", "commit": world["first"]}])
    with pytest.raises(packet.PacketError, match="donors_not_exact_ordered_chain"):
        prepared(world, donors=[{"label": "two", "commit": world["second"]}])
    with pytest.raises(packet.PacketError, match="base_not_ancestor_of_head"):
        prepared(world, base=world["second"], head=world["first"], donors=[{"label": "one", "commit": world["first"]}])
    with pytest.raises(packet.PacketError, match="branch_not_at_head"):
        prepared(world, head=world["first"], donors=[{"label": "one", "commit": world["first"]}])
    receipt(world, "unit")
    original_read = packet.read_bounded
    reads = []

    def changing(path, limit, field):
        data = original_read(path, limit, field)
        reads.append(field)
        return data + b" " if field == "input" else data
    monkeypatch.setattr(packet, "read_bounded", changing)
    with pytest.raises(packet.PacketError, match="moving_snapshot"):
        prepared(world, receipts=[{"check": "unit", "path": "unit.json"}])


@pytest.mark.parametrize("path,reason", [("../outside.json", "receipt_path_traversal"), ("/etc/hosts", "invalid_receipt_path"),
                                         ("link.json", "receipt_symlink"), ("folder/unit.json", "receipt_symlink"),
                                         ("missing.json", "receipt_missing")])
def test_traversal_and_symlinks_are_refused(world, path, reason):
    receipt(world, "unit")
    os.symlink(world["evidence"] / "unit.json", world["evidence"] / "link.json")
    real = world["tmp"] / "real-folder"
    real.mkdir()
    (real / "unit.json").write_text("{}")
    os.symlink(real, world["evidence"] / "folder")
    with pytest.raises(packet.PacketError, match=reason):
        prepared(world, receipts=[{"check": "unit", "path": path}])


def test_output_collision_and_symlinked_parent_are_refused(world):
    out, _ = prepared(world)
    with pytest.raises(packet.PacketError, match="output_collision"):
        packet.prepare(request(world), out)
    os.symlink(world["tmp"], world["tmp"] / "linked-parent")
    with pytest.raises(packet.PacketError, match="invalid_output_parent"):
        packet.prepare(request(world), world["tmp"] / "linked-parent" / "packet-new")


def test_later_stages_cannot_be_claimed_and_unknown_fields_are_refused(world):
    for stage in packet.LATER_STAGES:
        with pytest.raises(packet.PacketError, match="later_stage_not_settable_locally"):
            prepared(world, local_claims={stage: True})
    with pytest.raises(packet.PacketError, match="unknown_line_field"):
        prepared(world, merged=True)
    with pytest.raises(packet.PacketError, match="unknown_dependency"):
        prepared(world, depends_on=["E404"])


def test_bounded_inputs_and_outputs(world, monkeypatch):
    (world["evidence"] / "huge.json").write_bytes(b"{" + b" " * packet.LIMITS["receipt_bytes"] + b"}")
    with pytest.raises(packet.PacketError, match="receipt_too_large"):
        prepared(world, receipts=[{"check": "unit", "path": "huge.json"}])
    monkeypatch.setitem(packet.LIMITS, "changed_paths", 1)
    with pytest.raises(packet.PacketError, match="too_many_changed_paths"):
        prepared(world)
    monkeypatch.setitem(packet.LIMITS, "changed_paths", 2000)
    monkeypatch.setitem(packet.LIMITS, "packet_bytes", 100)
    with pytest.raises(packet.PacketError, match="packet_too_large"):
        prepared(world)


def test_rendering_is_deterministic_and_validation_detects_tampering(world):
    receipts = [receipt(world, "unit"), receipt(world, "gen_state_contract")]
    first, value = prepared(world, receipts=receipts)
    second, _ = prepared(world, receipts=receipts)
    for name in ("packet.json", "packet.md", "packet.sha256"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    text = (first / "packet.json").read_text()
    assert "/Users/" not in text and str(world["tmp"]) not in text
    assert "| unit | yes | claimed_pass |" in (first / "packet.md").read_text()
    (first / "packet.md").chmod(0o600)
    with open(first / "packet.md", "a") as handle:
        handle.write("edited\n")
    assert packet.validate(first, None, {})["status"] == "invalid"
    (world["evidence"] / "unit.json").write_text("{}")
    assert "evidence_changed:unit.json" in packet.validate(second, world["evidence"], {})["reasons"]
    commit(world["repo"], {"src/b.py": "B = 1\n"}, "moves the branch")
    assert "branch_moved:E9" in packet.validate(second, None, {"E9": world["repo"]})["reasons"]
    # Even a consistently re-signed packet cannot carry a later stage.
    forged = json.loads((second / "packet.json").read_text())
    forged["lines"][0]["stages"]["merged"] = True
    forged.pop("packet_id")
    forged["packet_id"] = packet.sha256(packet.canonical(forged).encode())
    body, markdown = packet.canonical(forged), packet.render_markdown(forged)
    fake = world["tmp"] / "forged"
    packet.write_new(fake, {"packet.json": body, "packet.md": markdown, "packet.sha256":
                            f"{packet.sha256(body.encode())}  packet.json\n{packet.sha256(markdown.encode())}  packet.md\n"})
    assert packet.validate(fake, None, {}) == {"status": "invalid", "reasons": ["later_stage_set:E9"]}


def test_long_absolute_worktree_paths_are_accepted(world):
    deep = world["tmp"] / ("long-" + "d" * 120) / ("deeper-" + "e" * 120) / "clone"
    deep.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "-b", "codex/invented", str(world["repo"]), str(deep)], env=ENV, check=True, capture_output=True)
    assert len(str(deep)) > 250
    _, value = prepared(world, worktree=str(deep))
    assert value["lines"][0]["label"] == "E9" and value["lines"][0]["worktree"]["worktree_at_head"] is True
    assert str(deep) not in json.dumps(value)
    with pytest.raises(packet.PacketError, match="invalid_worktree"):
        prepared(world, worktree="relative/repo")


def test_cli_reports_refusals_without_writing(world, capsys):
    out = world["tmp"] / "cli-packet"
    assert packet.main(["prepare", "--request", str(request(world, local_claims={"deployed": True})), "--out", str(out)]) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "refused", "reason": "later_stage_not_settable_locally"}
    assert not out.exists()
    assert packet.main(["prepare", "--request", str(request(world)), "--out", str(out)]) == 0
    assert packet.main(["validate", "--packet", str(out), "--worktree", f"E9={world['repo']}"]) == 0


# --- F2/R2: a receipt's whole binding is validated before any deduplication ---

def launcher_receipt(world, name, source_sha=None):
    body = {"exit_code": 0, "steps": [{"label": "journey", "code": 0, "seconds": 1.0}],
            "source_sha256": {"a.py": source_sha or packet.sha256(b"A = 1\n")}}
    (world["evidence"] / f"{name}.json").write_text(json.dumps(body))
    return {"check": "journey", "path": f"{name}.json", "kind": "journey_launcher", "source_prefix": "src/"}


@pytest.mark.parametrize("order", ["correct_first", "wrong_first"])
def test_identical_bytes_with_conflicting_claimed_heads_stay_contradictory(world, order):
    spec = receipt(world, "unit")
    right, wrong = dict(spec, claimed_head=world["second"]), dict(spec, claimed_head=world["first"])
    specs = [right, wrong] if order == "correct_first" else [wrong, right]
    _, value = prepared(world, receipts=specs, required_checks=["unit"])
    check = value["lines"][0]["checks"]["unit"]
    assert check["status"] == "contradictory" and len(check["receipts"]) == 2
    expected = ["matches", "mismatch"] if order == "correct_first" else ["mismatch", "matches"]
    assert [row["head_binding"] for row in check["receipts"]] == expected
    assert all("conflicting_duplicate_binding" in row["contradictions"] for row in check["receipts"])
    assert value["lines"][0]["stages"]["locally_tested"] == "unperformed"


def test_exact_duplicate_bindings_collapse_stably(world):
    spec = dict(receipt(world, "unit"), claimed_head=world["second"])
    _, value = prepared(world, receipts=[spec, dict(spec), dict(spec)], required_checks=["unit"])
    (row,) = value["lines"][0]["checks"]["unit"]["receipts"]
    assert row["duplicates"] == 2 and row["contradictions"] == [] and row["head_binding"] == "matches"
    assert value["lines"][0]["checks"]["unit"]["status"] == "claimed_pass"
    log_copy = dict(spec, log="unit-copy.log")
    (world["evidence"] / "unit-copy.log").write_bytes((world["evidence"] / "unit.log").read_bytes())
    _, again = prepared(world, receipts=[spec, log_copy], required_checks=["unit"])
    assert again["lines"][0]["checks"]["unit"]["receipts"][0]["duplicates"] == 1


@pytest.mark.parametrize("change", ["log", "source_prefix", "kind"])
def test_same_bytes_under_a_different_binding_are_preserved_as_a_conflict(world, change):
    if change == "log":
        first = receipt(world, "unit")
        (world["evidence"] / "other.log").write_bytes(b"a different log\n")
        second, name = dict(first, log="other.log"), "unit"
    elif change == "source_prefix":
        first = launcher_receipt(world, "launcher")
        second, name = dict(first, source_prefix=""), "journey"
    else:
        first = launcher_receipt(world, "launcher")
        second, name = {"check": "journey", "path": "launcher.json", "kind": "command"}, "journey"
    _, value = prepared(world, receipts=[first, second], required_checks=[name])
    check = value["lines"][0]["checks"][name]
    assert len(check["receipts"]) == 2 and check["status"] == "contradictory"
    assert all("conflicting_duplicate_binding" in row["contradictions"] for row in check["receipts"])


@pytest.mark.parametrize("bad,reason", [({"claimed_head": "not-a-commit"}, "invalid_claimed_head"),
                                        ({"kind": "shell"}, "invalid_receipt_kind"),
                                        ({"log": "../outside.log"}, "log_path_traversal"),
                                        ({"source_prefix": "/abs/"}, "invalid_source_prefix"),
                                        ({"source_prefix": "src/"}, "invalid_source_prefix")],
                         ids=["head", "kind", "log", "absolute_prefix", "prefix_on_command"])
def test_malformed_duplicate_metadata_is_refused_not_collapsed(world, bad, reason):
    spec = receipt(world, "unit")
    with pytest.raises(packet.PacketError, match=reason):
        prepared(world, receipts=[spec, dict(spec, **bad)])


def test_a_failing_row_is_never_replaced_by_an_equal_green_duplicate(world):
    failed = receipt(world, "unit@1", returncode=1)
    passed = receipt(world, "unit@2")
    _, value = prepared(world, receipts=[failed, passed, dict(failed)], required_checks=["unit"])
    check = value["lines"][0]["checks"]["unit"]
    assert [row["claim"]["exit"] for row in check["receipts"]] == [1, 0]
    assert check["receipts"][0]["duplicates"] == 1 and check["status"] == "claimed_pass_after_failure"


# --- F2/R3: --worktree compares the current checkout, not only commit identity ---

def worktree_result(result, name="E9"):
    return next(row for row in result["lines"] if row["label"] == name)


def test_validate_worktree_reports_tracked_edits_after_a_clean_packet(world):
    out, _ = prepared(world)
    clean = packet.validate(out, None, {"E9": world["repo"]})
    assert clean["status"] == "valid" and worktree_result(clean)["current_state"] == "clean"
    (world["repo"] / "src/a.py").write_text("A = 2\n")
    result = packet.validate(out, None, {"E9": world["repo"]})
    assert result["status"] == "invalid" and "worktree_state_changed:E9" in result["reasons"]
    row = worktree_result(result)
    assert row["commit_identity"] == "unchanged" and row["current_state"] == "drifted"
    assert row["tracked_dirty"] == ["src/a.py"]


@pytest.mark.parametrize("move", ["detach", "switch"])
def test_validate_worktree_reports_a_moved_head_while_the_branch_stays(world, move):
    out, _ = prepared(world)
    if move == "detach":
        run(world["repo"], "checkout", "-q", "--detach", world["first"])
    else:
        run(world["repo"], "checkout", "-q", "-b", "codex/other", world["first"])
    assert run(world["repo"], "rev-parse", "refs/heads/codex/invented") == world["second"]
    result = packet.validate(out, None, {"E9": world["repo"]})
    assert result["status"] == "invalid" and "worktree_head_changed:E9" in result["reasons"]
    assert worktree_result(result)["current_state"] == "drifted"


def test_untracked_drift_is_reported(world):
    out, _ = prepared(world)
    (world["repo"] / "new-untracked.txt").write_text("invented\n")
    result = packet.validate(out, None, {"E9": world["repo"]})
    assert result["status"] == "invalid" and "worktree_state_changed:E9" in result["reasons"]


def test_allowed_dirty_packets_validate_as_dirty_never_clean(world):
    (world["repo"] / "src/a.py").write_text("A = 2\n")
    receipts = [receipt(world, "unit"), receipt(world, "gen_state_contract")]
    out, value = prepared(world, allow_dirty=True, receipts=receipts)
    assert value["lines"][0]["stages"]["locally_tested"] == "partial"
    assert "DIRTY (1 tracked)" in (out / "packet.md").read_text()
    result = packet.validate(out, None, {"E9": world["repo"]})
    assert result["status"] == "valid" and worktree_result(result)["current_state"] == "dirty_as_recorded"
    (world["repo"] / "README").write_text("changed\n")
    assert packet.validate(out, None, {"E9": world["repo"]})["status"] == "invalid"
