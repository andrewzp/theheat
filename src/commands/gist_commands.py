"""Durable command admission for the serialized Gist write route (P00c, ROUTE-CONTRACT-v2).

The ``admit`` job of ``gist-commands.yml`` runs this module on the raw
``workflow_dispatch`` input. It never reads or writes a Gist and never holds the seal
key: it validates the PUBLIC shape only, then writes the immutable input bytes and an
IDs-only admission receipt that the workflow uploads as ``theheat-command-<command_id>``.

Two forms are admitted:

* v2 sealed envelope (every dashboard command) -- canonical ASCII JSON::

      {schema_version: 2, command_id, action, operation, requested_at, expires_at,
       producer: {kind, generation}, actor_subject, route_activation,
       seal: {alg: "A256GCM", kid, iv, tag, ciphertext}}

  The private body (targets and payload: draft edits, snapshots, feedback notes) exists
  only as AES-256-GCM ciphertext; every public field is authenticated by the Node
  sealer/consumer (``dashboard/lib/gist-command-seal.js``). Admission checks exact
  keys, enums, ids, times, producer generation and exact base64/byte bounds.
* v1 route control -- ``activate_route`` / ``deactivate_route`` only (payload
  ``{generation}``, no private content), AUTHENTICATED by root: an HMAC-SHA256 over
  every field (``auth: {alg: "HS256", kid, mac}``) under the root-held
  ``THEHEAT_ROUTE_CONTROL_KEY`` (never the dashboard). Any other v1 action is
  ``plaintext_command_refused``: there is no plaintext fallback.

Admission accepts only the configured key ids (non-secret repository variables
``THEHEAT_COMMAND_SEAL_KID`` and ``THEHEAT_ROUTE_CONTROL_KID``); unset means every sealed
or control command is refused (default-off). It never verifies a tag or MAC: the Node
consumer, which holds the keys, does.

The single Node consumer re-verifies every check, opens the seal and applies the
operation with the dashboard's own domain functions. Admission is not application.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID, uuid4

from src.commands import gist_route
from src.commands.command_roles import RoleError
from src.commands.schema import CommandError, canonical_json, utc_datetime, utc_text
from src.commands.writer_fencing import WriterGenerationRegistry

# GitHub: "The maximum payload for inputs is 65,535 characters." The sealed envelope (ASCII,
# so bytes == characters) stays below it with margin; route control is tiny.
MAX_COMMAND_BYTES = 64000
MAX_CONTROL_BYTES = 4096
MAX_PLAINTEXT_BYTES = 46000
MAX_CIPHERTEXT_B64 = 4 * -(-MAX_PLAINTEXT_BYTES // 3)  # 61,336 characters
ENVELOPE_SCHEMA = 2
SEAL_ALG = "A256GCM"
CONTROL_ALG = "HS256"
SEAL_KID_ENV = "THEHEAT_COMMAND_SEAL_KID"
CONTROL_KID_ENV = "THEHEAT_ROUTE_CONTROL_KID"
CONTROL_KEY_ENV = "THEHEAT_ROUTE_CONTROL_KEY"
MAX_LIFETIME = timedelta(days=1)
CLOCK_SKEW = timedelta(minutes=5)
ARTIFACT_PREFIX = "theheat-command-"
REFUSAL_PREFIX = "theheat-admission-refused-"
STATE_ACTIONS = frozenset({"draft_update", "reconcile_delivery", "activate_route", "deactivate_route"})
FEEDBACK_ACTIONS = frozenset({"post_feedback"})
CONTROL_ACTIONS = frozenset({"activate_route", "deactivate_route"})
ACTIONS = STATE_ACTIONS | FEEDBACK_ACTIONS
# Producer kind (an inventory writer name) -> the only actions it may submit.
PRODUCERS: dict[str, frozenset[str]] = {
    "dashboard_editor": frozenset({"draft_update"}),
    "dashboard_reconciliation": frozenset({"reconcile_delivery"}),
    "post_feedback": frozenset({"post_feedback"}),
    "gist_route_control": CONTROL_ACTIONS,
}
DRAFT_OPERATIONS = frozenset({"approve", "reject", "edit", "review", "auto_approve", "cancel_auto_approve",
                              "select_candidate", "bulk_reject_below", "attach_graphic", "remove_graphic", "episode"})
SEALED_OPERATIONS: dict[str, frozenset[str]] = {
    "draft_update": DRAFT_OPERATIONS,
    "reconcile_delivery": frozenset({"reconcile_delivery"}),
    "post_feedback": frozenset({"post_feedback"}),
}
_ENVELOPE_KEYS = {"schema_version", "command_id", "action", "operation", "requested_at", "expires_at", "producer",
                  "actor_subject", "route_activation", "seal"}
_CONTROL_KEYS = {"schema_version", "command_id", "action", "requested_at", "expires_at", "producer",
                 "actor_subject", "targets", "payload", "auth"}
_KID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_B64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")
_ACTOR = re.compile(r"[A-Za-z0-9_.:@-]{1,100}")
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


def _exact(value: Any, keys: set[str], label: str, code: str = "invalid_payload") -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise CommandError(code, f"{label} fields do not match the action")
    return value


def _uuid(value: Any, code: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise CommandError(code, "A canonical UUID is required") from None
    return value


def _b64(value: Any, *, exact: int | None = None, limit: int | None = None) -> bytes:
    if not isinstance(value, str) or not _B64.fullmatch(value) or (limit is not None and len(value) > limit):
        raise CommandError("invalid_envelope", "Seal fields must be canonical base64 within bounds")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise CommandError("invalid_envelope", "Seal fields must be canonical base64 within bounds") from None
    if base64.b64encode(data).decode("ascii") != value or not data or (exact is not None and len(data) != exact):
        raise CommandError("invalid_envelope", "Seal fields must be canonical base64 within bounds")
    return data


def _window(value: dict, now: datetime) -> None:
    requested, expires = utc_datetime(value["requested_at"]), utc_datetime(value["expires_at"])
    clock = utc_datetime(utc_text(now))
    if requested > clock + CLOCK_SKEW or expires <= requested or expires > requested + MAX_LIFETIME:
        raise CommandError("invalid_time", "Command time window is invalid")
    if expires <= clock:
        raise CommandError("expired", "Command expired before admission")


def _producer(value: dict, action: str) -> None:
    producer = _exact(value["producer"], {"kind", "generation"}, "Producer", "unauthorized_writer_generation_refused")
    if not isinstance(producer["kind"], str) or producer["kind"] not in PRODUCERS:
        raise RoleError("unauthorized_writer_generation_refused", "Unknown producer kind")
    if action not in PRODUCERS[producer["kind"]]:
        raise RoleError("unauthorized_writer_generation_refused", "This producer may not submit the action")
    if not isinstance(producer["generation"], str):
        raise RoleError("unauthorized_writer_generation_refused", "Producer generation must be text")
    admission_registry().check(producer["kind"], producer["generation"])


def _configured_kid(value: str | None, unconfigured: str) -> str:
    if not value or not _KID.fullmatch(value):
        raise CommandError(unconfigured, "No key id is configured for this command form (default-off)")
    return value


def _sealed(value: dict, now: datetime, seal_kid: str | None) -> None:
    """The public v2 envelope. No key here: authenticity is the Node consumer's check."""
    _exact(value, _ENVELOPE_KEYS, "Envelope", "invalid_envelope")
    _uuid(value["command_id"], "invalid_command_id")
    action = value["action"]
    if action not in SEALED_OPERATIONS:
        raise CommandError("invalid_action", "Unsupported sealed route action")
    if value["operation"] not in SEALED_OPERATIONS[action]:
        raise CommandError("invalid_operation", "Unsupported operation for this action")
    _window(value, now)
    _producer(value, action)
    if not isinstance(value["actor_subject"], str) or not _ACTOR.fullmatch(value["actor_subject"]):
        raise CommandError("invalid_envelope", "Actor subject must be a bounded identifier")
    _uuid(value["route_activation"], "invalid_envelope")
    seal = _exact(value["seal"], {"alg", "kid", "iv", "tag", "ciphertext"}, "Seal", "invalid_envelope")
    if seal["alg"] != SEAL_ALG or not isinstance(seal["kid"], str) or not _KID.fullmatch(seal["kid"]):
        raise CommandError("invalid_envelope", "Unsupported seal")
    if seal["kid"] != _configured_kid(seal_kid, "command_seal_unconfigured"):
        raise CommandError("command_seal_kid_unknown", "Sealed under a key id this repository does not use")
    _b64(seal["iv"], exact=12)
    _b64(seal["tag"], exact=16)
    _b64(seal["ciphertext"], limit=MAX_CIPHERTEXT_B64)


