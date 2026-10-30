"""OFFLINE PROTOCOL FIXTURE — models theheat_media.artifacts; it is NOT PostgreSQL.

A stand-in ``psycopg`` module that interprets only the media adapter's exact SQL
statements (copied here independently, so any SQL change fails loudly), backed by a
shared SQLite file so separate processes see one invented store. It models the
table's checks (key = SHA256(payload), byte_count, 1..8 MiB), immutability, role
privileges, read-only reader transactions, TLS/identity reporting and injectable
faults. Genuine PostgreSQL acceptance is tests/test_postgres_gist_assets.py in CI.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import types
from typing import Any

ENV = "THEHEAT_TEST_PG_PROTOCOL_FILE"
SQL_PRIVILEGES = ("SELECT has_table_privilege(current_user, 'theheat_media.artifacts', 'SELECT'), "
                  "has_table_privilege(current_user, 'theheat_media.artifacts', 'INSERT'), "
                  "has_table_privilege(current_user, 'theheat_media.artifacts', 'UPDATE'), "
                  "has_table_privilege(current_user, 'theheat_media.artifacts', 'DELETE'), "
                  "has_table_privilege(current_user, 'theheat_media.artifacts', 'TRUNCATE'), "
                  "current_database(), current_user")
SQL_SIZE = "SELECT byte_count, octet_length(payload) FROM theheat_media.artifacts WHERE sha = %s"
SQL_PAYLOAD = ("SELECT payload FROM theheat_media.artifacts "
               "WHERE sha = %s AND octet_length(payload) = %s AND octet_length(payload) <= %s")
SQL_INSERT = ("INSERT INTO theheat_media.artifacts (sha, payload, byte_count) VALUES (%s, %s, %s) "
              "ON CONFLICT (sha) DO NOTHING")
SECRET_HINT = "invented-secret-host.example password=invented-pass user=invented_reader"
READER = {"SELECT": 1, "INSERT": 0, "UPDATE": 0, "DELETE": 0, "TRUNCATE": 0}
WRITER = {"SELECT": 1, "INSERT": 1, "UPDATE": 0, "DELETE": 0, "TRUNCATE": 0}


class Error(Exception):
    pass


class OperationalError(Error):
    pass


class QueryCanceled(OperationalError):
    pass


class InsufficientPrivilege(Error):
    pass


class CheckViolation(Error):
    pass


class ReadOnlySqlTransaction(Error):
    pass


def create(path, *, users=None, dbname="media"):
    """A new invented backing store; ``users`` maps role name -> privilege dict."""
    users = users or {"media_reader": READER, "media_writer": WRITER}
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE artifacts (sha TEXT PRIMARY KEY, payload BLOB NOT NULL, byte_count INTEGER NOT NULL);
            CREATE TRIGGER artifacts_no_update BEFORE UPDATE ON artifacts BEGIN SELECT RAISE(ABORT, 'immutable media staging'); END;
            CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts BEGIN SELECT RAISE(ABORT, 'immutable media staging'); END;
            CREATE TABLE roles (name TEXT PRIMARY KEY, privileges TEXT NOT NULL);
            CREATE TABLE fixture (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
        """)
        for name, privileges in users.items():
            db.execute("INSERT INTO roles VALUES(?,?)", (name, json.dumps(privileges)))
        db.execute("INSERT INTO fixture VALUES('dbname',?)", (dbname,))
        db.execute("INSERT INTO fixture VALUES('fault','')")
    return Path(path)


def set_fault(path, fault):
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fixture SET value=? WHERE key='fault'", (fault,))


def counter(path, name):
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
    return row[0] if row else 0


def raw_insert(path, sha, payload):
    """Simulate out-of-band corruption (a row that violates the real table's check)."""
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO artifacts VALUES(?,?,?)", (sha, payload, len(payload)))


