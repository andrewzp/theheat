#!/usr/bin/env python3
"""Offline inspection of private request archives; there is no send mode.

Commands validate, inspect, lineage, reparse, compare and export read only the
retained scope files; reparse runs the real stage parsers on retained responses.
None of them generates text, calls a model, opens a URL, reads
Gist/DB state, executes archive content or alters archive bytes. Default
stdout is a content-free JSON summary; exact content goes only to a new
explicitly named owner-only file via ``export``.

Exit codes: 0 complete, 1 incomplete, 2 invalid or refused, 64 usage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXIT = {"complete": 0, "incomplete": 1, "invalid": 2}


def _emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    from src.two_bot.request_archive import RequestArchiveError
    from src.two_bot import request_archive_replay as replay

    parser = argparse.ArgumentParser(prog="replay_request_archive", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "inspect", "lineage", "reparse"):
        command = commands.add_parser(name)
        command.add_argument("archive", help="absolute path of one scope-<id> directory")
    command = commands.add_parser("compare")
    command.add_argument("archive_a")
    command.add_argument("archive_b")
    command.add_argument("--call-a", type=int)
    command.add_argument("--call-b", type=int)
    command = commands.add_parser("export")
    command.add_argument("archive")
    command.add_argument("--call", type=int, required=True)
    command.add_argument("--output", required=True, help="absolute NEW file in an existing 0700 directory")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        if args.command == "compare":
            left, right = replay.load_archive(args.archive_a), replay.load_archive(args.archive_b)
            result = replay.compare_archives(left, right)
            if args.call_a is not None or args.call_b is not None:
                if args.call_a is None or args.call_b is None:
                    _emit({"error": "compare_requires_both_calls"})
                    return 64
                result["call"] = replay.compare_calls(left, args.call_a, right, args.call_b)
            _emit(result)
            return max(EXIT[left.status], EXIT[right.status])
        archive = replay.load_archive(args.archive)
        if args.command == "validate":
            _emit({key: value for key, value in replay.summary(archive).items()
                   if key in ("read_api_version", "scope_id", "status", "problems", "manifest_sha256",
                              "records", "held", "authority")})
        elif args.command == "inspect":
            _emit(replay.summary(archive))
        elif args.command == "lineage":
            _emit({"read_api_version": replay.READ_API_VERSION, "status": archive.status,
                   "generations": replay.lineage(archive), "authority": "mechanical_evidence_only",
                   # Route families exist only in explicit v2 scopes; v1 output is unchanged.
                   **({"routes": replay.route_lineage(archive)} if archive.schema == replay.SCHEMA_V2 else {})})
        elif args.command == "reparse":
            # Real production parsers on retained bytes only; no model/source I/O.
            from src.two_bot.archive_reparse import reparse_archive
            _emit(reparse_archive(archive))
        else:
            outcome = replay.export_call(archive, args.call, args.output)
            _emit({"status": archive.status, "export": outcome, "call": args.call,
                   "content_written_to_stdout": False})
        return EXIT[archive.status]
    except (RequestArchiveError, replay.ArchiveInvalid) as exc:
        _emit({"error": getattr(exc, "code", None) or str(exc)})
        return 2
    except OSError as exc:
        _emit({"error": "filesystem_error", "errno": exc.errno})
        return 2


if __name__ == "__main__":
    sys.exit(main())
