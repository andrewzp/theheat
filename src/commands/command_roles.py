"""One binding map from roles to existing commands, capabilities and transitions.

Human operators keep the three existing ingress roles (viewer/editor/publisher)
resolved from an authenticated adapter. Automated workers use separate service
roles that no operator file or request body can name. Every mutation keeps its
existing command or trusted-method boundary; this module only binds who may
call it and which draft-status transition it may produce. It is not a new
permissions language: the vocabulary is the existing action and method names.

Gist remains the production draft store. Its dashboard path authenticates one
shared credential and cannot distinguish roles; that limitation is recorded
here rather than implied away.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.commands.schema import CommandError

HUMAN_ROLES = ("viewer", "editor", "publisher")
SERVICE_ROLES = ("producer", "checker", "media", "maintenance", "delivery")
DRAFT_STATUSES = ("pending", "approved", "rejected")

_EDIT = frozenset({"editor", "publisher"})
_PUBLISH = frozenset({"publisher"})
_OPEN = frozenset({"pending", "approved"})
_PENDING = frozenset({"pending"})


@dataclass(frozen=True)
class OperatorCommand:
    action: str
    capability: str
    roles: frozenset[str]
    # None: the command targets no draft (source, coverage, report, generation,
    # candidate). Such a command may create pending drafts but never approve or
    # remove one. The verified GHCN source-result invalidation below is the sole
    # exception for an existing draft: approved -> pending with approval cleared.
    from_statuses: frozenset[str] | None
    to_statuses: frozenset[str] | None


def _op(action, capability, roles, start=None, end=None):
    return OperatorCommand(action, capability, frozenset(roles), start, end)


OPERATOR_COMMANDS: dict[str, OperatorCommand] = {row.action: row for row in (
    _op("commit_nhc_source_run", "source.commit", _EDIT),
    _op("commit_ghcn_source_run", "source.commit", _EDIT),
    _op("evaluate_reference_coverage", "coverage.evaluate", _EDIT),
    _op("open_report_evidence", "report.open", _EDIT),
    _op("request_sourced_generation", "generation.request", _EDIT),
    _op("request_important_variants", "generation.request", _EDIT),
    _op("request_candidate_checks", "candidate.request_checks", _EDIT),
    _op("admit_checked_candidate", "candidate.admit", _EDIT),
    _op("admit_checked_slate", "candidate.admit", _EDIT),
    _op("edit_revision", "draft.edit", _EDIT, _OPEN, _PENDING),
    _op("select_candidate", "draft.edit", _EDIT, _OPEN, _PENDING),
    _op("record_review", "draft.review", _EDIT, _PENDING, _PENDING),
    _op("approve_revision", "draft.approve", _PUBLISH, _PENDING, frozenset({"approved"})),
    _op("schedule_revision", "draft.schedule", _PUBLISH, _PENDING, _PENDING),
    _op("cancel_approval", "draft.cancel_approval", _EDIT, _OPEN, _PENDING),
    _op("reject_revision", "draft.reject", _EDIT, _OPEN, frozenset({"rejected"})),
    _op("bulk_reject", "draft.reject", _EDIT, _PENDING, frozenset({"rejected"})),
    # Media approval parks a reviewed graphic; it never approves publication.
    _op("prepare_media_revision", "media.prepare", _EDIT, _OPEN, _PENDING),
    _op("request_revision_checks", "media.request_checks", _EDIT, _OPEN, _PENDING),
    _op("approve_media_revision", "media.approve", _PUBLISH, _OPEN, _PENDING),
    _op("attach_media_revision", "media.attach", _EDIT, _OPEN, _PENDING),
    _op("review_media_revision", "media.review", _EDIT, _OPEN, _PENDING),
    _op("remove_media_revision", "media.remove", _EDIT, _OPEN, _PENDING),
    # Existing authority-internal checks that are not draft commands.
    _op("stage_media_proposal", "media.stage", _EDIT),
    _op("abandon_submission", "command.abandon_own_submission", _EDIT),
)}


@dataclass(frozen=True)
class ServiceOperation:
    surface: str
    action: str
    capability: str
    roles: frozenset[str]
    writes: bool
    enforced_at: str


_SQLITE = "src.commands.job_authority:RoleBoundAuthority"
_PG = "declared_only:postgres_authority_scoped_closures"
_READ = frozenset(SERVICE_ROLES)


def _svc(surface, action, capability, roles, *, writes=True, enforced_at=_SQLITE):
    return ServiceOperation(surface, action, capability, frozenset(roles), writes, enforced_at)


SERVICE_OPERATIONS: dict[tuple[str, str], ServiceOperation] = {(row.surface, row.action): row for row in (
    _svc("batch_status", "read", "batch.read", _READ, writes=False),
    _svc("read_batch_plan", "read", "batch.read", _READ, writes=False),
    _svc("prepare_batch", "register", "batch.register", {"producer"}),
    _svc("batch_work", "status", "batch.read", _READ, writes=False),
    _svc("batch_work", "acquire", "batch.lease", {"producer"}),
    _svc("batch_work", "begin", "batch.dispatch", {"producer"}),
    _svc("batch_work", "uncertain", "batch.record_uncertainty", {"producer"}),
    _svc("batch_work", "observe_ack", "batch.retain_ack", {"producer"}),
    _svc("batch_work", "adopt", "batch.adopt", {"producer"}),
    _svc("batch_results", "record", "batch.retain_results", {"producer"}),
    _svc("batch_results", "index", "batch.read", _READ, writes=False),
    _svc("batch_results", "review", "batch.review_results", {"producer"}),
    _svc("check_lease", "acquire", "check.lease", {"checker"}),
    _svc("candidate_checks", "intake", "check.intake", {"checker"}),
    _svc("candidate_checks", "begin", "check.dispatch", {"checker"}),
    _svc("candidate_checks", "complete", "check.complete", {"checker"}),
    _svc("candidate_checks", "status", "check.read", _READ, writes=False),
    _svc("check_execution", "observe", "check.retain_observation", {"checker"}),
    _svc("check_execution", "read", "check.read", _READ, writes=False),
    _svc("check_artifact", "read", "check.read", _READ, writes=False),
    _svc("spending", "status", "spend.read", _READ, writes=False),
    _svc("spending", "reserve", "spend.reserve", {"producer", "checker"}),
    _svc("spending", "dispatch", "spend.dispatch", {"producer", "checker"}),
    _svc("spending", "uncertain", "spend.record_uncertainty", {"producer", "checker"}),
    _svc("spending", "configure", "spend.configure", {"maintenance"}),
    _svc("spending", "release", "spend.release_unstarted", {"maintenance"}),
    _svc("spending", "settle", "spend.settle", {"maintenance"}),
    _svc("domain", "import_snapshot", "history.import", {"maintenance"}),
    _svc("domain", "status", "history.read", _READ, writes=False),
    _svc("jobs", "inspect", "jobs.read", _READ, writes=False),
    _svc("jobs", "release_unstarted", "jobs.release_unstarted", {"maintenance"}),
    _svc("jobs", "reconcile", "jobs.reconcile", {"maintenance"}),
    # Existing PostgreSQL workers bind these roles through their scoped
    # closures (fixed owner/lease per execution). Linux CI owns their proof.
    _svc("media_worker", "render_proposal", "media.render", {"media"}, enforced_at=_PG),
    _svc("delivery_worker", "stage", "delivery.stage", {"delivery"}, enforced_at=_PG),
    _svc("delivery_worker", "reconcile", "delivery.reconcile", {"delivery", "maintenance"}, enforced_at=_PG),
)}

# Honest production-store limits; nothing here claims enforcement it lacks.
GIST_LIMITATIONS = {
    "identity": "one_shared_dashboard_credential",
    "role_separation": "unenforceable_on_gist_path",
    "mutation_guard": "exact_expected_revision_and_same_origin",
    "transactions": "get_then_patch_not_transactional",
    "service_roles": "process_environment_not_authenticated",
}


class RoleError(CommandError):
    """A terminal, sanitized refusal at the command or worker boundary."""


def operator_allowed(role: str, action: str) -> bool:
    """The command boundary's role decision for authenticated human operators."""
    if role not in HUMAN_ROLES:
        return False
    row = OPERATOR_COMMANDS.get(action)
    if row is None:
        # Unmapped authority-internal names keep the prior non-viewer rule.
        return role != "viewer"
    return role in row.roles


