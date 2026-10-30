"""Media-only PostgreSQL implementation of the immutable Gist media-byte interface.

It reuses ``theheat_media.artifacts`` (migration 009): exact SHA256 key, payload,
checked ``byte_count``, a database check that the key is the payload's SHA256, an
8 MiB per-row ceiling and update/delete/truncate refusal triggers. It never
initializes the command authority, installs tables, creates roles, updates,
deletes or expires a row, reads another table or fetches a URL. Gist remains the
draft, review, approval and receipt authority.

Each operation is one explicit transaction block on an autocommit connection, so
nothing outlives the block; the connection is closed on every outcome.

Capabilities are separate configurations: preview and sender use a read-only DSN
(``THEHEAT_MEDIA_STORE_DSN``); retention uses an insert-only DSN
(``THEHEAT_MEDIA_WRITER_DSN``) and is enabled explicitly. A reader has no write
path. DSNs are server-side settings only: they never appear in requests,
descriptors, command lines, errors or logs.

A network host requires ``sslmode=verify-full`` with an explicit ``sslrootcert``
(``system`` or an absolute CA file); a local Unix-socket host must say
``sslmode=disable``. Service, password-file, client-certificate and other libpq
lookups are disabled, ambient ``PG*`` settings are refused, and every connection
carries finite connect/statement/lock/idle/transaction timeouts.
"""
from __future__ import annotations

import hashlib
import os
import re

from src.media.gist_assets import MediaStoreError, SHA

TABLE = "theheat_media.artifacts"
MAX_ROW_BYTES = 8 * 1024 * 1024
MAX_BATCH_BYTES = 26 * 1024 * 1024
MAX_DSN_BYTES = 4096
CONNECT_TIMEOUT_SECONDS = 5
# Finite server budgets (milliseconds); a transaction never outlives these.
TIMEOUTS = {"statement_timeout": 10000, "lock_timeout": 2000, "idle_in_transaction_session_timeout": 15000,
            "transaction_timeout": 20000}
DISABLED_FILE = "/nonexistent/theheat-media-store-disabled"
ROLES = ("reader", "writer")
# Exact privileges each capability must have on the artifact table, and nothing more.
PRIVILEGES = {"reader": {"SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False, "TRUNCATE": False},
              "writer": {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False}}
_KEYS = frozenset({"host", "port", "dbname", "user", "password", "sslmode", "sslrootcert", "channel_binding"})
_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_$-]{0,62}")

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


def _refuse(code, reason):
    raise MediaStoreError(code, reason)


def _require(condition, code, reason):
    if not condition:
        _refuse(code, reason)


def parse_dsn(text):
    """Strict libpq keyword/value subset (no URIs); invalid input never reaches a dial."""
    _require(type(text) is str and 0 < len(text.encode("utf-8")) <= MAX_DSN_BYTES
             and not any(ord(c) < 32 or ord(c) == 127 for c in text), "media_store_unavailable",
             "the media store connection setting is invalid")
    params, position = {}, 0
    while position < len(text):
        if text[position] == " ":
            position += 1
            continue
        match = re.compile(r"([a-z_]+)=").match(text, position)
        _require(match is not None, "media_store_unavailable", "the media store connection setting is invalid")
        assert match is not None
        key, position = match[1], match.end()
        value = []
        if position < len(text) and text[position] == "'":
            position += 1
            while True:
                _require(position < len(text), "media_store_unavailable",
                         "the media store connection setting is invalid")
                char = text[position]
                if char == "\\":
                    _require(position + 1 < len(text), "media_store_unavailable",
                             "the media store connection setting is invalid")
                    value.append(text[position + 1])
                    position += 2
                elif char == "'":
                    position += 1
                    break
                else:
                    value.append(char)
                    position += 1
        else:
            while position < len(text) and text[position] != " ":
                _require(text[position] not in "'\\", "media_store_unavailable",
                         "the media store connection setting is invalid")
                value.append(text[position])
                position += 1
        _require(key in _KEYS and key not in params, "media_store_unavailable",
                 "the media store connection setting uses an unsupported or repeated option")
        params[key] = "".join(value)
    return validate_params(params)


