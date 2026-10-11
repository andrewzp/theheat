"""Explicit local-only HTTP adapter for the existing PostgreSQL authority.

No credential discovery, dotenv, sender, scheduler, migrations or Gist fallback.
The operator file is an invented local identity map, not a hosted identity system.
"""
from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import socket
import stat
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID

from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import Command, CommandError, MAX_COMMAND_BYTES, Principal
from src.editorial.policy import current_editorial_policy
from src.storage.postgres_projection import ProjectionError

AUTH_CONTEXT = "verified-local-preview-basic-v1"
ALLOWED_ACTIONS = frozenset({"edit_revision", "record_review", "approve_revision",
                             "reject_revision", "cancel_approval", "select_candidate",
                             "request_candidate_checks", "admit_checked_candidate"})


def safe_environment() -> None:
    """Refuse production and secrets before constructing a local adapter."""
    if os.environ.get("NODE_ENV") == "production" or os.environ.get("THEHEAT_ENVIRONMENT") == "production":
        raise ValueError("production_preview_refused")
    for name, value in os.environ.items():
        if name.startswith("PG") or (value and (
            re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?|PRIVATE_KEY|GIST_ID|DATABASE_URL)$", name)
            or name.startswith(("AWS_", "TWITTER_", "BLUESKY_", "X_API_"))
        )):
            raise ValueError("ambient_credentials_refused")


def strict_json(raw: bytes):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("duplicate_json_key")
            value[key] = item
        return value

    def nonfinite(_):
        raise ValueError("invalid_json")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid_json") from exc


class Operators:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("absolute_operator_file_required")
        self.rows()

    def rows(self) -> list[dict]:
        # Open without following a last-component link and validate the open file.
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_size > 16384):
                raise ValueError("private_operator_file_required")
            data = strict_json(stream.read(16385))
        if not isinstance(data, dict) or set(data) != {"operators"}:
            raise ValueError("invalid_operator_file")
        rows = data["operators"]
        if not isinstance(rows, list) or len(rows) > 20:
            raise ValueError("invalid_operator_file")
        subjects, usernames = set(), set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"username", "password", "subject", "role"}:
                raise ValueError("invalid_operator_file")
            if any(not isinstance(row[key], str) or not 1 <= len(row[key]) <= 200 for key in row):
                raise ValueError("invalid_operator_file")
            if ":" in row["username"] or row["username"] in usernames or row["subject"] in subjects:
                raise ValueError("duplicate_operator")
            Principal(row["subject"], row["role"], AUTH_CONTEXT)
            usernames.add(row["username"])
            subjects.add(row["subject"])
        return rows

    def authenticate(self, header: str) -> Principal | None:
        if not header.startswith("Basic ") or len(header) > 2048:
            return None
        try:
            username, password = base64.b64decode(header[6:], validate=True).decode("utf-8").split(":", 1)
        except (ValueError, UnicodeError):
            return None
        for row in self.rows():
            if hmac.compare_digest(row["username"].encode(), username.encode()) and hmac.compare_digest(row["password"].encode(), password.encode()):
                return Principal(row["subject"], row["role"], AUTH_CONTEXT)
        return None

    def resolve(self, subject: str) -> Principal | None:
        for row in self.rows():
            if row["subject"] == subject:
                return Principal(subject, row["role"], AUTH_CONTEXT)
        return None


class PreviewServer(HTTPServer):
    """Single bounded connection at a time; each request has a read deadline."""
    def __init__(self, authority: PostgresCommandAuthority, operators: Operators, *, port: int, origin: str, candidate_inputs: tuple[str, ...] = ()):
        safe_environment()
        parsed = urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("explicit_loopback_origin_required")
        if authority.environment != "local":
            raise ValueError("local_authority_required")
        if len(candidate_inputs) > 16 or len(set(candidate_inputs)) != len(candidate_inputs) or any(not re.fullmatch(r"[a-f0-9]{64}", v) for v in candidate_inputs):
            raise ValueError("invalid_candidate_allowlist")
        self.candidate_inputs = candidate_inputs
        self.authority, self.operators, self.origin = authority, operators, origin
        super().__init__(("127.0.0.1", port), PreviewHandler)

    def get_request(self):
        connection, address = super().get_request()
        # Header deadline fires first, allowing a private HTTP refusal when a
        # request line was received. Body reads install their remaining budget.
        connection.settimeout(6)
        return connection, address