def _route_control(value: dict, now: datetime, size: int, control_kid: str | None) -> None:
    """v1 plaintext: route control only (its payload is a generation, never private content)."""
    if value.get("action") not in CONTROL_ACTIONS:
        raise CommandError("plaintext_command_refused", "Only route control may travel without a seal")
    if size > MAX_CONTROL_BYTES:
        raise CommandError("command_too_large", "Route control command is too large")
    if "auth" not in value:
        raise CommandError("route_control_unauthenticated", "Route control must carry a root HMAC")
    _exact(value, _CONTROL_KEYS, "Command", "invalid_command")
    _uuid(value["command_id"], "invalid_command_id")
    _window(value, now)
    _producer(value, value["action"])
    if not isinstance(value["actor_subject"], str) or not value["actor_subject"] or len(value["actor_subject"]) > 200:
        raise CommandError("invalid_payload", "Actor subject must be nonempty text within 200 characters")
    if value["targets"] != []:
        raise CommandError("invalid_targets", "This action names no draft revision target")
    payload = _exact(value["payload"], {"generation"}, "Route control")
    if type(payload["generation"]) is not int or not 1 <= payload["generation"] <= gist_route.CODE_GENERATION:
        raise CommandError("invalid_route_generation", "Route generation must be a generation this code implements")
    auth = _exact(value["auth"], {"alg", "kid", "mac"}, "Route control authentication", "route_control_unauthenticated")
    if auth["alg"] != CONTROL_ALG or not isinstance(auth["kid"], str) or not _KID.fullmatch(auth["kid"]):
        raise CommandError("route_control_unauthenticated", "Route control must carry a root HMAC")
    _b64(auth["mac"], exact=32)
    if auth["kid"] != _configured_kid(control_kid, "route_control_unconfigured"):
        raise CommandError("route_control_kid_unknown", "Route control under a key id this repository does not use")