def _bump(db, name):
    db.execute("INSERT INTO counters VALUES(?,1) ON CONFLICT(name) DO UPDATE SET value=value+1", (name,))


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class Connection:
    def __init__(self, path, kwargs):
        self._path, self.kwargs = Path(path), kwargs
        self._db = sqlite3.connect(self._path, isolation_level=None, timeout=10)
        self._fault = self._db.execute("SELECT value FROM fixture WHERE key='fault'").fetchone()[0]
        self._dbname = self._db.execute("SELECT value FROM fixture WHERE key='dbname'").fetchone()[0]
        role = self._db.execute("SELECT privileges FROM roles WHERE name=?", (kwargs["user"],)).fetchone()
        self._privileges = json.loads(role[0]) if role else None
        self._read_only = "default_transaction_read_only=on" in kwargs["options"]
        self._open = True
        self.pgconn = types.SimpleNamespace(ssl_in_use=kwargs["sslmode"] == "verify-full")
        self.info = types.SimpleNamespace(server_version=170004)
        with self._counted():
            _bump(self._db, "connections")

    @contextmanager
    def _counted(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def close(self):
        if self._open:
            self._open = False
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            with self._counted():
                _bump(self._db, "closed")
            self._db.close()

    @contextmanager
    def transaction(self):
        self._db.execute("BEGIN IMMEDIATE")
        self._wrote = False
        try:
            yield self
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        if not self._wrote:  # Commit faults model the write transaction only.
            self._db.execute("COMMIT")
            return
        if self._fault == "commit_failure":  # Not applied, but the client cannot know that.
            self._db.execute("ROLLBACK")
            raise OperationalError("server closed the connection during COMMIT " + SECRET_HINT)
        self._db.execute("COMMIT")
        if self._fault == "lost_commit_ack":
            raise OperationalError("connection lost after COMMIT was sent " + SECRET_HINT)

    def execute(self, sql, params=()):
        if self._fault == "timeout" and sql != SQL_PRIVILEGES:
            raise QueryCanceled("canceling statement due to statement timeout " + SECRET_HINT)
        if sql == SQL_PRIVILEGES:
            p = dict(self._privileges or {})
            if self._fault == "revoked":
                p = {key: 0 for key in READER}
            return _Cursor((*(bool(p.get(k, 0)) for k in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")),
                            self._dbname, self.kwargs["user"]))
        if not (self._privileges or {}).get("SELECT") or self._fault == "revoked":
            raise InsufficientPrivilege("permission denied for table artifacts " + SECRET_HINT)
        if sql == SQL_SIZE:
            row = self._db.execute("SELECT byte_count, length(payload) FROM artifacts WHERE sha=?", params).fetchone()
            if row and self._fault == "wrong_length":
                row = (row[0], row[1] + 1)
            return _Cursor(row)
        if sql == SQL_PAYLOAD:
            if self._fault == "disconnect_before_commit" and getattr(self, "_wrote", False):
                raise OperationalError("server closed the connection unexpectedly " + SECRET_HINT)
            sha, exact, limit = params
            row = self._db.execute("SELECT payload FROM artifacts WHERE sha=? AND length(payload)=? AND length(payload)<=?",
                                   (sha, exact, limit)).fetchone()
            if row and self._fault == "tamper":
                row = (bytes([row[0][0] ^ 1]) + row[0][1:],)
            if row and self._fault == "truncate":
                row = (row[0][:-1],)
            _bump(self._db, "payload_reads")
            return _Cursor(row)
        if sql == SQL_INSERT:
            if self._read_only:
                raise ReadOnlySqlTransaction("cannot execute INSERT in a read-only transaction")
            if not (self._privileges or {}).get("INSERT"):
                raise InsufficientPrivilege("permission denied for table artifacts " + SECRET_HINT)
            sha, payload, count = params
            if not (1 <= len(payload) <= 8 * 1024 * 1024 and count == len(payload)
                    and sha == hashlib.sha256(payload).hexdigest()):
                raise CheckViolation("new row violates check constraint")
            self._db.execute("INSERT INTO artifacts VALUES(?,?,?) ON CONFLICT(sha) DO NOTHING", (sha, payload, count))
            self._wrote = True
            return _Cursor(None)
        raise Error("unsupported statement in the offline protocol fixture")


def module(path):
    """A ``psycopg``-shaped module bound to one invented backing file."""
    value: Any = types.ModuleType("psycopg")
    value.Error, value.OperationalError = Error, OperationalError

    def connect(**kwargs):
        required = {"host", "port", "dbname", "user", "password", "passfile", "connect_timeout", "sslmode",
                    "gssencmode", "application_name", "options", "autocommit"}
        assert required <= set(kwargs), "the adapter must state every connection setting"
        assert kwargs["passfile"].startswith("/nonexistent/") and kwargs["connect_timeout"] <= 10
        assert kwargs["autocommit"] is True
        for budget in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout", "transaction_timeout"):
            assert f"-c {budget}=" in kwargs["options"]
        with sqlite3.connect(path) as db:
            fault = db.execute("SELECT value FROM fixture WHERE key='fault'").fetchone()[0]
            _bump(db, "connect_attempts")
        if fault == "unavailable":
            raise OperationalError("connection to server at " + SECRET_HINT + " failed")
        if kwargs["dbname"] != "media":
            raise OperationalError("database does not exist " + SECRET_HINT)
        return Connection(path, kwargs)

    value.connect = connect
    return value


def install(path=None):
    """Child-process hook used only by tests: replace ``psycopg`` with this fixture."""
    import os
    sys.modules["psycopg"] = module(path or os.environ[ENV])


READER_DSN = "host=media.invented.test port=5432 dbname=media user=media_reader password=invented sslmode=verify-full sslrootcert=system"
WRITER_DSN = "host=media.invented.test port=5432 dbname=media user=media_writer password=invented sslmode=verify-full sslrootcert=system"
