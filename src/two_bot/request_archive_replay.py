"""Read-only verification, inspection and comparison of private request archives.

Versioned read API (``READ_API_VERSION``) for later private tools. Everything
returned is a verified mechanical record with explicit availability; nothing
here calls a model, sends a request, reads Gist/DB state, follows a URL, loads
pickles, executes archive content or writes into an archive. Exact content is
only ever written to a new explicitly selected owner-only file.

Verification proves byte binding between the manifest, its hash chain and the
content-addressed artifacts. It does not prove source truth, model quality, the
completeness of a historical run, billing, or that a call was charged.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any

from src.two_bot.request_archive import (
    ARTIFACTS, GENESIS, MANIFEST, MAX_RECORD_BYTES, MAX_SCOPE_CONTENT_BYTES, SCHEMA,
    RequestArchiveRefused, canonical_json, read_private_file, require_private_directory,
    sha256_hex, strict_json_loads, write_private_file_exclusive,
)

READ_API_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 + 1024
_SCOPE_NAME = re.compile(r"\Ascope-[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_TEMPORARY = re.compile(r"\A\.tmp-[0-9a-f]{24}\Z")
_KNOWN = frozenset({"scope_opened", "scope_closed", "scope_held", "generation_input", "candidate",
                    "revision_requested", "stage_outcome", "call_intent", "wire_request", "wire_response",
                    "call_result", "call_refused", "foreign_call_refused", "code_drift_observed", "terminal"})


class ArchiveInvalid(ValueError):
    """Integrity failure with a fixed code; no content."""


@dataclass(frozen=True)
class Body:
    availability: str
    artifact: str | None = None
    size: int | None = None
    form: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class WireAttempt:
    attempt: int
    transport_family: str
    host: str
    path: str
    query_present: bool
    request: Body
    status: int | None = None
    response: Body = Body("not_observed")
    response_headers: dict = field(default_factory=dict)
    provider_ids: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CallRecord:
    number: int
    stage: str
    provider: str
    model: str | None
    binding: dict
    logical_request: Body
    attempts: tuple[WireAttempt, ...]
    result: dict | None
    intent_seq: int

    @property
    def outcome(self) -> str:
        return "open_without_result" if self.result is None else str(self.result.get("outcome"))


@dataclass(frozen=True)
class VerifiedArchive:
    api_version: int
    directory: Path
    scope_id: str | None
    status: str  # complete | incomplete | invalid
    problems: tuple[str, ...]
    manifest_sha256: str
    records: tuple[dict, ...]
    opened: dict | None
    closed: dict | None
    held: str | None
    calls: tuple[CallRecord, ...]
    inputs: tuple[dict, ...]
    candidates: tuple[dict, ...]
    stage_outcomes: tuple[dict, ...]
    terminals: tuple[dict, ...]
    refusals: tuple[dict, ...]
    drift: tuple[dict, ...]
    artifact_sizes: dict

    def artifact(self, digest: str | None) -> bytes:
        """Return exact verified artifact bytes for a referenced digest."""
        if digest is None:
            raise ArchiveInvalid("artifact_unavailable")
        if digest not in self.artifact_sizes:
            raise ArchiveInvalid("artifact_not_referenced")
        try:
            data = read_private_file(self.directory / ARTIFACTS / digest, MAX_ARTIFACT_BYTES)
        except (OSError, RequestArchiveRefused):
            raise ArchiveInvalid("artifact_changed_after_validation") from None
        if sha256_hex(data) != digest or len(data) != self.artifact_sizes[digest]:
            raise ArchiveInvalid("artifact_changed_after_validation")
        return data


def _is_aware(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _body(value: Any, sizes: dict, problems: list[str], seq: int) -> Body:
    if type(value) is not dict or type(value.get("availability")) is not str:
        raise ArchiveInvalid(f"body_shape:{seq}")
    if value["availability"] == "captured":
        digest, size = value.get("artifact"), value.get("bytes")
        if type(digest) is not str or not _HEX64.fullmatch(digest) or not _int(size):
            raise ArchiveInvalid(f"body_reference:{seq}")
        _reference(digest, size, sizes, seq)
        return Body("captured", digest, size, value.get("form"))
    return Body(value["availability"], None, value.get("bytes") if _int(value.get("bytes")) else None,
                None, value.get("reason") if type(value.get("reason")) is str else None)


def _reference(digest: Any, size: Any, sizes: dict, seq: int) -> None:
    if digest is None:
        return
    if type(digest) is not str or not _HEX64.fullmatch(digest):
        raise ArchiveInvalid(f"artifact_reference:{seq}")
    if size is not None:
        if digest in sizes and sizes[digest] not in (None, size):
            raise ArchiveInvalid(f"artifact_size_conflict:{seq}")
        sizes[digest] = size
    else:
        sizes.setdefault(digest, None)


def load_archive(path: str | os.PathLike) -> VerifiedArchive:
    """Verify one scope directory from its retained files alone.

    Raises RequestArchiveRefused for an unsafe/unprivate location. Otherwise
    returns status ``invalid`` (integrity broken), ``incomplete`` (unsealed,
    truncated, held, stray temporary, call without result) or ``complete``.
    """
    directory = require_private_directory(path, create=False)
    if not _SCOPE_NAME.fullmatch(directory.name):
        raise RequestArchiveRefused("archive_scope_name_invalid")
    problems: list[str] = []
    entries = set(os.listdir(directory))
    if entries - {MANIFEST, ARTIFACTS}:
        problems.append("unexpected_scope_entry")
    artifacts_dir = directory / ARTIFACTS
    try:
        require_private_directory(artifacts_dir, create=False)
    except RequestArchiveRefused:
        return _invalid(directory, "artifacts_directory_unsafe")
    try:
        manifest = read_private_file(directory / MANIFEST, MAX_MANIFEST_BYTES)
    except (OSError, RequestArchiveRefused):
        return _invalid(directory, "manifest_unreadable")
    manifest_sha = sha256_hex(manifest)
    lines = manifest.split(b"\n")
    tail = lines.pop()
    if tail:
        problems.append("truncated_manifest_tail")
    records: list[dict] = []
    sizes: dict[str, int | None] = {}
    try:
        _verify_records(lines, records, sizes)
        state = _assemble(records, sizes, problems)
        _verify_artifacts(artifacts_dir, sizes, state, problems)
        _verify_bindings(records, artifacts_dir)
    except ArchiveInvalid as exc:
        return _invalid(directory, str(exc), manifest_sha)
    status = "complete" if not problems else "incomplete"
    return VerifiedArchive(READ_API_VERSION, directory, state["scope_id"], status, tuple(problems),
                           manifest_sha, tuple(records), state["opened"], state["closed"], state["held"],
                           tuple(state["calls"]), tuple(state["inputs"]), tuple(state["candidates"]),
                           tuple(state["outcomes"]), tuple(state["terminals"]), tuple(state["refusals"]),
                           tuple(state["drift"]), {k: v for k, v in sizes.items() if v is not None})


def _invalid(directory: Path, code: str, manifest_sha: str = "") -> VerifiedArchive:
    return VerifiedArchive(READ_API_VERSION, directory, None, "invalid", (code,), manifest_sha, (), None, None,
                           None, (), (), (), (), (), (), (), {})


def _verify_records(lines: list[bytes], records: list[dict], sizes: dict) -> None:
    previous = GENESIS
    for index, line in enumerate(lines, start=1):
        if len(line) + 1 > MAX_RECORD_BYTES:
            raise ArchiveInvalid(f"record_over_limit:{index}")
        try:
            record = strict_json_loads(line)
            if canonical_json(record) != line:
                raise ArchiveInvalid(f"record_not_canonical:{index}")
        except ArchiveInvalid:
            raise
        except (ValueError, UnicodeError):
            raise ArchiveInvalid(f"record_unparseable:{index}") from None
        if type(record) is not dict or set(record) != {"schema", "seq", "prev", "type", "at", "data"}:
            raise ArchiveInvalid(f"record_shape:{index}")
        if record["schema"] != SCHEMA:
            raise ArchiveInvalid(f"record_schema:{index}")
        if record["seq"] != index or type(record["seq"]) is not int:
            raise ArchiveInvalid(f"record_sequence:{index}")
        if record["prev"] != previous:
            raise ArchiveInvalid(f"record_chain:{index}")
        if record["type"] not in _KNOWN or type(record["data"]) is not dict or not _is_aware(record["at"]):
            raise ArchiveInvalid(f"record_type:{index}")
        previous = sha256_hex(line)
        records.append(record)


def _assemble(records: list[dict], sizes: dict, problems: list[str]) -> dict:
    state: dict[str, Any] = {"scope_id": None, "opened": None, "closed": None, "held": None, "calls": [],
                             "inputs": [], "candidates": [], "outcomes": [], "terminals": [],
                             "refusals": [], "drift": []}
    if not records or records[0]["type"] != "scope_opened":
        raise ArchiveInvalid("scope_opened_missing")
    calls: dict[int, dict] = {}
    open_call: int | None = None
    for record in records:
        seq, kind, data = record["seq"], record["type"], record["data"]
        if state["closed"] is not None:
            raise ArchiveInvalid(f"record_after_close:{seq}")
        if kind == "scope_opened":
            if seq != 1 or type(data.get("scope_id")) is not str:
                raise ArchiveInvalid(f"scope_opened_shape:{seq}")
            state["scope_id"], state["opened"] = data["scope_id"], data
        elif kind == "scope_closed":
            state["closed"] = data
        elif kind == "scope_held":
            state["held"] = state["held"] or data.get("reason")
        elif kind == "generation_input":
            for key in ("bundle_artifact", "memory_artifact"):
                _reference(data.get(key), None, sizes, seq)
            if type(data.get("bundle_sha256")) is not str or type(data.get("memory_sha256")) is not str:
                raise ArchiveInvalid(f"generation_input_shape:{seq}")
            state["inputs"].append({"seq": seq, **data})
        elif kind == "candidate":
            _reference(data.get("text_artifact"), None, sizes, seq)
            if data.get("text_artifact") != data.get("candidate_text_sha256"):
                raise ArchiveInvalid(f"candidate_binding:{seq}")
            state["candidates"].append({"seq": seq, **data})
        elif kind == "stage_outcome":
            _reference(data.get("reason_artifact"), None, sizes, seq)
            state["outcomes"].append({"seq": seq, **data})
        elif kind == "terminal":
            _reference(data.get("draft_artifact"), None, sizes, seq)
            _reference(data.get("kill_reason_artifact"), None, sizes, seq)
            state["terminals"].append({"seq": seq, **data})
        elif kind in ("call_refused", "foreign_call_refused"):
            state["refusals"].append({"seq": seq, "type": kind, **data})
        elif kind == "code_drift_observed":
            state["drift"].append({"seq": seq, **data})
        elif kind == "revision_requested":
            pass
        elif kind == "call_intent":
            number = data.get("call")
            if open_call is not None or number != len(calls) + 1:
                raise ArchiveInvalid(f"call_sequence:{seq}")
            calls[number] = {"intent": data, "seq": seq, "attempts": [], "responses": {}, "result": None,
                             "logical": _body(data.get("logical_request"), sizes, problems, seq)}
            open_call = number
        elif kind in ("wire_request", "wire_response", "call_result"):
            number = data.get("call")
            if number not in calls or number != open_call:
                raise ArchiveInvalid(f"call_reference:{seq}")
            call = calls[number]
            if kind == "wire_request":
                if data.get("attempt") != len(call["attempts"]) + 1 or data.get("recorded_before_send") is not True:
                    raise ArchiveInvalid(f"attempt_sequence:{seq}")
                call["attempts"].append({"data": data, "body": _body(data.get("body"), sizes, problems, seq)})
            elif kind == "wire_response":
                attempt = data.get("attempt")
                if attempt != len(call["attempts"]) or attempt in call["responses"]:
                    raise ArchiveInvalid(f"response_sequence:{seq}")
                body = data.get("body")
                parsed = (_body(body, sizes, problems, seq) if isinstance(body, dict)
                          and body.get("availability") == "captured" else
                          Body(str((body or {}).get("availability")), None,
                               (body or {}).get("bytes") if _int((body or {}).get("bytes")) else None))
                call["responses"][attempt] = {"data": data, "body": parsed}
            else:
                captured = sum(1 for r in call["responses"].values() if r["body"].availability == "captured")
                if (data.get("wire_attempts") != len(call["attempts"]) or data.get("wire_responses") != captured
                        or data.get("billing") != "unknown"):
                    raise ArchiveInvalid(f"call_result_counts:{seq}")
                call["result"] = data
                open_call = None
        else:  # pragma: no cover - _KNOWN guards this
            raise ArchiveInvalid(f"record_type:{seq}")
    for number, call in sorted(calls.items()):
        intent = call["intent"]
        attempts = []
        for item in call["attempts"]:
            request, body = item["data"], item["body"]
            response = call["responses"].get(request["attempt"])
            attempts.append(WireAttempt(
                request["attempt"], str(request.get("transport_family")), str(request.get("host")),
                str(request.get("path")), bool(request.get("query_present")), body,
                response["data"].get("status") if response else None,
                response["body"] if response else Body("not_observed"),
                dict(response["data"].get("headers") or {}) if response else {},
                dict(response["data"].get("provider_ids") or {}) if response else {}))
        state["calls"].append(CallRecord(number, str(intent.get("stage")), str(intent.get("provider")),
                                         intent.get("model") if type(intent.get("model")) is str else None,
                                         dict(intent.get("binding") or {}), call["logical"], tuple(attempts),
                                         call["result"], call["seq"]))
        if call["result"] is None:
            problems.append(f"call_without_result:{number}")
        elif call["result"].get("archival") != "complete":
            problems.append(f"call_archival_incomplete:{number}")
    if state["closed"] is None:
        problems.append("scope_not_sealed")
    else:
        closed = state["closed"]
        attempts_total = sum(len(call.attempts) for call in state["calls"])
        if closed.get("calls") != len(state["calls"]) or closed.get("wire_attempts") != attempts_total:
            raise ArchiveInvalid("scope_closed_counts")
    state["held"] = state["held"] or (state["closed"] or {}).get("held")
    if state["held"] is not None:
        problems.append(f"scope_held:{state['held']}")
    return state


def _verify_bindings(records: list[dict], directory: Path) -> None:
    """Check internal observation identities, not the archive author's truth."""
    from src.editorial.revisions import fingerprint, text_hash
    keys = ("event_id", "bundle_sha256", "memory_sha256", "candidate_text_sha256",
            "candidate_attempt", "phase", "revises_candidate_text_sha256")
    binding: dict = dict.fromkeys(keys)
    input_data: dict | None = None
    candidate: dict | None = None
    observed_outcomes: dict[str, str] = {}
    last_kill: tuple[str, str] | None = None

    def fields(data: dict, names: tuple[str, ...], code: str, seq: int) -> None:
        if set(data) != set(names):
            raise ArchiveInvalid(f"{code}_shape:{seq}")

    def artifact(digest: str) -> bytes:
        if type(digest) is not str or not _HEX64.fullmatch(digest):
            raise ArchiveInvalid("binding_artifact_reference")
        try:
            raw = read_private_file(directory / digest, MAX_ARTIFACT_BYTES)
            if sha256_hex(raw) != digest:
                raise ArchiveInvalid("artifact_changed_during_validation")
            return raw
        except (OSError, RequestArchiveRefused):
            raise ArchiveInvalid("artifact_changed_during_validation") from None

    def object_artifact(digest: str) -> dict:
        try:
            value = strict_json_loads(artifact(digest), allow_floats=True)
        except (ValueError, UnicodeError):
            raise ArchiveInvalid("binding_artifact_json") from None
        if type(value) is not dict:
            raise ArchiveInvalid("binding_artifact_object")
        return value

    for record in records:
        kind, data, seq = record["type"], record["data"], record["seq"]
        if kind == "generation_input":
            fields(data, ("event_id", "signal_kind", "bundle_sha256", "bundle_artifact", "bundle_form",
                          "memory_sha256", "memory_artifact", "memory_form"), "generation_input", seq)
            bundle = object_artifact(data["bundle_artifact"])
            memory = artifact(data["memory_artifact"])
            object_artifact(data["memory_artifact"])
            if (data["bundle_form"] != "bundle_capture_serialized" or data["memory_form"] != "memory_slice_json_v1"
                    or type(data["event_id"]) is not str or type(data["signal_kind"]) is not str
                    or fingerprint(bundle) != data["bundle_sha256"]
                    or sha256_hex(memory) != data["memory_sha256"]
                    or str(bundle.get("event_id")) != data["event_id"]):
                raise ArchiveInvalid(f"generation_input_binding:{seq}")
            input_data, candidate = data, None
            binding = {**dict.fromkeys(keys), "event_id": data["event_id"], "bundle_sha256": data["bundle_sha256"],
                       "memory_sha256": data["memory_sha256"], "phase": "writer"}
        elif kind == "candidate":
            fields(data, ("candidate_text_sha256", "attempt", "text_artifact", "characters", "authority"),
                   "candidate", seq)
            try:
                text = artifact(data["text_artifact"]).decode("utf-8")
            except UnicodeError:
                raise ArchiveInvalid(f"candidate_text_encoding:{seq}") from None
            if (input_data is None or type(data["attempt"]) is not int or data["attempt"] < 1
                    or type(data["characters"]) is not int or data["characters"] != len(text)
                    or data["authority"] != "observation_only" or text_hash(text) != data["candidate_text_sha256"]
                    or binding["phase"] not in ("writer", "revision")
                    or (binding["phase"] == "writer" and data["attempt"] != 1)
                    or (binding["phase"] == "revision" and data["attempt"] != binding["candidate_attempt"])):
                raise ArchiveInvalid(f"candidate_binding:{seq}")
            candidate = data
            binding.update(candidate_text_sha256=data["candidate_text_sha256"], candidate_attempt=data["attempt"],
                           phase="checks", revises_candidate_text_sha256=None)
        elif kind == "revision_requested":
            fields(data, ("attempt", "revises_candidate_text_sha256"), "revision", seq)
            if (candidate is None or type(data["attempt"]) is not int
                    or data["attempt"] != candidate["attempt"] + 1
                    or data["revises_candidate_text_sha256"] != candidate["candidate_text_sha256"]):
                raise ArchiveInvalid(f"revision_binding:{seq}")
            binding.update(candidate_text_sha256=None, candidate_attempt=data["attempt"], phase="revision",
                           revises_candidate_text_sha256=data["revises_candidate_text_sha256"])
        elif kind in ("call_intent", "stage_outcome"):
            if type(data.get("binding")) is not dict or data["binding"] != binding:
                raise ArchiveInvalid(f"{kind}_binding:{seq}")
            if kind == "call_intent":
                fields(data, ("call", "stage", "provider", "model", "binding", "logical_request",
                              "recorded_before_execution"), "call_intent", seq)
                if (data["recorded_before_execution"] is not True or type(data["stage"]) is not str
                        or data["provider"] not in {"anthropic", "google"}
                        or type(data["call"]) is not int or data["call"] < 1):
                    raise ArchiveInvalid(f"call_intent_shape:{seq}")
            else:
                fields(data, ("stage", "outcome", "binding", "reason_artifact"), "stage_outcome", seq)
                if type(data["stage"]) is not str or type(data["outcome"]) is not str:
                    raise ArchiveInvalid(f"stage_outcome_shape:{seq}")
                if data["reason_artifact"] is None:
                    observed_outcomes[data["stage"]] = data["outcome"]
                elif data["outcome"] == "kill":
                    last_kill = (data["stage"], data["reason_artifact"])
        elif kind == "terminal":
            fields(data, ("origin", "event_id", "accepted", "draft_artifact", "draft_text_sha256",
                          "reviewed_text_sha256", "reviewed_bundle_sha256", "reviewed_policy_sha256", "kill_stage",
                          "kill_reason_artifact", "stage_outcomes", "approval", "publication"), "terminal", seq)
            if (data["origin"] != "generate_draft_return" or type(data["accepted"]) is not bool
                    or data["approval"] != "none" or data["publication"] != "none"
                    or (input_data is not None and data["event_id"] != input_data["event_id"])
                    or data["stage_outcomes"] != observed_outcomes):
                raise ArchiveInvalid(f"terminal_binding:{seq}")
            if data["accepted"]:
                if (input_data is None or candidate is None or data["draft_artifact"] is None
                        or data["kill_stage"] is not None or data["kill_reason_artifact"] is not None
                        or last_kill is not None or "kill" in observed_outcomes.values()):
                    raise ArchiveInvalid(f"terminal_binding:{seq}")
                draft = object_artifact(data["draft_artifact"])
                meta = draft.get("two_bot_metadata")
                draft_text = draft.get("text")
                if (type(meta) is not dict or type(draft_text) is not str
                        or str(draft.get("event_id")) != input_data["event_id"]
                        or data["draft_text_sha256"] != text_hash(draft_text)
                        or data["reviewed_text_sha256"] != text_hash(draft_text)
                        or data["draft_text_sha256"] != binding["candidate_text_sha256"]
                        or data["reviewed_bundle_sha256"] != input_data["bundle_sha256"]
                        or type(data["reviewed_policy_sha256"]) is not str
                        or not _HEX64.fullmatch(data["reviewed_policy_sha256"])
                        or any(data[key] != meta.get(key) for key in (
                            "reviewed_text_sha256", "reviewed_bundle_sha256", "reviewed_policy_sha256"))):
                    raise ArchiveInvalid(f"terminal_binding:{seq}")
            else:
                if (any(data[key] is not None for key in ("draft_artifact", "draft_text_sha256", "reviewed_text_sha256",
                                                         "reviewed_bundle_sha256", "reviewed_policy_sha256"))
                        or last_kill is None or (data["kill_stage"], data["kill_reason_artifact"]) != last_kill):
                    raise ArchiveInvalid(f"terminal_binding:{seq}")
            observed_outcomes, last_kill = {}, None
            input_data, candidate = None, None


