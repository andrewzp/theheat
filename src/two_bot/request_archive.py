"""Explicit private evidence of synchronous model requests; default OFF.

An operator opens one capture scope, for one local rehearsal, with an explicit
absolute owner-only directory. While that scope is open in its owning thread,
the existing ``trial_budget.provider_call`` seam durably records each logical
request BEFORE execution and the actual serialized SDK body at the physical
send boundary, plus the decoded returned HTTP entity where the transport
exposes it. Records are append-only, hash-chained and bounded; artifacts are
content-addressed exact bytes.

This is mechanical evidence of what was sent and returned. It is never a
factual, editorial, approval, billing, invoice or completeness authority, and a
caller label never certifies anything. Missing inputs stay missing and unknown
cost stays unknown. Nothing here writes Gist, ordinary state, suppression rows,
public logs or saved drafts; errors carry fixed codes only, never bodies.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import stat
import threading
from typing import Any, Iterator

SCHEMA = "theheat.request-archive/v1"
# v2 is opted into explicitly per scope (``capture(..., routes=True)``). It adds
# only the closed route-family records below; a default scope stays v1 exactly.
SCHEMA_V2 = "theheat.request-archive/v2"
MIB = 1024 * 1024
MAX_LOGICAL_REQUEST_BYTES = 2 * MIB
MAX_WIRE_REQUEST_BYTES = 2 * MIB
MAX_RESPONSE_BYTES = 2 * MIB
MAX_RECORD_BYTES = 64 * 1024
MAX_CALLS = 128
MAX_WIRE_ATTEMPTS = 128
MAX_SCOPE_CONTENT_BYTES = 32 * MIB
MAX_LABEL_CHARS = 200

MANIFEST = "manifest.jsonl"
ARTIFACTS = "artifacts"
GENESIS = "0" * 64
_ROOT = Path(__file__).resolve().parents[2]
# Local provenance only: hashes of the named running sources at scope entry.
CODE_IDENTITY_FILES = (
    "src/two_bot/pipeline.py", "src/two_bot/writer.py", "src/two_bot/fact_check.py",
    "src/two_bot/critic.py", "src/voice/safety.py", "src/two_bot/memory.py",
    "src/two_bot/bundle_capture.py", "src/two_bot/retry.py", "src/two_bot/json_utils.py",
    "src/two_bot/source_links.py", "src/two_bot/strict_contract.py", "src/two_bot/trial_budget.py",
    "src/two_bot/request_archive.py", "src/two_bot/prompts/writer_prompt.py",
    "src/data/newsworthiness.py",
    "src/two_bot/prompts/fact_check_prompt.py", "src/two_bot/prompts/critic_prompt.py",
)
# Additional running sources observed only by route-family (v2) scopes.
ROUTE_CODE_IDENTITY_FILES = (
    "src/two_bot/batch_transport.py", "src/two_bot/batch_collector.py", "src/two_bot/check_transport.py",
    "src/two_bot/check_executor.py", "src/two_bot/provider_http.py",
)
SDK_DISTRIBUTIONS = ("anthropic", "google-genai", "httpx", "httpx2", "pydantic")
PROVIDER_HOSTS = {"anthropic": "api.anthropic.com", "google": "generativelanguage.googleapis.com"}
_PATHS = {"anthropic": re.compile(r"\A/v1/messages\Z"),
          "google": re.compile(r"\A/v1(?:beta|alpha)?/models/[A-Za-z0-9._-]{1,128}:generateContent\Z")}
_RESPONSE_HEADERS = ("content-type", "content-encoding", "content-length", "request-id", "x-request-id")
_BATCH_ID = r"msgbatch_[A-Za-z0-9_-]{1,128}"
# Closed operation families: provider, method, exact canonical path and the
# entity form each transport's EXISTING bounded reader exposes.
ROUTES = {
    "batch_submit": ("anthropic", "POST", re.compile(r"\A/v1/messages/batches\Z"), "decoded_http_entity"),
    "batch_metadata": ("anthropic", "GET", re.compile(rf"\A/v1/messages/batches/{_BATCH_ID}\Z"),
                       "decoded_http_entity"),
    "batch_results": ("anthropic", "GET", re.compile(rf"\A/v1/messages/batches/{_BATCH_ID}/results\Z"),
                      "decoded_http_entity"),
    "command_check": ("google", "POST", re.compile(r"\A/v1beta/models/[A-Za-z0-9._-]{1,160}:generateContent\Z"),
                      "raw_http_entity_identity"),
}
ROUTE_BINDING_SOURCES = frozenset({
    "batch_registration", "validated_plan", "batch_begin_result", "batch_results_status",
    "verified_current_context", "check_lease", "check_grant", "check_packet", "invoking_request", "missing"})
# Fixed transport diagnostics only; never an exception body or provider text.
ROUTE_REASONS = frozenset({
    "received", "batch_ack_read_bound_exceeded", "batch_submit_response_unavailable",
    "batch_read_size_exceeded", "batch_read_time_exceeded", "batch_read_unavailable", "batch_read_cleanup_failed",
    "size_exceeded", "time_exceeded", "transport_unavailable", "cleanup_failed"})
ROUTE_OUTCOMES = frozenset({"returned", "raised", "refused_before_send", "not_dispatched", "blocked"})
# Why a SENT route's retained entity is not complete evidence; None means complete.
ROUTE_EVIDENCE_GAPS = frozenset({"entity_not_recorded", "entity_not_observed", "entity_not_retained",
                                 "entity_bounded_prefix", "results_final_line_unparseable"})
_BATCH_ID_FULL = re.compile(rf"\A{_BATCH_ID}\Z")
_SAFE_ID = re.compile(r"\A[A-Za-z0-9_.:-]{1,200}\Z")
_LABEL = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,199}\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class RequestArchiveError(RuntimeError):
    """Fixed reason code only; never a body, path, key or exception repr."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RequestArchiveRefused(RequestArchiveError):
    """Capture refused before any physical send for this attempt."""


class RequestArchiveHeld(RequestArchiveError):
    """Archival failed after a possible purchase; the whole scope stays held."""


# ---------------------------------------------------------------- private I/O

def canonical_json(value: Any) -> bytes:
    """Exact bytes for manifest records: sorted keys, no floats, strict UTF-8."""
    _require_record_types(value, 0)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _require_record_types(value: Any, depth: int) -> None:
    if depth > 32:
        raise ValueError("record_too_deep")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        value.encode("utf-8")
        return
    if type(value) is list:
        for child in value:
            _require_record_types(child, depth + 1)
        return
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("record_key_type")
            key.encode("utf-8")
            _require_record_types(child, depth + 1)
        return
    raise ValueError("record_value_type")


def _reject_constant(value: str) -> Any:
    raise ValueError("nonfinite_number")


def _reject_float(value: str) -> Any:
    raise ValueError("float_not_allowed")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def strict_json_loads(data: bytes, *, allow_floats: bool = False) -> Any:
    """Parse strict UTF-8 JSON: no duplicate keys, NaN/Infinity or (by default) floats."""
    if not isinstance(data, bytes):
        raise ValueError("bytes_required")
    text = data.decode("utf-8")
    return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant,
                      parse_float=None if allow_floats else _reject_float)


