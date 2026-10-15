"""Explicit invented loopback transport configuration, never live publication."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
from uuid import UUID

SCOPE = "local_http_fixture_v1"
STAGES = {"x": ("upload", "alt", "create"), "bluesky": ("upload", "create")}
MAX_REQUEST = 9 * 1024 * 1024
MAX_RESPONSE = 128 * 1024
LEASE_SECONDS = 30
PHASE_SECONDS = 15
MIN_WINDOW_SECONDS = 17


def require(condition, code):
    if not condition:
        raise ValueError(code)


def clean_environment():
    # Inspect presence only. Never discover/read any provider credential store.
    require(os.environ.get("NODE_ENV") != "production"
            and os.environ.get("THEHEAT_ENVIRONMENT") != "production", "delivery_local_only")
    for name, value in os.environ.items():
        require(not (name.startswith("PG") or value and (re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?|PRIVATE_KEY|GIST_ID|DATABASE_URL)$", name)
                    or name.startswith(("PG", "AWS_", "TWITTER_", "BLUESKY_", "X_API_")))),
                "delivery_ambient_credentials_refused")


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "delivery_duplicate_key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("delivery_invalid_json")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)


def configuration(value):
    extension = {"platform_profile"} if type(value) is dict and value.get("schema_version") == 2 else set()
    require(type(value) is dict and set(value) == extension | {"schema_version", "scope", "invented", "instance_id", "origin", "routes_version", "actor"},
            "delivery_configuration_shape")
    require(type(value["schema_version"]) is int and value["schema_version"] in (1, 2)
            and value["scope"] == SCOPE and value["invented"] is True
            and type(value["routes_version"]) is int and value["routes_version"] == 1,
            "delivery_configuration_scope")
    require(not extension or value["platform_profile"] == "credentialless-loopback-v1",
            "delivery_configuration_profile")
    require(type(value["instance_id"]) is str and str(UUID(value["instance_id"])) == value["instance_id"],
            "delivery_instance_required")
    require(type(value["origin"]) is str and re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", value["origin"]),
            "delivery_loopback_origin_required")
    parsed = urlsplit(value["origin"])
    require(parsed.port is not None and 1 <= parsed.port <= 65535, "delivery_loopback_origin_required")
    require(value["actor"] == "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa", "delivery_invented_actor_required")
    return value


@dataclass(frozen=True)
class FixtureConfiguration:
    path: Path
    sha256: str

    @classmethod
    def load(cls, path):
        path = Path(path)
        require(path.is_absolute(), "delivery_absolute_configuration_required")
        raw = cls._read(path)
        return cls(path, hashlib.sha256(raw).hexdigest())

    @staticmethod
    def _read(path):
        parent = path.parent.lstat()
        require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
                and stat.S_IMODE(parent.st_mode) == 0o700, "delivery_private_directory_required")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            meta = os.fstat(stream.fileno())
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
                    and stat.S_IMODE(meta.st_mode) == 0o600 and 0 < meta.st_size <= 4096,
                    "delivery_private_configuration_required")
            raw = stream.read(4097)
        require(len(raw) <= 4096, "delivery_configuration_bound")
        configuration(strict_json(raw))
        return raw

    def read(self):
        raw = self._read(self.path)
        require(hashlib.sha256(raw).hexdigest() == self.sha256, "delivery_configuration_changed")
        return configuration(strict_json(raw))