def _verify_artifacts(directory: Path, sizes: dict, state: dict, problems: list[str]) -> None:
    present = set(os.listdir(directory))
    temporaries = {name for name in present if _TEMPORARY.fullmatch(name)}
    if temporaries:
        problems.append("stray_temporary_file")
    unknown = present - temporaries - {name for name in present if _HEX64.fullmatch(name)}
    if unknown:
        raise ArchiveInvalid("unexpected_artifact_name")
    total = 0
    for digest in sorted(sizes):
        if digest not in present:
            raise ArchiveInvalid("artifact_missing")
        try:
            data = read_private_file(directory / digest, MAX_ARTIFACT_BYTES)
        except RequestArchiveRefused as exc:
            raise ArchiveInvalid(f"artifact_unsafe:{exc.code}") from None
        except OSError:  # e.g. ELOOP from O_NOFOLLOW on a symlinked artifact.
            raise ArchiveInvalid("artifact_unsafe:unreadable") from None
        if sha256_hex(data) != digest:
            raise ArchiveInvalid("artifact_hash_mismatch")
        if sizes[digest] is not None and sizes[digest] != len(data):
            raise ArchiveInvalid("artifact_size_mismatch")
        sizes[digest] = len(data)
        total += len(data)
    if total > MAX_SCOPE_CONTENT_BYTES:
        raise ArchiveInvalid("scope_content_over_limit")
    extra = {name for name in present if _HEX64.fullmatch(name)} - set(sizes)
    closed = state["closed"]
    # A held scope may have published an artifact whose record then failed.
    tolerated = closed is None or state["held"] is not None
    if extra:
        if not tolerated:
            raise ArchiveInvalid("unreferenced_artifact_in_sealed_scope")
        problems.append("unreferenced_artifact")
    if closed is not None and (closed.get("retained_content_bytes") != total + sum(
            os.lstat(directory / name).st_size for name in extra) or closed.get("artifacts") != len(sizes) + len(extra)):
        if not tolerated:
            raise ArchiveInvalid("scope_closed_content_mismatch")
        problems.append("scope_closed_content_mismatch")


