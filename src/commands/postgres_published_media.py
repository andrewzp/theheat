"""Local-only immutable radar input retention, no acquisition or review grant."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from src.commands import postgres_media as media, postgres_sourced_generation as generation
from src.commands.schema import CommandError
from src.editorial.revisions import fingerprint
from src.media import published_radar as radar
from src.storage import postgres_projection as p

NAMESPACE = "published-radar-input-v1"


def private_bytes(path, limit):
    path = Path(path)
    radar.require(
        path.is_absolute() and not any(part.is_symlink() for part in (path, *path.parents)),
        "radar_private_path_required",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        radar.require(
            stat.S_ISREG(meta.st_mode)
            and meta.st_uid == os.getuid()
            and stat.S_IMODE(meta.st_mode) == 0o600
            and 0 < meta.st_size <= limit,
            "radar_private_file_required",
        )
        raw = stream.read(limit + 1)
        radar.require(len(raw) == meta.st_size, "radar_private_file_changed")
        return raw


def retain(authority, value, original, references, receipt):
    """Retain already acquired input; no authority, freshness or human verdict."""
    radar.require(authority.environment == "local", "radar_local_only")
    value = radar.document(value)
    radar.original_header(original, value)
    radar.shape(references, {"product", "reuse"})
    for name, raw in {**references, "receipt": receipt}.items():
        expected = value["receipt"] if name == "receipt" else value["references"][name]
        radar.require(
            type(raw) is bytes
            and len(raw) == expected["byte_count"]
            and radar.digest(raw) == expected["sha256"],
            "radar_reference_bytes_changed",
        )
    raw = radar.encoded(value)
    identity = radar.digest(raw)
    with authority.projections._connection(writing=True) as c:
        authority._validate(c)
        media.validate(c, authority.environment)
        for data in (raw, original, receipt, *references.values()):
            media._artifact(c, data)
        generation.record(c, NAMESPACE, identity, value)
    return {
        "namespace": NAMESPACE,
        "input_sha256": identity,
        "metadata_status": "unreviewed",
        "publication_approved": False,
    }


def configure(authority, load):
    radar.require(
        authority.environment == "local" and callable(load), "radar_configuration_invalid"
    )
    authority.published_radar_configuration = load


def configuration(authority):
    load = getattr(authority, "published_radar_configuration", None)
    radar.require(
        authority.environment == "local" and callable(load), "radar_selection_unavailable"
    )
    assert callable(load)
    value = p._decode(p._canonical(load()))
    radar.shape(value, {"schema_version", "selections"})
    radar.require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and type(value["selections"]) is dict
        and len(value["selections"]) <= 16,
        "radar_selection_invalid",
    )
    for k, v in value["selections"].items():
        radar.sha(k)
        radar.sha(v)
    return value


def read(c, identity):
    radar.sha(identity)
    radar.require(generation.exists(c, NAMESPACE, identity), "radar_input_not_retained")
    value = radar.document(generation.read(c, NAMESPACE, identity))
    radar.require(radar.digest(radar.encoded(value)) == identity, "radar_input_changed")
    original = media._raw(c, value["original"]["sha256"], radar.MAX_ORIGINAL)
    radar.original_header(original, value)
    for row in [value["receipt"], *value["references"].values()]:
        raw = media._raw(c, row["sha256"], radar.MAX_INPUT)
        radar.require(len(raw) == row["byte_count"], "radar_reference_bytes_changed")
    return value, original


def current(authority, c, brief_id, bundle, source_origin, now):
    try:
        config = configuration(authority)
        radar.require(brief_id in config["selections"], "radar_selection_missing")
        value, _ = read(c, config["selections"][brief_id])
        registry_path = Path(__file__).resolve().parents[2] / "data/place_registry.json"
        raw = registry_path.read_bytes()
        radar.require(len(raw) <= 2_000_000, "radar_registry_bound")
        matches = [p for p in json.loads(raw)["places"] if p["place_id"] == "pl0406"]
        radar.require(len(matches) == 1, "radar_registry_changed")
        row = matches[0]
        point = dict(
            place_id=row["place_id"], label=row["city"], latitude=row["lat"], longitude=row["lon"]
        )
        return radar.make_spec(
            bundle,
            value,
            source_origin=source_origin,
            registry_sha256=radar.digest(raw),
            point=point,
            selection_sha256=fingerprint(config),
            now=now,
        )
    except (radar.RadarHold, ValueError, KeyError, TypeError, OSError) as exc:
        raise CommandError(
            exc.code if isinstance(exc, radar.RadarHold) else "radar_input_unavailable",
            "The current source and published radar cannot be qualified",
        ) from None