def require_private_directory(path: str | os.PathLike, *, create: bool) -> Path:
    """Return an explicit absolute canonical owner-only (0700) directory.

    No environment/home discovery, relative paths, ``.``/``..`` components or
    symlinked components. A missing directory is created only when ``create``.
    """
    raw = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
    if not isinstance(raw, str) or not raw or "\x00" in raw or not os.path.isabs(raw):
        raise RequestArchiveRefused("private_path_not_absolute")
    if any(part in (".", "..") for part in raw.split(os.sep)) or raw != os.path.normpath(raw):
        raise RequestArchiveRefused("private_path_not_normalized")
    if os.path.realpath(raw) != raw:
        raise RequestArchiveRefused("private_path_not_canonical")
    parent = _open_directory_chain(os.path.dirname(raw))
    try:
        try:
            fd = os.open(os.path.basename(raw), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                         dir_fd=parent)
        except FileNotFoundError:
            if not create:
                raise RequestArchiveRefused("private_directory_missing") from None
            os.mkdir(os.path.basename(raw), 0o700, dir_fd=parent)
            fd = os.open(os.path.basename(raw), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                         dir_fd=parent)
            os.fchmod(fd, 0o700)
            os.fsync(parent)
        except NotADirectoryError:
            raise RequestArchiveRefused("private_path_not_directory") from None
        try:
            _require_directory_fd(fd)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    return Path(raw)


def _open_directory_chain(path: str | os.PathLike) -> int:
    """Pin each absolute directory component without following any symlink."""
    raw = os.fspath(path)
    if not os.path.isabs(raw) or raw != os.path.normpath(raw):
        raise RequestArchiveRefused("private_path_not_normalized")
    fd = os.open("/", os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC)
    try:
        for part in Path(raw).parts[1:]:
            child = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _require_directory_fd(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RequestArchiveRefused("private_directory_not_owned")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise RequestArchiveRefused("private_directory_not_owner_only")


def _fsync_directory(path: str | os.PathLike) -> None:
    fd = _open_directory_chain(path)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    """Every archive byte goes through here, so tests can inject real-path failures."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def read_private_file(path: str | os.PathLike, limit: int) -> bytes:
    """Read one regular owner-only (0600) file without following a symlink."""
    target = Path(path)
    parent = _open_directory_chain(target.parent)
    try:
        fd = os.open(target.name, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)
    return _read_private_fd(fd, limit)


def _read_private_fd(fd: int, limit: int) -> bytes:
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RequestArchiveRefused("private_file_not_regular")
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise RequestArchiveRefused("private_file_not_owner_only")
        if info.st_size > limit:
            raise RequestArchiveRefused("private_file_over_limit")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(1 << 20, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise RequestArchiveRefused("private_file_over_limit")
        return b"".join(chunks)
    finally:
        os.close(fd)


def write_private_file_exclusive(directory: Path, name: str, data: bytes, *, directory_fd: int | None = None) -> bool:
    """Atomically publish exact bytes once (0600); never replace other bytes.

    Returns False when identical bytes already exist (an idempotent retry) and
    refuses a conflicting existing file. A crash leaves at most a ``.tmp-``
    file, which readers report and never adopt; nothing is deleted later.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name) or name.startswith(".tmp-"):
        raise RequestArchiveRefused("private_file_name_invalid")
    parent = _open_directory_chain(directory) if directory_fd is None else os.dup(directory_fd)
    try:
        _require_directory_fd(parent)
        temporary = f".tmp-{secrets.token_hex(12)}"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC,
                     0o600, dir_fd=parent)
        try:
            os.fchmod(fd, 0o600)
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            try:
                os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            except FileExistsError:
                try:
                    existing = _read_private_fd(os.open(name, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC,
                                                       dir_fd=parent), len(data))
                except RequestArchiveRefused as exc:
                    if exc.code == "private_file_over_limit":
                        raise RequestArchiveRefused("private_file_conflict") from None
                    raise
                if existing != data:
                    raise RequestArchiveRefused("private_file_conflict") from None
                return False
        finally:
            os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)
        return True
    finally:
        os.close(parent)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------ logical request

class _Unrepresentable(ValueError):
    pass


def _logical_value(value: Any, depth: int = 0) -> Any:
    """A detached, type-tagged view of SDK kwargs. Not the bytes that were sent."""
    if depth > 64:
        raise _Unrepresentable("depth")
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is str:
        value.encode("utf-8")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _Unrepresentable("nonfinite_float")
        return {"$tagged": "float", "value": repr(value)}
    if type(value) is dict:
        if not all(type(key) is str for key in value):
            raise _Unrepresentable("dict_key_type")
        if any(key.startswith("$") for key in value):
            return {"$tagged": "dict", "value": [[key, _logical_value(child, depth + 1)]
                                                 for key, child in value.items()]}
        return {key: _logical_value(child, depth + 1) for key, child in value.items()}
    if type(value) is list:
        return [_logical_value(child, depth + 1) for child in value]
    if type(value) is tuple:
        return {"$tagged": "tuple", "value": [_logical_value(child, depth + 1) for child in value]}
    if type(value) is bytes:
        return {"$tagged": "bytes", "value": base64.b64encode(value).decode("ascii")}
    dump = getattr(type(value), "model_dump", None)
    module = getattr(type(value), "__module__", "")
    if callable(dump) and module.split(".")[0] in {"google", "anthropic", "pydantic"}:
        try:
            dumped = value.model_dump(mode="json", exclude_unset=True)
        except Exception as exc:
            raise _Unrepresentable("model_dump_failed") from exc
        return {"$tagged": "model", "class": f"{module}.{type(value).__qualname__}",
                "value": _logical_value(dumped, depth + 1)}
    raise _Unrepresentable("unsupported_type")


def logical_request_bytes(request: dict) -> tuple[bytes | None, str | None]:
    try:
        tree = {"kwargs": _logical_value(request)}
        return json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8"), None
    except _Unrepresentable as exc:
        return None, f"unrepresentable_{exc}"
    except (TypeError, ValueError, UnicodeError):
        return None, "unrepresentable_value"


def _require_body_only_options(provider: str, request: dict) -> None:
    """Transport overrides are outside the supported logical-body contract.

    Refuse before serialization: never retain, redact or label their values as
    model input. Client-level auth remains outside the request-body observation.
    """
    if any(name in request for name in ("extra_headers", "extra_query", "extra_body", "timeout",
                                         "request_options", "http_options")):
        raise RequestArchiveRefused("archive_transport_override_unsupported")
    if provider == "google":
        config = request.get("config")
        has_options = (any(config.get(key) is not None for key in ("http_options", "httpOptions"))
                       if isinstance(config, dict) else getattr(config, "http_options", None) is not None)
        if has_options:
            raise RequestArchiveRefused("archive_transport_override_unsupported")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_hashes(files: tuple[str, ...] = CODE_IDENTITY_FILES) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for relative in files:
        try:
            hashes[relative] = sha256_hex((_ROOT / relative).read_bytes())
        except OSError:
            hashes[relative] = None
    return hashes