# ------------------------------------------------------------ safe views

def summary(archive: VerifiedArchive) -> dict:
    """Content-free summary: identities, counts, availability and outcomes."""
    opened = archive.opened or {}
    return {"read_api_version": archive.api_version, "scope_id": archive.scope_id, "status": archive.status,
            "problems": list(archive.problems), "manifest_sha256": archive.manifest_sha256,
            "records": len(archive.records), "held": archive.held,
            "operation_label": (opened.get("operation") or {}).get("label"),
            "calls": [{"call": call.number, "stage": call.stage, "provider": call.provider, "model": call.model,
                       "outcome": call.outcome, "archival": (call.result or {}).get("archival"),
                       "logical_request": call.logical_request.availability,
                       "wire_attempts": len(call.attempts),
                       "responses": [a.response.availability for a in call.attempts],
                       "candidate_text_sha256": call.binding.get("candidate_text_sha256"),
                       "billing": "unknown"} for call in archive.calls],
            "generations": len(archive.inputs), "candidates": len(archive.candidates),
            "terminals": [{"event_id": t.get("event_id"), "accepted": t.get("accepted"),
                           "kill_stage": t.get("kill_stage")} for t in archive.terminals],
            "refusals": [{"type": r["type"], "reason": r.get("reason")} for r in archive.refusals],
            "code_drift": [d.get("path") for d in archive.drift],
            "authority": "mechanical_evidence_only"}


