#!/usr/bin/env python3
"""Finite pending-only import of one NHC-advisory trial proposal into Gist state.

Operator tool, not an application feature. `check` reads and validates without
writing; `apply` repeats every check and, with the exact state SHA-256 the
operator reviewed, performs at most one PATCH and one readback. No model call,
review, approval, publish intent or automatic schedule is created, and no other
draft, ledger entry or numeric spelling is rewritten (lossless raw insertion).

Gist is not transactional: two reads plus one readback detect some concurrent
writers but are not a compare-and-swap; a state revision number is not a lock.
An uncertain write is never resent or rolled back automatically: its durable
attempt marker blocks any second attempt for the same trial.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAX_BYTES = 8 * 1024 * 1024
PROPOSAL_SCHEMA = "theheat.nhc-advisory-pending-proposal/v1"
_DRAFT_KEYS = frozenset({"id", "text", "type", "event_id", "created_at", "updated_at", "status", "review_context",
                         "score", "approval_policy", "approval_mode", "content_revision", "decision_revision",
                         "manual_override"})
_PROPOSAL_KEYS = frozenset({"schema", "applied", "trial_id", "plan_sha256", "operator_recheck_deadline", "draft",
                            "checks", "human_reviewed", "approved"})
_REQUIRED_FLAGS = {"THEHEAT_PRODUCTION_PAUSED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "0",
                   "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "0", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
                   "THEHEAT_SELFHEAL_REPAIR_ENABLED": "0", "THEHEAT_WRITER_SAMPLES": "1"}
_PAID_BACKGROUND = ("THEHEAT_PAID_EVALUATION_ENABLED", "THEHEAT_PAID_PR_REPLAY_ENABLED")


class ImportRefused(ValueError):
    """A fixed refusal code; never source text, credentials or response bodies."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fail(code: str) -> NoReturn:
    raise ImportRefused(code)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stamp(value) -> datetime:
    if type(value) is not str:
        fail("aware_utc_required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("aware_utc_required")
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        fail("aware_utc_required")
    return result


def _number(token: str):
    value = float(token) if any(c in token for c in ".eE") else int(token)
    if not math.isfinite(value) or (float(value).is_integer() and abs(value) > 9007199254740991):
        fail("unsafe_number")
    return value


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            fail("duplicate_json_key")
        result[key] = value
    return result


DECODER = json.JSONDecoder(object_pairs_hook=_pairs, parse_int=_number, parse_float=_number,
                           parse_constant=lambda _: fail("nonfinite_number"))


def document(raw: bytes) -> tuple[dict, str]:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        fail("document_size")
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        fail("document_encoding")
    start = len(text) - len(text.lstrip())
    try:
        value, end = DECODER.raw_decode(text, start)
    except RecursionError:
        fail("document_depth")
    except ValueError as exc:
        if isinstance(exc, ImportRefused):
            raise
        fail("document_json")
    if not isinstance(value, dict) or text[end:].strip():
        fail("document_shape")

    def nodes(item, depth=0) -> int:
        if depth > 64:
            fail("document_depth")
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        return 1 + sum(nodes(child, depth + 1) for child in children)
    if nodes(value) > 1_000_000:
        fail("document_nodes")
    return value, text


def member(text: str, key: str) -> tuple[int, int]:
    """The original value span of a top-level member; never reserialize retained state."""
    pos = len(text) - len(text.lstrip()) + 1
    while True:
        while text[pos].isspace():
            pos += 1
        if text[pos] == "}":
            break
        name, pos = DECODER.raw_decode(text, pos)
        while text[pos].isspace():
            pos += 1
        if text[pos] != ":":
            fail("member_colon")
        pos += 1
        while text[pos].isspace():
            pos += 1
        begin = pos
        _, pos = DECODER.raw_decode(text, pos)
        if name == key:
            return begin, pos
        while text[pos].isspace():
            pos += 1
        if text[pos] == "}":
            break
        if text[pos] != ",":
            fail("member_separator")
        pos += 1
    fail("missing_member")


def validate_proposal(raw: bytes, expected_sha: str, now: datetime):
    """Exact pending-only NHC proposal with a retained, still-current-looking advisory."""
    from src.editorial.nhc_advisory import AdvisoryHold
    from src.editorial.nhc_advisory_runtime import check_copy
    from src.editorial.revisions import approval_is_current, review_is_current
    from src.two_bot.intern.nhc_advisory import RetainedAdvisory
    from src.two_bot.types import StoryBundle
    from src.voice.safety import check_month_repetition, check_regex, check_truncated_temperature
    if sha(raw) != expected_sha:
        fail("proposal_changed")
    p, text = document(raw)
    if set(p) != _PROPOSAL_KEYS or p["schema"] != PROPOSAL_SCHEMA:
        fail("proposal_shape")
    if p["applied"] is not False or p["human_reviewed"] is not False or p["approved"] is not False:
        fail("proposal_already_applied_or_authorized")
    trial_id = p["trial_id"]
    if type(trial_id) is not str or re.fullmatch(r"[a-f0-9]{32}", trial_id) is None:
        fail("proposal_trial_identity")
    d = p["draft"]
    if not isinstance(d, dict) or set(d) - _DRAFT_KEYS:
        fail("unexpected_draft_authority")
    match = re.fullmatch(r"nhc_trial_([a-f0-9]{32})_((?:al|ep)[0-9]{6})", d.get("id", ""))
    if match is None or match[1] != trial_id or d.get("type") != "nhc_advisory":
        fail("unsupported_draft_identity")
    policy = d.get("approval_policy") or {}
    if (d.get("status") != "pending" or d.get("approval_mode") != "manual" or policy.get("mode") != "manual_only"
            or policy.get("can_auto_approve") is not False):
        fail("draft_not_pending_manual")
    if not isinstance(d.get("text"), str) or not d["text"].strip() or len(d["text"]) > 280:
        fail("draft_text")
    context = d.get("review_context") or {}
    if set(context) != {"two_bot"} or set(context["two_bot"]) != {"bundle", "signal_kind"} \
            or context["two_bot"]["signal_kind"] != "nhc_advisory":
        fail("obsolete_checks_or_context")
    bundle = context["two_bot"]["bundle"]
    if not isinstance(bundle, dict) or bundle.get("event_id") != d["event_id"]:
        fail("draft_bundle_mismatch")
    try:
        retained = RetainedAdvisory(StoryBundle(**bundle))
        if retained.nomination.storm_id.lower() != match[2]:
            fail("unsupported_draft_identity")
        retained.check_times(now)
        check_copy(d["text"], retained)
    except AdvisoryHold as exc:
        fail(exc.code)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ImportRefused):
            raise
        fail("draft_bundle_invalid")
    if stamp(p["operator_recheck_deadline"]) != retained.deadline:
        fail("proposal_deadline_mismatch")
    for check in (check_regex, check_month_repetition, check_truncated_temperature):
        if not check(d["text"])[0]:
            fail("deterministic_text_rejected")
    if review_is_current(d) or approval_is_current(d, "manual"):
        fail("obsolete_authority")
    begin, end = member(text, "draft")
    return p, text[begin:end], trial_id, retained