def _sdk_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in SDK_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _policy_identity() -> str | None:
    try:
        from src.editorial.policy import current_editorial_policy
        from src.editorial.revisions import fingerprint
        policy = current_editorial_policy()
        return None if policy is None else fingerprint(policy)
    except Exception:
        return None


# ------------------------------------------------------------------- scopes

_ACTIVE: ContextVar[RequestArchiveScope | None] = ContextVar("theheat_request_archive", default=None)
_OPEN_LOCK = threading.Lock()
_OPEN_SCOPE: RequestArchiveScope | None = None


def active_scope() -> RequestArchiveScope | None:
    """The default inactive path returns None without touching anything.

    While a scope is open, only its owning context/thread may call providers;
    any other caller is refused before dispatch rather than silently uncaptured.
    """
    opened = _OPEN_SCOPE
    if opened is None:
        return None
    scope = _ACTIVE.get()
    if scope is not opened or scope._owner != threading.get_ident() or scope._closed:
        opened._note_foreign_refusal()
        raise RequestArchiveRefused("archive_foreign_context")
    return scope


def _bound_scope() -> RequestArchiveScope | None:
    opened = _OPEN_SCOPE
    if opened is None:
        return None
    scope = _ACTIVE.get()
    if scope is not opened or scope._owner != threading.get_ident() or scope._closed:
        return None
    return scope


@contextmanager
def capture(root: str | os.PathLike, *, operation: str, routes: bool = False) -> Iterator[RequestArchiveScope]:
    """Open one explicit private capture scope for the current thread only.

    ``root`` must already be (or be creatable as) an absolute canonical 0700
    directory selected by the operator. ``operation`` is a bounded caller label
    retained verbatim; it certifies nothing. Nested, concurrent, foreign and
    reused scopes are refused. The context resets on every exit path.

    ``routes=True`` opens a v2 scope that may also observe the closed batch and
    command-check route families. It never enables a disabled lane or sends.
    """
    global _OPEN_SCOPE
    if type(operation) is not str or not _LABEL.fullmatch(operation):
        raise RequestArchiveRefused("archive_operation_label_invalid")
    if type(routes) is not bool:
        raise RequestArchiveRefused("archive_routes_flag_invalid")
    if _ACTIVE.get() is not None:
        raise RequestArchiveRefused("archive_nested_scope")
    try:
        directory = require_private_directory(root, create=True)
    except OSError:
        raise RequestArchiveRefused("private_directory_unavailable") from None
    with _OPEN_LOCK:
        if _OPEN_SCOPE is not None:
            raise RequestArchiveRefused("archive_scope_already_open")
        try:
            scope = RequestArchiveScope(directory, operation, routes=routes)
        except RequestArchiveError:
            raise
        except Exception:
            raise RequestArchiveRefused("archive_open_failed") from None
        _OPEN_SCOPE = scope
    token = _ACTIVE.set(scope)
    exit_kind, exception_type = "normal", None
    try:
        yield scope
    except BaseException as exc:
        exit_kind, exception_type = "exception", type(exc).__qualname__
        raise
    finally:
        try:
            scope._close(exit_kind, exception_type)
        finally:
            _ACTIVE.reset(token)
            with _OPEN_LOCK:
                _OPEN_SCOPE = None