def validate_params(params):
    """Explicit TLS/socket identity; a network host never connects without verify-full."""
    _require(type(params) is dict and set(params) <= _KEYS and {"host", "port", "dbname", "user"} <= set(params),
             "media_store_unavailable", "the media store connection setting is incomplete")
    host, port = params["host"], params["port"]
    _require(type(host) is str and host and "," not in host
             and not any(ord(c) < 32 or ord(c) == 127 for c in host),
             "media_store_unavailable", "the media store connection setting is invalid")
    _require(type(port) is str and port.isdigit() and 1 <= int(port) <= 65535, "media_store_unavailable",
             "the media store connection setting is invalid")
    _require(all(type(params[k]) is str and _NAME.fullmatch(params[k]) for k in ("dbname", "user")),
             "media_store_unavailable", "the media store connection setting is invalid")
    if host.startswith("/"):
        # Local Unix-domain socket only (disposable test clusters, local operators).
        _require(os.path.isabs(host) and not host.startswith("//") and os.path.normpath(host) == host
                 and ".." not in host.split("/") and params.get("sslmode") == "disable"
                 and "sslrootcert" not in params and "channel_binding" not in params,
                 "media_store_unavailable", "a local socket store must state sslmode=disable and nothing else")
    else:
        _require(_HOSTNAME.fullmatch(host) is not None and ".." not in host, "media_store_unavailable",
                 "the media store connection setting is invalid")
        root = params.get("sslrootcert")
        _require(params.get("sslmode") == "verify-full" and type(root) is str
                 and (root == "system" or (os.path.isabs(root) and os.path.isfile(root)
                                          and not os.path.islink(root))),
                 "media_store_unavailable", "the media store requires verify-full TLS with an explicit root")
        _require(params.get("channel_binding", "require") == "require", "media_store_unavailable",
                 "the media store connection setting is invalid")
        _require(type(params.get("password")) is str and 0 < len(params["password"]) <= 256,
                 "media_store_unavailable", "the media store credential is missing")
    return dict(params)


def connection_kwargs(params, role):
    """The complete, explicit libpq keyword set; nothing is left to ambient lookup."""
    _require(role in ROLES, "media_store_unavailable", "unsupported media store capability")
    params = validate_params(params)
    options = " ".join(f"-c {key}={value}" for key, value in TIMEOUTS.items())
    options += " -c search_path=pg_catalog -c timezone=UTC"
    options += " -c default_transaction_read_only=" + ("on" if role == "reader" else "off")
    kwargs = dict(host=params["host"], port=int(params["port"]), dbname=params["dbname"], user=params["user"],
                  password=params.get("password", ""), passfile=DISABLED_FILE, connect_timeout=CONNECT_TIMEOUT_SECONDS,
                  sslmode=params["sslmode"], gssencmode="disable", application_name="theheat_media_" + role,
                  options=options, autocommit=True)
    if params["sslmode"] == "verify-full":
        kwargs.update(sslrootcert=params["sslrootcert"], channel_binding=params.get("channel_binding", "require"),
                      sslcertmode="disable", sslcert=DISABLED_FILE, sslkey=DISABLED_FILE, sslcrl=DISABLED_FILE,
                      sslcrldir=DISABLED_FILE, ssl_min_protocol_version="TLSv1.2")
    return kwargs


def _ambient():
    return any(name.startswith("PG") for name in os.environ)