def lineage(archive: VerifiedArchive) -> list[dict]:
    """Per generation: input → candidates → bound calls/stage outcomes → terminal.

    A verdict attaches only to the exact candidate hash bound when it was
    recorded; a revised text never inherits an earlier candidate's outcome.
    """
    generations = []
    boundaries = [item["seq"] for item in archive.inputs] + [10 ** 12]
    for index, item in enumerate(archive.inputs):
        start, end = boundaries[index], boundaries[index + 1]
        calls = [c for c in archive.calls if start < c.intent_seq < end]
        outcomes = [o for o in archive.stage_outcomes if start < o["seq"] < end]
        candidates = []
        for candidate in (c for c in archive.candidates if start < c["seq"] < end):
            digest = candidate["candidate_text_sha256"]
            stages: dict[str, dict] = {}
            for call in calls:
                if call.binding.get("candidate_text_sha256") == digest:
                    stages.setdefault(call.stage, {"calls": [], "outcome": None})["calls"].append(
                        {"call": call.number, "outcome": call.outcome})
            for outcome in outcomes:
                if (outcome.get("binding") or {}).get("candidate_text_sha256") == digest:
                    entry = stages.setdefault(outcome["stage"], {"calls": [], "outcome": None})
                    entry["outcome"] = outcome["outcome"]
            for entry in stages.values():
                entry["disposition"] = ("decided_without_provider_call" if not entry["calls"] and entry["outcome"]
                                        else "provider_called" if entry["calls"] else "no_decision_recorded")
            candidates.append({"candidate_text_sha256": digest, "attempt": candidate.get("attempt"),
                               "stages": stages})
        writer_calls = [{"call": c.number, "outcome": c.outcome, "phase": c.binding.get("phase"),
                         "revises": c.binding.get("revises_candidate_text_sha256")}
                        for c in calls if c.stage == "writer"]
        terminals = [t for t in archive.terminals if start < t["seq"] < end]
        generations.append({"event_id": item.get("event_id"), "bundle_sha256": item.get("bundle_sha256"),
                            "memory_sha256": item.get("memory_sha256"), "writer_calls": writer_calls,
                            "candidates": candidates,
                            "terminal": ({k: terminals[-1].get(k) for k in (
                                "accepted", "kill_stage", "draft_text_sha256", "reviewed_bundle_sha256")}
                                if terminals else "unavailable")})
    return generations


