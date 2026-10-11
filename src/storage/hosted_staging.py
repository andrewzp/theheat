"""Explicit, file-pinned preview TLS connections; never a production selector.

Callers supply a separately trusted setup identity. This module neither discovers
accounts nor obtains passwords. Wall-clock operation deadlines belong to a caller's
process supervisor; libpq/server timeouts are not a Python-operation deadline.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from src.storage.postgres_projection import ProjectionError, _require

MAX_CONFIG_BYTES = 16384
_PORT = 5432
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,62}")
_REMOTE_ID = re.compile(r"[a-z][a-z0-9-]{0,159}")
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
_COMMON = {"schema", "environment", "project_id", "branch_id", "endpoint_id", "host", "port",
           "database", "purpose", "role", "ca_path", "ca_sha256"}


def safe_environment() -> None:
    # Lazy: preview_ingress imports the authority, which imports projection.
    from src.commands.preview_ingress import safe_environment as guard
    try:
        guard()
    except ValueError:
        raise ProjectionError("hosted_environment_refused") from None


def _private_file(path: str | Path) -> bytes:
    """Validate opened directory and file descriptors, not only pathname metadata."""
    _require(isinstance(path, (str, Path)), "private_staging_file_required")
    path = Path(path)
    _require(path.is_absolute() and path == path.resolve(), "private_staging_file_required")
    parent = -1
    try:
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory = os.fstat(parent)
        _require(directory.st_uid == os.getuid() and stat.S_IMODE(directory.st_mode) == 0o700,
                 "private_staging_directory_required")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                     and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                     and 0 < info.st_size <= MAX_CONFIG_BYTES, "private_staging_file_required")
            value = stream.read(MAX_CONFIG_BYTES + 1)
            _require(len(value) <= MAX_CONFIG_BYTES, "private_staging_file_required")
            return value
    except OSError:
        raise ProjectionError("private_staging_file_required") from None
    finally:
        if parent >= 0:
            os.close(parent)


def _json(raw: bytes) -> dict:
    def pairs(rows):
        result = {}
        for key, value in rows:
            _require(key not in result, "invalid_staging_configuration")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _require(type(value) is dict, "invalid_staging_configuration")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ProjectionError("invalid_staging_configuration") from None


def _validate_identity(value: dict) -> None:
    _require(set(value) == _COMMON, "invalid_staging_identity")
    _require(type(value["schema"]) is int and value["schema"] == 1
             and value["environment"] == "preview", "production_adapter_unavailable")
    for name in ("project_id", "branch_id", "endpoint_id"):
        _require(type(value[name]) is str and _REMOTE_ID.fullmatch(value[name]) is not None,
                 "invalid_staging_identity")
    host = value["host"]
    _require(type(host) is str and _HOST.fullmatch(host) is not None
             and ".." not in host and "-pooler" not in host and not host.replace(".", "").isdigit(),
             "invalid_staging_host")
    _require(type(value["port"]) is int and value["port"] == _PORT, "invalid_staging_port")
    _require(value["purpose"] in ("owner", "runtime"), "invalid_staging_identity")
    for name in ("database", "role"):
        _require(type(value[name]) is str and _IDENTIFIER.fullmatch(value[name]) is not None,
                 "invalid_staging_identity")
    _require(type(value["ca_path"]) is str and Path(value["ca_path"]).is_absolute(),
             "invalid_staging_ca")
    _require(type(value["ca_sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["ca_sha256"]) is not None,
             "invalid_staging_ca")


def _check_ca(path: Path, digest: str) -> None:
    try:
        _require(path == path.resolve(), "invalid_staging_ca")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and not stat.S_IMODE(info.st_mode) & 0o022
                     and 0 < info.st_size <= 2 * 1024 * 1024, "invalid_staging_ca")
            raw = stream.read(2 * 1024 * 1024 + 1)
            _require(len(raw) <= 2 * 1024 * 1024 and hashlib.sha256(raw).hexdigest() == digest,
                     "invalid_staging_ca")
    except OSError:
        raise ProjectionError("invalid_staging_ca") from None


@dataclass(frozen=True, repr=False)
class HostedStagingConfig:
    """Factory input is loaded against a separate, reviewed identity receipt.

    Both files are reread before every dial. Changes to either require construction
    of a new explicitly reviewed input; secrets and paths have no printable repr.
    """
    config_path: Path = field(repr=False)
    identity_path: Path = field(repr=False)
    config_sha256: str
    identity_sha256: str

    @classmethod
    def load(cls, config_path: str | Path, *, trusted_identity: str | Path) -> HostedStagingConfig:
        safe_environment()
        raw, identity = _private_file(config_path), _private_file(trusted_identity)
        value = cls(Path(config_path), Path(trusted_identity), hashlib.sha256(raw).hexdigest(),
                    hashlib.sha256(identity).hexdigest())
        value.parameters()
        return value

    def parameters(self) -> dict:
        safe_environment()
        raw, identity_raw = _private_file(self.config_path), _private_file(self.identity_path)
        _require(hashlib.sha256(raw).hexdigest() == self.config_sha256
                 and hashlib.sha256(identity_raw).hexdigest() == self.identity_sha256,
                 "staging_configuration_changed")
        value, identity = _json(raw), _json(identity_raw)
        _validate_identity(identity)
        _require(set(value) == _COMMON | {"password"}, "invalid_staging_configuration")
        _validate_identity({key: value[key] for key in _COMMON})
        _require({key: value[key] for key in _COMMON} == identity, "staging_identity_mismatch")
        # Existing PostgreSQL passwords need not have our generated role-password
        # format. Preserve their exact text; forbid missing/control data and known
        # URI/management-key formats. The server still authenticates the DB role.
        password = value["password"]
        _require(type(password) is str and 1 <= len(password) <= 256 and password.isprintable()
                 and not password.lower().startswith(("postgres://", "postgresql://", "neon_api_", "napi_", "nkey_", "nkey-")),
                 "invalid_staging_password")
        _check_ca(Path(value["ca_path"]), value["ca_sha256"])
        return value


@contextmanager
def connection(config: HostedStagingConfig, driver):
    """One strict TLS dial; transaction/SQL semantics remain in the repository."""
    _require(type(config) is HostedStagingConfig, "explicit_staging_config_required")
    value = config.parameters()
    disabled = config.config_path.parent / "disabled-libpq-file"
    _require(not disabled.exists() and not disabled.is_symlink(), "implicit_libpq_file_refused")
    with driver.connect(
        host=value["host"], port=_PORT, dbname=value["database"], user=value["role"],
        password=value["password"], passfile=str(disabled), connect_timeout=5,
        sslmode="verify-full", channel_binding="require", sslrootcert=value["ca_path"],
        sslcertmode="disable", sslcert=str(disabled), sslkey=str(disabled),
        sslcrl=str(disabled), sslcrldir=str(disabled), gssencmode="disable",
        ssl_min_protocol_version="TLSv1.2", application_name="theheat_hosted_staging",
        options="-c statement_timeout=10000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000 -c timezone=UTC -c search_path=pg_catalog",
        autocommit=True,
    ) as conn:
        _require(170000 <= conn.info.server_version < 180000, "unsupported_postgres_version")
        params = {row.keyword.decode(): row.val.decode() if row.val is not None else None for row in conn.pgconn.info}
        _require(all(params.get(k) == str(v) for k, v in {
            "host": value["host"], "port": _PORT, "dbname": value["database"], "user": value["role"],
            "sslmode": "verify-full", "channel_binding": "require", "sslcertmode": "disable",
            "sslrootcert": value["ca_path"], "gssencmode": "disable",
        }.items()) and conn.pgconn.ssl_in_use, "staging_tls_identity_mismatch")
        row = conn.execute("SELECT current_database(),current_user,ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()").fetchone()
        _require(row == (value["database"], value["role"], True), "staging_database_identity_mismatch")
        yield conn
