"""Restore and rollback execution plans over a separate local command authority.

A plan verifies, before any target mutation: the backup artifact (exact sha256,
strict parse), media completeness (every PNG the backup references is present in
a verified ``theheat_media_export_v1`` directory), protected target records (no
delivered, unknown, submitted or legacy attempt and no posted draft may be lost
or changed), active jobs (W13 ``job_recovery.inspect_jobs``) and receipt
references (one post ID binds one event). Execution re-verifies the plan, then
only appends: the backup becomes a retained ``origin='restore'`` domain snapshot
through the W14.2 importer (idempotent per restore_id) and media closures go
through the insert-only export restore. Current
state, the backup file and the export directory are never replaced, overwritten
or deleted, so rollback is verification that the prior current state is still
exactly the state recorded in the plan.

Not covered (Root operations): production migration, hosted restore, credential
or authority switching, Gist writes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from src.commands import domain_journal, import_plan, job_recovery
from src.commands.schema import CommandError, canonical_json

KIND = "theheat_restore_plan_v1"
COLD_START_INPUTS = (
    {"name": "target_database", "required": True,
     "description": "Separate local SQLite command authority file (never the bot's store)"},
    {"name": "environment", "required": True, "description": "local or preview; must match the target authority"},
    {"name": "backup_snapshot", "required": True, "description": "Exact Gist-format state bytes to restore"},
    {"name": "expected_backup_sha256", "required": True, "description": "sha256 recorded when the backup was taken"},
    {"name": "media_export", "required": "when the backup references a PNG",
     "description": "Private theheat_media_export_v1 directory from scripts/retain_gist_media.py export"},
    {"name": "media_store", "required": "when media is restored", "description": "Empty or insert-only target media store"},
    {"name": "operators_file", "required": "for later commands",
     "description": "Trusted local operator fixture; not a hosted identity provider"},
)
_ACTIVE_JOB_STATES = {"unstarted", "submitted", "started_result_unknown"}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _state_sha(state: dict) -> str:
    return _sha(canonical_json(state).encode("utf-8"))


def _protected(state: dict) -> dict[str, Any]:
    """Records a restore must never lose: every non-not_sent attempt and posted draft."""
    out: dict[str, Any] = {}
    for event_id, row in (state.get("publish_ledger") or {}).items():
        if not isinstance(row, dict) or row.get("phase") != "not_sent" or row.get("tweet_id") or row.get("attempt_conflicts"):
            out[f"ledger:{event_id}"] = row
    for draft in state.get("drafts") or []:
        if isinstance(draft, dict) and (draft.get("status") == "posted" or draft.get("tweet_id")):
            out[f"draft:{draft.get('id')}"] = draft
    return out


def _media_references(state: dict) -> set[str]:
    refs = set()
    for draft in state.get("drafts") or []:
        attachment = draft.get("media_attachment") if isinstance(draft, dict) else None
        if isinstance(attachment, dict) and isinstance(attachment.get("png_sha256"), str):
            refs.add(attachment["png_sha256"])
    for row in (state.get("publish_ledger") or {}).values():
        identity = row.get("delivery_identity") if isinstance(row, dict) else None
        if isinstance(identity, dict) and isinstance(identity.get("png_sha256"), str):
            refs.add(identity["png_sha256"])
    return refs


def _receipt_conflicts(state: dict) -> list[str]:
    owners: dict[str, set[str]] = {}
    for event_id, row in (state.get("publish_ledger") or {}).items():
        rows = [row, *(row.get("attempt_conflicts") or [])] if isinstance(row, dict) else []
        for item in rows:
            if isinstance(item, dict) and item.get("tweet_id"):
                owners.setdefault(str(item["tweet_id"]), set()).add(event_id)
    for draft in state.get("drafts") or []:
        if isinstance(draft, dict) and draft.get("tweet_id"):
            owners.setdefault(str(draft["tweet_id"]), set()).add(str(draft.get("event_id") or draft.get("id")))
    return sorted(tweet for tweet, events in owners.items() if len(events) > 1)


def _active_jobs(authority: Any, now: datetime | str) -> list[str]:
    inspection = job_recovery.inspect_jobs(authority, now=now)
    active = [row["job_id"] for row in inspection["jobs"]
              if row.get("start_state") in _ACTIVE_JOB_STATES or (row.get("lease") or {}).get("active")]
    active += [row["check_set_id"] for row in inspection["check_sets"]
               if any(state in {"granted", "started_result_unknown"} for state in (row.get("stages") or {}).values())]
    return sorted(set(active))


def plan(authority: Any, backup: bytes, *, expected_sha256: str, restore_id: str, now: datetime | str,
         media_export: str | Path | None = None) -> dict:
    """Verify everything; write nothing. ``executable`` only with zero refusals."""
    refusals: list[dict] = []
    sha = _sha(backup)
    if sha != expected_sha256:
        refusals.append({"code": "backup_artifact_changed"})
    try:
        backup_state = domain_journal.parse_snapshot(backup)
    except (domain_journal.DomainJournalError, CommandError, ValueError):
        backup_state = None
        refusals.append({"code": "backup_unreadable"})
    version, current = authority.read()
    media: dict[str, Any] = {"referenced": [], "export_verified": False}
    if backup_state is not None:
        refs = _media_references(backup_state)
        media["referenced"] = sorted(refs)
        if refs and media_export is None:
            refusals.append({"code": "media_export_required"})
        elif media_export is not None:
            from src.media import gist_media_export
            try:
                _index, blobs = gist_media_export.verify(media_export)
                media["export_verified"] = True
                refusals.extend({"code": "media_artifact_missing", "png_sha256": ref} for ref in sorted(refs - set(blobs)))
            except gist_media_export.ExportError as exc:
                refusals.append({"code": "media_export_invalid", "reason": exc.code})
        target_protected, restored = _protected(current), _protected(backup_state)
        for key in sorted(target_protected):
            if key not in restored:
                refusals.append({"code": "protected_record_would_be_lost", "record": key})
            elif restored[key] != target_protected[key]:
                refusals.append({"code": "protected_record_would_change", "record": key})
        merged = {"drafts": [*(current.get("drafts") or []), *(backup_state.get("drafts") or [])],
                  "publish_ledger": {**(backup_state.get("publish_ledger") or {}), **(current.get("publish_ledger") or {})}}
        refusals.extend({"code": "receipt_reference_conflict", "tweet_id": tweet} for tweet in _receipt_conflicts(backup_state))
        refusals.extend({"code": "receipt_reference_conflict_with_target", "tweet_id": tweet}
                        for tweet in _receipt_conflicts(merged) if tweet not in _receipt_conflicts(backup_state))
    refusals.extend({"code": "active_job_present", "job": job} for job in _active_jobs(authority, now))
    importer = (import_plan.plan([(restore_id, backup)], authority=authority, origin="restore")
                if backup_state is not None else None)
    if importer is not None and not importer["executable"]:
        refusals.append({"code": "import_plan_not_executable"})
    return {
        "kind": KIND, "mutation": "none", "restore_id": restore_id, "backup_sha256": sha,
        "target": {"version": version, "state_sha256": _state_sha(current), "environment": authority.environment},
        "media": media, "refusals": refusals, "executable": not refusals, "import_plan": importer,
        "steps": [] if refusals else [
            {"step": "append_domain_snapshot", "origin": "restore", "import_id": restore_id, "replaces_current_state": False},
            *([{"step": "insert_only_media_restore", "items": media["referenced"]}] if media["referenced"] else [])],
        "rollback": {"mode": "verify_prior_state_unchanged", "directory_replacement": False, "overwrite": False,
                     "prior_version": version, "prior_state_sha256": _state_sha(current)},
        "cold_start_inputs": list(COLD_START_INPUTS),
    }


def execute(authority: Any, plan_value: dict, backup: bytes, *, expected_sha256: str, now: datetime | str,
            media_export: str | Path | None = None, media_writer: Any = None) -> dict:
    """Re-verify the plan against the live target, then append only."""
    again = plan(authority, backup, expected_sha256=expected_sha256, restore_id=plan_value.get("restore_id", ""),
                 now=now, media_export=media_export)
    for key in ("backup_sha256", "target", "media", "steps"):
        if again[key] != plan_value.get(key):
            raise CommandError("restore_plan_stale", "The target, backup or media changed since the plan; plan again")
    if not again["executable"]:
        raise CommandError("restore_plan_refused", "The plan has refusals; nothing was changed")
    if again["media"]["referenced"] and media_writer is None:
        raise CommandError("media_store_required", "Supply the insert-only target media store")
    imported = import_plan.execute(authority, again["import_plan"], [(again["restore_id"], backup)])
    restored_media = None
    if again["media"]["referenced"]:
        from src.media import gist_media_export
        restored_media = gist_media_export.restore(media_writer, media_export)
    return {"restore_id": again["restore_id"], "imported": imported, "media": restored_media,
            "current_state_replaced": False, "rollback": verify_rollback(authority, again)}


def verify_rollback(authority: Any, plan_value: dict) -> dict:
    """The rollback target is the prior current state, which a restore never replaces."""
    version, current = authority.read()
    prior = plan_value["rollback"]
    unchanged = version == prior["prior_version"] and _state_sha(current) == prior["prior_state_sha256"]
    return {"prior_state_unchanged": unchanged, "action_required": None if unchanged else "inspect_changes_since_plan"}