def _json_tree(archive: VerifiedArchive, body: Body) -> Any:
    if body.availability != "captured" or body.artifact is None:
        return None
    try:
        return strict_json_loads(archive.artifact(body.artifact), allow_floats=True)
    except (ValueError, UnicodeError):
        return None


def _diff(a: Any, b: Any, path: str, out: list[dict], limit: int = 200) -> None:
    if len(out) >= limit:
        return
    if type(a) is dict and type(b) is dict:
        for key in sorted(set(a) | set(b)):
            child = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in a or key not in b:
                out.append({"path": child, "change": "added" if key not in a else "removed"})
            else:
                _diff(a[key], b[key], child, out, limit)
    elif type(a) is list and type(b) is list:
        if len(a) != len(b):
            out.append({"path": path, "change": "length", "a": len(a), "b": len(b)})
        for index, (left, right) in enumerate(zip(a, b)):
            _diff(left, right, f"{path}/{index}", out, limit)
    elif a != b or type(a) is not type(b):
        out.append({"path": path or "/", "change": "value",
                    "a_sha256": sha256_hex(canonical_json(_scalar(a))),
                    "b_sha256": sha256_hex(canonical_json(_scalar(b)))})


def _scalar(value: Any) -> Any:
    return repr(value) if type(value) is float else value