def parse_command(raw: str | bytes, *, now: datetime, seal_kid: str | None = None,
                  control_kid: str | None = None) -> dict:
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
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise CommandError("invalid_command", "Unsupported command schema")
    if value["schema_version"] == ENVELOPE_SCHEMA:
        if not text.isascii():
            raise CommandError("invalid_envelope", "A sealed envelope is ASCII")
        _sealed(value, now, seal_kid)
    elif value["schema_version"] == 1:
        _route_control(value, now, len(data), control_kid)
    else:
        raise CommandError("invalid_command", "Unsupported command schema")
    return {"command": value, "digest": hashlib.sha256(data).hexdigest(), "raw": text}


def store_of(action: str) -> str:
    return "feedback_gist" if action in FEEDBACK_ACTIONS else "gist_state"


def admit(raw: str | bytes, out_dir: Path, *, now: datetime, seal_kid: str | None = None,
          control_kid: str | None = None) -> dict:
    """Admit one command into an immutable artifact directory; never touches a Gist.

    Key ids default to the non-secret repository variables exported to the admit job.
    """
    seal_kid = os.environ.get(SEAL_KID_ENV) if seal_kid is None else seal_kid
    control_kid = os.environ.get(CONTROL_KID_ENV) if control_kid is None else control_kid
    try:
        parsed = parse_command(raw, now=now, seal_kid=seal_kid, control_kid=control_kid)
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


def parse_control_key(value: str | None) -> tuple[str, bytes]:
    """``<kid>:<standard base64 of exactly 32 random bytes>`` (root-held; never logged or echoed)."""
    kid, _, encoded = (value or "").partition(":")
    if not _KID.fullmatch(kid) or not _B64.fullmatch(encoded):
        raise CommandError("route_control_key_invalid", "Set THEHEAT_ROUTE_CONTROL_KEY to <kid>:<base64 of 32 bytes>")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise CommandError("route_control_key_invalid", "Set THEHEAT_ROUTE_CONTROL_KEY to <kid>:<base64 of 32 bytes>") from None
    if len(key) != 32 or base64.b64encode(key).decode("ascii") != encoded:
        raise CommandError("route_control_key_invalid", "Set THEHEAT_ROUTE_CONTROL_KEY to <kid>:<base64 of 32 bytes>")
    return kid, key


def control_mac(command: dict, kid: str, key: bytes) -> str:
    """HMAC-SHA256 over the canonical command with ``auth`` reduced to ``{alg, kid}`` (every field bound)."""
    signed = {**{k: v for k, v in command.items() if k != "auth"}, "auth": {"alg": CONTROL_ALG, "kid": kid}}
    digest = hmac.new(key, canonical_json(signed).encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def route_command(action: str, *, generation: int, actor_subject: str, now: datetime, control_key: str,
                  lifetime: timedelta = timedelta(hours=2)) -> str:
    """Root-authenticated ``activate_route``/``deactivate_route`` command for the controlled rollout."""
    if action not in PRODUCERS["gist_route_control"]:
        raise CommandError("invalid_action", "Only route activation or deactivation")
    kid, key = parse_control_key(control_key)
    at = now.astimezone(UTC).replace(microsecond=0)
    command: dict[str, Any] = {"schema_version": 1, "command_id": str(uuid4()), "action": action,
                               "requested_at": utc_text(at), "expires_at": utc_text(at + lifetime),
                               "producer": {"kind": "gist_route_control", "generation": str(gist_route.CODE_GENERATION)},
                               "actor_subject": actor_subject, "targets": [], "payload": {"generation": generation}}
    command["auth"] = {"alg": CONTROL_ALG, "kid": kid, "mac": control_mac(command, kid, key)}
    raw = canonical_json(command)
    parse_command(raw, now=now, control_kid=kid)
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
        try:
            raw = route_command(args.action, generation=args.generation, actor_subject=args.actor, now=now,
                                control_key=os.environ.get(CONTROL_KEY_ENV, ""))
        except CommandError as exc:
            print(json.dumps({"status": "refused", "code": exc.code}), file=sys.stderr)
            return 2
        sys.stdout.write(raw + "\n")
        return 0
    result = admit(os.environ.get("THEHEAT_COMMAND_INPUT", ""), args.out, now=now)
    _github_output({"admitted": "true" if result["admitted"] else "false",
                    "command_id": result["command_id"] or "", "code": result["code"] or "",
                    "store": result.get("store") or ""})
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
