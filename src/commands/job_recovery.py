"""Overdue job inspection, scheduled-role diagnosis and bounded recovery.

Reads the existing durable journals of the local command authority (batch
registration, worker leases/grants/acks/adoptions, result receipts/reviews,
check attempts/receipts and spending events). It never infers that granted
work did not start: a grant without an adopted acknowledgment or a check
attempt without a receipt is ``started_result_unknown``, and only work with no
grant and a still-reserved allowance is ``unstarted``.

Recovery commands reuse existing operations only: an unstarted job may be
resumed through its own executor or have its reservation released (the spend
journal refuses release once dispatched); unknown or submitted work gets a
reconciliation record and is never retried. A missed schedule is diagnosed as
``missing``; it never authorizes rerunning paid or publishing work.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import closing
from datetime import datetime
import json
from typing import Any

from src.commands import batch_journal, batch_worker_journal
from src.commands.command_roles import RoleError
from src.commands.schema import utc_datetime

# Cadence (minutes) and side effects of the existing monitored workflows
# (scripts/workflow_health.MONITORED_WORKFLOWS; dashboard/lib/automation.js).
SCHEDULED_ROLES: dict[str, dict[str, Any]] = {
    "theheat-bot": {"file": "bot.yml", "cadence_minutes": 60, "effects": ("paid_model", "publishing")},
    "voice-regression": {"file": "voice-regression.yml", "cadence_minutes": 1440, "effects": ("paid_model",)},
    "refresh-thresholds": {"file": "refresh-thresholds.yml", "cadence_minutes": 10080, "effects": ("source_acquisition",)},
    "source-health-sentinel": {"file": "source-health-sentinel.yml", "cadence_minutes": 60, "effects": ()},
    "time-travel-canary": {"file": "time-travel-canary.yml", "cadence_minutes": 10080, "effects": ()},
}
SCHEDULE_STATUSES = ("completed", "missing", "blocked", "disabled", "failing", "unknown")
START_STATES = ("unstarted", "released", "started_result_unknown", "submitted", "results_retained", "reviewed")
REASONS = {
    "resume_or_release": "No provider request was granted. Resume through the job's own executor, or release its reservation.",
    "release_only": "No provider request was granted, but the useful window has passed. Only release is safe.",
    "lease_held": "A live owner holds this job's lease; wait for it to finish or expire.",
    "reconcile_unknown": "A provider request was granted without an adopted acknowledgment. The outcome is unknown and is never retried.",
    "collect_submitted": "The provider accepted this job. Collect its results with the producer; nothing is resent.",
    "results_retained": "Results are retained; review them through the existing result review.",
    "terminal": "No recovery action is available.",
    "released": "The reservation was released before any request; nothing was sent.",
    "check_granted_unknown": "A required check was granted without a receipt. Its outcome is unknown and is never retried.",
}


def _at(value: datetime | str) -> str:
    return value if isinstance(value, str) else value.isoformat().replace("+00:00", "Z")


def _spend_state(connection, intent_id: str | None) -> str:
    if intent_id is None:
        return "none"
    kinds = {row[0] for row in connection.execute("SELECT kind FROM spend_events WHERE intent_id=?", (intent_id,))}
    for kind in ("settled", "released", "uncertain", "dispatched"):
        if kind in kinds:
            return kind
    return "reserved"


def _rows(connection, sql: str, *args) -> list[dict]:
    return [dict(row) for row in connection.execute(sql, args)]


def _tables(connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _batch_job(connection, job_id: str, now: str, tables: set[str]) -> dict:
    registration = batch_journal.read(connection, job_id)
    stages: list[tuple[str, str]] = [("registered", registration["registered_at"])]
    leases = _rows(connection, "SELECT fence,owner,expires_at,recorded_at FROM batch_worker_leases WHERE job_id=? ORDER BY fence", job_id)
    stages += [("leased", row["recorded_at"]) for row in leases]
    submission = connection.execute("SELECT fence,grant_id,recorded_at FROM batch_worker_submissions WHERE job_id=?", (job_id,)).fetchone()
    if submission:
        stages.append(("granted", submission["recorded_at"]))
    for table, label in (("batch_worker_uncertainties", "uncertainty_recorded"), ("batch_worker_acks", "acknowledgment_retained"),
                         ("batch_worker_adoptions", "acknowledgment_adopted")):
        stages += [(label, row["recorded_at"]) for row in _rows(connection, f"SELECT recorded_at FROM {table} WHERE job_id=?", job_id)]
    receipts = reviews = []
    if "batch_result_receipts" in tables:
        receipts = _rows(connection, "SELECT recorded_at FROM batch_result_receipts WHERE job_id=?", job_id)
        reviews = _rows(connection, "SELECT recorded_at FROM batch_result_reviews WHERE job_id=?", job_id)
        stages += [("results_retained", r["recorded_at"]) for r in receipts] + [("results_reviewed", r["recorded_at"]) for r in reviews]
    spend = _spend_state(connection, registration["intent_id"])
    stages += [(f"spend_{row['kind']}", row["recorded_at"]) for row in _rows(
        connection, "SELECT kind,recorded_at FROM spend_events WHERE intent_id=? ORDER BY sequence", registration["intent_id"])]
    adopted = connection.execute("SELECT 1 FROM batch_worker_adoptions WHERE job_id=?", (job_id,)).fetchone() is not None
    if reviews:
        start = "reviewed"
    elif receipts:
        start = "results_retained"
    elif adopted:
        start = "submitted"
    elif submission is not None or spend in {"dispatched", "uncertain", "settled"}:
        start = "started_result_unknown"
    elif spend == "released":
        start = "released"
    else:
        start = "unstarted"
    stamp = utc_datetime(now)
    lease = leases[-1] if leases else None
    lease_active = bool(lease and stamp < utc_datetime(lease["expires_at"]))
    useful = stamp < utc_datetime(registration["useful_until"])
    last = max(stages, key=lambda item: (utc_datetime(item[1]), stages.index(item)))
    worker_state = None
    try:
        worker_state = batch_worker_journal.apply(connection, "status", {"job_id": job_id}, now=now)["state"]
    except (ValueError, KeyError):
        worker_state = "unreadable"
    if start == "unstarted":
        operations, reason = ((), "lease_held") if lease_active else (
            (("resume", "release_unstarted"), "resume_or_release") if useful else (("release_unstarted",), "release_only"))
    elif start == "started_result_unknown":
        operations, reason = ("reconcile",), "reconcile_unknown"
    elif start == "submitted":
        operations, reason = ("reconcile",), "collect_submitted"
    elif start == "results_retained":
        operations, reason = (), "results_retained"
    elif start == "released":
        operations, reason = (), "released"
    else:
        operations, reason = (), "terminal"
    terminal = start in {"released", "reviewed"}
    return {
        "kind": "batch", "job_id": job_id, "start_state": start, "worker_state": worker_state,
        "spend_state": spend, "last_durable_stage": {"stage": last[0], "recorded_at": last[1]},
        "lease": {"owner": lease["owner"], "fence": lease["fence"], "expires_at": lease["expires_at"],
                  "active": lease_active} if lease else None,
        "deadline": registration["useful_until"], "overdue": not terminal and not useful,
        "grant_id": submission["grant_id"] if submission else None,
        "operations": list(operations), "hold_code": reason, "reason": REASONS[reason],
        "retry_authorized": False,
    }


def _check_sets(connection, now: str) -> list[dict]:
    out = []
    for row in _rows(connection, "SELECT check_set_id,job_id,recorded_at FROM check_sets ORDER BY recorded_at, check_set_id"):
        attempts = {a["stage"]: a for a in _rows(connection, "SELECT grant_id,stage,intent_id,recorded_at FROM check_attempts WHERE check_set_id=?", row["check_set_id"])}
        stages: dict[str, str] = {}
        timeline = [("intake", row["recorded_at"])]
        for stage in ("deterministic", "safety", "fact_check", "critic"):
            attempt = attempts.get(stage)
            if attempt is None:
                stages[stage] = "unstarted"
                continue
            timeline.append((f"{stage}_granted", attempt["recorded_at"]))
            receipt = connection.execute("SELECT disposition,recorded_at FROM check_receipts WHERE grant_id=?", (attempt["grant_id"],)).fetchone()
            if receipt is None:
                stages[stage] = "started_result_unknown"
            else:
                stages[stage] = receipt["disposition"]
                timeline.append((f"{stage}_{receipt['disposition']}", receipt["recorded_at"]))
        last = max(timeline, key=lambda item: (utc_datetime(item[1]), timeline.index(item)))
        unknown = any(v == "started_result_unknown" for v in stages.values())
        out.append({"kind": "check_set", "check_set_id": row["check_set_id"], "job_id": row["job_id"], "stages": stages,
                    "last_durable_stage": {"stage": last[0], "recorded_at": last[1]},
                    "operations": ["reconcile"] if unknown else [],
                    "hold_code": "check_granted_unknown" if unknown else "terminal",
                    "reason": REASONS["check_granted_unknown" if unknown else "terminal"], "retry_authorized": False})
    return out


def inspect_jobs(authority: Any, *, now: datetime | str) -> dict:
    """Read-only, bounded inspection of every local job and check set."""
    at = _at(now)
    with closing(authority._connect()) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        authority._check_environment(connection)
        tables = _tables(connection)
        jobs = []
        if "batch_jobs" in tables:
            for (job_id,) in connection.execute("SELECT job_id FROM batch_jobs ORDER BY registered_at, job_id LIMIT 1000").fetchall():
                jobs.append(_batch_job(connection, job_id, at, tables))
        checks = _check_sets(connection, at) if "check_sets" in tables else []
        connection.rollback()
    return {"inspected_at": at, "jobs": jobs, "check_sets": checks,
            "overdue": sum(job["overdue"] for job in jobs), "automatic_retry": False}


def _job(authority: Any, job_id: str, now: str) -> dict:
    found = [row for row in inspect_jobs(authority, now=now)["jobs"] if row["job_id"] == job_id]
    if not found:
        raise RoleError("job_not_found", "No retained job has this identity")
    return found[0]


def _inner(authority: Any) -> Any:
    return getattr(authority, "inner", authority)


def release_unstarted(maintenance: Any, job_id: str, *, now: datetime | str) -> dict:
    """Release a reservation only when no request was ever granted.

    The spend journal itself refuses release after dispatch, so a concurrent
    grant cannot be erased by a stale inspection.
    """
    at = _at(now)
    if hasattr(maintenance, "_bind"):
        maintenance._bind("jobs", "release_unstarted")
    row = _job(_inner(maintenance), job_id, at)
    if "release_unstarted" not in row["operations"]:
        raise RoleError("release_refused_started_or_unknown", REASONS[row["hold_code"]])
    registration = maintenance.batch_status(job_id)
    result = maintenance.spending("release", {"intent_id": registration["intent_id"]}, now=at)
    return {"job_id": job_id, "operation": "release_unstarted", "spend": result, "sent": False}


def resume_unstarted(producer: Any, job_id: str, *, executor: Callable[[], dict], now: datetime | str) -> dict:
    """Re-run only never-granted work through its existing executor and adapter."""
    row = _job(_inner(producer), job_id, _at(now))
    if "resume" not in row["operations"]:
        raise RoleError("resume_refused_started_or_unknown", REASONS[row["hold_code"]])
    return executor()


def reconcile(maintenance: Any, job_id: str, *, now: datetime | str) -> dict:
    """Reconciliation-only record: evidence and hold, never a resend."""
    if hasattr(maintenance, "_bind"):
        maintenance._bind("jobs", "reconcile")
    row = _job(_inner(maintenance), job_id, _at(now))
    if "reconcile" not in row["operations"]:
        raise RoleError("reconcile_not_applicable", REASONS[row["hold_code"]])
    return {"job_id": job_id, "operation": "reconcile", "outcome": "unknown" if row["start_state"] == "started_result_unknown" else "submitted",
            "grant_id": row["grant_id"], "last_durable_stage": row["last_durable_stage"], "spend_state": row["spend_state"],
            "retry_authorized": False, "reason": row["reason"]}


def _latest_run(row: Mapping[str, Any]) -> str | None:
    for key in ("run_created_at", "last_success_at"):
        value = row.get(key)
        if isinstance(value, str):
            return value
    return None


def diagnose_schedules(classifications: Iterable[Mapping[str, Any]], *, now: datetime | str,
                       disabled: Iterable[str] = (), blocked: Mapping[str, str] | None = None,
                       grace: float = 1.5) -> list[dict]:
    """Join existing workflow-health rows to cadence; never authorizes a rerun."""
    stamp = utc_datetime(_at(now))
    off, holds = set(disabled), dict(blocked or {})
    seen = {row.get("workflow"): row for row in classifications if isinstance(row, Mapping)}
    out = []
    for name, spec in SCHEDULED_ROLES.items():
        row = seen.get(name, {})
        latest = _latest_run(row)
        age = None
        if latest is not None:
            try:
                age = (stamp - datetime.fromisoformat(latest.replace("Z", "+00:00"))).total_seconds() / 60
            except ValueError:
                latest = None
        if name in off:
            status, reason = "disabled", "Intentionally disabled; not a failure and not overdue."
        elif name in holds:
            status, reason = "blocked", f"Held: {holds[name]}"
        elif row.get("category") == "failing":
            status, reason = "failing", "The latest decisive run failed."
        elif latest is None or (age is not None and age > spec["cadence_minutes"] * grace):
            status, reason = "missing", "No run within its schedule. A missed run is not authority to rerun paid or publishing work."
        elif row.get("category") == "healthy":
            status, reason = "completed", "Ran within its schedule."
        else:
            status, reason = "unknown", "No decisive run is recorded."
        effects = list(spec["effects"])
        out.append({"workflow": name, "file": spec["file"], "status": status, "reason": reason,
                    "last_run_at": latest, "cadence_minutes": spec["cadence_minutes"], "effects": effects,
                    "rerun_authorized": False,
                    "recovery": "inspect_jobs_resume_only_unstarted" if status == "missing" and effects else "none"})
    return out


def operations_holds(schedules: Iterable[Mapping[str, Any]], inspection: Mapping[str, Any]) -> list[dict]:
    """One bounded list of actionable holds for the Operations surface."""
    holds = [{"subject": f"schedule:{row['workflow']}", "code": f"schedule_{row['status']}", "reason": row["reason"],
              "operations": []} for row in schedules if row["status"] in {"missing", "blocked", "failing"}]
    for job in inspection.get("jobs", []):
        if job["operations"] or job["overdue"]:
            holds.append({"subject": f"job:{job['job_id']}", "code": job["hold_code"], "reason": job["reason"],
                          "operations": list(job["operations"]), "last_durable_stage": job["last_durable_stage"]})
    for check in inspection.get("check_sets", []):
        if check["operations"]:
            holds.append({"subject": f"check:{check['check_set_id']}", "code": check["hold_code"], "reason": check["reason"],
                          "operations": list(check["operations"]), "last_durable_stage": check["last_durable_stage"]})
    return holds[:200]


def render(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
