"""Offline all-writer inventory and fail-closed backend-cutover compatibility.

This module never activates a fence, rotates a credential, contacts a store or
adopts a hosted resource. It names every existing writer (source, editor,
archive, batch, check, maintenance, metrics and sender), the store it mutates
and the guard it actually has, then answers whether an explicit future cutover
could be fenced. Gist GET-then-PATCH is not a transaction and is never counted
as a fence. A supplied ``WriterGenerationRegistry`` refuses retired or
unauthorized producer generations at the worker adapter; without one nothing
is enforced (the current, unactivated state).
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import sys

from src.commands.command_roles import RoleError

KINDS = ("source", "editor", "archive", "batch", "check", "maintenance", "metrics", "sender")
STORES = ("gist_state", "request_archive_files", "command_authority", "x_platform", "bluesky_platform")
TARGETS = ("command_authority_sqlite", "command_authority_postgres")


@dataclass(frozen=True)
class Writer:
    name: str
    kind: str
    call_site: str  # module:qualname, or repository path:exported name for JS
    store: str
    guard: str
    fenced: bool  # True only for a durable owner/lease/transaction refusal


WRITERS: tuple[Writer, ...] = (
    Writer("bot_state", "source", "src.state:write_state", "gist_state", "expected_draft_get_then_patch", False),
    Writer("draft_save", "source", "src.orchestrator.draft_save:save_draft", "gist_state", "via_write_state", False),
    Writer("nhc_advisory_import", "source", "scripts/nhc_advisory_import.py:execute", "gist_state",
           "expected_state_sha256_get_then_patch", False),
    Writer("dashboard_editor", "editor", "dashboard/lib/state-store.js:updateDraftStore", "gist_state",
           "expected_revision_get_then_patch", False),
    Writer("dashboard_state", "editor", "dashboard/lib/state-store.js:writeStateStore", "gist_state",
           "get_then_patch", False),
    Writer("metrics", "metrics", "src.orchestrator.hot10:_run_twitter_metrics", "gist_state", "via_write_state", False),
    Writer("request_archive", "archive", "src.two_bot.request_archive:write_private_file_exclusive",
           "request_archive_files", "exclusive_create_content_addressed", True),
    Writer("command_authority:operator", "editor", "src.commands.sqlite_authority:SQLiteAuthority.consume",
           "command_authority", "serialized_transaction_expected_revision_role_map", True),
    Writer("command_authority:producer", "batch", "src.commands.job_authority:RoleBoundAuthority.batch_work",
           "command_authority", "lease_fence_owner_binding_role_map", True),
    Writer("command_authority:checker", "check", "src.commands.job_authority:RoleBoundAuthority.candidate_checks",
           "command_authority", "lease_fence_owner_binding_role_map", True),
    Writer("command_authority:maintenance", "maintenance", "src.commands.job_authority:RoleBoundAuthority.spending",
           "command_authority", "serialized_transaction_role_map", True),
    Writer("x_sender", "sender", "src.orchestrator.posting:post_approved", "x_platform",
           "publish_ledger_intent_then_single_send", False),
    Writer("bluesky_sender", "sender", "src.posting.bluesky:post_to_bluesky", "bluesky_platform", "none", False),
)
_BY_NAME = {row.name: row for row in WRITERS}


def inventory() -> list[dict]:
    return [{"name": w.name, "kind": w.kind, "call_site": w.call_site, "store": w.store,
             "guard": w.guard, "fenced": w.fenced} for w in WRITERS]


def compatibility(target: str) -> dict:
    """Fail closed: a cutover is compatible only when no unfenced writer remains.

    A Gist-state writer must be retired or rerouted through the target before
    cutover; a platform sender must have reconciled outcomes. Nothing activates.
    """
    if target not in TARGETS:
        raise RoleError("unknown_cutover_target", "Unknown backend cutover target")
    blockers = []
    for writer in WRITERS:
        if writer.store == "gist_state":
            blockers.append({"writer": writer.name, "code": "gist_writer_not_rerouted",
                             "reason": "Writes the production Gist; GET-then-PATCH cannot be fenced"})
        elif not writer.fenced and writer.store in {"x_platform", "bluesky_platform"}:
            blockers.append({"writer": writer.name, "code": "platform_sender_unfenced",
                             "reason": "Sends to a platform without a durable owner fence"})
        elif not writer.fenced:
            blockers.append({"writer": writer.name, "code": "unfenced_writer", "reason": "No durable fence"})
    return {"target": target, "compatible": not blockers, "activation": "not_performed",
            "gist_transactional": False, "writers": len(WRITERS), "blockers": blockers}


class WriterGenerationRegistry:
    """Explicit allowed/retired producer generations, supplied by a future cutover."""

    def __init__(self, *, authorized: Mapping[str, Iterable[str]], retired: Mapping[str, Iterable[str]] | None = None):
        self.authorized = {self._writer(k): frozenset(v) for k, v in authorized.items()}
        self.retired = {self._writer(k): frozenset(v) for k, v in (retired or {}).items()}

    @staticmethod
    def _writer(name: str) -> str:
        if name not in _BY_NAME:
            raise RoleError("unknown_writer", "Writer is not in the offline inventory")
        return name

    def check(self, writer: str, generation: str) -> None:
        self._writer(writer)
        if generation in self.retired.get(writer, frozenset()):
            raise RoleError("retired_writer_generation_refused", "This producer generation has been retired")
        if generation not in self.authorized.get(writer, frozenset()):
            raise RoleError("unauthorized_writer_generation_refused", "This producer generation is not authorized")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline writer inventory; never activates a fence")
    parser.add_argument("--target", choices=TARGETS, required=True)
    args = parser.parse_args(argv)
    json.dump({"inventory": inventory(), "compatibility": compatibility(args.target)}, sys.stdout,
              sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