def service_operation(role: str, surface: str, action: str) -> ServiceOperation:
    row = SERVICE_OPERATIONS.get((surface, action))
    if row is None:
        raise RoleError("unmapped_service_operation", "This worker operation has no declared role binding")
    if role not in SERVICE_ROLES:
        raise RoleError("invalid_service_role", "Unknown worker role")
    if role not in row.roles:
        raise RoleError("cross_role_write_refused", "This worker role cannot perform that operation")
    return row


def _drafts(state: Any) -> dict[str, Any] | None:
    drafts = state.get("drafts") if isinstance(state, Mapping) else None
    if not isinstance(drafts, list):
        return None
    rows: dict[str, Any] = {}
    for draft in drafts:
        if isinstance(draft, Mapping) and isinstance(draft.get("id"), str):
            rows.setdefault(draft["id"], draft.get("status"))
    return rows


def require_transitions(before: Any, after: Any, action: str, target_ids: tuple[str, ...] = (), *,
                        source_invalidation_ids: tuple[str, ...] = ()) -> None:
    """Refuse a reduction whose draft-status effect lies outside the action's binding.

    Called inside the authority transaction after the reducer, so a refusal
    becomes a terminal rejected result with no state change. Source invalidation
    IDs come only from the verified source transition, never command payloads.
    """
    old, new = _drafts(before), _drafts(after)
    if old is None or new is None:
        return  # The reducer already refuses malformed stores.
    row = OPERATOR_COMMANDS.get(action)
    if set(old) - set(new):
        raise RoleError("transition_not_allowed", "A command cannot remove a retained draft")
    targets = set(target_ids)
    invalidations = set(source_invalidation_ids) if action == "commit_ghcn_source_run" and not targets else set()
    for draft_id, status in new.items():
        prior = old.get(draft_id)
        if draft_id not in old:
            if status == "approved":
                raise RoleError("transition_not_allowed", "A new draft cannot be born approved")
            continue
        if draft_id in targets and row is not None and row.from_statuses is not None:
            if prior not in row.from_statuses or status not in (row.to_statuses or ()):
                raise RoleError("transition_not_allowed", "This action cannot produce that draft status")
            continue
        if status != prior:
            if draft_id in invalidations and prior == "approved" and status == "pending":
                draft = next(d for d in after["drafts"] if isinstance(d, Mapping) and d.get("id") == draft_id)
                if draft.get("approval_mode") == "manual" and not any(key in draft for key in (
                        "approval_binding", "approved_at", "auto_approve_at", "auto_approve_requested_at",
                        "autoship_on_critic_pass", "review_binding")):
                    # The source helper retains old publish-intent fields as
                    # historical evidence; they do not restore cleared approval.
                    continue
            raise RoleError("transition_not_allowed", "This action cannot change another draft's status")


def describe() -> dict:
    """Bounded, offline declaration for Operations and Root review."""
    return {
        "human_roles": list(HUMAN_ROLES), "service_roles": list(SERVICE_ROLES),
        "operator_commands": {a: {"capability": r.capability, "roles": sorted(r.roles),
                                  "from": sorted(r.from_statuses) if r.from_statuses is not None else None,
                                  "to": sorted(r.to_statuses) if r.to_statuses is not None else None}
                              for a, r in sorted(OPERATOR_COMMANDS.items())},
        "service_operations": [{"surface": r.surface, "action": r.action, "capability": r.capability,
                                "roles": sorted(r.roles), "writes": r.writes, "enforced_at": r.enforced_at}
                               for r in SERVICE_OPERATIONS.values()],
        "gist_limitations": dict(GIST_LIMITATIONS),
    }
