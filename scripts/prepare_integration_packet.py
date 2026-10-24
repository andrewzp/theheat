#!/usr/bin/env python3
"""Prepare and validate a local integration packet for root review.

A packet binds one or more donor lines (base -> head commits) to exact changed
paths and byte hashes, clean/dirty state, ordered donor commits, generator
impact and explicitly supplied command receipts, so root can integrate without
rereading a conversation. It is local evidence only: it cannot establish
stronger review, exact-head CI, merge, deployment, runtime observation or
product acceptance, and it never promotes anything.

    prepare_integration_packet.py prepare --request request.json --out NEW_DIR
    prepare_integration_packet.py validate --packet DIR [--evidence-root DIR] [--worktree LABEL=DIR ...]

Inputs are only what the request names. Git is used read-only with fixed
arguments and a scrubbed environment. Receipts are parsed as data, never
executed; a receipt's exit code is a supplied claim, kept separate from the
verified identity of its bytes. Missing checks are UNPERFORMED, never pass.
See docs/INTEGRATION_PACKET.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

REQUEST_SCHEMA = "theheat.integration-packet-request/v1"
PACKET_SCHEMA = "theheat.integration-packet/v1"
LOCAL_STAGES = ("implemented", "locally_tested")
LATER_STAGES = ("stronger_review", "exact_head_ci", "merged", "deployed", "runtime_observed", "product_accepted")
# Explicit generator outputs (scripts/gen_*.py at a87bb66); impact is never guessed.
GENERATORS = {
    "source_registry": ("dashboard/lib/source-registry.json",),
    "editorial_policy": ("dashboard/lib/editorial-policy-manifest.js",),
    "dashboard_graphic_runtime": ("dashboard/graphic-runtime.zip", "dashboard/lib/graphic-runtime-manifest.json"),
    "state_contract": ("dashboard/lib/state-contract.js",),
    "usage_cost_contract": ("dashboard/lib/usage-cost-contract.js",),
    "runtime_report_workflow": (".github/workflows/runtime-report.yml",),
}
LIMITS = dict(lines=16, donors=64, receipts=256, artifacts=256, changed_paths=2000, listed_untracked=50,
              receipt_bytes=1_048_576, artifact_bytes=64 * 1_048_576, packet_bytes=4 * 1_048_576, text=200)
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
GIT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C", "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


class PacketError(Exception):
    """A refusal with a fixed reason code; nothing is written."""


def refuse(reason: str) -> NoReturn:
    raise PacketError(reason)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key")
        return dict(items)

    def constant(name: str) -> NoReturn:
        raise ValueError("nonfinite")
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=1, ensure_ascii=True, allow_nan=False) + "\n"


def text(value: Any, field: str) -> str:
    if type(value) is not str or not value or len(value) > LIMITS["text"] or not value.isprintable() or not value.isascii():
        refuse(f"invalid_{field}")
    return value


def absolute_path(value: Any, field: str) -> Path:
    """A caller-named absolute path (never recorded); long temporary paths are fine."""
    if type(value) is not str or not value.startswith("/") or len(value) > 4096 or not value.isprintable():
        refuse(f"invalid_{field}")
    return Path(value)


def label(value: Any, field: str) -> str:
    if type(value) is not str or not LABEL.fullmatch(value):
        refuse(f"invalid_{field}")
    return value


def commit_id(value: Any, field: str) -> str:
    if type(value) is not str or not SHA1.fullmatch(value):
        refuse(f"invalid_{field}")
    return value


def git(worktree: Path, *args: str) -> bytes:
    """Read-only git with fixed argv; never a shell, hook, pager or credential."""
    result = subprocess.run(["git", "-C", str(worktree), "--no-pager", *args], env=GIT_ENV, capture_output=True,
                            timeout=60, check=False, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        refuse("git_read_failed")
    return result.stdout


def git_ok(worktree: Path, *args: str) -> bool:
    result = subprocess.run(["git", "-C", str(worktree), "--no-pager", *args], env=GIT_ENV, capture_output=True,
                            timeout=60, check=False, stdin=subprocess.DEVNULL)
    return result.returncode == 0


def resolve(worktree: Path, revision: str) -> tuple[str, str]:
    commit = git(worktree, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}").decode().strip()
    tree = git(worktree, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{tree}}").decode().strip()
    if commit != revision or not SHA1.fullmatch(tree):
        refuse("revision_not_exact")
    return commit, tree


def inside(root: Path, relative: Any, field: str) -> Path:
    """An existing regular file under root, reached without any symlink or '..'."""
    if type(relative) is not str or not relative or relative.startswith("/") or "\\" in relative:
        refuse(f"invalid_{field}_path")
    parts = PurePosixPath(relative).parts
    if any(part in ("", ".", "..") for part in parts):
        refuse(f"{field}_path_traversal")
    current = root
    for part in parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except OSError:
            refuse(f"{field}_missing")
        if stat.S_ISLNK(mode):
            refuse(f"{field}_symlink")
    if not stat.S_ISREG(mode):
        refuse(f"{field}_not_regular")
    return current


def read_bounded(path: Path, limit: int, field: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        refuse(f"{field}_unreadable")
    with os.fdopen(descriptor, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        refuse(f"{field}_too_large")
    return data


def finite_number(value: Any, high: float) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > high:
        return None
    return float(value)


def exit_code(value: Any) -> int | None:
    return value if type(value) is int and -1024 <= value <= 1024 else None


def parse_receipt(kind: str, data: bytes) -> tuple[dict[str, Any], dict[str, str]]:
    """Claimed fields only; malformed receipts are kept and can never pass."""
    try:
        value = strict_json(data)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return {"malformed": True}, {}
    if type(value) is not dict:
        return {"malformed": True}, {}
    claim: dict[str, Any] = {"malformed": False}
    sources: dict[str, str] = {}
    if kind == "command":
        claim["exit"] = exit_code(value.get("returncode"))
        claim["seconds"] = finite_number(value.get("seconds"), 7 * 86400)
        log = value.get("log_sha256")
        claim["log_sha256"] = log if type(log) is str and SHA256.fullmatch(log) else None
        if claim["exit"] is None or claim["seconds"] is None:
            claim["malformed"] = True
    elif kind == "journey_launcher":
        claim["exit"] = exit_code(value.get("exit_code"))
        steps = value.get("steps")
        claim["seconds"] = None
        if type(steps) is list and 0 < len(steps) <= 32:
            seconds = [finite_number(step.get("seconds"), 7 * 86400) if type(step) is dict else None for step in steps]
            known = [item for item in seconds if item is not None]
            if len(known) == len(seconds):
                claim["seconds"] = round(sum(known), 3)
        claim["log_sha256"] = None
        raw = value.get("source_sha256")
        if type(raw) is dict and len(raw) <= 256 and all(type(k) is str and type(v) is str and SHA256.fullmatch(v) for k, v in raw.items()):
            sources = dict(raw)
        if claim["exit"] is None or claim["seconds"] is None or not sources:
            claim["malformed"] = True
    else:
        refuse("invalid_receipt_kind")
    return claim, sources


def blob_sha(worktree: Path, commit: str, path: str) -> tuple[str, int]:
    data = git(worktree, "cat-file", "blob", f"{commit}:{path}")
    return sha256(data), len(data)


def changed_paths(worktree: Path, base: str, head: str) -> list[dict[str, Any]]:
    raw = git(worktree, "diff", "--no-renames", "--name-status", "-z", base, head, "--")
    fields = raw.split(b"\0")
    rows: list[dict[str, Any]] = []
    for index in range(0, len(fields) - 1, 2):
        status, path = fields[index].decode(), fields[index + 1].decode("utf-8", "strict")
        if status not in ("A", "M", "D", "T"):
            refuse("unsupported_change_status")
        row: dict[str, Any] = {"path": path, "status": status}
        if status != "D":
            row["head_sha256"], row["head_bytes"] = blob_sha(worktree, head, path)
        if status != "A":
            row["base_sha256"], row["base_bytes"] = blob_sha(worktree, base, path)
        rows.append(row)
        if len(rows) > LIMITS["changed_paths"]:
            refuse("too_many_changed_paths")
    return rows


def worktree_state(worktree: Path, head: str) -> dict[str, Any]:
    at = git(worktree, "rev-parse", "--verify", "HEAD").decode().strip()
    if at != head:
        return {"worktree_at_head": False, "tracked_dirty": None, "untracked": None}
    raw = git(worktree, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = [entry.decode("utf-8", "strict") for entry in raw.split(b"\0") if entry]
    tracked = sorted(entry[3:] for entry in entries if not entry.startswith("??"))
    untracked = sorted(entry[3:] for entry in entries if entry.startswith("??"))
    return {"worktree_at_head": True, "tracked_dirty": tracked[:LIMITS["listed_untracked"]], "tracked_dirty_count": len(tracked),
            "untracked": untracked[:LIMITS["listed_untracked"]], "untracked_count": len(untracked)}


def snapshot(worktree: Path, line: dict[str, Any]) -> dict[str, Any]:
    """Every git identity that must not move while the packet is prepared."""
    base, base_tree = resolve(worktree, line["base"])
    head, head_tree = resolve(worktree, line["head"])
    if not git_ok(worktree, "merge-base", "--is-ancestor", base, head):
        refuse("base_not_ancestor_of_head")
    chain = git(worktree, "rev-list", "--reverse", "--first-parent", f"{base}..{head}").decode().split()
    branch = None
    if line.get("branch") is not None:
        branch = git(worktree, "rev-parse", "--verify", "--end-of-options", f"refs/heads/{line['branch']}^{{commit}}").decode().strip()
    return {"base": base, "base_tree": base_tree, "head": head, "head_tree": head_tree, "chain": chain, "branch_commit": branch,
            "state": worktree_state(worktree, head)}


def check_status(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "unperformed"
    if any(row["contradictions"] for row in rows):
        return "contradictory"
    if any(row["claim"]["malformed"] for row in rows):
        return "malformed"
    exits = [row["claim"]["exit"] for row in rows]
    if exits[-1] != 0:
        return "claimed_fail"
    return "claimed_pass" if all(code == 0 for code in exits) else "claimed_pass_after_failure"


def prepare_line(raw: Any, root: Path, seen: set[str]) -> dict[str, Any]:
    if type(raw) is not dict:
        refuse("invalid_line")
    allowed = {"label", "worktree", "branch", "base", "head", "donors", "depends_on", "allow_dirty", "required_checks",
               "receipts", "skipped_checks", "artifacts", "local_claims"}
    if set(raw) - allowed:
        refuse("unknown_line_field")
    name = label(raw.get("label"), "line_label")
    if name in seen:
        refuse("duplicate_line_label")
    seen.add(name)
    line: dict[str, Any] = {"base": commit_id(raw.get("base"), "base"), "head": commit_id(raw.get("head"), "head"),
            "branch": None if raw.get("branch") is None else text(raw.get("branch"), "branch")}
    worktree = absolute_path(raw.get("worktree"), "worktree")
    claims = raw.get("local_claims", {})
    if type(claims) is not dict or set(claims) - set(LOCAL_STAGES):
        refuse("later_stage_not_settable_locally" if type(claims) is dict and set(claims) & set(LATER_STAGES) else "invalid_local_claims")
    if not all(type(value) is bool for value in claims.values()):
        refuse("invalid_local_claims")
    first = snapshot(worktree, line)
    donors = raw.get("donors")
    if type(donors) is not list or not donors or len(donors) > LIMITS["donors"]:
        refuse("invalid_donors")
    donor_rows: list[dict[str, Any]] = []
    for donor in donors:
        if type(donor) is not dict or set(donor) != {"label", "commit"}:
            refuse("invalid_donor")
        donor_rows.append({"label": label(donor["label"], "donor_label"), "commit": commit_id(donor["commit"], "donor_commit")})
    if [row["commit"] for row in donor_rows] != first["chain"]:
        refuse("donors_not_exact_ordered_chain")
    for donor_row in donor_rows:
        parent = git(worktree, "rev-parse", "--verify", "--end-of-options", f"{donor_row['commit']}^").decode().strip()
        donor_row["parent"] = parent
        donor_row["tree"] = git(worktree, "rev-parse", "--verify", "--end-of-options", f"{donor_row['commit']}^{{tree}}").decode().strip()
        donor_row["changed_paths"] = changed_paths(worktree, parent, donor_row["commit"])
    paths = changed_paths(worktree, line["base"], line["head"])
    state = first["state"]
    if state["worktree_at_head"] and state["tracked_dirty_count"] and raw.get("allow_dirty") is not True:
        refuse("tracked_source_dirty")
    if line["branch"] is not None and first["branch_commit"] != line["head"]:
        refuse("branch_not_at_head")
    depends = raw.get("depends_on", [])
    if type(depends) is not list or len(depends) > LIMITS["lines"]:
        refuse("invalid_depends_on")
    required = raw.get("required_checks", [])
    if type(required) is not list or len(required) > LIMITS["receipts"]:
        refuse("invalid_required_checks")
    required_names = [label(name, "check") for name in required]
    if len(set(required_names)) != len(required_names):
        refuse("duplicate_required_check")
    receipts = raw.get("receipts", [])
    if type(receipts) is not list or len(receipts) > LIMITS["receipts"]:
        refuse("invalid_receipts")
    head_blobs = {row["path"]: row.get("head_sha256") for row in paths}
    by_check: dict[str, list[dict[str, Any]]] = {}
    inputs: list[dict[str, Any]] = []
    contradictions: list[dict[str, str]] = []
    for spec in receipts:
        if type(spec) is not dict or set(spec) - {"check", "path", "kind", "log", "claimed_head", "source_prefix"}:
            refuse("invalid_receipt")
        check = label(spec.get("check"), "check")
        kind = spec.get("kind", "command")
        location = inside(root, spec.get("path"), "receipt")
        data = read_bounded(location, LIMITS["receipt_bytes"], "receipt")
        digest = sha256(data)
        rows = by_check.setdefault(check, [])
        if any(row["sha256"] == digest for row in rows):
            next(row for row in rows if row["sha256"] == digest)["duplicates"] += 1
            continue
        claim, sources = parse_receipt(kind, data)
        row: dict[str, Any] = {"path": spec["path"], "sha256": digest, "bytes": len(data), "kind": kind, "claim": claim,
                               "duplicates": 0, "contradictions": [], "log": "not_supplied", "head_binding": "unstated",
                               "source_binding": "absent"}
        inputs.append({"path": spec["path"], "sha256": digest})
        if spec.get("log") is not None:
            log_path = inside(root, spec["log"], "log")
            log_data = read_bounded(log_path, LIMITS["artifact_bytes"], "log")
            inputs.append({"path": spec["log"], "sha256": sha256(log_data)})
            row["log_path"], row["log_sha256"] = spec["log"], sha256(log_data)
            row["log"] = "verified" if claim.get("log_sha256") == sha256(log_data) else "mismatch"
            if row["log"] == "mismatch":
                row["contradictions"].append("log_hash_mismatch")
        if spec.get("claimed_head") is not None:
            row["head_binding"] = "matches" if commit_id(spec["claimed_head"], "claimed_head") == line["head"] else "mismatch"
            if row["head_binding"] == "mismatch":
                row["contradictions"].append("claimed_head_mismatch")
        if sources:
            prefix = spec.get("source_prefix", "")
            if type(prefix) is not str or (prefix and not prefix.endswith("/")) or ".." in prefix or prefix.startswith("/"):
                refuse("invalid_source_prefix")
            mismatched = []
            for source, expected in sorted(sources.items()):
                path = prefix + source
                actual = head_blobs.get(path)
                if actual is None:
                    try:
                        actual = blob_sha(worktree, line["head"], path)[0]
                    except PacketError:
                        actual = None
                if actual != expected:
                    mismatched.append(path)
            row["source_binding"] = "matches" if not mismatched else "mismatch"
            if mismatched:
                row["contradictions"].append("source_hash_mismatch")
                row["source_mismatches"] = mismatched[:20]
        rows.append(row)
    skipped = raw.get("skipped_checks", [])
    if type(skipped) is not list or len(skipped) > LIMITS["receipts"]:
        refuse("invalid_skipped_checks")
    skips = {}
    for spec in skipped:
        if type(spec) is not dict or set(spec) != {"check", "reason"}:
            refuse("invalid_skipped_check")
        skips[label(spec["check"], "check")] = text(spec["reason"], "skip_reason")
    checks = {}
    for check_name in sorted(set(required_names) | set(by_check) | set(skips)):
        rows = by_check.get(check_name, [])
        status = "skipped" if check_name in skips and not rows else check_status(rows)
        if check_name in skips and rows:
            contradictions.append({"kind": "skipped_check_has_receipts", "check": check_name})
            status = "contradictory"
        checks[check_name] = {"required": check_name in required_names, "status": status, "receipts": rows,
                              **({"skip_reason": skips[check_name]} if check_name in skips else {})}
    artifacts = raw.get("artifacts", [])
    if type(artifacts) is not list or len(artifacts) > LIMITS["artifacts"]:
        refuse("invalid_artifacts")
    artifact_rows = []
    for relative in artifacts:
        data = read_bounded(inside(root, relative, "artifact"), LIMITS["artifact_bytes"], "artifact")
        artifact_rows.append({"path": relative, "sha256": sha256(data), "bytes": len(data)})
        inputs.append({"path": relative, "sha256": sha256(data)})
    passing = {"claimed_pass", "claimed_pass_after_failure"}
    required_states = [checks[name]["status"] for name in required_names]
    clean = (not state["worktree_at_head"]) or not state["tracked_dirty_count"]
    if required_states and all(value in passing for value in required_states) and clean:
        tested = "claimed"
    elif any(value in passing for value in required_states):
        tested = "partial"
    else:
        tested = "unperformed"
    stages: dict[str, Any] = {"implemented": "verified_commits", "locally_tested": tested}
    for stage in LATER_STAGES:
        stages[stage] = "not_established_by_local_packet"
    for stage, claimed in claims.items():
        if claimed and stages[stage] not in ("verified_commits", "claimed"):
            contradictions.append({"kind": "local_claim_not_supported", "check": stage})
    changed = {row["path"] for row in paths}
    generator = {name: {"outputs_changed": sorted(changed & set(outputs)),
                        "check": checks.get(f"gen_{name}", {"status": "unperformed"})["status"]}
                 for name, outputs in GENERATORS.items()}
    second = snapshot(worktree, line)
    if second != first:
        refuse("moving_snapshot")
    return {"label": name, "base": first["base"], "base_tree": first["base_tree"], "head": first["head"],
            "head_tree": first["head_tree"], "branch": line["branch"], "donors": donor_rows,
            "depends_on": [label(item, "depends_on") for item in depends], "changed_paths": paths, "worktree": first["state"],
            "checks": checks, "artifacts": artifact_rows, "generator_impact": generator, "stages": stages,
            "local_claims": dict(sorted(claims.items())), "contradictions": contradictions, "_inputs": inputs}


def render_markdown(packet: dict[str, Any]) -> str:
    out = [f"# Integration packet `{packet['packet_id'][:16]}`", "",
           "Local evidence only. CI, merge, deployment, runtime and product acceptance are not established here.", ""]
    for line in packet["lines"]:
        state = line["worktree"]
        clean = "worktree not at head" if not state["worktree_at_head"] else (
            "clean" if not state["tracked_dirty_count"] else f"DIRTY ({state['tracked_dirty_count']} tracked)")
        out += [f"## {line['label']}", "",
                f"- base `{line['base']}` (tree `{line['base_tree'][:12]}`) → head `{line['head']}` (tree `{line['head_tree'][:12]}`)",
                f"- branch: {line['branch'] or 'not stated'}; snapshot: {clean}; depends on: {', '.join(line['depends_on']) or 'none'}",
                f"- donors (cherry-pick order): {', '.join(f'{d['label']} `{d['commit'][:12]}`' for d in line['donors'])}",
                f"- changed paths: {len(line['changed_paths'])}", ""]
        out += ["| check | required | status | receipts |", "|---|---|---|---|"]
        for name, check in line["checks"].items():
            receipts = "; ".join(f"exit {row['claim'].get('exit')} `{row['sha256'][:12]}`" + (" ⚠ " + ",".join(row["contradictions"]) if row["contradictions"] else "")
                                 for row in check["receipts"]) or check.get("skip_reason", "—")
            out.append(f"| {name} | {'yes' if check['required'] else 'no'} | {check['status']} | {receipts} |")
        impact = [f"{name}: {value['check']}" + (f" (changed: {', '.join(value['outputs_changed'])})" if value["outputs_changed"] else "")
                  for name, value in line["generator_impact"].items()]
        out += ["", f"- generators: {'; '.join(impact)}",
                "- stages: " + "; ".join(f"{stage}={line['stages'][stage]}" for stage in LOCAL_STAGES + LATER_STAGES)]
        if line["contradictions"]:
            out.append("- contradictions: " + "; ".join(f"{row['kind']}:{row['check']}" for row in line["contradictions"]))
        out.append("")
    return "\n".join(out)


def build(request_path: Path) -> tuple[str, str]:
    request = strict_json(read_bounded(request_path, LIMITS["receipt_bytes"], "request"))
    if type(request) is not dict or request.get("schema") != REQUEST_SCHEMA or set(request) - {"schema", "evidence_root", "lines"}:
        refuse("invalid_request")
    root = absolute_path(request.get("evidence_root"), "evidence_root")
    if not root.is_dir() or root.is_symlink():
        refuse("invalid_evidence_root")
    lines = request.get("lines")
    if type(lines) is not list or not lines or len(lines) > LIMITS["lines"]:
        refuse("invalid_lines")
    seen: set[str] = set()
    prepared = [prepare_line(line, root, seen) for line in lines]
    for line in prepared:
        if set(line["depends_on"]) - seen or line["label"] in line["depends_on"]:
            refuse("unknown_dependency")
    inputs = [row for line in prepared for row in line.pop("_inputs")]
    # Re-read every input: a file that changed while preparing is a moving snapshot.
    for row in inputs:
        if sha256(read_bounded(inside(root, row["path"], "input"), LIMITS["artifact_bytes"], "input")) != row["sha256"]:
            refuse("moving_snapshot")
    packet: dict[str, Any] = {"schema": PACKET_SCHEMA, "lines": prepared, "limits": LIMITS, "generators": {k: list(v) for k, v in GENERATORS.items()},
                              "statement": "Local packet: identities verified, exit codes claimed. Later stages are not established."}
    packet["packet_id"] = sha256(canonical(packet).encode())
    body = canonical(packet)
    if len(body.encode()) > LIMITS["packet_bytes"]:
        refuse("packet_too_large")
    if re.search(r'"/(Users|home|private|tmp|var)/', body):
        refuse("absolute_path_in_packet")
    # Render from the canonical JSON so validation can reproduce it exactly.
    return body, render_markdown(json.loads(body))


def write_new(out: Path, files: dict[str, str]) -> None:
    parent = out.parent
    if not parent.is_dir() or parent.is_symlink():
        refuse("invalid_output_parent")
    try:
        os.mkdir(out, 0o700)
    except FileExistsError:
        refuse("output_collision")
    for name, content in files.items():
        descriptor = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)


def prepare(request_path: Path, out: Path) -> dict[str, Any]:
    body, markdown = build(request_path)
    marker = f"{sha256(body.encode())}  packet.json\n{sha256(markdown.encode())}  packet.md\n"
    write_new(out, {"packet.json": body, "packet.md": markdown, "packet.sha256": marker})
    return {"status": "prepared", "packet_id": json.loads(body)["packet_id"]}


def validate(directory: Path, evidence_root: Path | None, worktrees: dict[str, Path]) -> dict[str, Any]:
    reasons: list[str] = []
    try:
        if directory.is_symlink() or not directory.is_dir():
            refuse("invalid_packet_directory")
        files = {name: read_bounded(inside(directory, name, "packet_file"), LIMITS["packet_bytes"], "packet_file")
                 for name in ("packet.json", "packet.md", "packet.sha256")}
        expected = f"{sha256(files['packet.json'])}  packet.json\n{sha256(files['packet.md'])}  packet.md\n".encode()
        if files["packet.sha256"] != expected:
            reasons.append("marker_mismatch")
        packet = strict_json(files["packet.json"])
        if type(packet) is not dict or packet.get("schema") != PACKET_SCHEMA:
            refuse("invalid_packet_schema")
        identity = dict(packet)
        identity.pop("packet_id", None)
        if packet.get("packet_id") != sha256(canonical(identity).encode()) or canonical(packet).encode() != files["packet.json"]:
            reasons.append("packet_id_or_canonical_form_mismatch")
        if render_markdown(packet).encode() != files["packet.md"]:
            reasons.append("markdown_not_rendered_from_json")
        for line in packet["lines"]:
            if any(line["stages"].get(stage) != "not_established_by_local_packet" for stage in LATER_STAGES):
                reasons.append(f"later_stage_set:{line['label']}")
            if evidence_root is not None:
                rows = [(row["path"], row["sha256"]) for check in line["checks"].values() for row in check["receipts"]]
                rows += [(row["log_path"], row["log_sha256"]) for check in line["checks"].values()
                         for row in check["receipts"] if "log_path" in row]
                rows += [(row["path"], row["sha256"]) for row in line["artifacts"]]
                for relative, digest in rows:
                    try:
                        if sha256(read_bounded(inside(evidence_root, relative, "input"), LIMITS["artifact_bytes"], "input")) != digest:
                            reasons.append(f"evidence_changed:{relative}")
                    except PacketError as error:
                        reasons.append(f"evidence_{error}:{relative}")
            if line["label"] in worktrees:
                try:
                    now = snapshot(worktrees[line["label"]], {"base": line["base"], "head": line["head"], "branch": line["branch"]})
                    if (now["head_tree"], now["base_tree"]) != (line["head_tree"], line["base_tree"]):
                        reasons.append(f"tree_moved:{line['label']}")
                    if line["branch"] is not None and now["branch_commit"] != line["head"]:
                        reasons.append(f"branch_moved:{line['label']}")
                except PacketError as error:
                    reasons.append(f"git_{error}:{line['label']}")
    except PacketError as error:
        reasons.append(str(error))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        reasons.append("malformed_packet")
    return {"status": "invalid" if reasons else "valid", "reasons": sorted(set(reasons))[:50]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("prepare")
    make.add_argument("--request", required=True, type=Path)
    make.add_argument("--out", required=True, type=Path)
    check = commands.add_parser("validate")
    check.add_argument("--packet", required=True, type=Path)
    check.add_argument("--evidence-root", type=Path)
    check.add_argument("--worktree", action="append", default=[], help="LABEL=DIR: recheck that line's commits")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.request, args.out)
        else:
            worktrees = {}
            for item in args.worktree:
                name, _, path = item.partition("=")
                worktrees[label(name, "line_label")] = Path(path)
            result = validate(args.packet, args.evidence_root, worktrees)
    except PacketError as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("prepared", "valid") else 1


if __name__ == "__main__":
    sys.exit(main())
