#!/usr/bin/env python3
"""Local-only retention of already acquired Gist media inputs into the durable store.

No fetch, upload endpoint, review or approval: this retains exact private files and
prints the immutable identity to select in the Workbench. Inputs must be absolute,
non-symlinked, owner-only (0600) regular files. Retention uses the explicit
writer store (THEHEAT_MEDIA_WRITER_STORE / THEHEAT_MEDIA_WRITER_DSN), as does restore;
verify, backup and export use the read-only store (THEHEAT_MEDIA_STORE /
THEHEAT_MEDIA_STORE_DSN). --store sqlite:<absolute path> selects one local store for both.

export writes a NEW private (0700) directory with each selected item's complete,
re-verified closure; restore verifies every byte and relation before any insert.
Neither is a database-wide backup or a draft-state migration; nothing is deleted.

  retain_gist_media.py published --product nhc_track_cone_v1 --metadata M --original O \
      --product-reference P --reuse-reference R --receipt C
  retain_gist_media.py crw-packet --packet PACKET.json
  retain_gist_media.py verify --manifest SHA256
  retain_gist_media.py backup --target /absolute/new-backup.sqlite3
  retain_gist_media.py export --target /absolute/new-dir --manifest SHA256 --crw-packet SHA256
  retain_gist_media.py restore --source /absolute/export-dir
  retain_gist_media.py plan --state /absolute/private-state.json
  retain_gist_media.py readback --manifest SHA256 --crw-packet SHA256

readback is the cross-host acceptance read: through the read-only store of THIS host
(the PostgreSQL adapter first proves the role holds exactly SELECT on the artifact
table) it re-reads each named identity and verifies every hash and relation. It
prints the store kind, counts and identities only: never a DSN, host, user or bytes.

plan reads a saved state snapshot (an owner-only local file; nothing is fetched) and
lists every retained media item its drafts need, why (unresolved delivery, current
review, delivered history), and whether this store can serve it. Missing or changed
items are named holds; present ones are grouped into export arguments.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.media import gist_assets  # noqa: E402

LIMIT = 2 * 1024 * 1024


def private_bytes(value, limit=LIMIT):
    path = Path(value)
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise SystemExit("input must be an absolute path without symlinks")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if not (stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
                and stat.S_IMODE(meta.st_mode) == 0o600 and 0 < meta.st_size <= limit):
            raise SystemExit("input must be a private (0600) regular file within its bound")
        raw = stream.read(limit + 1)
    if len(raw) != meta.st_size:
        raise SystemExit("input changed while reading")
    return raw


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError) as exc:
        raise SystemExit("input is not strict UTF-8 JSON") from exc


def main(argv=None, environ=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--store", help="sqlite:<absolute path> (default: THEHEAT_MEDIA_STORE)")
    commands = parser.add_subparsers(dest="command", required=True)
    pub = commands.add_parser("published")
    pub.add_argument("--product", required=True)
    for name in ("metadata", "original", "product-reference", "reuse-reference", "receipt"):
        pub.add_argument("--" + name, required=True)
    commands.add_parser("crw-packet").add_argument("--packet", required=True)
    commands.add_parser("verify").add_argument("--manifest", required=True)
    commands.add_parser("backup").add_argument("--target", required=True)
    exp = commands.add_parser("export")
    exp.add_argument("--target", required=True)
    exp.add_argument("--manifest", action="append", default=[], help="published manifest SHA256 (repeatable)")
    exp.add_argument("--crw-packet", action="append", default=[], help="CRW packet artifact SHA256 (repeatable)")
    commands.add_parser("restore").add_argument("--source", required=True)
    commands.add_parser("plan").add_argument("--state", required=True)
    back = commands.add_parser("readback")
    back.add_argument("--manifest", action="append", default=[])
    back.add_argument("--crw-packet", action="append", default=[])
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    if args.store:  # One explicit local store for this operator command (both capabilities).
        env[gist_assets.ENV] = env[gist_assets.WRITER_ENV] = args.store
    try:
        writes = args.command in ("published", "crw-packet", "restore")
        store = gist_assets.configured_writer(env) if writes else gist_assets.configured(env)
        if args.command == "published":
            from src.media import gist_published_media as published
            manifest = published.retain(
                store, args.product, _json(private_bytes(args.metadata, 64 * 1024)), private_bytes(args.original),
                {"product": private_bytes(args.product_reference, 64 * 1024),
                 "reuse": private_bytes(args.reuse_reference, 64 * 1024)},
                private_bytes(args.receipt, 64 * 1024))
            result = {"manifest_sha256": manifest, "metadata_status": "unreviewed", "publication_approved": False}
        elif args.command == "crw-packet":
            from src.media import gist_crw_media as crw
            result = {"packet_artifact_sha256": crw.retain_packet(store, _json(private_bytes(args.packet, 500_000))),
                      "publication_approved": False}
        elif args.command == "verify":
            from src.media import gist_published_media as published
            manifest, original, png = published.read(store, args.manifest)
            result = {"product": manifest["product"], "original_sha256": manifest["document"]["original"]["sha256"],
                      "derivative_sha256": manifest["derivative"]["sha256"], "original_bytes": len(original),
                      "derivative_bytes": len(png), "verified": True}
        elif args.command == "export":
            from src.media import gist_media_export as portable
            items = [("published", sha) for sha in args.manifest] + [("crw_packet", sha) for sha in args.crw_packet]
            result = portable.export(store, items, args.target)
        elif args.command == "restore":
            from src.media import gist_media_export as portable
            result = portable.restore(store, args.source)
        elif args.command == "readback":
            from src.media import gist_crw_media as crw, gist_published_media as published
            if not args.manifest and not args.crw_packet:
                raise SystemExit("readback needs at least one --manifest or --crw-packet identity")
            items = []
            for sha in args.manifest:
                manifest, original, png = published.read(store, sha)
                items.append({"kind": "published", "manifest_sha256": sha, "product": manifest["product"],
                              "original_bytes": len(original), "derivative_bytes": len(png), "verified": True})
            for sha in args.crw_packet:
                packet = crw.load_packet(store, sha)
                items.append({"kind": "crw_packet", "packet_artifact_sha256": sha,
                              "packet_bytes": len(gist_assets.encode_document(packet)), "verified": True})
            result = {"capability": "reader", "store_kind": type(store).__name__, "items": items,
                      "credentials_printed": False, "publication_approved": False}
        elif args.command == "plan":
            from src.media import gist_media_export as portable
            result = portable.plan(store, _json(private_bytes(args.state, 32 * 1024 * 1024)))
        else:
            copy = store.backup(args.target)
            result = {"backup": str(copy.path), "verified": True}
    except ValueError as exc:
        print(json.dumps({"held": getattr(exc, "code", "media_asset_invalid"), "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
