"""Durable command admission for the serialized Gist write route (P00c).

The ``admit`` job of ``gist-commands.yml`` runs this module on the raw
``workflow_dispatch`` input. It never reads or writes a Gist. It validates the
envelope (exact canonical JSON, duplicate keys refused, at most 65535 bytes, the
GitHub dispatch-input bound), its expiry window and the producer generation
(``WriterGenerationRegistry``), then writes the immutable canonical bytes and an
admission receipt that the workflow uploads as ``theheat-command-<command_id>``.

The single Node consumer (``dashboard/lib/gist-command-consumer.js``) re-verifies
every check against the authoritative route record and applies the command with
the dashboard's exact revision checks. Admission is not application.

Envelope (all numbers are safe integers; draft content travels as embedded JSON
text so its digest is byte-identical in Python and Node)::

    {schema_version: 1, command_id: <uuid>, action, requested_at, expires_at,
     producer: {kind, generation}, actor_subject, targets: [...], payload: {...}}
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID, uuid4

from src.commands import gist_route
from src.commands.command_roles import RoleError
from src.commands.schema import CommandError, DraftTarget, canonical_json, utc_datetime, utc_text
from src.commands.writer_fencing import WriterGenerationRegistry

MAX_COMMAND_BYTES = 65535  # GitHub workflow_dispatch input payload limit (<= 64 KiB).
MAX_EMBEDDED_JSON = 60000
MAX_UPDATES = 500
MAX_LIFETIME = timedelta(days=1)
CLOCK_SKEW = timedelta(minutes=5)
ARTIFACT_PREFIX = "theheat-command-"
REFUSAL_PREFIX = "theheat-admission-refused-"
STATE_ACTIONS = frozenset({"draft_update", "reconcile_delivery", "activate_route", "deactivate_route"})
FEEDBACK_ACTIONS = frozenset({"post_feedback"})
ACTIONS = STATE_ACTIONS | FEEDBACK_ACTIONS
# Producer kind (an inventory writer name) -> the only actions it may submit.
PRODUCERS: dict[str, frozenset[str]] = {
    "dashboard_editor": frozenset({"draft_update"}),
    "dashboard_reconciliation": frozenset({"reconcile_delivery"}),
    "post_feedback": frozenset({"post_feedback"}),
    "gist_route_control": frozenset({"activate_route", "deactivate_route"}),
}
DRAFT_OPERATIONS = frozenset({"approve", "reject", "edit", "review", "auto_approve", "cancel_auto_approve",
                              "select_candidate", "bulk_reject_below", "attach_graphic", "remove_graphic",
                              "episode", "dispatch_rollback"})
CONFIRM_ACTIONS = frozenset({"review", "approve", "auto_approve"})
_HEX = re.compile(r"[a-f0-9]{64}")
_DRAFT_ID = re.compile(r"[A-Za-z0-9_.:-]{1,200}")
_SAFE = 9007199254740991


def admission_registry() -> WriterGenerationRegistry:
    """Static generations this code admits; the consumer re-checks the recorded generation.

    Generation "0" names every pre-route producer (direct legacy writers): retired.
    """
    known = {str(g) for g in range(1, gist_route.CODE_GENERATION + 1)}
    return WriterGenerationRegistry(authorized={kind: known for kind in PRODUCERS},
                                    retired={kind: {"0"} for kind in PRODUCERS})


def _unique(pairs):
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise CommandError("duplicate_key", "Command JSON repeats a key")
        out[key] = value
    return out


def _no_floats(value: Any) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if type(value) is int:
        if not -_SAFE <= value <= _SAFE:
            raise CommandError("unsafe_number", "Command numbers must be safe integers")
        return
    if isinstance(value, list):
        for item in value:
            _no_floats(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            _no_floats(item)
        return
    raise CommandError("unsafe_number", "Command numbers must be safe integers")


def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise CommandError("invalid_payload", f"{label} must be nonempty text within {limit} characters")
    return value


def _embedded(value: Any, label: str) -> Any:
    """Embedded JSON text (draft patch, request, feedback input): strict, bounded, object."""
    _text(value, label, MAX_EMBEDDED_JSON)
    try:
        parsed = json.loads(value, object_pairs_hook=_unique)
    except CommandError:
        raise
    except (ValueError, TypeError):
        raise CommandError("invalid_payload", f"{label} must be valid JSON") from None
    if not isinstance(parsed, dict):
        raise CommandError("invalid_payload", f"{label} must be a JSON object")
    canonical_json(parsed)  # Finite, valid Unicode.
    return parsed


def _exact(value: Any, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise CommandError("invalid_payload", f"{label} fields do not match the action")
    return value


def _draft_update(targets: list, payload: dict) -> None:
    _exact(payload, {"operation", "updates", "confirm", "follow_up"}, "Draft update")
    if payload["operation"] not in DRAFT_OPERATIONS:
        raise CommandError("invalid_payload", "Unknown draft operation")
    updates = payload["updates"]
    if not isinstance(updates, list) or not 1 <= len(updates) <= MAX_UPDATES or len(updates) != len(targets):
        raise CommandError("invalid_targets", "Each target needs exactly one compare-and-swap update")
    if payload["operation"] != "bulk_reject_below" and len(updates) != 1:
        raise CommandError("invalid_targets", "Only bulk rejection may name several drafts")
    for target, update in zip(targets, updates):
        _exact(update, {"draft_id", "expected_snapshot", "expected_numeric_sha256", "patch_json"}, "Update")
        if update["draft_id"] != target.draft_id or not _DRAFT_ID.fullmatch(update["draft_id"]):
            raise CommandError("invalid_targets", "Update and target drafts differ")
        if not all(isinstance(update[key], str) and _HEX.fullmatch(update[key])
                   for key in ("expected_snapshot", "expected_numeric_sha256")):
            raise CommandError("invalid_payload", "Supply the exact observed draft and numeric snapshots")
        patch = _embedded(update["patch_json"], "Draft patch")
        if (set(patch) != {"set", "unset", "order"} or not isinstance(patch["set"], dict)
                or not isinstance(patch["unset"], list) or not isinstance(patch["order"], list)
                or not all(isinstance(k, str) for k in [*patch["unset"], *patch["order"]])
                or set(patch["set"]) - set(patch["order"]) or set(patch["unset"]) & set(patch["order"])
                or len(set(patch["order"])) != len(patch["order"]) or "id" in patch["set"] or "id" in patch["unset"]):
            raise CommandError("invalid_payload", "Draft patch must name set, unset and the resulting key order")
    confirm = payload["confirm"]
    if confirm is not None:
        _exact(confirm, {"name", "action", "checked_policy_sha256", "checked_automatic_epoch"}, "Confirmation")
        if (confirm["name"] != "draft_decision" or confirm["action"] not in CONFIRM_ACTIONS
                or confirm["action"] != payload["operation"]
                or not isinstance(confirm["checked_policy_sha256"], str)
                or not _HEX.fullmatch(confirm["checked_policy_sha256"])
                or (confirm["checked_automatic_epoch"] is not None
                    and not isinstance(confirm["checked_automatic_epoch"], str))
                or (confirm["action"] == "auto_approve") != (confirm["checked_automatic_epoch"] is not None)):
            raise CommandError("invalid_payload", "Unsupported confirmation")
    elif payload["operation"] in CONFIRM_ACTIONS:
        raise CommandError("invalid_payload", "This decision must be re-confirmed by the consumer")
    follow = payload["follow_up"]
    if follow is not None:
        _exact(follow, {"kind", "publish_intent_id"}, "Follow-up")
        try:
            canonical = str(UUID(follow["publish_intent_id"]))
        except (ValueError, TypeError, AttributeError):
            canonical = None
        if follow["kind"] != "bot_manual_tweet" or canonical != follow["publish_intent_id"] or payload["operation"] != "approve":
            raise CommandError("invalid_payload", "Only an approval names one manual publication intent")
    elif payload["operation"] == "approve":
        raise CommandError("invalid_payload", "An approval must name its publication intent")


def _reconcile(payload: dict) -> None:
    _exact(payload, {"event_id", "request_json", "actor", "at", "expected_snapshot", "expected_numeric_sha256"},
           "Reconciliation")
    _text(payload["event_id"], "Event ID", 300)
    request = _embedded(payload["request_json"], "Reconciliation request")
    if request.get("event_id") != payload["event_id"]:
        raise CommandError("invalid_payload", "Reconciliation request names another event")
    _text(payload["actor"], "Actor", 200)
    utc_datetime(payload["at"])
    if not all(isinstance(payload[key], str) and _HEX.fullmatch(payload[key])
               for key in ("expected_snapshot", "expected_numeric_sha256")):
        raise CommandError("invalid_payload", "Supply the exact observed attempt snapshots")


def _route_control(payload: dict) -> None:
    _exact(payload, {"generation"}, "Route control")
    if type(payload["generation"]) is not int or not 1 <= payload["generation"] <= gist_route.CODE_GENERATION:
        raise CommandError("invalid_route_generation", "Route generation must be a generation this code implements")


def _feedback(payload: dict) -> None:
    _exact(payload, {"input_json"}, "Feedback")
    value = _embedded(payload["input_json"], "Feedback input")
    try:
        if str(UUID(value["request_id"])) != value["request_id"]:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise CommandError("invalid_payload", "Feedback needs its request identifier") from None


def parse_command(raw: str | bytes, *, now: datetime) -> dict:
    """Validate one raw dispatch input; return ``{command, digest, raw}`` or raise ``CommandError``/``RoleError``."""
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(data) > MAX_COMMAND_BYTES:
        raise CommandError("command_too_large", "Command exceeds the dispatch input limit")
    try:
        text = data.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_unique)
    except CommandError:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise CommandError("invalid_json", "Command is not valid JSON") from None
    _no_floats(value)
    if canonical_json(value) != text:
        raise CommandError("non_canonical_command", "Submit the exact canonical command bytes")
    _exact(value, {"schema_version", "command_id", "action", "requested_at", "expires_at", "producer",
                   "actor_subject", "targets", "payload"}, "Command")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise CommandError("invalid_command", "Unsupported command schema")
    try:
        if str(UUID(value["command_id"])) != value["command_id"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise CommandError("invalid_command_id", "A canonical UUID is required") from None
    action = value["action"]
    if action not in ACTIONS:
        raise CommandError("invalid_action", "Unsupported route action")
    requested, expires = utc_datetime(value["requested_at"]), utc_datetime(value["expires_at"])
    clock = utc_datetime(utc_text(now))
    if requested > clock + CLOCK_SKEW or expires <= requested or expires > requested + MAX_LIFETIME:
        raise CommandError("invalid_time", "Command time window is invalid")
    if expires <= clock:
        raise CommandError("expired", "Command expired before admission")
    producer = _exact(value["producer"], {"kind", "generation"}, "Producer")
    if not isinstance(producer["kind"], str) or producer["kind"] not in PRODUCERS:
        raise RoleError("unauthorized_writer_generation_refused", "Unknown producer kind")
    if action not in PRODUCERS[producer["kind"]]:
        raise RoleError("unauthorized_writer_generation_refused", "This producer may not submit the action")
    if not isinstance(producer["generation"], str):
        raise RoleError("unauthorized_writer_generation_refused", "Producer generation must be text")
    admission_registry().check(producer["kind"], producer["generation"])
    _text(value["actor_subject"], "Actor subject", 200)
    rows = value["targets"]
    if not isinstance(rows, list) or len(rows) > MAX_UPDATES:
        raise CommandError("invalid_targets", "Targets must be a bounded list")
    targets = [DraftTarget.parse(row) for row in rows]
    if len({row.draft_id for row in targets}) != len(targets):
        raise CommandError("invalid_targets", "Duplicate draft targets are not allowed")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise CommandError("invalid_payload", "Payload must be an object")
    if action == "draft_update":
        if not targets:
            raise CommandError("invalid_targets", "A draft update names its exact draft revisions")
        _draft_update(targets, payload)
    elif targets:
        raise CommandError("invalid_targets", "This action names no draft revision target")
    elif action == "reconcile_delivery":
        _reconcile(payload)
    elif action == "post_feedback":
        _feedback(payload)
    else:
        _route_control(payload)
    return {"command": value, "digest": hashlib.sha256(data).hexdigest(), "raw": text}


def store_of(action: str) -> str:
    return "feedback_gist" if action in FEEDBACK_ACTIONS else "gist_state"


def admit(raw: str | bytes, out_dir: Path, *, now: datetime) -> dict:
    """Admit one command into an immutable artifact directory; never touches a Gist."""
    try:
        parsed = parse_command(raw, now=now)
    except CommandError as exc:
        command_id = None
        try:
            candidate = json.loads(raw)
            if isinstance(candidate, dict) and str(UUID(candidate.get("command_id"))) == candidate.get("command_id"):
                command_id = candidate["command_id"]
        except Exception:  # noqa: BLE001 - the refusal code is the result; never echo input.
            command_id = None
        return {"admitted": False, "code": exc.code, "command_id": command_id}
    command = parsed["command"]
    receipt = {"schema_version": 1, "command_id": command["command_id"], "digest": parsed["digest"],
               "action": command["action"], "store": store_of(command["action"]),
               "requested_at": command["requested_at"], "expires_at": command["expires_at"],
               "producer": command["producer"], "admitted_at": utc_text(now)}
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "command.json").write_text(parsed["raw"], encoding="utf-8")
    (out_dir / "admission.json").write_text(canonical_json(receipt), encoding="utf-8")
    return {"admitted": True, "code": None, "command_id": command["command_id"], "digest": parsed["digest"],
            "store": receipt["store"]}


def route_command(action: str, *, generation: int, actor_subject: str, now: datetime,
                  lifetime: timedelta = timedelta(hours=2)) -> str:
    """Canonical ``activate_route``/``deactivate_route`` command for root's controlled rollout."""
    if action not in PRODUCERS["gist_route_control"]:
        raise CommandError("invalid_action", "Only route activation or deactivation")
    at = now.astimezone(UTC).replace(microsecond=0)
    command = {"schema_version": 1, "command_id": str(uuid4()), "action": action,
               "requested_at": utc_text(at), "expires_at": utc_text(at + lifetime),
               "producer": {"kind": "gist_route_control", "generation": str(gist_route.CODE_GENERATION)},
               "actor_subject": actor_subject, "targets": [], "payload": {"generation": generation}}
    raw = canonical_json(command)
    parse_command(raw, now=now)
    return raw


def _github_output(values: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serialized Gist route command admission (never writes a Gist)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    admit_cmd = sub.add_parser("admit", help="Admit THEHEAT_COMMAND_INPUT into --out")
    admit_cmd.add_argument("--out", required=True, type=Path)
    build = sub.add_parser("route-command", help="Print a canonical activate/deactivate command")
    build.add_argument("--action", required=True, choices=sorted(PRODUCERS["gist_route_control"]))
    build.add_argument("--generation", required=True, type=int)
    build.add_argument("--actor", required=True)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.cmd == "route-command":
        sys.stdout.write(route_command(args.action, generation=args.generation, actor_subject=args.actor, now=now) + "\n")
        return 0
    result = admit(os.environ.get("THEHEAT_COMMAND_INPUT", ""), args.out, now=now)
    _github_output({"admitted": "true" if result["admitted"] else "false",
                    "command_id": result["command_id"] or "", "code": result["code"] or "",
                    "store": result.get("store") or ""})
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
