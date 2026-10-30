"""Offline fixture runner for the experimental local command authority.

The operator file is trusted local test configuration, not authentication. This
CLI is deliberately unavailable for production and has no publication adapter.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import sqlite3

from src.commands.domain_journal import DomainJournalError, inspect as inspect_domain, parse_snapshot
from src.commands.domain_projection import DomainProjectionError, read_packets
from src.commands.schema import Command, CommandError, Principal, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority


def _read(path: str) -> dict:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise CommandError("invalid_fixture", "Fixture must be a JSON object")
    return value


def _resolve(path: str, subject: str) -> Principal | None:
    # Re-read on execution so a local role revocation is effective while draining.
    row = _read(path).get(subject)
    if row is None:
        return None
    if not isinstance(row, dict) or set(row) != {"role", "authentication_context"}:
        raise CommandError("invalid_fixture", "Operator fixture must contain role and authentication_context")
    return Principal(subject, row["role"], row["authentication_context"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Separate local SQLite file; never the bot's existing store")
    parser.add_argument("--environment", choices=("local", "preview"), default="local")
    actions = parser.add_subparsers(dest="action", required=True)
    initialize = actions.add_parser("init")
    initialize.add_argument("--state", required=True, help="Offline initial state fixture")
    initialize.add_argument("--source-namespace", default="local-fixtures", help="Stable source identity for draft aliases across imports")
    importer = actions.add_parser("import")
    importer.add_argument("--state", required=True, help="Private snapshot retained as evidence; does not change current state")
    importer.add_argument("--import-id", required=True, help="Stable identity for idempotent replay of these exact bytes")
    actions.add_parser("domain-migrate", help="Explicit v1->v2 domain journal migration (reconciliation/restore origins)")
    domain = actions.add_parser("domain-status")
    domain.add_argument("--verify", action="store_true", help="Verify retained artifact hashes and foreign keys")
    domain.add_argument("--projection-record", action="append", default=[], metavar="FILE",
        help="Explicit bounded owner-artifact packet; proves integrity only, not ownership or truth")
    submit = actions.add_parser("submit")
    submit.add_argument("--request", required=True)
    submit.add_argument("--operators", required=True, help="Trusted local operator fixture, not a hosted identity provider")
    submit.add_argument("--subject", required=True)
    drain = actions.add_parser("drain")
    drain.add_argument("--operators", required=True)
    drain.add_argument("--limit", type=int, default=100)
    actions.add_parser("status")
    jobs = actions.add_parser("jobs", help="Read-only overdue job inspection and scheduled-role diagnosis")
    jobs.add_argument("--workflow-health", help="Offline JSON list of existing workflow-health classifications")
    jobs.add_argument("--disabled", action="append", default=[], help="Workflow intentionally disabled")
    recover = actions.add_parser("recover", help="Release never-granted work or record reconciliation; never resends")
    recover.add_argument("--job-id", required=True)
    recover.add_argument("--operation", choices=("release_unstarted", "reconcile"), required=True)
    import_plan_parser = actions.add_parser("import-plan", help="Lossless pre-mutation import plan; writes nothing")
    import_plan_parser.add_argument("--item", action="append", required=True, metavar="IMPORT_ID=FILE")
    import_run = actions.add_parser("import-run", help="Resumable idempotent import of a reviewed plan")
    import_run.add_argument("--plan", required=True)
    import_run.add_argument("--item", action="append", required=True, metavar="IMPORT_ID=FILE")
    restore = actions.add_parser("restore-plan", help="Verify a backup against this authority; writes nothing")
    restore_run = actions.add_parser("restore-run", help="Re-verify a reviewed restore plan, then append only")
    for sub in (restore, restore_run):
        sub.add_argument("--backup", required=True)
        sub.add_argument("--expected-sha256", required=True)
        sub.add_argument("--restore-id", required=True)
        sub.add_argument("--media-export", help="theheat_media_export_v1 directory")
    restore_run.add_argument("--plan", required=True)
    restore_run.add_argument("--media-store", help="Insert-only target SQLite media store")
    delivery = actions.add_parser("delivery", help="Inspect, confirm or cancel a publish attempt; never sends")
    delivery.add_argument("operation", choices=("inspect", "confirm", "cancel"))
    delivery.add_argument("--request", help="Reconciliation request JSON (confirm/cancel)")
    delivery.add_argument("--operators")
    delivery.add_argument("--subject")
    args = parser.parse_args(argv)
    try:
        store = SQLiteAuthority(args.database, environment=args.environment)
        if args.action == "init":
            raw = Path(args.state).read_bytes()
            store.initialize(parse_snapshot(raw), source_namespace=args.source_namespace, raw=raw)
            output = {"initialized": True, "environment": args.environment}
        elif args.action == "import":
            output = store.import_snapshot(Path(args.state).read_bytes(), import_id=args.import_id)
        elif args.action == "domain-migrate":
            output = store.migrate_domain()
        elif args.action == "domain-status":
            if args.projection_record:
                records = read_packets(args.projection_record)
                with closing(store._connect()) as connection:
                    connection.execute("PRAGMA query_only=ON")
                    connection.execute("BEGIN")
                    store._check_environment(connection)
                    output = inspect_domain(connection, verify=args.verify, projection_records=records)
            else:
                output = store.domain_status(verify=args.verify)
        elif args.action == "submit":
            principal = _resolve(args.operators, args.subject)
            if principal is None:
                raise CommandError("forbidden", "No local operator fixture exists for this subject")
            now = datetime.now(UTC)
            command = Command.from_request(_read(args.request), principal, environment=args.environment, now=now)
            output = store.accept(command, principal, now=now)
        elif args.action == "drain":
            if not 1 <= args.limit <= 1000:
                raise CommandError("invalid_limit", "Drain limit must be between 1 and 1000")
            results = []
            for _ in range(args.limit):
                result = store.consume(lambda subject: _resolve(args.operators, subject))
                if result is None:
                    break
                results.append(result)
            output = {"results": results, "automatic_publication_enabled": False}
        elif args.action in {"import-plan", "import-run"}:
            from src.commands import import_plan
            pairs = [value.split("=", 1) for value in args.item]
            if any(len(pair) != 2 for pair in pairs):
                raise CommandError("invalid_import_item", "Use IMPORT_ID=FILE")
            items = [(name, Path(path).read_bytes()) for name, path in pairs]
            if args.action == "import-plan":
                output = import_plan.plan(items, authority=store)
            else:
                output = import_plan.execute(store, _read(args.plan), items)
        elif args.action in {"restore-plan", "restore-run"}:
            from src.commands import restore_plan
            backup = Path(args.backup).read_bytes()
            if args.action == "restore-plan":
                output = restore_plan.plan(store, backup, expected_sha256=args.expected_sha256, restore_id=args.restore_id,
                                           now=datetime.now(UTC), media_export=args.media_export)
            else:
                writer = None
                if args.media_store:
                    from src.media import gist_assets
                    writer = gist_assets.SQLiteMediaStore(args.media_store)
                output = restore_plan.execute(store, _read(args.plan), backup, expected_sha256=args.expected_sha256,
                                              now=datetime.now(UTC), media_export=args.media_export, media_writer=writer)
        elif args.action == "delivery":
            from src.commands import delivery_reconciliation
            if args.operation == "inspect":
                output = delivery_reconciliation.inspect(store.read()[1])
            else:
                principal = _resolve(args.operators, args.subject) if args.operators and args.subject else None
                if principal is None:
                    raise CommandError("forbidden", "No local operator fixture exists for this subject")
                request = _read(args.request)
                if request.get("action") != args.operation:
                    raise CommandError("reconciliation_action_invalid", "Request action must match the operation")
                output = store.delivery_reconciliation(request, principal)
        elif args.action == "jobs":
            from src.commands import job_recovery
            now = datetime.now(UTC)
            inspection = job_recovery.inspect_jobs(store, now=now)
            health = json.loads(Path(args.workflow_health).read_text()) if args.workflow_health else []
            if not isinstance(health, list):
                raise CommandError("invalid_fixture", "Workflow health must be a JSON list")
            schedules = job_recovery.diagnose_schedules(health, now=now, disabled=args.disabled)
            output = {"inspection": inspection, "schedules": schedules,
                      "holds": job_recovery.operations_holds(schedules, inspection)}
        elif args.action == "recover":
            from src.commands import job_recovery
            from src.commands.job_authority import RoleBoundAuthority, ServiceIdentity
            maintenance = RoleBoundAuthority(store, ServiceIdentity("maintenance", "local-cli-maintenance"))
            operation = job_recovery.release_unstarted if args.operation == "release_unstarted" else job_recovery.reconcile
            output = operation(maintenance, args.job_id, now=datetime.now(UTC))
        else:
            version, _ = store.read()
            events = store.journal()
            accepted = sum(row["event"] == "accepted" for row in events)
            completed = sum(row["event"] == "completed" for row in events)
            output = {"environment": args.environment, "state_version": version,
                      "accepted": accepted, "completed": completed, "pending": accepted - completed}
        print(canonical_json(output))
        return 0
    except (CommandError, DomainJournalError, DomainProjectionError, sqlite3.DatabaseError, OSError, ValueError) as exc:
        # ReconciliationError is a ValueError carrying its bounded refusal code.
        print(canonical_json({"error": getattr(exc, "code", "local_fixture_error"), "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