def compare_calls(a: VerifiedArchive, call_a: int, b: VerifiedArchive, call_b: int) -> dict:
    """Precise field/hash differences between two calls; no content."""
    left, right = _call(a, call_a), _call(b, call_b)
    fields = []
    for name in ("stage", "provider", "model", "outcome"):
        if getattr(left, name) != getattr(right, name):
            fields.append({"field": name, "a": getattr(left, name), "b": getattr(right, name)})
    for key in sorted(set(left.binding) | set(right.binding)):
        if left.binding.get(key) != right.binding.get(key):
            fields.append({"field": f"binding.{key}", "a": left.binding.get(key), "b": right.binding.get(key)})
    differences: list[dict] = []
    identical = (left.logical_request.artifact is not None
                 and left.logical_request.artifact == right.logical_request.artifact)
    tree_a, tree_b = _json_tree(a, left.logical_request), _json_tree(b, right.logical_request)
    if tree_a is not None and tree_b is not None and not identical:
        _diff(tree_a, tree_b, "", differences)
    logical = {"a": left.logical_request.artifact, "b": right.logical_request.artifact,
               "availability": [left.logical_request.availability, right.logical_request.availability],
               "identical": identical, "differences": differences}
    attempts = []
    for index in range(max(len(left.attempts), len(right.attempts))):
        la = left.attempts[index] if index < len(left.attempts) else None
        ra = right.attempts[index] if index < len(right.attempts) else None
        attempts.append({"attempt": index + 1,
                         "request_sha256": [la.request.artifact if la else None, ra.request.artifact if ra else None],
                         "response_sha256": [la.response.artifact if la else None,
                                             ra.response.artifact if ra else None],
                         "status": [la.status if la else None, ra.status if ra else None]})
    return {"read_api_version": READ_API_VERSION, "fields": fields, "logical_request": logical,
            "attempts": attempts, "authority": "mechanical_comparison_only"}


