#!/usr/bin/env python3
"""Local-only retention of already acquired Gist media inputs into the durable store.

No fetch, upload endpoint, review or approval: this retains exact private files and
prints the immutable identity to select in the Workbench. Inputs must be absolute,
non-symlinked, owner-only (0600) regular files. The store is THEHEAT_MEDIA_STORE or
--store sqlite:<absolute path>.

  retain_gist_media.py published --product nhc_track_cone_v1 --metadata M --original O \
      --product-reference P --reuse-reference R --receipt C
  retain_gist_media.py crw-packet --packet PACKET.json
  retain_gist_media.py verify --manifest SHA256
  retain_gist_media.py backup --target /absolute/new-backup.sqlite3
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
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    if args.store:
        env[gist_assets.ENV] = args.store
    try:
        store = gist_assets.configured(env)
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
