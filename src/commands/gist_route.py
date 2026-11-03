"""Serialized Gist write route (P00c): configuration, route record and the writer guard.

Default-off. With ``THEHEAT_GIST_WRITE_ROUTE`` unset (or ``legacy``) and no route
record in the state Gist, every writer behaves exactly as before.

Route mode is effective when either the configured variable says ``serialized``
or the state Gist's route record (``gist-write-route.json``, written only by the
consumer's ``activate_route``/``deactivate_route`` commands) says ``serialized``.
In route mode a writer may PATCH the Gist only when it holds the serialized-writer
marker that a job of the ``theheat-bot`` concurrency group exports, and only when
its code generation is at least the generation recorded at activation. Everything
else refuses with an explicit code before any PATCH.

The marker is self-asserted process configuration, not a credential: it prevents
new code from writing outside the serialized group. Pre-candidate deployments
cannot check anything; root's credential rotation is the fence for them.

The route record and command results live in their own files of the state Gist
(written in the same single PATCH as ``state.json``). Legacy writers PATCH only
the files they own, so they can never erase or rewrite either file.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
import os
import re
from typing import Any
from uuid import UUID

ROUTE_ENV = "THEHEAT_GIST_WRITE_ROUTE"
MARKER_ENV = "THEHEAT_SERIALIZED_WRITER"
ROUTE_FILENAME = "gist-write-route.json"
RESULTS_FILENAME = "gist-command-results.json"
# The route protocol generation this code implements. Activation records the
# consumer's generation; a writer whose code is older refuses once that is newer.
CODE_GENERATION = 1
MODES = ("legacy", "serialized")
_MARKER = re.compile(r"([0-9]{1,32}):([A-Za-z0-9_.-]{1,100})")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_RECORD_KEYS = {"schema_version", "mode", "generation", "changed_at", "changed_by_run", "command_id"}
MAX_RECORD_BYTES = 4096


class RouteRefused(RuntimeError):
    """A Gist write that the serialized route forbids; ``code`` is the stable reason."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def configured_mode(env: Mapping[str, str] | None = None) -> str:
    """Exact enum: unset/"legacy" is legacy, "serialized" is route mode, anything else refuses."""
    value = (os.environ if env is None else env).get(ROUTE_ENV, "")
    if value in ("", "legacy"):
        return "legacy"
    if value == "serialized":
        return "serialized"
    raise RouteRefused("invalid_gist_write_route")


def decode_record(content: Any) -> dict:
    """Strictly decode the route record written by the consumer (never trusted loosely)."""
    if not isinstance(content, str) or len(content.encode("utf-8", "surrogatepass")) > MAX_RECORD_BYTES:
        raise RouteRefused("gist_write_route_unreadable")

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out
    try:
        value = json.loads(content, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise RouteRefused("gist_write_route_unreadable") from None
    if (not isinstance(value, dict) or set(value) != _RECORD_KEYS or type(value["schema_version"]) is not int
            or value["schema_version"] != 1 or value["mode"] not in MODES
            or type(value["generation"]) is not int or not 1 <= value["generation"] <= 2**31
            or not isinstance(value["changed_at"], str) or not _UTC.fullmatch(value["changed_at"])
            or not isinstance(value["changed_by_run"], str) or not _MARKER.fullmatch(value["changed_by_run"])):
        raise RouteRefused("gist_write_route_unreadable")
    try:
        datetime.fromisoformat(value["changed_at"].replace("Z", "+00:00"))
        if str(UUID(value["command_id"])) != value["command_id"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise RouteRefused("gist_write_route_unreadable") from None
    return value


def record_from_files(files: Any) -> dict | None:
    """Route record from a Gist ``files`` envelope that the writer already fetched.

    Absent file: ``None`` (the legacy state). A present but truncated, non-string or
    malformed file refuses: it can only have been written by the route consumer.
    """
    if not isinstance(files, dict) or ROUTE_FILENAME not in files:
        return None
    meta = files[ROUTE_FILENAME]
    if not isinstance(meta, dict) or meta.get("truncated"):
        raise RouteRefused("gist_write_route_unreadable")
    return decode_record(meta.get("content"))


def serialized_writer_marker(env: Mapping[str, str] | None = None) -> str | None:
    """The ``<run id>:<job>`` marker of a serialized group job, or ``None`` when absent."""
    source = os.environ if env is None else env
    value = source.get(MARKER_ENV, "")
    if value == "":
        return None
    match = _MARKER.fullmatch(value)
    run_id = source.get("GITHUB_RUN_ID", "")
    if match is None or (run_id and match.group(1) != run_id):
        raise RouteRefused("invalid_serialized_writer_marker")
    return value


def route_effective(record: dict | None, env: Mapping[str, str] | None = None) -> bool:
    return configured_mode(env) == "serialized" or (record is not None and record["mode"] == "serialized")


def check_writer(record: dict | None, *, writer: str, env: Mapping[str, str] | None = None) -> str:
    """Return ``legacy`` or ``serialized``; raise :class:`RouteRefused` when the PATCH is forbidden.

    ``writer`` is the inventory name (``src.commands.writer_fencing``) used in the refusal log.
    """
    from src.commands import writer_fencing

    if writer not in {row.name for row in writer_fencing.WRITERS}:
        raise RouteRefused("unknown_writer")
    if not route_effective(record, env):
        return "legacy"
    if serialized_writer_marker(env) is None:
        raise RouteRefused("direct_write_disabled_by_route")
    if record is not None and CODE_GENERATION < record["generation"]:
        raise RouteRefused("stale_writer_generation")
    return "serialized"


def refusal_line(writer: str, code: str) -> str:
    """Fixed-vocabulary log line: never payloads, URLs or credentials."""
    return f"[gist-route] {writer} write refused: {code}"