def compare_archives(a: VerifiedArchive, b: VerifiedArchive) -> dict:
    code_a = ((a.opened or {}).get("code_identity") or {})
    code_b = ((b.opened or {}).get("code_identity") or {})
    files = sorted(set(code_a.get("files") or {}) | set(code_b.get("files") or {}))
    return {"read_api_version": READ_API_VERSION, "status": [a.status, b.status],
            "code_files_differing": [p for p in files if (code_a.get("files") or {}).get(p)
                                     != (code_b.get("files") or {}).get(p)],
            "sdk_versions_differing": sorted(k for k in set(code_a.get("sdk_versions") or {})
                                             | set(code_b.get("sdk_versions") or {})
                                             if (code_a.get("sdk_versions") or {}).get(k)
                                             != (code_b.get("sdk_versions") or {}).get(k)),
            "editorial_policy_identical": code_a.get("editorial_policy_sha256") == code_b.get("editorial_policy_sha256"),
            "stage_sequence": [[c.stage for c in a.calls], [c.stage for c in b.calls]],
            "logical_requests_identical": [c.logical_request.artifact for c in a.calls]
            == [c.logical_request.artifact for c in b.calls],
            "wire_requests_identical": [[x.request.artifact for x in c.attempts] for c in a.calls]
            == [[x.request.artifact for x in c.attempts] for c in b.calls],
            "authority": "mechanical_comparison_only"}


