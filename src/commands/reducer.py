"""Pure revision-aware transitions. No network, dispatch, storage or model calls."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.commands.schema import Command, CommandError, Principal, authorize, utc_datetime, utc_text, valid_epoch
from src.editorial.revisions import (
    bind_reviewed_revision, decision_revision, draft_identity, has_unresolved_publish,
    fingerprint, invalidate_text, record_human_review, revoke_approval, review_is_current,
)


@dataclass(frozen=True)
class AutomaticPolicy:
    """Trusted execution policy, not copied from a submitted command.

    The local authority defaults paused. A hosted adapter must derive this from
    P00b's current effective control inside the authority boundary.
    """
    enabled: bool = False
    epoch: str | None = None


@dataclass(frozen=True)
class Reduction:
    state: dict
    changed_ids: tuple[str, ...]
    identities: tuple[dict, ...]
    publish_intent_id: str | None = None


def _identity(draft: dict) -> dict:
    return {"draft_id": draft.get("id"), **draft_identity(draft), "decision_revision": decision_revision(draft)}



def _validate_attempt(attempt: Any) -> None:
    if not isinstance(attempt, dict):
        raise CommandError("invalid_revision", "Stored publication attempt is malformed")
    conflicts = attempt.get("attempt_conflicts", [])
    if not isinstance(conflicts, list):
        raise CommandError("invalid_revision", "Stored publication conflicts are malformed")
    for conflict in conflicts:
        _validate_attempt(conflict)


def _target_drafts(state: dict, command: Command) -> list[dict]:
    drafts = state.get("drafts", [])
    if not isinstance(drafts, list):
        raise CommandError("invalid_state", "Stored drafts are not a list")
    result = []
    for target in command.targets:
        matches = [draft for draft in drafts if isinstance(draft, dict) and draft.get("id") == target.draft_id]
        if len(matches) != 1:
            raise CommandError("draft_not_found" if not matches else "ambiguous_draft", "Target draft is missing or duplicated")
        draft = matches[0]
        history = draft.get("revision_history", [])
        if not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
            raise CommandError("invalid_revision", "Stored revision history must be a list of revision objects")
        ledger = state.get("publish_ledger", {})
        if not isinstance(ledger, dict):
            raise CommandError("invalid_revision", "Stored publication evidence is malformed")
        attempt = ledger.get(draft.get("event_id") or draft.get("id"))
        if attempt is not None:
            _validate_attempt(attempt)
        try:
            identity = _identity(draft)
        except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
            raise CommandError("invalid_revision", "Stored revision cannot be validated") from exc
        if identity != target.as_dict():
            raise CommandError("revision_conflict", "Draft text, evidence or decision changed; refresh before applying this action")
        if draft.get("status") not in {"pending", "approved"}:
            raise CommandError("draft_not_editable", "This draft can no longer be changed")
        if has_unresolved_publish(draft, state):
            raise CommandError("publication_unresolved", "Resolve the existing platform outcome before changing this draft")
        if command.action in {"record_review", "approve_revision", "schedule_revision", "bulk_reject"} and draft.get("status") != "pending":
            raise CommandError("draft_not_pending", "Cancel the queued approval before applying this action")
        result.append(draft)
    return result


def reduce_command(state: dict, command: Command, principal: Principal, *, now: datetime,
                   policy: AutomaticPolicy = AutomaticPolicy()) -> Reduction:
    """Apply all targets together or raise without changing caller-owned state."""
    if principal.subject != command.actor_subject:
        raise CommandError("forbidden", "The authenticated identity no longer matches this command")
    authorize(principal, command.action)
    if now >= utc_datetime(command.expires_at):
        raise CommandError("command_expired", "This command expired; refresh the draft before trying again")
    # Read and validate EVERY fixed target before creating or changing any copy.
    original = _target_drafts(state, command)
    updated = deepcopy(state)
    drafts = _target_drafts(updated, command)
    payload = command.payload
    at = utc_text(now)
    intent_id = None
    for draft in drafts:
        action = command.action
        if action == "edit_revision":
            invalidate_text(draft, payload["text"], at=at)
        elif action == "select_candidate":
            candidates = draft.get("candidates", [])
            if not isinstance(candidates, list):
                raise CommandError("invalid_candidate", "Stored candidates are invalid")
            candidates_at_rank = [candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("rank") == payload["candidate_rank"]]
            if len(candidates_at_rank) != 1:
                raise CommandError("candidate_not_found", "Selected candidate is missing or ambiguous")
            selected = candidates_at_rank[0]
            if fingerprint(selected) != payload["candidate_sha256"]:
                raise CommandError("candidate_conflict", "Selected candidate changed; refresh before choosing it")
            if not isinstance(selected.get("text"), str):
                raise CommandError("invalid_candidate", "Candidate text is invalid")
            invalidate_text(draft, selected["text"], at=at)
            draft["selected_candidate_rank"] = selected["rank"]
            draft["candidate_score"] = deepcopy(selected.get("score"))
        elif action == "record_review":
            record_human_review(draft, at=at)
            draft["review_binding"].update(reviewed_at=at, reviewer=principal.subject, reason=payload["reason"], command_id=command.command_id)
        elif action in {"approve_revision", "schedule_revision"}:
            if not review_is_current(draft):
                raise CommandError("review_required", "Review this exact text against its source evidence first")
            if action == "schedule_revision":
                control = state.get("publication_control", {})
                approval_policy = draft.get("approval_policy", {})
                if not isinstance(control, dict) or not isinstance(approval_policy, dict):
                    raise CommandError("invalid_state", "Stored publication policy is malformed")
                retired = control.get("retired_epochs", [])
                if (not policy.enabled or not policy.epoch or payload["publication_epoch"] != policy.epoch
                        or not isinstance(retired, list) or not all(valid_epoch(epoch) for epoch in retired) or policy.epoch in retired
                        or control.get("invalid_control")):
                    raise CommandError("automatic_publication_paused", "The requested release epoch is paused, retired or unverified")
                if draft.get("review_binding", {}).get("kind") != "model":
                    raise CommandError("model_review_required", "Scheduling requires current model checks")
                if approval_policy.get("can_auto_approve") is False:
                    raise CommandError("manual_only", "This story type requires manual approval")
                revoke_approval(draft)
                bind_reviewed_revision(draft, "auto", at=at, publication_epoch=policy.epoch)
                draft["auto_approve_at"] = utc_text(now + timedelta(minutes=payload["delay_minutes"]))
                draft["auto_approve_requested_at"] = at
                draft["approval_mode"] = "auto"
            else:
                intent_id = str(uuid5(NAMESPACE_URL, f"theheat:{command.environment}:{command.command_id}:publish"))
                revoke_approval(draft)
                bind_reviewed_revision(draft, "manual", at=at, intent_id=intent_id)
                draft.update(status="approved", approved_at=at, approval_mode="manual", publish_requested_at=at)
            draft["approval_binding"].update(authorized_at=at, actor=principal.subject, reason=payload["reason"], command_id=command.command_id)
            draft["post_error"] = None
        elif action == "cancel_approval":
            revoke_approval(draft)
            draft["status"] = "pending"
        elif action in {"reject_revision", "bulk_reject"}:
            revoke_approval(draft)
            draft.update(status="rejected", rejected_reason=payload["reason"], post_error=None)
        else:
            raise CommandError("invalid_action", "Unsupported mutation action")
    changed = []
    for before, after in zip(original, drafts, strict=True):
        if before != after:
            after["updated_at"] = at
            changed.append(after["id"])
    return Reduction(updated, tuple(changed), tuple(_identity(draft) for draft in drafts), intent_id)


def failure_result(error: Exception) -> dict[str, Any]:
    if isinstance(error, CommandError):
        return {"status": "rejected", "code": error.code, "message": str(error)}
    # Deterministic malformed-revision validation is a terminal command failure;
    # storage/runtime failures must propagate and roll the transaction back.
    if isinstance(error, (ValueError, TypeError, UnicodeError, OverflowError)):
        return {"status": "rejected", "code": "invalid_revision", "message": str(error)}
    raise error
