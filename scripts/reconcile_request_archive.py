#!/usr/bin/env python3
"""Offline usage and operator-supplied billing reconciliation for private archives.

Commands: validate (one billing file), reconcile (archives + billing + optional
retained state -> private JSON/Markdown), inspect (verify a report), export
(Markdown from a verified report). Nothing calls a provider, reads Gist/DB
state, follows a URL or a path found inside an input file, settles a hold or
changes a budget. Every input is an explicit absolute owner-only file.

Exit codes: 0 ok, 1 completed with incomplete/rejected inputs, 2 refused/invalid, 64 usage.
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


def _read(path: str, limit: int = MAX_STANDALONE_BYTES) -> bytes:
    from src.two_bot.request_archive import RequestArchiveRefused, read_private_file, require_private_directory
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise RequestArchiveRefused("private_path_not_canonical")
    require_private_directory(os.path.dirname(path), create=False)
    return read_private_file(path, limit)


def _directory_bytes(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path, followlinks=False):
        total += sum(os.lstat(os.path.join(root, name)).st_size for name in files)
    return total


def _as_of(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError("as_of_not_aware")
    return moment


def main(argv: list[str] | None = None) -> int:
    from src.evaluation import invoice_evidence as evidence
    from src.two_bot.request_archive import (RequestArchiveError, require_private_directory, strict_json_loads,
                                             write_private_file_exclusive)

    parser = argparse.ArgumentParser(prog="reconcile_request_archive", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("billing")
    validate.add_argument("--document", help="original document file whose sha256 the evidence declares")
    rec = commands.add_parser("reconcile")
    rec.add_argument("--archive", action="append", default=[], required=True)
    rec.add_argument("--billing", action="append", default=[])
    rec.add_argument("--billing-with-document", nargs=2, action="append", default=[], metavar=("BILLING", "DOCUMENT"))
    rec.add_argument("--account-binding", action="append", default=[], help="provider:account[:project]")
    rec.add_argument("--state", help="optional retained state JSON file (read, never rewritten)")
    rec.add_argument("--scenario", help="explicit named price scenario, e.g. google-standard-paid-2026-10-02")
    rec.add_argument("--as-of", required=True, help="aware ISO time; the only clock used")
    rec.add_argument("--output-dir", required=True, help="existing absolute 0700 directory")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("report")
    export = commands.add_parser("export")
    export.add_argument("report")
    export.add_argument("--output", required=True, help="absolute NEW .md file in a 0700 directory")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    try:
        if args.command == "validate":
            document = _read(args.document) if args.document else None
            parsed = evidence.parse_billing_evidence(_read(args.billing), original_document=document)
            _emit({"status": "valid", "schema": parsed["schema"], "document_id": parsed["document_id"],
                   "provider": parsed["provider"], "statement": parsed["statement"], "currency": parsed["currency"],
                   "items": len(parsed["items"]), "totals": parsed["totals"], "document_check": parsed["document_check"],
                   "coverage": parsed["coverage"], "evidence_sha256": parsed["evidence_sha256"],
                   "file_sha256": parsed["file_sha256"]})
            return 0
        if args.command in ("inspect", "export"):
            report = evidence.verify_report(strict_json_loads(_read(args.report, 64 * 1024 * 1024),
                                                              allow_floats=True))
            if args.command == "inspect":
                _emit({"status": "verified", "report_sha256": report["report_sha256"], "as_of": report["as_of"],
                       "denominators": report["observed"]["denominators"],
                       "matches": len(report["reconciliation"]["matches"]),
                       "unmatched_billing_items": len(report["reconciliation"]["unmatched_billing_items"]),
                       "quarantined": len(report["supplied_billing"]["quarantined"])})
                return 0
            output = args.output
            if not os.path.isabs(output) or not output.endswith(".md"):
                _emit({"error": "export_requires_absolute_md_path"})
                return 64
            directory = require_private_directory(os.path.dirname(output), create=False)
            written = write_private_file_exclusive(directory, os.path.basename(output),
                                                   evidence.render_markdown(report).encode("utf-8"))
            _emit({"status": "written" if written else "identical_existing", "report_sha256": report["report_sha256"]})
            return 0
        return _reconcile(args, evidence)
    except (RequestArchiveError, evidence.BillingEvidenceInvalid) as exc:
        _emit({"error": getattr(exc, "code", None) or str(exc)})
        return 2
    except ValueError as exc:
        _emit({"error": str(exc) if str(exc).isidentifier() else "invalid_input"})
        return 2
    except OSError as exc:
        _emit({"error": "filesystem_error", "errno": exc.errno})
        return 2


def _reconcile(args, evidence) -> int:
    from src.evaluation import archive_usage
    from src.two_bot.request_archive import (RequestArchiveRefused, require_private_directory, sha256_hex,
                                             strict_json_loads, write_private_file_exclusive)
    from src.two_bot.request_archive_replay import load_archive
    from src.two_bot.usage_summary import summarize_usage

    as_of = _as_of(args.as_of)
    output_dir = require_private_directory(args.output_dir, create=False)
    budget = sum(_directory_bytes(path) for path in args.archive)
    if budget > MAX_TOTAL_INPUT_BYTES:
        raise RequestArchiveRefused("diagnosis_input_over_limit")
    archives = [load_archive(path) for path in args.archive]
    files = [{"role": "archive_manifest", "sha256": a.manifest_sha256,
              "bytes": os.lstat(a.directory / "manifest.jsonl").st_size} for a in archives]
    documents, rejected = [], []
    pairs = [(path, None) for path in args.billing] + [tuple(pair) for pair in args.billing_with_document]
    for billing_path, document_path in pairs:
        data = _read(billing_path)
        original = _read(document_path) if document_path else None
        budget += len(data) + len(original or b"")
        if budget > MAX_TOTAL_INPUT_BYTES:
            raise RequestArchiveRefused("diagnosis_input_over_limit")
        files.append({"role": "billing_evidence", "sha256": sha256_hex(data), "bytes": len(data)})
        if original is not None:
            files.append({"role": "original_document", "sha256": sha256_hex(original), "bytes": len(original)})
        try:
            documents.append(evidence.parse_billing_evidence(data, original_document=original))
        except evidence.BillingEvidenceInvalid as exc:
            rejected.append({"file_sha256": sha256_hex(data), "reason": str(exc)})
    bindings = [evidence.parse_account_binding(value) for value in args.account_binding]
    state_summary = None
    if args.state:
        data = _read(args.state)
        budget += len(data)
        if budget > MAX_TOTAL_INPUT_BYTES:
            raise RequestArchiveRefused("diagnosis_input_over_limit")
        files.append({"role": "retained_state", "sha256": sha256_hex(data), "bytes": len(data)})
        state = strict_json_loads(data, allow_floats=True)
        if type(state) is not dict:
            raise ValueError("state_not_object")
        state_summary = {"source": "explicit_retained_state_file_read_only",
                         **summarize_usage(state, now=as_of)}
    usage = archive_usage.archive_usage(archives)
    scenario = archive_usage.priced_scenario(usage, args.scenario) if args.scenario else None
    report = evidence.build_report(as_of=as_of, usage=usage, documents=documents, rejected_billing=rejected,
                                   bindings=bindings, scenario=scenario, state_summary=state_summary,
                                   input_files=files)
    data = evidence.report_bytes(report)
    markdown = evidence.render_markdown(report).encode("utf-8")
    written = [write_private_file_exclusive(output_dir, "reconciliation.json", data),
               write_private_file_exclusive(output_dir, "reconciliation.md", markdown)]
    identity = report["inputs"]["identity_reconciliation"]
    degraded = bool(rejected) or any(a.status != "complete" for a in archives) or bool(
        report["supplied_billing"]["quarantined"]) or identity["status"] != "consistent"
    _emit({"status": "completed_with_gaps" if degraded else "completed",
           "report_sha256": report["report_sha256"],
           "written": ["new" if w else "identical_existing" for w in written],
           "denominators": report["observed"]["denominators"],
           "identity": {key: identity[key] for key in ("status", "supplied_inputs", "counted_captures",
                                                       "duplicate_inputs", "quarantined_inputs")},
           "token_totals_status": report["observed"]["token_totals_status"],
           "matches": len(report["reconciliation"]["matches"]),
           "unmatched_billing_items": len(report["reconciliation"]["unmatched_billing_items"]),
           "conflicting_matches": len(report["reconciliation"]["conflicting_matches"]),
           "quarantined": len(report["supplied_billing"]["quarantined"]),
           "rejected_billing_files": len(rejected), "content_written_to_stdout": False})
    return 1 if degraded else 0


if __name__ == "__main__":
    sys.exit(main())
