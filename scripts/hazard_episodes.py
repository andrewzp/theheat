#!/usr/bin/env python3
"""Operator commands over a retained hazard-episode ledger (W07). Offline only.

inspect      show an episode, its history, relationships and report joins
split        move named source revisions to a new episode (expected revision required)
reassign     move one source revision between episodes (expected revisions required)
supersede    mark an episode superseded by another (expected revision required)
remove-join  withdraw a report↔physical join (report hash stays retained)
publish      project each episode's status, relationships and report joins onto the drafts
             bound to it in --state, so the normal editor can inspect and correct them

Mutations write the ledger atomically and, with --state, revoke review/approval of
pending dependent drafts in that state snapshot (delivered/unknown ones untouched).
Exit codes: 0 done, 2 refused, 64 usage.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _write(path: str, value: object) -> None:
    tmp = Path(path + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=1) + "\n")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    from src.editorial import hazard_episodes as he

    parser = argparse.ArgumentParser(prog="hazard_episodes")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--state")
    parser.add_argument("--actor", default="operator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect").add_argument("--episode", required=True)
    sp = sub.add_parser("split")
    sp.add_argument("--episode", required=True)
    sp.add_argument("--revision", action="append", required=True)
    sp.add_argument("--new-source-id", required=True)
    sp.add_argument("--expected", type=int, required=True)
    sp.add_argument("--evidence-packet-sha256")
    ra = sub.add_parser("reassign")
    ra.add_argument("--revision", required=True)
    ra.add_argument("--from-episode", required=True)
    ra.add_argument("--to-episode", required=True)
    ra.add_argument("--expected-from", type=int, required=True)
    ra.add_argument("--expected-to", type=int, required=True)
    su = sub.add_parser("supersede")
    su.add_argument("--episode", required=True)
    su.add_argument("--by", required=True)
    su.add_argument("--expected", type=int, required=True)
    rj = sub.add_parser("remove-join")
    rj.add_argument("--join-id", required=True)
    sub.add_parser("publish")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 64
    try:
        ledger = json.loads(Path(args.ledger).read_text())
        if ledger.get("schema") != he.SCHEMA:
            raise ValueError("ledger_schema")
        if args.command == "inspect":
            episode = ledger["episodes"][args.episode]
            sys.stdout.write(json.dumps({
                "episode": episode,
                "relationships": [r for r in ledger["relationships"] if args.episode in r["episodes"]],
                "report_joins": [j for j in ledger["report_joins"] if j["episode_id"] == args.episode],
                "writer_statements": he.writer_statements(ledger, args.episode)}, sort_keys=True, indent=1) + "\n")
            return 0
        if args.command == "publish":
            if not args.state:
                raise ValueError("publish_requires_state")
            state = json.loads(Path(args.state).read_text())
            published = he.publish_bindings(ledger, state)
            _write(args.state, state)
            _write(args.ledger, ledger)
            sys.stdout.write(json.dumps(published, sort_keys=True) + "\n")
            return 0
        if args.command == "split":
            result = he.split(ledger, args.episode, args.revision, new_source_id=args.new_source_id,
                              expected_revision=args.expected, actor=args.actor,
                              evidence_packet_sha256=args.evidence_packet_sha256)
        elif args.command == "reassign":
            result = he.reassign(ledger, args.revision, source_episode=args.from_episode,
                                 target_episode=args.to_episode, actor=args.actor,
                                 expected_revisions={args.from_episode: args.expected_from,
                                                     args.to_episode: args.expected_to})
        elif args.command == "supersede":
            result = he.supersede(ledger, args.episode, args.by, expected_revision=args.expected, actor=args.actor)
        else:
            result = he.remove_join(ledger, args.join_id, actor=args.actor)
        if args.state:
            state = json.loads(Path(args.state).read_text())
            result["dependents"] = he.invalidate_dependents(state, result["affected_episodes"])
            _write(args.state, state)
        _write(args.ledger, ledger)
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.stdout.write(json.dumps({"refused": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
