"""Immutable local PostgreSQL projections; never a production state backend.

Canonical JSON objects are reconstructed, not original provider/wire bytes.
The optional driver is lazy. Every call owns its connection/transaction, and a
write receipt is returned only after commit. There is no current-state pointer.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.hosted_staging import HostedStagingConfig

MAX_BYTES = 16 * 1024 * 1024
MAX_FIELDS = 512
MAX_DEPTH = 32
MAX_NODES = 1_000_000
MAX_INTEGER = 2**53 - 1
MIGRATION = Path(__file__).with_name("migrations") / "001_projection.sql"
SCHEMA = "theheat_projection"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")


class ProjectionError(ValueError):
    """Codes only: connection/SQL error text may contain private values."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ProjectionError(code)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identifier(value: Any) -> str:
    _require(type(value) is str and _ID.fullmatch(value) is not None, "invalid_identifier")
    return value


def _check_structure(value: Any, *, _with_bound: bool = False) -> int | None:
    """Validate every node, optionally measuring a conservative encoding bound.

    The internal measurement is only for newly parsed private JSON. Saturating
    it never ends validation early or changes the original refusal order.
    """
    stack = [(value, 0)]
    count = 0
    size = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, "projection_structure_bound")
        kind = type(item)
        if kind is dict:
            _require(all(type(k) is str for k in item), "invalid_json_key")
            _require(len(item) <= MAX_NODES, "projection_structure_bound")
            _require(count + len(stack) + len(item) <= MAX_NODES, "projection_structure_bound")
            stack.extend((child, depth + 1) for child in item.values())
            if _with_bound and size <= MAX_BYTES:
                size += 2 + max(0, len(item) - 1) + sum(6 * len(name) + 3 for name in item)
        elif kind is list:
            _require(len(item) <= MAX_NODES, "projection_structure_bound")
            _require(count + len(stack) + len(item) <= MAX_NODES, "projection_structure_bound")
            stack.extend((child, depth + 1) for child in item)
            if _with_bound and size <= MAX_BYTES:
                size += 2 + max(0, len(item) - 1)
        elif kind is int:
            _require(abs(item) <= MAX_INTEGER, "unsafe_json_integer")
        elif kind is float:
            _require(math.isfinite(item), "nonfinite_json_number")
        elif kind is str:
            _require(len(item) <= MAX_BYTES, "projection_byte_bound")
        else:
            _require(item is None or kind is bool, "unsupported_json_value")
        if _with_bound and size <= MAX_BYTES:
            if kind is str:
                size += 6 * len(item) + 2
            elif kind is int or kind is float:
                size += len(repr(item))
            elif kind is not dict and kind is not list:
                size += 4 if item is None else 5
        if _with_bound and size > MAX_BYTES:
            size = MAX_BYTES + 1
    return size if _with_bound else None


def _bounded_snapshot(value: Any) -> tuple[Any, int] | None:
    """Detach containers only while a conservative UTF-8 JSON bound fits.

    One code point needs at most six bytes (a JSON control escape). Count every
    occurrence, including shared children. Immutable scalars can be shared; no
    caller-owned container reaches the whole encoder. A loose overestimate
    returns None to select the original bounded incremental path.
    """
    root: list[Any] = [None]
    pending: list[tuple[Any, int, Any, Any]] = [(value, 0, root, 0)]
    size = 0
    count = 0
    while pending:
        item, depth, parent, key = pending.pop()
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, "projection_structure_bound")
        kind = type(item)
        if kind is dict:
            _require(len(item) <= MAX_NODES and count + len(pending) + len(item) <= MAX_NODES,
                     "projection_structure_bound")
            copied: Any = {}
            parent[key] = copied
            size += 2
            for name, child in item.items():
                _require(type(name) is str, "invalid_json_key")
                size += 6 * len(name) + 3 + bool(copied)  # Quoted key, colon, comma.
                if size > MAX_BYTES:
                    return None
                _require(count + len(pending) + 1 <= MAX_NODES, "projection_structure_bound")
                copied[name] = None
                pending.append((child, depth + 1, copied, name))
        elif kind is list:
            _require(len(item) <= MAX_NODES and count + len(pending) + len(item) <= MAX_NODES,
                     "projection_structure_bound")
            copied = []
            parent[key] = copied
            size += 2
            for child in item:
                size += bool(copied)
                if size > MAX_BYTES:
                    return None
                _require(count + len(pending) + 1 <= MAX_NODES, "projection_structure_bound")
                pending.append((child, depth + 1, copied, len(copied)))
                copied.append(None)
        elif kind is str:
            _require(len(item) <= MAX_BYTES, "projection_byte_bound")
            size += 6 * len(item) + 2
            parent[key] = item
        elif kind is int:
            _require(abs(item) <= MAX_INTEGER, "unsafe_json_integer")
            size += len(repr(item))
            parent[key] = item
        elif kind is float:
            _require(math.isfinite(item), "nonfinite_json_number")
            size += len(repr(item))
            parent[key] = item
        else:
            _require(item is None or kind is bool, "unsupported_json_value")
            size += 4 if item is None else 5  # null / true or false.
            parent[key] = item
        if size > MAX_BYTES:
            return None
    return root[0], size