class RequestArchiveScope:
    """One private, append-only capture for one owning thread."""

    def __init__(self, root: Path, operation: str, *, routes: bool = False):
        self._lock = threading.RLock()
        self._routes_enabled = routes
        self._schema = SCHEMA_V2 if routes else SCHEMA
        self._route: _RouteRecorder | None = None
        self._route_count = 0
        self._route_attempts = 0
        self._route_hook: Any = None
        self._route_clients: list = []
        self._owner = threading.get_ident()
        self._closed = False
        self._held: str | None = None
        self._calls = 0
        self._attempts = 0
        self._retained = 0
        self._records = 0
        self._prev = GENESIS
        self._artifacts: set[str] = set()
        self._current: _CallRecorder | None = None
        self._binding: dict[str, Any] = {}
        self._drift_reported: set[str] = set()
        self._foreign_refusals = 0
        self._request_hooks: list = []
        self._response_hooks: list = []
        self.scope_id = "scope-" + secrets.token_hex(16)
        self.directory = root / self.scope_id
        try:
            root_fd = _open_directory_chain(root)
            try:
                _require_directory_fd(root_fd)
                os.mkdir(self.scope_id, 0o700, dir_fd=root_fd)
                self._directory_fd = os.open(self.scope_id, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                                             dir_fd=root_fd)
                os.fchmod(self._directory_fd, 0o700)
                os.mkdir(ARTIFACTS, 0o700, dir_fd=self._directory_fd)
                self._artifacts_fd = os.open(ARTIFACTS, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                                             dir_fd=self._directory_fd)
                os.fchmod(self._artifacts_fd, 0o700)
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
            self._manifest = os.open(MANIFEST, os.O_WRONLY | os.O_APPEND | os.O_CREAT
                                     | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC, 0o600, dir_fd=self._directory_fd)
            os.fchmod(self._manifest, 0o600)
            os.fsync(self._directory_fd)
            self._code = _file_hashes(CODE_IDENTITY_FILES + (ROUTE_CODE_IDENTITY_FILES if routes else ()))
            opened = {
                "scope_id": self.scope_id,
                "operation": {"label": operation, "authority": "caller_label_only"},
                "limits": {"logical_request_bytes": MAX_LOGICAL_REQUEST_BYTES,
                           "wire_request_bytes": MAX_WIRE_REQUEST_BYTES,
                           "response_bytes": MAX_RESPONSE_BYTES, "record_bytes": MAX_RECORD_BYTES,
                           "calls": MAX_CALLS, "wire_attempts": MAX_WIRE_ATTEMPTS,
                           "scope_content_bytes": MAX_SCOPE_CONTENT_BYTES},
                "code_identity": {"files": self._code, "editorial_policy_sha256": _policy_identity(),
                                  "sdk_versions": _sdk_versions(),
                                  "python": platform.python_version(),
                                  "authority": "local_provenance_only"},
            }
            if routes:
                opened["route_families"] = sorted(ROUTES)
            self._record("scope_opened", opened)
        except BaseException:
            for name in ("_manifest", "_artifacts_fd", "_directory_fd"):
                fd = getattr(self, name, None)
                if type(fd) is int:
                    os.close(fd)
            raise

    # -------------------------------------------------------------- storage
    @property
    def held(self) -> str | None:
        return self._held

    def _hold(self, code: str) -> None:
        with self._lock:
            if self._held is None:
                self._held = code
                try:
                    self._record("scope_held", {"reason": code})
                except Exception:
                    pass  # The in-memory hold remains authoritative for this process.

    def _record(self, kind: str, data: dict) -> None:
        with self._lock:
            line = canonical_json({"schema": self._schema, "seq": self._records + 1, "prev": self._prev,
                                   "type": kind, "at": _now(), "data": data})
            if len(line) + 1 > MAX_RECORD_BYTES:
                raise RequestArchiveError("archive_record_limit")
            _write_all(self._manifest, line + b"\n")
            os.fsync(self._manifest)
            self._records += 1
            self._prev = sha256_hex(line)

    def _artifact(self, data: bytes) -> str:
        with self._lock:
            digest = sha256_hex(data)
            if digest in self._artifacts:
                return digest
            if self._retained + len(data) > MAX_SCOPE_CONTENT_BYTES:
                raise RequestArchiveError("archive_scope_content_limit")
            write_private_file_exclusive(self.directory / ARTIFACTS, digest, data, directory_fd=self._artifacts_fd)
            self._artifacts.add(digest)
            self._retained += len(data)
            return digest

    def _require_usable(self) -> None:
        if self._closed:
            raise RequestArchiveRefused("archive_scope_closed")
        if threading.get_ident() != self._owner:
            raise RequestArchiveRefused("archive_foreign_context")
        if self._held is not None:
            raise RequestArchiveRefused("archive_scope_held")

    def _note_foreign_refusal(self) -> None:
        with self._lock:
            self._foreign_refusals += 1
            if self._closed or self._held is not None:
                return
            try:
                self._record("foreign_call_refused", {"count": self._foreign_refusals})
            except Exception:
                self._held = "archive_write_failed"

    def _check_drift(self) -> None:
        current = _file_hashes(tuple(self._code))
        for path, before in self._code.items():
            after = current.get(path)
            if after != before and path not in self._drift_reported:
                self._drift_reported.add(path)
                self._record("code_drift_observed", {"path": path, "at_entry": before, "observed": after})

    def _close(self, exit_kind: str, exception_type: str | None) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if self._current is not None or self._route is not None:
                    self._hold("archive_call_left_open")
                self._check_drift()
                closed = {
                    "exit": exit_kind, "exception_type": exception_type, "calls": self._calls,
                    "wire_attempts": self._attempts - self._route_attempts, "retained_content_bytes": self._retained,
                    "artifacts": len(self._artifacts), "held": self._held,
                    "foreign_refusals": self._foreign_refusals}
                if self._routes_enabled:
                    closed.update(routes=self._route_count, route_wire_attempts=self._route_attempts)
                self._record("scope_closed", closed)
            except Exception:
                self._held = self._held or "archive_close_failed"
            finally:
                self._closed = True
                os.close(self._manifest)
                os.close(self._artifacts_fd)
                os.close(self._directory_fd)

    # ------------------------------------------------- pipeline bindings
    def _note(self, kind: str, build) -> None:
        with self._lock:
            if self._closed or self._held is not None:
                return
            try:
                self._record(kind, build())
            except Exception:
                self._hold("archive_write_failed")

    def _binding_snapshot(self) -> dict:
        keys = ("event_id", "bundle_sha256", "memory_sha256", "candidate_text_sha256",
                "candidate_attempt", "phase", "revises_candidate_text_sha256")
        return {key: self._binding.get(key) for key in keys}

    def run_generation(self, bundle, state, **kwargs) -> tuple[dict | None, dict]:
        """Run the actual pipeline and retain its actual terminal association."""
        with self._lock:
            self._require_usable()
        from src.two_bot import pipeline
        result_out: dict = {}
        draft = pipeline.generate_draft(bundle, state, result_out=result_out, **kwargs)
        with self._lock:
            if self._held is not None or self._closed:
                raise RequestArchiveHeld(self._held or "archive_scope_closed")
            try:
                self._record_terminal(bundle, draft, result_out)
            except Exception:
                self._hold("archive_write_failed")
                raise RequestArchiveHeld("archive_write_failed") from None
        return draft, result_out

    def _record_terminal(self, bundle, draft: dict | None, result_out: dict) -> None:
        from src.editorial.revisions import text_hash
        metadata = (draft or {}).get("two_bot_metadata") or {}
        reason = result_out.get("kill_reason")
        draft_artifact = None
        if draft is not None:
            draft_artifact = self._artifact(json.dumps(draft, ensure_ascii=False, sort_keys=True,
                                                       default=str, allow_nan=False).encode("utf-8"))
        outcomes = result_out.get("stage_outcomes")
        self._record("terminal", {
            "origin": "generate_draft_return", "event_id": str(bundle.event_id),
            "accepted": draft is not None,
            "draft_artifact": draft_artifact,
            "draft_text_sha256": text_hash(draft["text"]) if draft is not None else None,
            "reviewed_text_sha256": metadata.get("reviewed_text_sha256"),
            "reviewed_bundle_sha256": metadata.get("reviewed_bundle_sha256"),
            "reviewed_policy_sha256": metadata.get("reviewed_policy_sha256"),
            "kill_stage": result_out.get("kill_stage") if draft is None else None,
            "kill_reason_artifact": (self._artifact(reason.encode("utf-8"))
                                     if draft is None and isinstance(reason, str) else None),
            "stage_outcomes": ({str(k): str(v) for k, v in outcomes.items()}
                               if isinstance(outcomes, dict) else None),
            "approval": "none", "publication": "none"})

    # --------------------------------------------------------- calls
    def begin_call(self, stage: str, provider: str, request: dict) -> _CallRecorder:
        """Durably record logical intent BEFORE execution, or refuse the call."""
        with self._lock:
            self._require_usable()
            if self._current is not None or self._route is not None:
                raise RequestArchiveRefused("archive_call_already_open")
            if self._calls >= MAX_CALLS:
                self._try_record_refusal(None, "archive_call_limit")
                raise RequestArchiveRefused("archive_call_limit")
            if provider not in PROVIDER_HOSTS or type(stage) is not str or not _LABEL.fullmatch(stage):
                raise RequestArchiveRefused("archive_unsupported_provider")
            if not isinstance(request, dict) or request.get("stream"):
                self._try_record_refusal(None, "archive_streaming_unsupported")
                raise RequestArchiveRefused("archive_streaming_unsupported")
            _require_body_only_options(provider, request)
            logical, unavailable = logical_request_bytes(request)
            if logical is not None and len(logical) > MAX_LOGICAL_REQUEST_BYTES:
                self._try_record_refusal(None, "archive_logical_request_limit")
                raise RequestArchiveRefused("archive_logical_request_limit")
            number = self._calls + 1
            try:
                self._check_drift()
                artifact = self._artifact(logical) if logical is not None else None
                model = request.get("model")
                self._record("call_intent", {
                    "call": number, "stage": stage, "provider": provider,
                    "model": model if isinstance(model, str) else None,
                    "binding": self._binding_snapshot(),
                    "logical_request": ({"availability": "captured", "artifact": artifact,
                                         "bytes": len(logical), "form": "tagged_kwargs_json_v1"}
                                        if logical is not None else
                                        {"availability": "unavailable", "reason": unavailable}),
                    "recorded_before_execution": True})
            except RequestArchiveError as exc:
                if exc.code == "archive_scope_content_limit":
                    # Capacity is checked before any byte is written: refuse, do not hold.
                    self._try_record_refusal(None, exc.code)
                else:
                    self._hold(exc.code)
                raise RequestArchiveRefused(exc.code) from None
            except Exception:
                self._hold("archive_write_failed_before_dispatch")
                raise RequestArchiveRefused("archive_write_failed_before_dispatch") from None
            self._calls = number
            self._current = _CallRecorder(self, number, stage, provider)
            return self._current

    def _try_record_refusal(self, call: int | None, code: str) -> None:
        try:
            self._record("call_refused", {"call": call, "reason": code, "before_dispatch": True})
        except Exception:
            self._hold("archive_write_failed")

    def wire_hooks(self, provider: str) -> dict[str, list]:
        """Event hooks for the SDK's own HTTP client family (httpx2 or httpx)."""
        def request_hook(request):
            self._on_wire_request(provider, request)

        def response_hook(response):
            self._on_wire_response(provider, response)
        self._request_hooks.append(request_hook)
        self._response_hooks.append(response_hook)
        return {"request": [request_hook], "response": [response_hook]}

    def require_supported_sender(self, provider: str, send) -> None:
        """Only the pinned synchronous SDK method with this scope's hooks sends.

        Arbitrary callables, earlier clients, streaming, async and replaced
        transports are refused before execution. Offline stand-ins are installed
        explicitly by tests; there is no production no-hook exception.
        """
        transport: Any = None
        if inspect.ismethod(send):
            if provider == "anthropic":
                from anthropic.resources.messages import Messages
                if type(send.__self__) is Messages and send.__func__ is Messages.create:
                    transport = send.__self__._client._client
            elif provider == "google":
                from google.genai.models import Models
                if type(send.__self__) is Models and send.__func__ is Models.generate_content:
                    transport = send.__self__._api_client._httpx_client
        hooks = getattr(transport, "event_hooks", {})
        if not (any(h is expected for h in hooks.get("request", []) for expected in self._request_hooks)
                and any(h is expected for h in hooks.get("response", []) for expected in self._response_hooks)):
            self._try_record_refusal(None, "archive_unobserved_transport")
            raise RequestArchiveRefused("archive_unobserved_transport")

    def _on_wire_request(self, provider: str, request) -> None:
        with self._lock:
            call = self._current
            if call is None or call.provider != provider or self._closed or threading.get_ident() != self._owner:
                self._hold("archive_unbound_wire_request")
                raise RequestArchiveRefused("archive_unbound_wire_request")
            code = self._held or self._unsupported_endpoint(provider, request)
            body = None
            if code is None:
                try:
                    body = request.read()  # Already-built SDK entity; redirects re-read it.
                except Exception:
                    code = "archive_unreadable_request_body"
            if code is None and (not isinstance(body, bytes) or len(body) > MAX_WIRE_REQUEST_BYTES):
                code = "archive_wire_request_limit"
            if code is None and self._attempts >= MAX_WIRE_ATTEMPTS:
                code = "archive_wire_attempt_limit"
            if code is not None:
                call.refusal = code
                if call.attempts:
                    self._hold(code)  # A later redirect/retry after a real send.
                raise RequestArchiveRefused(code)
            assert isinstance(body, bytes)
            url = request.url
            try:
                artifact = self._artifact(body)
                self._record("wire_request", {
                    "call": call.number, "attempt": call.attempts + 1,
                    "transport_family": type(request).__module__.split(".")[0],
                    "method": str(request.method), "scheme": str(url.scheme), "host": str(url.host),
                    "path": str(url.path), "query_present": bool(url.query),
                    "content_type": request.headers.get("content-type"),
                    "body": {"availability": "captured", "artifact": artifact, "bytes": len(body),
                             "form": "exact_request_entity"},
                    "recorded_before_send": True})
            except Exception as exc:
                code = exc.code if isinstance(exc, RequestArchiveError) else "archive_write_failed_before_dispatch"
                call.refusal = code
                self._hold(code)
                raise RequestArchiveRefused(code) from None
            call.attempts += 1
            self._attempts += 1

    @staticmethod
    def _unsupported_endpoint(provider: str, request) -> str | None:
        try:
            url = request.url
            query = url.query.decode() if isinstance(url.query, bytes) else str(url.query)
            if ("alt=sse" in query or str(url.path).endswith(":streamGenerateContent")
                    or request.headers.get("x-stainless-raw-response") == "stream"):
                return "archive_streaming_unsupported"
            if str(request.method) != "POST" or url.scheme != "https" or url.host != PROVIDER_HOSTS[provider]:
                return "archive_unsupported_endpoint"
            if not _PATHS[provider].fullmatch(str(url.path)):
                return "archive_unsupported_endpoint"
        except Exception:
            return "archive_unsupported_endpoint"
        return None

    def _on_wire_response(self, provider: str, response) -> None:
        with self._lock:
            call = self._current
            if call is None or call.provider != provider or self._closed:
                self._hold("archive_unbound_wire_response")
                return
            attempt = call.attempts
            try:
                response.read()
            except BaseException:
                # A transport read failure is an unknown provider outcome, not a
                # recorder failure: label it and keep the caller's retry rules.
                self._safe_record("wire_response", {
                    "call": call.number, "attempt": attempt, "status": None, "headers": {},
                    "body": {"availability": "read_failed"}, "provider_ids": {}})
                raise
            try:
                data = response.content
                headers = {name: response.headers[name] for name in _RESPONSE_HEADERS if name in response.headers}
                record: dict[str, Any] = {"call": call.number, "attempt": attempt,
                                          "status": int(response.status_code), "headers": headers,
                                          "provider_ids": self._provider_ids(provider, headers, data)}
                if len(data) > MAX_RESPONSE_BYTES:
                    record["body"] = {"availability": "not_retained_over_limit", "bytes": len(data),
                                      "sha256": sha256_hex(data)}
                    self._record("wire_response", record)
                    call.incomplete = "archive_response_over_limit"
                    self._hold("archive_response_over_limit")
                    return
                record["body"] = {"availability": "captured", "artifact": self._artifact(data),
                                  "bytes": len(data), "form": "decoded_http_entity"}
                self._record("wire_response", record)
                call.responses += 1
            except Exception as exc:
                code = exc.code if isinstance(exc, RequestArchiveError) else "archive_write_failed_after_dispatch"
                call.incomplete = code
                self._hold(code)

    def _safe_record(self, kind: str, data: dict) -> None:
        try:
            self._record(kind, data)
        except Exception:
            self._hold("archive_write_failed_after_dispatch")

    @staticmethod
    def _provider_ids(provider: str, headers: dict, data: bytes) -> dict:
        ids: dict[str, str] = {}
        header = headers.get("request-id")
        if provider == "anthropic" and isinstance(header, str) and _SAFE_ID.fullmatch(header):
            ids["request_id_header"] = header
        try:
            body = strict_json_loads(data, allow_floats=True)
        except Exception:
            return ids
        field = "id" if provider == "anthropic" else "responseId"
        value = body.get(field) if isinstance(body, dict) else None
        if isinstance(value, str) and _SAFE_ID.fullmatch(value):
            ids[f"response_body_{field}"] = value
        return ids

    # ------------------------------------------------------- route families
    def route_hook(self):
        """This scope's single request-only witness; never a response reader."""
        with self._lock:
            if self._route_hook is None:
                def request_hook(request):
                    self._on_route_request(request)
                self._route_hook = request_hook
            return self._route_hook

    def observe_client(self, client) -> None:
        """Install the request witness on one transport-owned HTTP client."""
        with self._lock:
            self._require_usable()
            if not self._routes_enabled:
                self._try_record_refusal(None, "archive_route_scope_required")
                raise RequestArchiveRefused("archive_route_scope_required")
            hooks = client.event_hooks
            hook = self.route_hook()
            requests = list(hooks.get("request", []))
            if not any(item is hook for item in requests):
                requests.append(hook)
            client.event_hooks = {"request": requests, "response": list(hooks.get("response", []))}
            if not any(item is client for item in self._route_clients):
                self._route_clients.append(client)

    def begin_route(self, family: str, *, client: Any, expected_path: str, binding: dict,
                    logical: Any = None) -> _RouteRecorder:
        """Durably record one route operation BEFORE execution, or refuse it."""
        with self._lock:
            self._require_usable()
            if not self._routes_enabled:
                self._try_record_refusal(None, "archive_route_scope_required")
                raise RequestArchiveRefused("archive_route_scope_required")
            if self._current is not None or self._route is not None:
                raise RequestArchiveRefused("archive_call_already_open")
            if family not in ROUTES:
                raise RequestArchiveRefused("archive_unsupported_route")
            if self._route_count >= MAX_CALLS:
                self._try_record_refusal(None, "archive_call_limit")
                raise RequestArchiveRefused("archive_call_limit")
            provider, method, pattern, _ = ROUTES[family]
            if type(expected_path) is not str or not pattern.fullmatch(expected_path):
                self._try_record_refusal(None, "archive_unsupported_endpoint")
                raise RequestArchiveRefused("archive_unsupported_endpoint")
            hooks = getattr(client, "event_hooks", None)
            if (client is None or not any(item is client for item in self._route_clients)
                    or not isinstance(hooks, dict) or not any(h is self._route_hook for h in hooks.get("request", []))
                    or getattr(client, "follow_redirects", True) is not False):
                self._try_record_refusal(None, "archive_unobserved_transport")
                raise RequestArchiveRefused("archive_unobserved_transport")
            checked = _route_binding(binding)
            if checked is None:
                self._try_record_refusal(None, "archive_route_binding_invalid")
                raise RequestArchiveRefused("archive_route_binding_invalid")
            encoded, unavailable = (None, "not_applicable") if logical is None else logical_request_bytes(logical)
            if encoded is not None and len(encoded) > MAX_LOGICAL_REQUEST_BYTES:
                self._try_record_refusal(None, "archive_logical_request_limit")
                raise RequestArchiveRefused("archive_logical_request_limit")
            number = self._route_count + 1
            try:
                self._check_drift()
                artifact = self._artifact(encoded) if encoded is not None else None
                self._record("route_intent", {
                    "route": number, "family": family, "provider": provider, "method": method,
                    "expected_path": expected_path, "binding": checked,
                    "logical_request": ({"availability": "captured", "artifact": artifact,
                                         "bytes": len(encoded), "form": "tagged_kwargs_json_v1"}
                                        if encoded is not None else
                                        {"availability": "unavailable", "reason": unavailable}),
                    "recorded_before_execution": True})
            except RequestArchiveError as exc:
                if exc.code == "archive_scope_content_limit":
                    self._try_record_refusal(None, exc.code)
                else:
                    self._hold(exc.code)
                raise RequestArchiveRefused(exc.code) from None
            except Exception:
                self._hold("archive_write_failed_before_dispatch")
                raise RequestArchiveRefused("archive_write_failed_before_dispatch") from None
            self._route_count = number
            self._route = _RouteRecorder(self, number, family, expected_path)
            return self._route

    def _on_route_request(self, request) -> None:
        with self._lock:
            route = self._route
            if route is None or self._closed or threading.get_ident() != self._owner:
                self._hold("archive_unbound_wire_request")
                raise RequestArchiveRefused("archive_unbound_wire_request")
            code = self._held or route.endpoint_problem(request)
            if code is None and route.attempts:
                code = "archive_second_send_refused"
            body = None
            if code is None:
                try:
                    body = request.read()  # The SDK's already-built entity; nothing is re-encoded.
                except Exception:
                    code = "archive_unreadable_request_body"
            if code is None and (not isinstance(body, bytes) or len(body) > MAX_WIRE_REQUEST_BYTES
                                 or (route.method == "GET" and body)):
                code = "archive_wire_request_limit"
            if code is None and self._attempts >= MAX_WIRE_ATTEMPTS:
                code = "archive_wire_attempt_limit"
            if code is not None:
                route.refusal = code
                if route.attempts:
                    self._hold(code)  # Any later send after a real send.
                raise RequestArchiveRefused(code)
            assert isinstance(body, bytes)
            try:
                observed = ({"custom_ids": _custom_ids(body)} if route.family == "batch_submit" else {})
                self._record("route_wire_request", {
                    "route": route.number, "attempt": 1, "method": str(request.method),
                    "scheme": str(request.url.scheme), "host": str(request.url.host), "path": str(request.url.path),
                    "query_present": bool(request.url.query), "content_type": request.headers.get("content-type"),
                    "body": ({"availability": "captured", "artifact": self._artifact(body), "bytes": len(body),
                              "form": "exact_request_entity"} if route.method == "POST" else
                             {"availability": "no_entity", "bytes": 0}),
                    "observed": observed, "recorded_before_send": True})
            except Exception as exc:
                code = exc.code if isinstance(exc, RequestArchiveError) else "archive_write_failed_before_dispatch"
                route.refusal = code
                self._hold(code)
                raise RequestArchiveRefused(code) from None
            route.attempts = 1
            self._attempts += 1
            self._route_attempts += 1

    def _on_route_response(self, family: str, status: Any, headers: Any, data: Any, complete: Any,
                           reason: Any) -> None:
        """Retain what the existing bounded reader saw; never raises or reads."""
        with self._lock:
            route = self._route
            if route is None or route.family != family or self._closed or threading.get_ident() != self._owner:
                self._hold("archive_unbound_wire_response")
                return
            if route.attempts == 0:
                return  # Nothing was sent; the route result says so.
            if route.responses:
                route.incomplete = "archive_second_response"
                self._hold("archive_second_response")
                return
            try:
                if (not (data is None or isinstance(data, bytes)) or type(complete) is not bool
                        or (data is None and complete) or reason not in ROUTE_REASONS
                        or not (status is None or type(status) is int)):
                    raise RequestArchiveError("archive_route_observation_invalid")
                kept = {name: str(headers[name]) for name in _RESPONSE_HEADERS
                        if headers is not None and name in headers}
                record: dict[str, Any] = {"route": route.number, "attempt": 1, "status": status, "headers": kept,
                                          "complete": complete, "reason": reason, "observed": {}}
                if data is None:
                    # The SDK raised before the bounded reader saw any byte (e.g.
                    # its own status error); that entity was never observed here.
                    record["body"] = {"availability": "not_observed"}
                    self._record("route_response", record)
                    route.responses, route.entity = 1, "not_observed"
                    return
                record["observed"] = _route_ids(family, kept, data, complete)
                form = ROUTES[family][3] + ("" if complete else "_bounded_prefix")
                if len(data) > MAX_RESPONSE_BYTES:
                    record["body"] = {"availability": "not_retained_over_limit", "bytes": len(data),
                                      "sha256": sha256_hex(data)}
                    self._record("route_response", record)
                    route.responses, route.entity = 1, "not_retained"
                    route.incomplete = "archive_response_over_limit"
                    self._hold("archive_response_over_limit")
                    return
                record["body"] = {"availability": "captured", "artifact": self._artifact(data),
                                  "bytes": len(data), "form": form}
                self._record("route_response", record)
                route.responses, route.entity = 1, "captured"
                route.entity_complete = complete
                route.final_line_unparseable = (family == "batch_results" and complete
                                                and jsonl_final_line_unparseable(data))
            except Exception as exc:
                code = exc.code if isinstance(exc, RequestArchiveError) else "archive_write_failed_after_dispatch"
                route.incomplete = code
                self._hold(code)