def _call(archive: VerifiedArchive, number: int) -> CallRecord:
    for call in archive.calls:
        if call.number == number:
            return call
    raise ArchiveInvalid("call_not_found")


def _content(archive: VerifiedArchive, body: Body) -> dict:
    if body.availability != "captured" or body.artifact is None:
        return {"availability": body.availability}
    data = archive.artifact(body.artifact)
    try:
        return {"availability": "captured", "sha256": body.artifact, "encoding": "utf-8", "text": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"availability": "captured", "sha256": body.artifact, "encoding": "base64",
                "data": base64.b64encode(data).decode("ascii")}


def export_call(archive: VerifiedArchive, number: int, output: str | os.PathLike) -> str:
    """Write one call's exact retained content to a NEW private file (0600)."""
    if archive.status == "invalid":
        raise ArchiveInvalid("archive_invalid")
    raw = os.fspath(output)
    if not isinstance(raw, str) or not os.path.isabs(raw):
        raise RequestArchiveRefused("private_path_not_absolute")
    parent = require_private_directory(os.path.dirname(raw), create=False)
    call = _call(archive, number)
    payload = {"read_api_version": READ_API_VERSION, "scope_id": archive.scope_id,
               "archive_status": archive.status, "call": call.number, "stage": call.stage,
               "provider": call.provider, "model": call.model, "binding": call.binding,
               "logical_request": _content(archive, call.logical_request),
               "attempts": [{"attempt": a.attempt, "transport_family": a.transport_family, "host": a.host,
                             "path": a.path, "status": a.status, "request": _content(archive, a.request),
                             "response": _content(archive, a.response), "provider_ids": a.provider_ids}
                            for a in call.attempts],
               "result": call.result, "authority": "private_mechanical_evidence_only"}
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    if not write_private_file_exclusive(parent, os.path.basename(raw), data):
        return "identical_existing"
    return "written"