def _canonical(value: Any) -> bytes:
    """Finite JSON, exact Python numeric types, no coercion of unsupported data."""
    try:
        _check_structure(value)
        encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        bounded = _bounded_snapshot(value)
        if bounded is not None:
            encoded = encoder.encode(bounded[0]).encode("utf-8")
            _require(len(encoded) <= MAX_BYTES, "projection_byte_bound")
            return encoded
        parts = []
        size = 0
        for part in encoder.iterencode(value):
            encoded = part.encode("utf-8")
            size += len(encoded)
            _require(size <= MAX_BYTES, "projection_byte_bound")
            parts.append(encoded)
        return b"".join(parts)
    except (UnicodeError, RecursionError, RuntimeError, TypeError):
        raise ProjectionError("invalid_json") from None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _canonical_private_decoded(value: Any) -> bytes:
    """Encode only the fresh tree owned by this decode, without a second copy."""
    try:
        bound = _check_structure(value, _with_bound=True)
        encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if bound is not None and bound <= MAX_BYTES:
            encoded = encoder.encode(value).encode("utf-8")
            _require(len(encoded) <= MAX_BYTES, "projection_byte_bound")
            return encoded
        parts = []
        size = 0
        for part in encoder.iterencode(value):
            encoded = part.encode("utf-8")
            size += len(encoded)
            _require(size <= MAX_BYTES, "projection_byte_bound")
            parts.append(encoded)
        return b"".join(parts)
    except (UnicodeError, RecursionError, RuntimeError, TypeError):
        raise ProjectionError("invalid_json") from None


def _decode_with_canonical(payload: bytes) -> tuple[Any, bytes]:
    """Return fresh parsed data and the bytes already checked on this decode."""
    _require(type(payload) is bytes and len(payload) <= MAX_BYTES, "invalid_payload_bytes")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs)
        return value, _canonical_private_decoded(value)
    except (ValueError, UnicodeError, RecursionError):
        raise ProjectionError("invalid_stored_json") from None


def _decode(payload: bytes) -> Any:
    return _decode_with_canonical(payload)[0]


class _ReaderDecoding:
    """A single connection/pass's bounded pure byte decoder, never a proof.

    Fresh SQL reads, sizes, digests, row relationships and all domain/currentness
    checks remain with their callers. Only parsing the SAME complete bytes and
    calculating their canonical encoding can be repeated without more work.
    """
    def __init__(self, connection):
        self.connection = connection
        self.thread = threading.get_ident()
        self.open = True
        self.entries: dict[bytes, tuple[Any, bytes]] = {}
        self.byte_count = 0
        self.implementation: tuple | None = None

    def close(self):
        self.open = False
        self.connection = None
        self.entries.clear()
        self.byte_count = 0


_READER_DECODING: ContextVar[_ReaderDecoding | None] = ContextVar(
    "projection_reader_decoding", default=None)


@contextmanager
def _reader_decoding_scope(connection):
    # Nested calls start empty too; no connection/operation can inherit a result.
    calculation = _ReaderDecoding(connection)
    token = _READER_DECODING.set(calculation)
    try:
        yield
    finally:
        calculation.close()
        _READER_DECODING.reset(token)