class _CallRecorder:
    def __init__(self, scope: RequestArchiveScope, number: int, stage: str, provider: str):
        self.scope = scope
        self.number = number
        self.stage = stage
        self.provider = provider
        self.attempts = 0
        self.responses = 0
        self.refusal: str | None = None
        self.incomplete: str | None = None

    def _finish(self, data: dict) -> RequestArchiveError | None:
        scope = self.scope
        with scope._lock:
            scope._current = None
            data = {"call": self.number, "wire_attempts": self.attempts,
                    "wire_responses": self.responses, "billing": "unknown", **data}
            if self.incomplete is not None or scope._held is not None:
                data["archival"] = "incomplete"
                scope._safe_record("call_result", data)
                return RequestArchiveHeld(self.incomplete or scope._held or "archive_scope_held")
            try:
                scope._record("call_result", data)
            except Exception:
                scope._hold("archive_write_failed_after_dispatch")
                return RequestArchiveHeld("archive_write_failed_after_dispatch")
            return None

    def returned(self, response: Any) -> RequestArchiveError | None:
        """Record the parsed object's association; never raises."""
        complete = self.attempts > 0 and self.responses == self.attempts
        return self._finish({"outcome": "returned", "returned_type": type(response).__qualname__,
                             "archival": "complete" if complete else (
                                 "no_physical_send_observed" if self.attempts == 0 else "partial")})

    def raised(self, exc: BaseException) -> RequestArchiveError | None:
        """Record a failure by class only (never a repr/message); never raises."""
        if self.refusal is not None and self.attempts == 0:
            held = self._finish({"outcome": "refused_before_send", "reason": self.refusal,
                                 "archival": "complete", "provider_outcome": "not_sent"})
            return held or RequestArchiveRefused(self.refusal)
        status = None
        for field in ("status_code", "code"):
            value = getattr(exc, field, None)
            if type(value) is int:
                status = value
                break
        outcome = ("raised_after_send" if self.attempts else "raised_before_send")
        # Archival describes the recorder; a missing provider response is its own field.
        return self._finish({"outcome": outcome, "exception_type": type(exc).__qualname__,
                             "status_code": status, "archival": "complete" if self.attempts else "no_physical_send_observed",
                             "response_observed": self.responses > 0,
                             "provider_outcome": "unknown"})