def validate_report(raw: bytes, now: datetime, code_sha: str, source_sha: str) -> dict:
    """The deployed configuration-only report must match this checkout's code and policy."""
    from src.editorial.policy import valid_policy
    r, _ = document(raw)
    inv = r.get("runtime_inventory") or {}
    p = inv.get("editorial_policy")
    if (r.get("kind") != "configuration_only" or r.get("collection_paused") is not True
            or inv.get("mode") != "runtime_report" or inv.get("git_sha") != code_sha
            or not isinstance(p, dict) or not valid_policy(p) or p["source_sha256"] != source_sha):
        fail("policy_unverified")
    flags = inv.get("flags") or {}
    if (flags.get("automatic_publication_enabled") is not False or flags.get("writer_samples") != 1
            or flags.get("critic_enabled") is not True or flags.get("critic_revise_enabled") is not False
            or (inv.get("credentials_present") or {}).get("safety_gemini") is not True):
        fail("report_profile_invalid")
    if not timedelta(0) <= now - stamp(inv.get("captured_at")) <= timedelta(hours=6):
        fail("policy_stale")
    if p["flags"] != {"writer_samples": 1, "critic_enabled": True, "critic_revise_enabled": False,
                      "safety_llm_enabled": True}:
        fail("policy_flags_changed")
    return p


