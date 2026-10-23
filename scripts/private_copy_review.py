#!/usr/bin/env python3
"""Private blind copy review: build an offline pack, import exported ballots.

build   verified archives + operator selection -> NEW public pack dir (page assets
        and display data only) + NEW private record (origins/provenance/bindings)
import  private record + ballot files -> private import report via the existing
        comparison summarizer, with an explicit --as-of clock
verify  private record + pack dir -> rebuilt identity and an origin-leak scan

Nothing generates text, calls a model, judges copy, serves a page, reads live
state or follows a path found inside an input. Exit codes: 0 ok, 1 completed
with held/refused items, 2 refused/invalid, 64 usage.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ASSETS = ROOT / "tools/private-copy-review"
ASSET_NAMES = ("index.html", "app.js", "styles.css")
MAX_STANDALONE_BYTES = 8 * 1024 * 1024


def _emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def _aware(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError("time_not_aware")
    return moment


def _read(path: str, limit: int = MAX_STANDALONE_BYTES) -> bytes:
    from src.two_bot.request_archive import RequestArchiveRefused, read_private_file, require_private_directory
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise RequestArchiveRefused("private_path_not_canonical")
    require_private_directory(os.path.dirname(path), create=False)
    return read_private_file(path, limit)


def _json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8")


def leak_scan(pack_dir: Path, private: dict) -> list[str]:
    """Origin/provenance strings that must never appear in exported page assets."""
    from src.two_bot.request_archive import read_private_file
    page = b"".join(read_private_file(pack_dir / name, MAX_STANDALONE_BYTES)
                    for name in (*ASSET_NAMES, "pack-data.js"))
    needles = {"private_mapping", "pairs_input", "side_assignments", "edited_from", "author_assertion", "manual_edit:"}
    for candidate_id, record in private.get("provenance", {}).items():
        needles.add(candidate_id)
        needles.add(str(record.get("scope_id")))
        needles.add(str(record.get("manifest_sha256")))
    for pair in private.get("pairs_input", []):
        for candidate in pair["candidates"]:
            needles.add(candidate["origin"])
    for archive in private.get("archives", []):
        needles.add(str(archive.get("scope_id")))
    return sorted(n for n in needles if n and n != "None" and n.encode("utf-8") in page)


def main(argv: list[str] | None = None) -> int:
    from src.evaluation import private_copy_pack as packs
    from src.two_bot.request_archive import (RequestArchiveError, require_private_directory, sha256_hex,
                                             strict_json_loads, write_private_file_exclusive)
    from src.two_bot.request_archive_replay import load_archive

    parser = argparse.ArgumentParser(prog="private_copy_review", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--selection", required=True)
    build.add_argument("--archive", action="append", default=[], required=True)
    build.add_argument("--created-at", required=True, help="aware ISO time recorded in the pack")
    build.add_argument("--pack-dir", required=True, help="absolute NEW directory for page assets")
    build.add_argument("--private-dir", required=True, help="existing absolute 0700 directory, separate from the pack")
    imp = commands.add_parser("import")
    imp.add_argument("--private", required=True)
    imp.add_argument("--ballot", action="append", default=[], required=True)
    imp.add_argument("--as-of", required=True)
    imp.add_argument("--output-dir", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--private", required=True)
    verify.add_argument("--pack-dir", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        if args.command == "build":
            created = _aware(args.created_at)
            private_dir = require_private_directory(args.private_dir, create=False)
            if os.path.lexists(args.pack_dir):
                raise ValueError("pack_dir_must_be_new")
            if os.path.commonpath([os.path.realpath(args.pack_dir), str(private_dir)]) == str(private_dir):
                raise ValueError("pack_dir_inside_private_dir")
            selection = packs.parse_selection(_read(args.selection))
            archives = [load_archive(path) for path in args.archive]
            public, private, held = packs.build_pack(selection, archives, created_at=created,
                                                     seed=secrets.token_bytes(32))
            held_name = f"held-{selection['selection_sha256'][:16]}.json"
            write_private_file_exclusive(private_dir, held_name, _json(held))
            if public is None:
                _emit({"status": "held_no_pair", "held_pairs": len(held["held_pairs"]), "held_report": held_name,
                       "reasons": sorted({r for h in held["held_pairs"] for r in h["reasons"]})})
                return 1
            pack_dir = require_private_directory(args.pack_dir, create=True)
            for name in ASSET_NAMES:
                write_private_file_exclusive(pack_dir, name, (ASSETS / name).read_bytes())
            write_private_file_exclusive(pack_dir, "pack-data.js", packs.pack_data_script(public))
            private_name = f"pack-private-{public['pack_id']}.json"
            write_private_file_exclusive(private_dir, private_name, _json(private))
            leaks = leak_scan(pack_dir, private)
            if leaks:
                raise ValueError("origin_leak_detected")
            _emit({"status": "pack_built" if not held["held_pairs"] else "pack_built_with_held_pairs",
                   "pack_id": public["pack_id"], "pack_sha256": public["pack_sha256"], "pairs": len(public["pairs"]),
                   "held_pairs": len(held["held_pairs"]), "private_record": private_name, "held_report": held_name,
                   "origin_leak_scan": "clean"})
            return 0 if not held["held_pairs"] else 1
        private = strict_json_loads(_read(args.private))
        if args.command == "verify":
            pack = packs.verify_private_record(private)
            from src.two_bot.request_archive import read_private_file
            data = read_private_file(Path(args.pack_dir) / "pack-data.js", MAX_STANDALONE_BYTES)
            leaks = leak_scan(Path(args.pack_dir), private)
            _emit({"status": "verified" if data == packs.pack_data_script(pack) and not leaks else "mismatch",
                   "pack_id": pack["pack_id"], "page_data_matches": data == packs.pack_data_script(pack),
                   "origin_leaks": len(leaks)})
            return 0 if data == packs.pack_data_script(pack) and not leaks else 2
        output_dir = require_private_directory(args.output_dir, create=False)
        if len(args.ballot) > packs.MAX_BALLOTS:
            raise packs.CopyReviewError("too_many_ballots")
        ballots = [_read(path, packs.MAX_BALLOT_BYTES) for path in args.ballot]
        report = packs.import_ballots(private, ballots, as_of=_aware(args.as_of))
        data = _json(report)
        name = f"import-{report['pack_id']}-{sha256_hex(data)[:12]}.json"
        written = write_private_file_exclusive(output_dir, name, data)
        refused = sum(1 for b in report["ballots"] if b["outcome"] != "ballot_read")
        human, synthetic = report["human_asserted_summary"], report["synthetic_fixture_summary"]
        _emit({"status": "imported" if not (refused or report["conflicts"]) else "imported_with_refusals",
               "report": name, "written": "new" if written else "identical_existing",
               "ballots": len(ballots), "refused_items": refused, "conflicts": len(report["conflicts"]),
               "identical_retries_collapsed": report["identical_retries_collapsed"],
               "real_human_ratings_added": report["real_human_ratings_added"],
               "human_asserted_preferences": human["eligible_preferences_by_display_side"],
               "synthetic_fixture_preferences": synthetic["eligible_preferences_by_display_side"],
               "unrated_pairs": synthetic["unrated_pair_count"] if not human["unique_rating_count"]
               else human["unrated_pair_count"], "publication_approved": False})
        return 0 if not (refused or report["conflicts"]) else 1
    except (RequestArchiveError, packs.CopyReviewError) as exc:
        _emit({"error": getattr(exc, "code", None) or str(exc)})
        return 2
    except ValueError as exc:
        _emit({"error": str(exc) if str(exc).replace("_", "").isalnum() else "invalid_input"})
        return 2
    except OSError as exc:
        _emit({"error": "filesystem_error", "errno": exc.errno})
        return 2


if __name__ == "__main__":
    sys.exit(main())