class _RouteRecorder:
    def __init__(self, scope: RequestArchiveScope, number: int, family: str, expected_path: str):
        self.scope = scope
        self.number = number
        self.family = family
        self.provider, self.method, _, _ = ROUTES[family]
        self.expected_path = expected_path
        self.attempts = 0
        self.responses = 0
        self.refusal: str | None = None
        self.incomplete: str | None = None
        self.entity: str | None = None
        self.entity_complete = False
        self.final_line_unparseable = False
        self.finished = False

    def endpoint_problem(self, request) -> str | None:
        """Exact method, host and canonical path; any query (e.g. ``alt=sse``) refuses."""
        try:
            url = request.url
            if (str(request.method) != self.method or url.scheme != "https"
                    or url.host != PROVIDER_HOSTS[self.provider] or str(url.path) != self.expected_path
                    or url.query or url.fragment):
                return "archive_unsupported_endpoint"
        except Exception:
            return "archive_unsupported_endpoint"
        return None

    def bind(self, binding: dict) -> None:
        """Add identities known only after authority (e.g. a grant), BEFORE any send."""
        scope = self.scope
        with scope._lock:
            scope._require_usable()
            if self.attempts or self.finished or scope._route is not self:
                raise RequestArchiveRefused("archive_route_bind_after_send")
            checked = _route_binding(binding)
            if not checked:
                raise RequestArchiveRefused("archive_route_binding_invalid")
            try:
                scope._record("route_bound", {"route": self.number, "binding": checked})
            except Exception:
                scope._hold("archive_write_failed_before_dispatch")
                raise RequestArchiveRefused("archive_write_failed_before_dispatch") from None

    def finish(self, outcome: str, disposition: dict | None = None) -> str | None:
        """Close this route with the caller's fixed disposition; never raises.

        Returns a hold or evidence-gap code when evidence is incomplete. It never
        changes the caller's own outcome: an archive failure after a send is not a result.
        """
        scope = self.scope
        with scope._lock:
            if self.finished:
                return scope._held
            self.finished = True
            scope._route = None
            if outcome not in ROUTE_OUTCOMES:
                outcome = "raised"
            sent = self.attempts > 0
            # A sent route is complete evidence only with its whole entity retained.
            # A fully retained negative provider response is still complete evidence.
            gap = None if not sent else (
                "entity_not_recorded" if not self.responses else
                "entity_not_observed" if self.entity == "not_observed" else
                "entity_not_retained" if self.entity != "captured" else
                "entity_bounded_prefix" if not self.entity_complete else
                "results_final_line_unparseable" if self.final_line_unparseable else None)
            data: dict[str, Any] = {
                "route": self.number, "family": self.family, "outcome": outcome,
                "wire_attempts": self.attempts, "responses": self.responses,
                "physical_send_observed": sent, "refusal": self.refusal if not sent else None,
                "disposition": _route_disposition(disposition), "billing": "unknown",
                "provider_outcome": ("not_sent" if not sent else "response_observed"
                                     if self.entity in ("captured", "not_retained") else "unknown"),
                "evidence_gap": gap}
            if self.incomplete is not None or scope._held is not None or gap is not None:
                # Incomplete evidence never changes the caller's outcome or holds the scope;
                # only a recorder failure (or no response record at all) holds it.
                data["archival"] = "incomplete"
                scope._safe_record("route_result", data)
                if sent and not self.responses and scope._held is None:
                    scope._hold("archive_route_response_not_observed")
                return self.incomplete or scope._held or gap
            data["archival"] = "complete"
            try:
                scope._record("route_result", data)
            except Exception:
                scope._hold("archive_write_failed_after_dispatch" if sent else "archive_write_failed")
                return scope._held
            return None