def _reader_decode_with_canonical(connection, payload):
    calculation = _READER_DECODING.get()
    limits = (MAX_BYTES, MAX_FIELDS, MAX_DEPTH, MAX_NODES, MAX_INTEGER)
    if (calculation is None or not calculation.open or calculation.connection is not connection
            or calculation.thread != threading.get_ident() or type(payload) is not bytes
            or not 4096 <= len(payload) <= 1_000_000 or not all(type(v) is int for v in limits)):
        return _decode_with_canonical(payload)
    implementation = (_decode_with_canonical, _canonical_private_decoded, _check_structure,
                      _pairs, _require, json.loads, json.JSONEncoder,
                      json.JSONEncoder.encode, json.JSONEncoder.iterencode, *limits)
    if calculation.implementation != implementation:
        calculation.entries.clear()
        calculation.byte_count = 0
        calculation.implementation = implementation
    if payload in calculation.entries:
        value, canonical = calculation.entries[payload]
        return deepcopy(value), canonical
    # Failures are never cached. This is the unchanged finite/duplicate-key/
    # canonical decoder, not a replacement for its acceptance conditions.
    value, canonical = _decode_with_canonical(payload)
    size = len(payload) + len(canonical)
    if len(calculation.entries) < 8 and calculation.byte_count + size <= 2_000_000:
        calculation.entries[payload] = deepcopy(value), canonical
        calculation.byte_count += size
    return value, canonical


def _snapshot(value: Any) -> tuple[bytes, dict[bytes, bytes]]:
    _require(type(value) is dict and len(value) <= MAX_FIELDS, "invalid_projection")
    encoded = _canonical(value)
    # Freeze before splitting; a caller cannot mutate half the retained version.
    detached = _decode(encoded)
    fields = {}
    for key, item in detached.items():
        name = _canonical(key)
        _require(len(name) <= 1024, "field_name_bound")
        fields[name] = _canonical(item)
    return encoded, fields


def _driver():
    try:
        import psycopg
        return psycopg
    except ImportError:
        raise ProjectionError("optional_postgres_driver_required") from None


@dataclass(frozen=True)
class ProjectionReceipt:
    namespace: str
    snapshot_id: str
    canonical_sha256: str
    byte_count: int
    field_count: int
    created_at: str


def _catalog(connection, schema: str = SCHEMA) -> str:
    """Fingerprint semantic catalog definitions, excluding OIDs/physical layout."""
    queries = (
        """SELECT n.nspname,pg_get_userbyid(n.nspowner),
           CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
           a.privilege_type,a.is_grantable FROM pg_namespace n
           CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a
           WHERE n.nspname=%s ORDER BY 1,2,3,4,5""",
        """SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner),c.relrowsecurity,c.relforcerowsecurity
           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname=%s ORDER BY c.relname""",
        """SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
           a.attidentity,a.attgenerated,co.collname,pg_get_expr(d.adbin,d.adrelid)
           FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
           JOIN pg_namespace n ON n.oid=c.relnamespace
           LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
           LEFT JOIN pg_collation co ON co.oid=a.attcollation
           WHERE n.nspname=%s AND a.attnum>0 AND NOT a.attisdropped
           ORDER BY c.relname,a.attnum""",
        """SELECT c.conname,c.contype,c.convalidated,pg_get_constraintdef(c.oid)
           FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
           WHERE n.nspname=%s ORDER BY c.conname""",
        """SELECT c.relname,pg_get_indexdef(c.oid),i.indisvalid,i.indisready
           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_index i ON i.indexrelid=c.oid
           WHERE n.nspname=%s ORDER BY c.relname""",
        """SELECT t.tgname,t.tgenabled,pg_get_triggerdef(t.oid)
           FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname=%s AND NOT t.tgisinternal ORDER BY t.tgname""",
        """SELECT p.proname,pg_get_functiondef(p.oid),p.prosecdef,p.proconfig
           FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname=%s ORDER BY p.proname""",
        """SELECT p.proname,pg_get_userbyid(p.proowner),
           CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
           a.privilege_type,a.is_grantable FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
           WHERE n.nspname=%s ORDER BY 1,2,3,4,5""",
        """WITH relations AS (SELECT c.* FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s)
           SELECT c.relname::text,CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
           a.privilege_type,a.is_grantable FROM relations c
           CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault(CASE WHEN c.relkind='S' THEN 'S'::"char" ELSE 'r'::"char" END,c.relowner))) a
           WHERE c.relkind IN ('r','S')
           UNION ALL
           SELECT c.relname||'.'||col.attname,CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
           a.privilege_type,a.is_grantable FROM relations c JOIN pg_attribute col ON col.attrelid=c.oid
           CROSS JOIN LATERAL aclexplode(col.attacl) a
           WHERE col.attnum>0 AND NOT col.attisdropped ORDER BY 1,2,3,4""",
    )
    # Queue every unchanged query before waiting for results. Pipeline exit
    # synchronizes (and raises SQL errors) on this same connection/transaction;
    # only a complete, ordered set of results may become a fingerprint.
    with connection.pipeline():
        cursors = [connection.execute(q, (schema,)) for q in queries]
    material = [cursor.fetchall() for cursor in cursors]
    return _sha(json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode())


