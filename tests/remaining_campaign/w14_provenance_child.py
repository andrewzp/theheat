"""W14.6 provenance channel: real import journal -> real local preview ``GET /state`` reply.

An invented snapshot is imported through the W14.2 importer into a separate local SQLite
command authority. The real ``PreviewHandler`` then answers ``GET /state`` over an invented
current state (the local preview authority is faked; the HTTP handler, operator file and
journal reader are real) through an in-memory connection: no socket is opened. Runs
in-process (pytest) or as a fresh process (Node feeds the exact reply to /api/dashboard).
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = 3999
ORIGIN = f"http://127.0.0.1:{PORT}"
OPERATOR = {"username": "w14p-publisher", "password": "invented-w14p-password", "subject": "w14p-publisher", "role": "publisher"}
IMPORT_ID = "w14p-import"
TWEET_ID = "1900000000000005151"


class Connection:
    """Just enough of a socket for StreamRequestHandler: bytes in, bytes out."""

    def __init__(self, raw: bytes):
        self._reader = io.BytesIO(raw)
        self.sent = bytearray()

    def makefile(self, mode, *_args, **_kwargs):
        if "r" not in mode:
            raise AssertionError("unbuffered writes go through sendall")
        return self._reader

    def sendall(self, data) -> None:
        self.sent += data

    def settimeout(self, _value) -> None:
        pass

    def shutdown(self, _how) -> None:
        pass

    def close(self) -> None:
        pass


class LocalAuthority:
    """Invented local preview authority: only what ``GET /state`` reads."""

    environment = "local"

    def __init__(self, state: dict):
        self.state = state

    def read(self) -> tuple[int, dict]:
        return 7, deepcopy(self.state)

    def candidate_projection(self, _allowed, *, now, resolve_principal=None) -> list:
        return []

    def generated_candidate_inputs(self) -> tuple:
        return ()

    def local_cost_projection(self, *, now) -> dict:
        return {"schema_version": 1, "status": "unconfigured", "reason": "not_configured"}


def _draft(key: str, place: str, *, status: str = "pending") -> dict:
    from src.editorial.revisions import initialize_revision, record_human_review
    draft = {"id": f"w14p-{key}", "event_id": f"w14p-ev-{key}", "type": "monthly_high", "status": status,
             "text": f"Invented {place} reached 39 C, a monthly high.", "created_at": "2026-10-30T08:00:00Z",
             "review_context": {"two_bot": {"bundle": {"event_id": f"w14p-ev-{key}", "signal_kind": "monthly_high",
                                                       "current_facts": [{"label": "place", "value": place}]}}}}
    initialize_revision(draft, at="2026-10-30T08:05:00Z")
    record_human_review(draft, at="2026-10-30T08:06:00Z")
    return draft


def fixture() -> tuple[dict, dict]:
    """(imported snapshot, current local state): held/posted unchanged, edited moved on, fresh never imported."""
    from src.editorial.revisions import record_human_review
    held, posted, edited = _draft("held", "Brackwater Fen"), _draft("posted", "Thistle Reach", status="posted"), _draft("edited", "Ossory Flats")
    posted.update(tweet_id=TWEET_ID, posted_at="2026-10-30T09:00:00Z")
    ledger = {"w14p-ev-posted": {"phase": "confirmed", "tweet_id": TWEET_ID, "text": posted["text"], "at": "2026-10-30T09:00:00Z",
                                 "confirmed_at": "2026-10-30T09:00:00Z"}}
    snapshot: dict[str, Any] = {"drafts": [held, posted, edited], "publish_ledger": ledger}
    current = deepcopy(snapshot)
    moved = current["drafts"][2]
    moved.update(text="Invented Ossory Flats reached 39 C, its warmest month on the invented record.", content_revision=2)
    record_human_review(moved, at="2026-10-30T10:00:00Z")
    current["drafts"].append(_draft("fresh", "Larkspur Gap"))
    return snapshot, current


def operators_file(directory: Path) -> Path:
    path = directory / "operators.json"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"operators": [OPERATOR]}, stream)
    return path


def server(state: dict, operators: Path, journal: str | None):
    """A PreviewServer with its real attributes and no bound socket."""
    from src.commands import preview_ingress
    value = preview_ingress.PreviewServer.__new__(preview_ingress.PreviewServer)
    value.authority, value.operators, value.origin = LocalAuthority(state), preview_ingress.Operators(operators), ORIGIN
    value.candidate_inputs, value.server_port, value.recovery_journal = (), PORT, journal
    return value


def get_state(target) -> tuple[int, dict]:
    from src.commands import preview_ingress
    token = base64.b64encode(f"{OPERATOR['username']}:{OPERATOR['password']}".encode()).decode()
    connection = Connection(f"GET /state HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nAuthorization: Basic {token}\r\n\r\n".encode())
    preview_ingress.PreviewHandler(cast(Any, connection), ("127.0.0.1", 49152), target)  # in-memory, never a socket
    head, _, body = bytes(connection.sent).partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), json.loads(body)


def run(workdir: str) -> dict:
    from src.commands import import_plan
    from src.commands.schema import canonical_json
    from src.commands.sqlite_authority import SQLiteAuthority
    directory = Path(workdir)
    snapshot, current = fixture()
    raw = canonical_json(snapshot).encode()
    journal = SQLiteAuthority(directory / "journal.sqlite3")
    journal.initialize({"drafts": [], "publish_ledger": {}})
    reviewed = import_plan.plan([(IMPORT_ID, raw)], authority=journal)
    imported = import_plan.execute(journal, reviewed, [(IMPORT_ID, raw)])
    journal_sha = hashlib.sha256(Path(journal.path).read_bytes()).hexdigest()
    operators = operators_file(directory)
    status, reply = get_state(server(current, operators, journal.path))
    unconfigured_status, unconfigured = get_state(server(current, operators, None))
    return {"source_sha256": hashlib.sha256(raw).hexdigest(), "import": [row["status"] for row in imported["items"]],
            "status": status, "reply": reply, "unconfigured_status": unconfigured_status,
            "unconfigured_provenance": unconfigured.get("recovery_provenance"),
            "journal_unchanged": hashlib.sha256(Path(journal.path).read_bytes()).hexdigest() == journal_sha}


if __name__ == "__main__":
    from contextlib import redirect_stdout
    with tempfile.TemporaryDirectory() as directory:
        with redirect_stdout(sys.stderr):
            result = run(directory)
        print(json.dumps(result, sort_keys=True))