def plan(proposal_raw: bytes, proposal_sha: str, files: dict, flags: dict, now: datetime, code_sha: str,
         source_sha: str):
    from src.editorial.revisions import approval_is_current, has_unresolved_publish, review_is_current
    p, draft_raw, trial_id, retained = validate_proposal(proposal_raw, proposal_sha, now)
    for key, value in _REQUIRED_FLAGS.items():
        if flags.get(key) != value:
            fail("controls_changed:" + key.lower())
    if any(flags.get(key, "0") != "0" for key in _PAID_BACKGROUND):
        fail("paid_background_enabled")
    raw = files.get("state.json")
    if raw is None or files.get("runtime-inventory.json") is None:
        fail("gist_file_inventory_changed")
    state, text = document(raw)
    policy = validate_report(files["runtime-inventory.json"], now, code_sha, source_sha)
    drafts = state.get("drafts")
    d = p["draft"]
    if not isinstance(drafts, list) or any(not isinstance(v, dict) for v in drafts):
        fail("state_drafts_shape")
    if any(v.get("id") == d["id"] or v.get("event_id") == d["event_id"] for v in drafts):
        fail("duplicate_draft")
    if d["event_id"] in (state.get("posted_events") or []) or d["event_id"] in (state.get("publish_ledger") or {}):
        fail("publication_history_exists")
    if has_unresolved_publish(d, state):
        fail("publication_unresolved")
    if any(str(v.get("id", "")).startswith("nhc_trial_" + trial_id + "_") for v in drafts):
        fail("trial_import_limit")
    if review_is_current(d, policy=policy) or approval_is_current(d, "manual", policy=policy):
        fail("draft_has_authority")
    _, end = member(text, "drafts")
    closing = end - 1
    if text[closing] != "]":
        fail("drafts_span")
    content = (text[:closing] + ("," if drafts else "") + draft_raw + text[closing:]).encode()
    result, _ = document(content)
    if result["drafts"][:-1] != drafts or result["drafts"][-1] != d:
        fail("draft_preservation_failed")
    if {k: v for k, v in result.items() if k != "drafts"} != {k: v for k, v in state.items() if k != "drafts"}:
        fail("state_preservation_failed")
    return content, trial_id, d, retained


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_bytes(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def durable(path: Path, value) -> None:
    durable_bytes(path, (json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode())


@contextmanager
def operator_lock(journal: Path):
    journal.mkdir(mode=0o700, exist_ok=True)
    sync_directory(journal.parent)
    with (journal / "operator.lock").open("a+b") as handle:
        os.chmod(handle.name, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _fresh_source(bundle, clock) -> None:
    """The import operator's own owner: one fixed two-request NHC re-read for this phase."""
    from src.editorial.nhc_advisory import AdvisoryHold
    from src.editorial.nhc_advisory_runtime import AdvisoryOwner, advisory_owner_scope, guard_advisory_story
    try:
        with advisory_owner_scope(AdvisoryOwner(clock=clock)):
            guard_advisory_story(bundle, generating=False, live=True)
    except AdvisoryHold as exc:
        fail(exc.code)


def _bundle_of(draft: dict):
    from src.two_bot.types import StoryBundle
    return StoryBundle(**draft["review_context"]["two_bot"]["bundle"])


def check(proposal_raw: bytes, proposal_sha: str, *, read, clock, code_sha: str, source_sha: str) -> dict:
    """Dry run: everything except the claim/write. Returns what an apply would require."""
    first, flags = read()
    content, trial_id, draft, _retained = plan(proposal_raw, proposal_sha, first, flags, clock(), code_sha, source_sha)
    _fresh_source(_bundle_of(draft), clock)
    return {"trial_id": trial_id, "draft_id": draft["id"], "state_sha256": sha(first["state.json"]),
            "payload_sha256": sha(content), "writes": 0, "provider_calls": 0, "posts": 0,
            "race_window": "unfenced_gist_read_write"}


def execute(proposal_raw: bytes, proposal_sha: str, *, expected_state_sha256: str, read, patch, journal: Path,
            clock, code_sha: str, source_sha: str) -> dict:
    # An expired/invalid proposal stops before any network access, lock or claim.
    _, _, trial_id, _ = validate_proposal(proposal_raw, proposal_sha, clock())
    with operator_lock(journal):
        first, flags = read()
        if sha(first.get("state.json", b"")) != expected_state_sha256:
            fail("state_changed_since_review")
        content, _, draft, _ = plan(proposal_raw, proposal_sha, first, flags, clock(), code_sha, source_sha)
        claim = sha((trial_id + "\n" + draft["id"]).encode())
        if (journal / (claim + ".attempt.json")).exists():
            fail("attempt_already_consumed")
        if any(json.loads(path.read_text())["trial_id"] == trial_id for path in journal.glob("*.attempt.json")):
            fail("trial_attempt_limit")
        second, new_flags = read()
        if second != first or new_flags != flags:
            fail("snapshot_changed_before_write")
        _fresh_source(_bundle_of(draft), clock)
        # Time may pass during reads, the lock or the source check.
        final, _, _, _ = plan(proposal_raw, proposal_sha, second, new_flags, clock(), code_sha, source_sha)
        if final != content:
            fail("plan_changed")
        backup = journal / claim
        backup.mkdir(mode=0o700, exist_ok=False)
        sync_directory(journal)
        for index, (name, raw) in enumerate(sorted(second.items())):
            durable_bytes(backup / f"before-{index}.bin", raw)
        durable_bytes(backup / "proposed-state.bin", content)
        durable(backup / "before-controls.json", flags)
        durable(backup / "inventory.json", {"before": {name: {"sha256": sha(raw), "file": f"before-{index}.bin"}
                                                       for index, (name, raw) in enumerate(sorted(second.items()))},
                                            "proposed_state_sha256": sha(content)})
        durable(journal / (claim + ".attempt.json"), {"trial_id": trial_id, "draft_id": draft["id"],
                                                     "proposal_sha256": proposal_sha, "payload_sha256": sha(content),
                                                     "at": clock().isoformat(), "no_automatic_resend": True})
        # Backups/fsync may consume the remaining freshness window. A durable
        # attempt is not permission to PATCH after that window; expiry leaves
        # this attempt consumed and the original state untouched.
        final, _, _, _ = plan(proposal_raw, proposal_sha, second, new_flags, clock(), code_sha, source_sha)
        if final != content:
            fail("plan_changed")
        acknowledged = False
        try:
            patch(content)
            acknowledged = True
        except Exception:
            pass  # One readback may reconcile; never repeat the PATCH or roll back.
        result = {"trial_id": trial_id, "draft_id": draft["id"], "write_acknowledged": acknowledged,
                  "outcome": "unknown", "patch_attempts": 1, "readback_attempts": 1,
                  "after_snapshot_retained": False, "provider_calls": 0, "posts": 0, "reviews": 0,
                  "approvals": 0, "race_window": "unfenced_gist_read_write"}
        try:
            after, after_flags = read()
            after_dir = backup / "after"
            after_dir.mkdir(mode=0o700, exist_ok=False)
            sync_directory(backup)
            inventory = {}
            for index, (name, raw) in enumerate(sorted(after.items())):
                durable_bytes(after_dir / f"file-{index}.bin", raw)
                inventory[name] = {"sha256": sha(raw), "file": f"file-{index}.bin"}
            durable(after_dir / "inventory.json", inventory)
            durable(after_dir / "controls.json", after_flags)
            result["after_snapshot_retained"] = True
            if after == {**second, "state.json": content} and after_flags == flags:
                result["outcome"] = ("confirmed_pending" if acknowledged
                                     else "confirmed_pending_after_uncertain_response")
            else:
                result["outcome"] = "readback_conflict_hold_no_resend"
        except Exception:
            pass
        durable(journal / (claim + ".result.json"), result)
        return result


class GitHub:
    """Normal authenticated CLI usage only; fixed gist/variables routes, no credential files."""

    def __init__(self, gist_id: str, repository: str):
        if re.fullmatch(r"[a-f0-9]{20,64}", gist_id or "") is None or \
                re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository or "") is None:
            fail("invalid_gist_or_repository")
        self.gist_id, self.repository, self.patches = gist_id, repository, 0

    def _api(self, args: list[str], body: bytes | None = None) -> bytes:
        result = subprocess.run(["gh", "api", *args], input=body, capture_output=True, timeout=60)
        if result.returncode:
            fail("github_request_failed")
        return result.stdout

    def read(self):
        gist = json.loads(self._api([f"gists/{self.gist_id}"]))
        files = {}
        for name in ("state.json", "runtime-inventory.json"):
            entry = (gist.get("files") or {}).get(name)
            if not isinstance(entry, dict) or type(entry.get("truncated")) is not bool:
                fail("gist_file_inventory_changed")
            if entry["truncated"]:
                # The real state exceeds GitHub's inline-content threshold. Use
                # its ordinary fixed-gist/fixed-file CLI raw read, as the trial
                # workflow already does; never parse or splice the shortened JSON.
                result = subprocess.run(["gh", "gist", "view", self.gist_id, "--raw", "--filename", name],
                                        capture_output=True, timeout=60)
                if result.returncode:
                    fail("github_request_failed")
                raw = result.stdout
            else:
                if type(entry.get("content")) is not str:
                    fail("gist_file_inventory_changed")
                raw = entry["content"].encode()
            if len(raw) > MAX_BYTES:
                fail("document_size")
            files[name] = raw
        rows = json.loads(self._api([f"repos/{self.repository}/actions/variables?per_page=100"]))
        flags = {row["name"]: row["value"] for row in rows.get("variables", [])}
        return files, flags

    def patch(self, content: bytes) -> None:
        self.patches += 1
        if self.patches > 1:
            fail("second_patch_forbidden")
        body = json.dumps({"files": {"state.json": {"content": content.decode()}}}).encode()
        self._api(["--method", "PATCH", f"gists/{self.gist_id}", "--input", "-"], body)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=("check", "apply"))
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--proposal-sha256", required=True)
    parser.add_argument("--gist-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--expected-state-sha256")
    args = parser.parse_args()
    try:
        from src.editorial.policy import current_editorial_policy
        code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
        policy = current_editorial_policy()
        if policy is None:
            fail("policy_unavailable")
        client = GitHub(args.gist_id, args.repository)
        raw = args.proposal.read_bytes()
        clock = lambda: datetime.now(timezone.utc)  # noqa: E731
        if args.action == "check":
            result = check(raw, args.proposal_sha256, read=client.read, clock=clock, code_sha=code_sha,
                           source_sha=policy["source_sha256"])
        else:
            if not args.expected_state_sha256 or args.journal is None:
                parser.error("apply requires --expected-state-sha256 from a reviewed check and --journal")
            result = execute(raw, args.proposal_sha256, expected_state_sha256=args.expected_state_sha256,
                             read=client.read, patch=client.patch, journal=args.journal, clock=clock,
                             code_sha=code_sha, source_sha=policy["source_sha256"])
        print(json.dumps(result, sort_keys=True))
        return 0
    except ImportRefused as exc:
        print(json.dumps({"status": "refused", "reason": exc.code, "writes": 0}))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