class PostgresProjectionRepository:
    """Explicit Unix-socket local rehearsal. Hosted auth/cutover are separate."""

    _hosted_config: HostedStagingConfig

    def __init__(self, *, socket_directory: str | Path, database: str, user: str,
                 port: int = 5432, environment: str = "local"):
        _require(type(environment) is str and environment in {"local", "preview"}, "production_adapter_unavailable")
        _require(isinstance(socket_directory, (str, Path)), "explicit_local_socket_required")
        socket = Path(socket_directory)
        _require(socket.is_absolute() and socket.is_dir(), "explicit_local_socket_required")
        _require(type(port) is int and 1 <= port <= 65535, "invalid_port")
        self.socket_directory = str(socket)
        self.database, self.user = _identifier(database), _identifier(user)
        self.port, self.environment = port, environment

    @classmethod
    def for_hosted_staging(cls, config):
        """Explicit preview-only factory; normal construction stays Unix-only."""
        from src.storage.hosted_staging import HostedStagingConfig
        _require(cls is PostgresProjectionRepository and type(config) is HostedStagingConfig,
                 "explicit_staging_config_required")
        value = config.parameters()
        result = cls.__new__(cls)
        result.database, result.user = value["database"], value["role"]
        result.port, result.environment = 5432, "preview"
        result._hosted_config = config
        return result

    @contextmanager
    def _transaction(self, connection):
        with connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            connection.execute("SET LOCAL search_path=pg_catalog")
            connection.execute("SET LOCAL synchronous_commit=on")
            _require(170000 <= connection.info.server_version < 180000,
                     "unsupported_postgres_version")
            yield connection

    @contextmanager
    def _connection(self, *, writing=False):
        hosted = getattr(self, "_hosted_config", None)
        if hosted is not None:
            from src.storage.hosted_staging import connection as hosted_connection
            driver = _driver()
            try:
                with hosted_connection(hosted, driver) as connection:
                    with self._transaction(connection):
                        yield connection
            except driver.Error:
                raise ProjectionError("write_outcome_unknown" if writing else "storage_unavailable") from None
            return
        # libpq may otherwise pick up a service/host/password from the process.
        _require(not any(k.startswith("PG") for k in os.environ), "ambient_postgres_configuration_refused")
        _require(not (Path(self.socket_directory) / "password-file-disabled").exists(), "password_file_refused")
        driver = _driver()
        try:
            with driver.connect(host=self.socket_directory, port=self.port, dbname=self.database,
                                user=self.user, password="", passfile=str(Path(self.socket_directory) / "password-file-disabled"), connect_timeout=5,
                                application_name="theheat_projection_local", autocommit=True,
                                options="-c statement_timeout=30000 -c lock_timeout=10000 -c timezone=UTC") as connection:
                with self._transaction(connection):
                    yield connection
        except driver.Error:
            # A disconnect around COMMIT is ambiguous. Retry the same identity;
            # never return a receipt until the transaction context has exited.
            raise ProjectionError("write_outcome_unknown" if writing else "storage_unavailable") from None

    def _validate(self, connection, *, runtime: bool = True) -> None:
        row = connection.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
        _require(row is not None and row[0] == 1 and row[1] == _sha(MIGRATION.read_bytes()), "unsupported_projection_schema")
        _require(row[3] == self.environment, "projection_environment_mismatch")
        _require(row[2] == _catalog(connection), "changed_projection_schema")
        if runtime:
            role = connection.execute("""SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,
                pg_has_role(current_user,%s,'MEMBER'),
                pg_has_role(current_user,(SELECT datdba FROM pg_database WHERE datname=current_database()),'MEMBER'),
                EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user))
                FROM pg_roles WHERE rolname=current_user""", (row[4],)).fetchone()
            _require(role is not None and role[0] == row[5] and not any(role[1:]), "non_owner_runtime_role_required")

    def initialize(self, *, runtime_role: str) -> None:
        """Migration-owner only, explicitly provisioned role; never creates users."""
        runtime_role = _identifier(runtime_role)
        driver = _driver()
        with self._connection(writing=True) as connection:
            # Serializes empty-schema creation as well as existing migration checks.
            connection.execute("SELECT pg_advisory_xact_lock(724718,1101)")
            exists = connection.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone()
            if exists:
                self._validate(connection, runtime=False)
                stored = connection.execute(f"SELECT owner_role,runtime_role FROM {SCHEMA}.metadata").fetchone()
                _require(stored == (self.user, runtime_role), "migration_role_mismatch")
                return
            role = connection.execute("""SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,
                pg_has_role(%s,current_user,'MEMBER'),
                pg_has_role(%s,(SELECT datdba FROM pg_database WHERE datname=current_database()),'MEMBER'),
                EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
                FROM pg_roles WHERE rolname=%s""", (runtime_role, runtime_role, runtime_role)).fetchone()
            _require(role is not None and not any(role) and runtime_role != self.user, "invalid_runtime_role")
            connection.execute(MIGRATION.read_text())
            role_name = driver.sql.Identifier(runtime_role)
            # Owner default privileges may be broader than this archive allows.
            # Revoke them explicitly before establishing the fixed runtime role.
            connection.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM PUBLIC")
            connection.execute(driver.sql.SQL(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {{}}").format(role_name))
            connection.execute(driver.sql.SQL(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM {{}}").format(role_name))
            connection.execute(driver.sql.SQL(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}").format(role_name))
            connection.execute(driver.sql.SQL(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}").format(role_name))
            connection.execute(driver.sql.SQL(f"GRANT INSERT ON {SCHEMA}.artifacts,{SCHEMA}.versions,{SCHEMA}.fields TO {{}}").format(role_name))
            connection.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,current_user,%s)",
                               (_sha(MIGRATION.read_bytes()), _catalog(connection), self.environment, runtime_role))
            self._validate(connection, runtime=False)

    @staticmethod
    def _read(connection, namespace: str, snapshot_id: str) -> tuple[ProjectionReceipt, dict]:
        row = connection.execute(f"SELECT canonical_sha,byte_count,field_count,created_at FROM {SCHEMA}.versions WHERE namespace=%s AND snapshot_id=%s", (namespace, snapshot_id)).fetchone()
        _require(row is not None, "projection_not_found")
        sha, byte_count, field_count, created = row
        # Bound the complete transfer before fetching any potentially large values.
        # Repeated references count repeatedly in the reconstructed projection.
        refs = connection.execute(f"""SELECT f.name_json,f.artifact_sha,a.byte_count
            FROM {SCHEMA}.fields f LEFT JOIN {SCHEMA}.artifacts a ON a.sha=f.artifact_sha
            WHERE f.namespace=%s AND f.snapshot_id=%s LIMIT %s""", (namespace, snapshot_id, MAX_FIELDS + 1)).fetchall()
        _require(len(refs) == field_count <= MAX_FIELDS, "projection_reference_mismatch")
        _require(all(type(r[2]) is int and 1 <= r[2] <= MAX_BYTES for r in refs), "corrupt_projection_artifact")
        expected_size = 2 + sum(len(r[0]) + 1 + r[2] for r in refs) + max(0, len(refs) - 1)
        _require(expected_size == byte_count <= MAX_BYTES, "corrupt_projection_identity")
        sizes: dict[str, int] = {}
        for _, artifact_sha, artifact_size in refs:
            _require(artifact_sha not in sizes or sizes[artifact_sha] == artifact_size, "corrupt_projection_artifact")
            sizes[artifact_sha] = artifact_size
        payloads = {}
        if sizes:
            # Transfer each distinct artifact once, after the complete preflight.
            # Refuse changed lengths in SQL before transferring the value; a
            # corrupt restore must not turn one bounded read into a large batch.
            rows = connection.execute(f"""SELECT a.sha,
                CASE WHEN octet_length(a.payload)=wanted.byte_count THEN a.payload END
                FROM {SCHEMA}.artifacts a
                JOIN unnest(%s::text[],%s::integer[]) AS wanted(sha,byte_count) ON a.sha=wanted.sha
                LIMIT %s""", (list(sizes), list(sizes.values()), len(sizes) + 1)).fetchall()
            _require(len(rows) == len(sizes), "corrupt_projection_artifact")
            for row in rows:
                _require(isinstance(row, (tuple, list)) and len(row) == 2, "corrupt_projection_artifact")
                artifact_sha, payload = row
                _require(type(artifact_sha) is str and artifact_sha in sizes and artifact_sha not in payloads,
                         "corrupt_projection_artifact")
                _require(type(payload) is bytes and len(payload) == sizes[artifact_sha]
                         and _sha(payload) == artifact_sha, "corrupt_projection_artifact")
                payloads[artifact_sha] = payload
        restored = {}
        for name_bytes, artifact_sha, artifact_size in refs:
            payload = payloads[artifact_sha]
            name, canonical_name = _reader_decode_with_canonical(connection, name_bytes)
            _require(type(name) is str and name not in restored and canonical_name == name_bytes, "corrupt_projection_field")
            value, canonical_value = _reader_decode_with_canonical(connection, payload)
            _require(canonical_value == payload, "noncanonical_projection_artifact")
            restored[name] = value
        encoded = _canonical(restored)
        _require(len(encoded) == byte_count and _sha(encoded) == sha, "corrupt_projection_identity")
        return ProjectionReceipt(namespace, snapshot_id, sha, byte_count, field_count, created.isoformat()), restored

    def read(self, namespace: str, snapshot_id: str) -> tuple[ProjectionReceipt, dict]:
        namespace, snapshot_id = _identifier(namespace), _identifier(snapshot_id)
        with self._connection() as connection:
            self._validate(connection)
            result = self._read(connection, namespace, snapshot_id)
        return result

    def record(self, namespace: str, snapshot_id: str, value: dict) -> ProjectionReceipt:
        """Idempotent immutable version, acknowledged only after commit."""
        namespace, snapshot_id = _identifier(namespace), _identifier(snapshot_id)
        encoded, fields = _snapshot(value)
        with self._connection(writing=True) as connection:
            self._validate(connection)
            receipt = self._record(connection, namespace, snapshot_id, encoded, fields)
        return receipt

    @classmethod
    def _record(cls, connection, namespace: str, snapshot_id: str, encoded: bytes,
                fields: dict[bytes, bytes]) -> ProjectionReceipt:
        """Compose only inside a validated caller-owned transaction.

        Private callers must use _snapshot and the connection/schema/role guards.
        This provisional receipt must not escape before the outer commit succeeds.
        """
        digest = _sha(encoded)
        inserted = connection.execute(f"""INSERT INTO {SCHEMA}.versions
            (namespace,snapshot_id,canonical_sha,byte_count,field_count) VALUES(%s,%s,%s,%s,%s)
            ON CONFLICT(namespace,snapshot_id) DO NOTHING RETURNING snapshot_id""",
            (namespace, snapshot_id, digest, len(encoded), len(fields))).fetchone()
        if inserted:
            # Sorting shared artifact keys also avoids inverse lock ordering
            # when concurrent, different versions reuse overlapping fields.
            for payload in sorted(set(fields.values()), key=_sha):
                artifact_sha = _sha(payload)
                connection.execute(f"INSERT INTO {SCHEMA}.artifacts VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (artifact_sha, payload, len(payload)))
                actual = connection.execute(f"SELECT payload,byte_count FROM {SCHEMA}.artifacts WHERE sha=%s", (artifact_sha,)).fetchone()
                _require(actual == (payload, len(payload)), "corrupt_projection_artifact")
            for name, payload in fields.items():
                connection.execute(f"INSERT INTO {SCHEMA}.fields VALUES(%s,%s,%s,%s)", (namespace, snapshot_id, name, _sha(payload)))
        receipt, _ = cls._read(connection, namespace, snapshot_id)
        _require(receipt.canonical_sha256 == digest, "projection_idempotency_conflict")
        return receipt
