"""Opt-in, loopback-only bulk rejection with one durable fixed submission.

The file retains a request, not authority state. Only the authenticated HTTP
adapter and its separate consumer decide acceptance and completion.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from http.client import HTTPConnection, HTTPException
import os
from pathlib import Path
import re
import stat
import socket
import threading
import time
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from src.commands.preview_ingress import AUTH_CONTEXT, Operators, safe_environment, strict_json
from src.commands.schema import Command, DraftTarget, MAX_COMMAND_BYTES, MAX_TARGETS, Principal, canonical_json, utc_datetime, utc_text
from src.editorial.revisions import decision_revision, draft_identity
from src.storage.postgres_projection import MAX_BYTES

REASON = "operator_bulk_reject"
MAX_ENVELOPE_BYTES = MAX_COMMAND_BYTES + 4096
HTTP_DEADLINE_SECONDS = 10.0


class ClientError(ValueError):
    """A fixed safe code; never carry source text or transport exception bodies."""


def require(condition, code):
    if not condition:
        raise ClientError(code)


def origin_port(value: str) -> int:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        require(port is not None and 1 <= port <= 65535
                and value == f"http://127.0.0.1:{port}", "local_endpoint_required")
        assert port is not None
        return port
    except (TypeError, ValueError):
        raise ClientError("local_endpoint_required") from None


def file_sync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class BulkRejectionClient:
    endpoint: str
    origin: str
    operators: Path
    subject: str
    request_file: Path

    def credentials(self) -> dict:
        rows = [row for row in Operators(self.operators).rows() if row["subject"] == self.subject]
        require(len(rows) == 1, "operator_unavailable")
        return rows[0]

    def validate(self) -> None:
        safe_environment()
        origin_port(self.endpoint)
        origin_port(self.origin)
        require(self.request_file.is_absolute(), "absolute_request_file_required")
        self.credentials()

    def http(self, path: str, raw: bytes | None = None) -> tuple[int, dict]:
        self.validate()
        require(raw is None or len(raw) <= MAX_COMMAND_BYTES, "command_bound")
        row = self.credentials()
        auth = base64.b64encode((row["username"] + ":" + row["password"]).encode()).decode()
        connection = HTTPConnection("127.0.0.1", origin_port(self.endpoint), timeout=HTTP_DEADLINE_SECONDS)
        deadline = time.monotonic() + HTTP_DEADLINE_SECONDS
        wire: list[socket.socket] = []

        def expire():
            # Keep the actual socket: HTTP/1.0 getresponse detaches it from
            # HTTPConnection while the body is still being read.
            if wire:
                try:
                    wire[0].shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = threading.Timer(HTTP_DEADLINE_SECONDS, expire)
        timer.daemon = True
        timer.start()
        try:
            connection.connect()
            assert connection.sock is not None
            wire.append(connection.sock)
            require(time.monotonic() < deadline, "readback_deadline")
            connection.request("GET" if raw is None else "POST", path, body=raw,
                headers={"Authorization": "Basic " + auth, "Origin": self.origin, "Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(MAX_BYTES + 1)
            require(time.monotonic() < deadline, "readback_deadline")
            require(len(data) <= MAX_BYTES, "readback_bound")
            value = strict_json(data)
            require(type(value) is dict, "invalid_readback")
            require(time.monotonic() < deadline, "readback_deadline")
            return response.status, value
        finally:
            timer.cancel()
            connection.close()

    def validate_envelope(self, envelope: dict) -> dict:
        require(type(envelope) is dict and set(envelope) == {
            "schema_version", "endpoint", "origin", "subject", "request", "request_sha256"}, "invalid_request_file")
        require(type(envelope["schema_version"]) is int and envelope["schema_version"] == 1
                and envelope["endpoint"] == self.endpoint and envelope["origin"] == self.origin
                and envelope["subject"] == self.subject, "request_binding_changed")
        request = envelope["request"]
        # Syntax validation is not authentication. The server supplies its actor.
        command = Command.from_request(request, Principal(self.subject, "editor", AUTH_CONTEXT),
            environment="local", now=utc_datetime(request["requested_at"]))
        require(command.action == "bulk_reject" and command.payload == {"reason": REASON}
                and utc_datetime(command.expires_at) == utc_datetime(command.requested_at) + timedelta(minutes=5),
                "invalid_bulk_request")
        raw = canonical_json(request).encode()
        require(hashlib.sha256(raw).hexdigest() == envelope["request_sha256"], "request_hash_changed")
        return envelope

    def load(self) -> dict | None:
        try:
            fd = os.open(self.request_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
                    and stat.S_IMODE(metadata.st_mode) == 0o600
                    and metadata.st_size <= MAX_ENVELOPE_BYTES, "private_request_file_required")
            raw = stream.read(MAX_ENVELOPE_BYTES + 1)
            require(len(raw) <= MAX_ENVELOPE_BYTES, "request_file_bound")
            envelope = self.validate_envelope(strict_json(raw))
            require(raw == canonical_json(envelope).encode(), "noncanonical_request_file")
            os.fsync(stream.fileno())
        # Also covers a race in which another creator linked the complete file
        # but has not yet synced its directory. No POST precedes these syncs.
        file_sync(self.request_file.parent)
        return envelope

    def retain(self, envelope: dict) -> dict:
        raw = canonical_json(self.validate_envelope(envelope)).encode()
        require(len(raw) <= MAX_ENVELOPE_BYTES, "request_file_bound")
        fd, temporary = tempfile.mkstemp(prefix=".bulk-request-", dir=self.request_file.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Atomic visibility with no overwrite: a losing creator must
                # resume the winner's targets, never submit its own selection.
                os.link(temporary, self.request_file)
            except FileExistsError:
                pass
            file_sync(self.request_file.parent)
        finally:
            os.unlink(temporary)
        retained = self.load()
        require(retained is not None, "request_file_unavailable")
        assert retained is not None
        return retained

    def select(self, value: dict) -> dict | None:
        require(value.get("local_preview") is True and value.get("publication_enabled") is False
                and value.get("operator_subject") == self.subject, "invalid_local_state")
        drafts = value.get("state", {}).get("drafts")
        require(type(drafts) is list and all(type(draft) is dict for draft in drafts), "invalid_drafts")
        targets = []
        ids = set()
        for draft in drafts:
            require(type(draft.get("id")) is str and draft["id"] not in ids, "ambiguous_draft")
            ids.add(draft["id"])
            if draft.get("status") != "pending":
                continue
            require("content_revision" in draft and "decision_revision" in draft
                    and type(draft.get("text")) is str, "unknown_revision")
            targets.append(DraftTarget.parse({"draft_id": draft["id"], **draft_identity(draft),
                                             "decision_revision": decision_revision(draft)}).as_dict())
            require(len(targets) <= MAX_TARGETS, "target_bound")
        if not targets:
            return None
        now = datetime.now(UTC)
        request = dict(command_id=str(uuid4()), action="bulk_reject", requested_at=utc_text(now),
            expires_at=utc_text(now + timedelta(minutes=5)), targets=targets, payload={"reason": REASON})
        return self.validate_envelope(dict(schema_version=1, endpoint=self.endpoint, origin=self.origin,
            subject=self.subject, request=request, request_sha256=hashlib.sha256(canonical_json(request).encode()).hexdigest()))

    def outcome(self, envelope: dict, code: int, value: dict, *, posted: bool = False) -> dict:
        request = envelope["request"]
        base = dict(command_id=request["command_id"], request_sha256=envelope["request_sha256"])
        if code == 202 and posted:
            expected_command = Command.from_request(request, Principal(self.subject, "editor", AUTH_CONTEXT),
                environment="local", now=utc_datetime(request["requested_at"]))
            receipt = value.get("receipt", {})
            require(value.get("local_preview") is True and value.get("status") == "pending"
                    and receipt.get("command_id") == request["command_id"]
                    and receipt.get("digest") == expected_command.digest, "invalid_acceptance")
            return dict(base, status="pending", retry_same_command=True)
        if code != 200:
            # A refusal to this HTTP attempt is not proof an earlier attempt
            # was never accepted. Preserve recovery, even after a 404/expiry.
            error = value.get("code")
            return dict(base, status="unknown", code=error if type(error) is str and re.fullmatch(r"[a-z_]{1,64}", error)
                        else "command_not_acknowledged", retry_same_command=True)
        require(value.get("local_preview") is True and value.get("publication_enabled") is False
                and value.get("recoverable_command") == request, "command_readback_changed")
        if value.get("status") == "pending" and value.get("result") is None:
            return dict(base, status="pending", retry_same_command=True)
        result = value.get("result")
        require(value.get("status") == "completed" and type(result) is dict, "invalid_command_result")
        assert isinstance(result, dict)
        status = result.get("status")
        if status == "rejected":
            reason = result.get("code")
            require(type(reason) is str and re.fullmatch(r"[a-z_]{1,64}", reason), "invalid_refusal")
            return dict(base, status="rejected", code=reason, retry_same_command=False)
        expected = [target["draft_id"] for target in request["targets"]]
        require(status in {"applied", "unchanged"} and result.get("changed_ids") == (expected if status == "applied" else []),
                "invalid_command_result")
        return dict(base, status=status, changed_ids=result["changed_ids"], rejected_count=len(result["changed_ids"]), retry_same_command=False)

    def run(self) -> dict:
        envelope = None
        try:
            self.validate()
            envelope = self.load()
            if envelope is None:
                code, value = self.http("/state")
                require(code == 200, "state_unavailable")
                selected = self.select(value)
                if selected is None:
                    return dict(status="noop", rejected_count=0, command_id=None)
                envelope = self.retain(selected)
            # Read first even on initial creation. This handles competing
            # creators and a completed original without a second POST.
            request = envelope["request"]
            code, value = self.http("/commands/" + request["command_id"])
            if code == 404 and value.get("code") == "command_not_found":
                code, value = self.http("/commands", canonical_json(request).encode())
                return self.outcome(envelope, code, value, posted=True)
            return self.outcome(envelope, code, value)
        except (OSError, HTTPException, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            if envelope is not None:
                return dict(status="unknown", command_id=envelope["request"]["command_id"],
                    request_sha256=envelope["request_sha256"], code="retry_original_request", retry_same_command=True)
            return dict(status="refused", code="local_request_unavailable", retry_same_command=True)