class PostgresMediaStore:
    """One store-owned transaction per operation; connection closed on every outcome."""

    backend = "postgres"

    def __init__(self, params, *, role, driver=None):
        _require(role in ROLES, "media_store_unavailable", "unsupported media store capability")
        self._params = validate_params(params)
        self.role = role
        self._driver = driver

    def __repr__(self):  # Never print a credential, host or user.
        return f"PostgresMediaStore(role={self.role!r})"

    def _module(self):
        if self._driver is not None:
            return self._driver
        try:
            import psycopg  # Loaded only once a PostgreSQL store is configured.
        except ImportError:
            raise MediaStoreError("media_store_unavailable", "the media store driver is not installed") from None
        return psycopg

    def _connect(self):
        _require(not _ambient(), "media_store_unavailable", "ambient PostgreSQL settings are refused")
        _require(not os.path.lexists(DISABLED_FILE), "media_store_unavailable", "an implicit libpq file exists")
        driver = self._module()
        try:
            connection = driver.connect(**connection_kwargs(self._params, self.role))
        except Exception:  # Driver errors carry hosts/users; never expose or chain them.
            raise MediaStoreError("media_store_unavailable", "the media store is unavailable") from None
        try:
            remote = not self._params["host"].startswith("/")
            _require(not remote or bool(connection.pgconn.ssl_in_use), "media_store_unavailable",
                     "the media store connection is not encrypted")
            _require(170000 <= connection.info.server_version < 190000, "media_store_unavailable",
                     "unsupported media store server")
            with connection.transaction():
                row = connection.execute(SQL_PRIVILEGES).fetchone()
            _require(row is not None and tuple(row[5:]) == (self._params["dbname"], self._params["user"]),
                     "media_store_unavailable", "the media store identity does not match its configuration")
            expected = PRIVILEGES[self.role]
            _require(tuple(row[:5]) == tuple(expected[p] for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")),
                     "media_store_unavailable", "the media store role has the wrong permissions")
        except MediaStoreError:
            connection.close()
            raise
        except Exception:
            connection.close()
            raise MediaStoreError("media_store_unavailable", "the media store is unavailable") from None
        return connection

    def get(self, sha, *, limit):
        _require(type(sha) is str and SHA.fullmatch(sha), "media_asset_invalid", "invalid asset reference")
        _require(type(limit) is int and 0 < limit, "media_asset_invalid", "invalid asset bound")
        limit = min(limit, MAX_ROW_BYTES)
        connection = self._connect()
        try:
            with connection.transaction():
                size = connection.execute(SQL_SIZE, (sha,)).fetchone()
                _require(size is not None, "media_asset_missing", "a retained asset is missing from the media store")
                assert size is not None
                count, stored = size
                _require(type(count) is int and type(stored) is int and count == stored, "media_asset_changed",
                         "a retained asset changed")
                # Refuse an oversized row before its payload is read into memory.
                _require(0 < count <= limit, "media_asset_invalid", "a retained asset exceeds its bound")
                row = connection.execute(SQL_PAYLOAD, (sha, count, limit)).fetchone()
        except MediaStoreError:
            raise
        except Exception:
            raise MediaStoreError("media_store_unavailable", "the media store is unavailable") from None
        finally:
            connection.close()
        _require(row is not None, "media_asset_changed", "a retained asset changed")
        raw = bytes(row[0]) if isinstance(row[0], (bytes, bytearray, memoryview)) else None
        _require(raw is not None and len(raw) == count and hashlib.sha256(raw).hexdigest() == sha,
                 "media_asset_changed", "a retained asset changed")
        return raw

    def put_many(self, blobs):
        """Atomic, idempotent insert-only retention; a conflicting same-hash row is refused."""
        _require(self.role == "writer", "media_store_unavailable", "this store configuration is read-only")
        blobs = list(blobs) if isinstance(blobs, (list, tuple)) else None
        _require(blobs is not None and 0 < len(blobs) <= 64
                 and all(type(raw) is bytes and 0 < len(raw) <= MAX_ROW_BYTES for raw in blobs)
                 and sum(map(len, blobs)) <= MAX_BATCH_BYTES, "media_asset_invalid", "a retained asset exceeds its bound")
        identities = [hashlib.sha256(raw).hexdigest() for raw in blobs]
        connection = self._connect()
        commit_sent = False
        try:
            with connection.transaction():
                for sha, raw in zip(identities, blobs):
                    connection.execute(SQL_INSERT, (sha, raw, len(raw)))
                    size = connection.execute(SQL_SIZE, (sha,)).fetchone()
                    _require(size is not None and tuple(size) == (len(raw), len(raw)), "media_asset_changed",
                             "a different asset already uses this identity")
                    row = connection.execute(SQL_PAYLOAD, (sha, len(raw), MAX_ROW_BYTES)).fetchone()
                    _require(row is not None and bytes(row[0]) == raw, "media_asset_changed",
                             "a different asset already uses this identity")
                commit_sent = True  # The block's exit sends COMMIT next.
        except MediaStoreError:
            raise
        except Exception:
            # A failure once COMMIT was sent is an unknown outcome, never success.
            raise MediaStoreError("media_retention_unknown" if commit_sent else "media_store_unavailable",
                                  "the media store did not confirm the write") from None
        finally:
            connection.close()
        return identities

    def backup(self, target):
        _refuse("media_store_unavailable", "database-wide backup is not part of the media store; export manifests")
