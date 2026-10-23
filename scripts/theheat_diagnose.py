#!/usr/bin/env python3
"""One private, offline diagnosis across archives, billing, copy review and receipts.

diagnose     verify every supplied component and its exact lineage, run the existing
             Node weekly/outcome readers on an optional explicit state snapshot, and
             write diagnosis.json/.md/.html plus a completion marker (written last)
verify       restore and verify a written diagnosis in a new process
export-copy  write one archived candidate's exact text and stage reasons to a NEW
             private file (the only command that emits copy, and never to stdout)

No command generates, replays, calls a provider, approves, releases budget, posts,
corrects, reads Gist/DB live state or follows a path found inside an input.
Exit codes: 0 complete, 1 completed with held/absent-lineage components, 2 refused, 64 usage.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_STANDALONE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 128 * 1024 * 1024


def _emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def _aware(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError("as_of_not_aware")
    return moment


def _read(path: str, limit: int = MAX_STANDALONE_BYTES) -> bytes:
    from src.two_bot.request_archive import RequestArchiveRefused, read_private_file, require_private_directory
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise RequestArchiveRefused("private_path_not_canonical")
    require_private_directory(os.path.dirname(path), create=False)
    return read_private_file(path, limit)


def _tree_bytes(path: str) -> int:
    return sum(os.lstat(os.path.join(root, name)).st_size for root, _, files in os.walk(path) for name in files)


def main(argv: list[str] | None = None) -> int:
    from src.evaluation import operator_diagnosis as diagnosis
    from src.two_bot.request_archive import RequestArchiveError

    parser = argparse.ArgumentParser(prog="theheat_diagnose", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("diagnose")
    run.add_argument("--archive", action="append", default=[], required=True)
    run.add_argument("--reconciliation")
    run.add_argument("--copy-private")
    run.add_argument("--copy-import")
    run.add_argument("--state")
    run.add_argument("--feedback")
    run.add_argument("--as-of", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--node", default=diagnosis.NODE, help="explicit pinned Node executable")
    verify = commands.add_parser("verify")
    verify.add_argument("--output-dir", required=True)
    export = commands.add_parser("export-copy")
    export.add_argument("--archive", required=True)
    export.add_argument("--candidate", required=True, help="candidate_text_sha256 from the diagnosis")
    export.add_argument("--output", required=True, help="absolute NEW file in an existing 0700 directory")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        if args.command == "verify":
            result = diagnosis.verify_output(args.output_dir)
            _emit(result)
            return {"complete": 0, "incomplete": 1}.get(result["status"], 2)
        if args.command == "export-copy":
            return _export(args)
        return _diagnose(args, diagnosis)
    except (RequestArchiveError, diagnosis.DiagnosisError) as exc:
        _emit({"error": getattr(exc, "code", None) or str(exc)})
        return 2
    except ValueError as exc:
        _emit({"error": str(exc) if str(exc).replace("_", "").isalnum() else "invalid_input"})
        return 2
    except OSError as exc:
        _emit({"error": "filesystem_error", "errno": exc.errno})
        return 2


def _diagnose(args, diagnosis) -> int:
    from src.two_bot.request_archive import RequestArchiveRefused, sha256_hex, strict_json_loads
    from src.two_bot.request_archive_replay import load_archive

    as_of = _aware(args.as_of)
    budget = sum(_tree_bytes(path) for path in args.archive)
    files = []

    def load(role: str, path: str | None, *, floats: bool = True):
        nonlocal budget
        if path is None:
            return None, None
        data = _read(path)
        budget += len(data)
        if budget > MAX_TOTAL_INPUT_BYTES:
            raise RequestArchiveRefused("diagnosis_input_over_limit")
        files.append({"role": role, "sha256": sha256_hex(data), "bytes": len(data)})
        try:
            return strict_json_loads(data, allow_floats=floats), data
        except (ValueError, UnicodeError):
            return {"unparseable": True}, data

    if budget > MAX_TOTAL_INPUT_BYTES:
        raise RequestArchiveRefused("diagnosis_input_over_limit")
    archives = [load_archive(path) for path in args.archive]
    files += [{"role": "archive_manifest", "sha256": a.manifest_sha256,
               "bytes": os.lstat(a.directory / "manifest.jsonl").st_size} for a in archives]
    reconciliation, _ = load("reconciliation_report", args.reconciliation)
    copy_private, _ = load("copy_review_private_record", args.copy_private, floats=False)
    copy_import, _ = load("copy_review_import_report", args.copy_import)
    state, _ = load("retained_state", args.state)
    feedback, _ = load("feedback_records", args.feedback)
    readers = None
    if args.state:
        readers = diagnosis.run_review_readers(node=args.node, state_path=args.state, feedback_path=args.feedback,
                                               as_of=as_of)
    components, usable = diagnosis.verify_components(
        archives=archives, reconciliation=reconciliation, copy_private=copy_private, copy_import=copy_import,
        readers=readers, state=state, feedback=feedback, as_of=as_of)
    report = diagnosis.diagnose(archives=archives, components=components, usable=usable, as_of=as_of,
                                input_files=files)
    written = diagnosis.write_report(args.output_dir, report)
    held = [c for c in components if c["status"] not in ("complete", "verified", "absent")]
    _emit({"status": "completed_with_held_components" if held else "completed",
           "report_sha256": report["report_sha256"], "written": written,
           "held_components": [{"component": c["component"], "status": c["status"]} for c in held],
           "candidates": len(report["candidates"]), "generations": len(report["generations"]),
           "unjoined_posts": len(report["unjoined_posts"]), "promotion": "HOLD", "content_written_to_stdout": False})
    return 1 if held else 0


def _export(args) -> int:
    from src.two_bot.request_archive import RequestArchiveRefused, require_private_directory, write_private_file_exclusive
    from src.two_bot.request_archive_replay import load_archive

    archive = load_archive(args.archive)
    if archive.status == "invalid":
        _emit({"error": "archive_invalid"})
        return 2
    output = args.output
    if not os.path.isabs(output):
        raise RequestArchiveRefused("private_path_not_absolute")
    directory = require_private_directory(os.path.dirname(output), create=False)
    matches = [c for c in archive.candidates if c["candidate_text_sha256"] == args.candidate]
    if not matches:
        _emit({"error": "candidate_not_in_archive"})
        return 2
    if len(matches) != 1:
        _emit({"error": "candidate_identity_ambiguous"})
        return 2
    record = matches[0]
    inputs = [i for i in archive.inputs if i["seq"] < record["seq"]]
    if not inputs:
        _emit({"error": "candidate_input_unavailable"})
        return 2
    generation = inputs[-1]
    stop = next((r["seq"] for r in archive.records if r["seq"] > record["seq"]
                 and r["type"] in ("candidate", "generation_input", "terminal")), len(archive.records) + 1)
    reasons = [{"stage": o["stage"], "outcome": o["outcome"], "reason": archive.artifact(o["reason_artifact"]).decode("utf-8")}
               for o in archive.stage_outcomes if record["seq"] < o["seq"] < stop and o.get("reason_artifact")
               and (o.get("binding") or {}).get("candidate_text_sha256") == args.candidate]
    payload = {"schema": "theheat.private-candidate-export/v1", "scope_id": archive.scope_id,
               "archive_status": archive.status, "candidate_text_sha256": args.candidate,
               "text": archive.artifact(record["text_artifact"]).decode("utf-8"), "attempt": record.get("attempt"),
               "bundle_sha256": generation["bundle_sha256"], "stage_reasons": reasons,
               "authority": "private_mechanical_evidence_only"}
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    written = write_private_file_exclusive(directory, os.path.basename(output), data)
    _emit({"status": "written" if written else "identical_existing", "content_written_to_stdout": False})
    return 0


if __name__ == "__main__":
    sys.exit(main())