_ROUTE_BINDING_KEYS = frozenset({
    "job_id", "plan_sha256", "policy_sha256", "lease_fence", "grant_id", "provider_batch_id", "submission_state",
    "context_sha256", "check_set_id", "stage", "request_sha256", "packet_sha256", "candidate_text_sha256",
    "source_origin_sha256", "model"})
_ROUTE_DISPOSITION_KEYS = frozenset({
    "outcome", "reason", "state", "grant_id", "provider_batch_id", "job_id", "receipt_id", "complete",
    "processing_status", "http_status", "stage", "observation_complete"})


def route_entry(value: Any, source: str) -> dict:
    """One binding entry; an absent value is explicitly ``missing``, never guessed."""
    return {"value": value, "source": source} if value is not None else {"value": None, "source": "missing"}


def jsonl_final_line_unparseable(data: bytes) -> bool:
    """True when a JSONL entity ends mid-record: an unterminated last line that is not one JSON value."""
    if not data or data.endswith(b"\n"):
        return False
    try:
        strict_json_loads(data.rsplit(b"\n", 1)[-1], allow_floats=True)
    except Exception:
        return True
    return False


def _route_value(value: Any) -> bool:
    return value is None or type(value) in (bool, int) or (type(value) is str and bool(_SAFE_ID.fullmatch(value)))