class PreviewHandler(BaseHTTPRequestHandler):
    server: PreviewServer

    def setup(self):
        super().setup()
        # An inactivity timeout alone can be extended indefinitely by trickled
        # headers. Stop header reads after an absolute five-second deadline.
        self.header_deadline = threading.Timer(5, self.stop_header_read)
        self.header_deadline.daemon = True
        self.header_deadline.start()

    def stop_header_read(self):
        try:
            self.connection.shutdown(socket.SHUT_RD)
        except OSError:
            pass

    def parse_request(self):
        try:
            return super().parse_request()
        finally:
            self.header_deadline.cancel()

    def finish(self):
        self.header_deadline.cancel()
        super().finish()

    def log_message(self, format, *args):
        pass  # No paths, request bodies, credentials or provider errors in logs.

    def reply(self, status: int, value: dict) -> None:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        if status == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="theheat local preview"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def send_error(self, code, message=None, explain=None):
        # Includes parser errors and unsupported methods; never echo a request
        # target/header in BaseHTTPRequestHandler's default HTML response.
        self.reply(code, {"error": "Invalid or unsupported local HTTP request", "code": "http_request_refused"})

    def handle_request(self):
        try:
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get_all("Host") != [host]:
                self.reply(403, {"error": "Local host required", "code": "origin_refused"})
                return
            origins = self.headers.get_all("Origin", [])
            origin = self.headers.get("Origin")
            if origins and origins != [self.server.origin]:
                self.reply(403, {"error": "Same-origin request required", "code": "origin_refused"})
                return
            if len(self.headers.get_all("Authorization", [])) != 1:
                actor = None
            else:
                actor = self.server.operators.authenticate(self.headers.get("Authorization", ""))
            if actor is None:
                self.reply(401, {"error": "Local sign-in required", "code": "unauthorized"})
                return
            if self.command == "GET" and self.path == "/state":
                version, state = self.server.authority.read()
                self.reply(200, {"state_version": version, "state": state,
                                 "editorial_policy": current_editorial_policy(), "role": actor.role,
                                 "candidates": self.server.authority.candidate_projection(self.server.candidate_inputs, now=datetime.now(UTC)),
                                 "local_preview": True, "publication_enabled": False})
                return
            if self.command == "GET" and re.fullmatch(r"/commands/[a-f0-9-]{36}", self.path):
                command_id = self.path.removeprefix("/commands/")
                if str(UUID(command_id)) != command_id:
                    raise ValueError("invalid_command_id")
                authority = self.server.authority
                # Read existing intent/result together without consuming work.
                with authority.projections._connection() as connection:
                    authority._validate(connection)
                    intent = authority._intent(connection, command_id)
                    result = authority._result(connection, command_id)
                if intent is None:
                    self.reply(404, {"error": "Command has not been durably accepted", "code": "command_not_found"})
                    return
                self.reply(200, {"status": "completed" if result else "pending", "result": result,
                                 "receipt": intent[1],
                                 "local_preview": True, "publication_enabled": False})
                return
            if self.command != "POST" or self.path != "/commands":
                self.reply(404, {"error": "Preview route not found"})
                return
            if origin != self.server.origin:
                self.reply(403, {"error": "Same-origin request required", "code": "origin_refused"})
                return
            if self.headers.get_all("Content-Type") != ["application/json"]:
                self.reply(415, {"error": "JSON required"})
                return
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
                self.reply(400, {"error": "Bounded content length required"})
                return
            size = int(lengths[0])
            if size > MAX_COMMAND_BYTES:
                self.reply(413, {"error": "Command too large"})
                return
            deadline = time.monotonic() + 5
            raw = b""
            while len(raw) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(min(16384, size - len(raw)))
                if not chunk:
                    break
                raw += chunk
            if len(raw) != size:
                self.reply(400, {"error": "Incomplete command"})
                return
            body = strict_json(raw)
            now = datetime.now(UTC)
            command = Command.from_request(body, actor, environment="local", now=now)
            if command.action not in ALLOWED_ACTIONS:
                self.reply(400, {"error": "Action unavailable in local preview", "code": "preview_action_unavailable"})
                return
            if command.action in {"request_candidate_checks", "admit_checked_candidate"} and command.payload["admission_input_id"] not in self.server.candidate_inputs:
                raise CommandError("candidate_not_allowlisted", "Candidate is not in this local fixture")
            receipt = self.server.authority.accept(command, actor, now=now)
            self.reply(202, {"status": "pending", "receipt": receipt, "local_preview": True})
        except CommandError as exc:
            status = 403 if exc.code == "forbidden" else 503 if exc.code == "authorization_unavailable" else 409
            self.reply(status, {"error": str(exc), "code": exc.code})
        except (ValueError, RecursionError):
            self.reply(400, {"error": "Invalid preview request", "code": "invalid_request"})
        except (BrokenPipeError, ConnectionResetError):
            return  # Lost HTTP acknowledgement does not undo a committed intent.
        except (OSError, ProjectionError):
            self.reply(503, {"error": "Local authority unavailable; retain the same command for retry", "code": "authority_unavailable"})


def arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--socket-directory", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--database-port", type=int, default=55473)
    parser.add_argument("--operators", required=True)


def adapter(args) -> tuple[PostgresCommandAuthority, Operators]:
    safe_environment()
    operators = Operators(args.operators)
    authority = PostgresCommandAuthority(socket_directory=args.socket_directory, database=args.database,
                                         user=args.user, port=args.database_port, environment="local")
    return authority, operators


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    arguments(parser)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--candidate-input-id", action="append", default=[])
    args = parser.parse_args()
    try:
        authority, operators = adapter(args)
        with PreviewServer(authority, operators, port=args.port, origin=args.origin, candidate_inputs=tuple(args.candidate_input_id)) as server:
            server.serve_forever()
    except (ValueError, OSError, CommandError, ProjectionError):
        print('{"error":"local_preview_unavailable"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
