"""Offline fixture runner for the experimental local command authority.

The operator file is trusted local test configuration, not authentication. This
CLI is deliberately unavailable for production and has no publication adapter.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import sqlite3

from src.commands.domain_journal import DomainJournalError, parse_snapshot
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
    domain = actions.add_parser("domain-status")
    domain.add_argument("--verify", action="store_true", help="Verify retained artifact hashes and foreign keys")
    submit = actions.add_parser("submit")
    submit.add_argument("--request", required=True)
    submit.add_argument("--operators", required=True, help="Trusted local operator fixture, not a hosted identity provider")
    submit.add_argument("--subject", required=True)
    drain = actions.add_parser("drain")
    drain.add_argument("--operators", required=True)
    drain.add_argument("--limit", type=int, default=100)
    actions.add_parser("status")
    args = parser.parse_args(argv)
    try:
        store = SQLiteAuthority(args.database, environment=args.environment)
        if args.action == "init":
            raw = Path(args.state).read_bytes()
            store.initialize(parse_snapshot(raw), source_namespace=args.source_namespace, raw=raw)
            output = {"initialized": True, "environment": args.environment}
        elif args.action == "import":
            output = store.import_snapshot(Path(args.state).read_bytes(), import_id=args.import_id)
        elif args.action == "domain-status":
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
        else:
            version, _ = store.read()
            events = store.journal()
            accepted = sum(row["event"] == "accepted" for row in events)
            completed = sum(row["event"] == "completed" for row in events)
            output = {"environment": args.environment, "state_version": version,
                      "accepted": accepted, "completed": completed, "pending": accepted - completed}
        print(canonical_json(output))
        return 0
    except (CommandError, DomainJournalError, sqlite3.DatabaseError, OSError, ValueError) as exc:
        print(canonical_json({"error": getattr(exc, "code", "local_fixture_error"), "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