def _route_binding(binding: Any) -> dict | None:
    """Fixed identity fields, each with its explicit source; missing stays missing."""
    if type(binding) is not dict or not set(binding) <= _ROUTE_BINDING_KEYS:
        return None
    result = {}
    for key, entry in binding.items():
        if (type(entry) is not dict or set(entry) != {"value", "source"} or entry["source"] not in ROUTE_BINDING_SOURCES
                or not _route_value(entry["value"]) or (entry["source"] == "missing") != (entry["value"] is None)):
            return None
        result[key] = {"value": entry["value"], "source": entry["source"]}
    return result


def _route_disposition(disposition: Any) -> dict:
    if type(disposition) is not dict:
        return {}
    return {key: value for key, value in disposition.items()
            if key in _ROUTE_DISPOSITION_KEYS and _route_value(value)}


def _custom_ids(body: bytes) -> dict:
    """Custom IDs observed in the exact outgoing batch entity; never repaired."""
    try:
        value = strict_json_loads(body, allow_floats=True)
        rows = value.get("requests") if isinstance(value, dict) else None
        if type(rows) is not list:
            return {"availability": "unparseable"}
        ids = [row.get("custom_id") if isinstance(row, dict) else None for row in rows]
        if len(ids) > MAX_CALLS or not all(type(item) is str and _SAFE_ID.fullmatch(item) for item in ids):
            return {"availability": "invalid", "count": len(ids)}
        return {"availability": "observed", "values": ids}
    except Exception:
        return {"availability": "unparseable"}


def _route_ids(family: str, headers: dict, data: bytes, complete: bool) -> dict:
    ids: dict[str, Any] = {}
    header = headers.get("request-id")
    if family != "command_check" and isinstance(header, str) and _SAFE_ID.fullmatch(header):
        ids["request_id_header"] = header
    if not complete or family == "batch_results":
        return ids  # A prefix or a JSONL stream is never parsed into an identity here.
    try:
        body = strict_json_loads(data, allow_floats=True)
    except Exception:
        return ids
    if not isinstance(body, dict):
        return ids
    if family == "command_check":
        value = body.get("responseId")
        if isinstance(value, str) and _SAFE_ID.fullmatch(value):
            ids["response_body_responseId"] = value
    else:
        value = body.get("id")
        if isinstance(value, str) and _BATCH_ID_FULL.fullmatch(value):
            ids["provider_batch_id"] = value
        status = body.get("processing_status")
        if isinstance(status, str) and _SAFE_ID.fullmatch(status):
            ids["processing_status"] = status
    return ids


def route_scope() -> RequestArchiveScope | None:
    """None when capture is OFF; a foreign or v1-only open scope refuses."""
    scope = active_scope()
    if scope is not None and not scope._routes_enabled:
        scope._try_record_refusal(None, "archive_route_scope_required")
        raise RequestArchiveRefused("archive_route_scope_required")
    return scope


def observe_route_response(family: str, *, status: Any, headers: Any, data: Any, complete: Any,
                           reason: Any) -> None:
    """Observation seam after a transport's existing bounded reader; no-op when OFF."""
    scope = _bound_scope()
    if scope is None or not scope._routes_enabled:
        return
    scope._on_route_response(family, status, headers, data, complete, reason)


# ------------------------------------------------- pipeline binding notes

def note_generation_input(event_id: Any, signal_kind: Any, capture: Any, memory_slice: Any) -> None:
    """Bind the actual checked bundle and memory slice. No-op unless capturing."""
    scope = _bound_scope()
    if scope is None:
        return

    def build() -> dict:
        from src.editorial.revisions import fingerprint
        from src.two_bot.json_utils import json_default
        bundle_bytes = capture.serialized.encode("utf-8")
        memory_bytes = json.dumps(memory_slice.to_dict(), ensure_ascii=False, sort_keys=True,
                                  default=json_default, allow_nan=False).encode("utf-8")
        bundle_sha = fingerprint(capture.payload())
        memory_sha = sha256_hex(memory_bytes)
        scope._binding = {"event_id": str(event_id), "bundle_sha256": bundle_sha, "memory_sha256": memory_sha,
                          "candidate_text_sha256": None, "candidate_attempt": None, "phase": "writer",
                          "revises_candidate_text_sha256": None}
        return {"event_id": str(event_id), "signal_kind": str(signal_kind),
                "bundle_sha256": bundle_sha, "bundle_artifact": scope._artifact(bundle_bytes),
                "bundle_form": "bundle_capture_serialized", "memory_sha256": memory_sha,
                "memory_artifact": scope._artifact(memory_bytes), "memory_form": "memory_slice_json_v1"}
    scope._note("generation_input", build)


def note_candidate(text: Any, attempt: int) -> None:
    """Bind the exact selected text that later checks receive."""
    scope = _bound_scope()
    if scope is None:
        return

    def build() -> dict:
        data = text.encode("utf-8")
        digest = sha256_hex(data)
        scope._binding.update(candidate_text_sha256=digest, candidate_attempt=int(attempt),
                              phase="checks", revises_candidate_text_sha256=None)
        return {"candidate_text_sha256": digest, "attempt": int(attempt),
                "text_artifact": scope._artifact(data), "characters": len(text),
                "authority": "observation_only"}
    scope._note("candidate", build)


def note_revision_request(previous_text: Any, attempt: int) -> None:
    scope = _bound_scope()
    if scope is None:
        return

    def build() -> dict:
        previous = sha256_hex(previous_text.encode("utf-8"))
        scope._binding.update(candidate_text_sha256=None, candidate_attempt=int(attempt), phase="revision",
                              revises_candidate_text_sha256=previous)
        return {"attempt": int(attempt), "revises_candidate_text_sha256": previous}
    scope._note("revision_requested", build)


def note_stage_outcome(stage: Any, outcome: Any, reason: Any = None) -> None:
    scope = _bound_scope()
    if scope is None:
        return

    def build() -> dict:
        return {"stage": str(stage), "outcome": str(outcome), "binding": scope._binding_snapshot(),
                "reason_artifact": (scope._artifact(reason.encode("utf-8"))
                                    if isinstance(reason, str) else None)}
    scope._note("stage_outcome", build)
