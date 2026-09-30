"""Default-OFF local required checks, one stage and one request per invocation.

This runner is not connected to Gist, a workflow or posting. The caller supplies
current evidence/state and an independently justified reservation for the exact
prepared request. Replaying an old grant never authorizes another provider call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import hashlib
import os

from src.commands import check_journal as checks
from src.commands.schema import canonical_json, utc_datetime
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.two_bot import check_requests
from src.two_bot.check_transport import (
    CheckObservation,
    GoogleCheckTransport,
    LEASE_SECONDS,
    READ_BUDGET_SECONDS,
    SOCKET_TIMEOUT_SECONDS,
)
from src.voice import safety


def _report(outcome, *, reason=None, stage=None, status=None):
    result = dict(
        outcome=outcome,
        publication_approved=False,
        dispatch_granted=False,
        required_checks_completed=False,
        accounting_complete=False,
        cost_usd=None,
    )
    if reason:
        result["reason"] = reason
    if stage:
        result["stage"] = stage
    if status:
        result["checks"] = status
        result["required_checks_completed"] = status["required_checks_completed"]
    return result


def _finish(authority, identity, packet, stage, attempt, clock):
    # A grant from another adapter/version must not be interpreted as this
    # executor's exact request merely because its role/model labels match.
    expected = canonical_json(check_requests.prepare_request(packet, stage)).encode()
    binding = attempt["binding"]
    if (
        hashlib.sha256(expected).hexdigest() != binding["request_sha256"]
        or authority.read_artifact(binding["request_sha256"]) != expected
    ):
        return _report("reconciliation_required", reason="check_request_not_exact", stage=stage)
    observation = attempt["observation"]
    if observation is None:
        return _report("reconciliation_required", reason="check_response_not_retained", stage=stage)
    raw = authority.read_artifact(observation["raw_sha256"])
    outcome = check_requests.interpret_observation(packet, stage, observation, raw)
    receipt = dict(outcome, grant_id=attempt["grant_id"], request_sha256=binding["request_sha256"])
    # A recovered observation still belongs to the original execution owner.
    # If its lease expired, completion is retained as stale rather than promoted.
    completion = dict(
        identity,
        stage=stage,
        grant_id=attempt["grant_id"],
        owner=binding["owner"],
        fence=binding["fence"],
    )
    authority.candidate_checks("complete", completion, receipt=receipt, now=clock())
    status = authority.candidate_checks("status", identity, now=clock())
    return _report("completed", stage=stage, status=status)


def _read(authority, check_set_id, clock):
    return authority.check_execution("read", {"check_set_id": check_set_id}, now=clock())


def _window_available(packet, lease, now):
    midnight = utc_datetime(packet["check_date"] + "T00:00:00Z") + timedelta(days=1)
    deadline = min(
        utc_datetime(lease["expires_at"]), utc_datetime(packet["useful_until"]), midnight
    )
    return (
        deadline - utc_datetime(now)
    ).total_seconds() > READ_BUDGET_SECONDS + 2 * SOCKET_TIMEOUT_SECONDS


def execute_check_once(
    authority: SQLiteAuthority,
    check_set_id: str,
    *,
    current_context: dict,
    checker_state: dict,
    owner: str,
    clock: Callable[[], str],
    reservation: dict | None = None,
    enabled: bool = False,
) -> dict:
    """No generic checker callback and no retry, rewrite or synchronous fallback.

    Disabled means zero I/O, including clock, policy, database and credentials.
    Provider response bytes are committed before strict parsing. A missing or
    unconfirmed grant/response leaves reconciliation work and the spending hold.
    """
    if type(enabled) is not bool:
        raise ValueError("check_execution_flag_requires_boolean")
    if not enabled:
        return _report("disabled")
    stage = None
    transport = None
    report = None
    try:
        if not isinstance(checker_state, dict) or not isinstance(current_context, dict):
            return _report("blocked", reason="invalid_current_check_context")
        saved = _read(authority, check_set_id, clock)
        packet = saved["packet"]
        check_requests.retained_inputs(packet)
        policy = current_editorial_policy()
        if policy is None:
            return _report("blocked", reason="current_check_policy_unavailable")
        context = dict(current_context, policy_sha256=fingerprint(policy))
        leased = authority.batch_work(
            "acquire",
            dict(job_id=packet["job_id"], owner=owner, ttl_seconds=LEASE_SECONDS),
            now=clock(),
        )
        identity = dict(
            check_set_id=check_set_id,
            owner=owner,
            fence=leased["lease"]["fence"],
            current_context=context,
            checker_state_sha256=fingerprint(checker_state),
        )
        status = authority.candidate_checks("status", identity, now=clock())
        if status["blocked_reason"]:
            return _report("blocked", reason=status["blocked_reason"], status=status)
        stage = next((s for s in checks.STAGES if status["stages"][s] != "passed"), None)
        if stage is None:
            return _report("checks_completed", status=status)
        if status["stages"][stage] == "unresolved":
            # Refresh after the status read in case another process retained an
            # observation. Never call begin/transport on an unresolved grant.
            attempt = _read(authority, check_set_id, clock)["attempts"][stage]
            return _finish(authority, identity, packet, stage, attempt, clock)
        if status["stages"][stage] != "pending":
            return _report(
                "blocked", reason="required_check_not_passed", stage=stage, status=status
            )
        request = check_requests.prepare_request(packet, stage)
        encoded = canonical_json(request).encode()
        if stage != "deterministic":
            if not _window_available(packet, leased["lease"], clock()):
                return _report("blocked", reason="insufficient_check_window", stage=stage)
            key = (
                safety.GEMINI_API_KEY if stage == "safety" else os.environ.get("GEMINI_API_KEY", "")
            )
            if not isinstance(key, str) or not key.strip():
                return _report("blocked", reason="missing_check_credential", stage=stage)
            transport = GoogleCheckTransport(api_key=key, model=request["model"])
        try:
            grant = authority.candidate_checks(
                "begin",
                dict(identity, stage=stage, reservation=reservation),
                request=encoded,
                now=clock(),
            )
        except Exception:
            # Even a lost commit acknowledgment must never trigger a dispatch.
            return _report(
                "reconciliation_required", reason="check_grant_not_confirmed", stage=stage
            )
        if not grant["dispatch_granted"]:
            return _report("not_dispatched", reason="check_attempt_already_recorded", stage=stage)
        status = authority.candidate_checks("status", identity, now=clock())
        if status["blocked_reason"]:
            return _report(
                "reconciliation_required",
                reason="check_context_changed_before_execution",
                stage=stage,
            )
        if stage == "deterministic":
            observed = CheckObservation(
                canonical_json(check_requests.deterministic_result(packet)).encode(),
                None,
                True,
                "local",
            )
        else:
            assert transport is not None
            if not _window_available(packet, leased["lease"], clock()):
                return _report(
                    "reconciliation_required",
                    reason="check_window_changed_before_execution",
                    stage=stage,
                )
            observed = transport.execute(request)
        metadata = dict(
            check_set_id=check_set_id,
            stage=stage,
            grant_id=grant["grant_id"],
            request_sha256=hashlib.sha256(encoded).hexdigest(),
            raw_sha256=hashlib.sha256(observed.raw).hexdigest(),
            http_status=observed.http_status,
            complete=observed.complete,
            reason=observed.reason,
        )
        authority.check_execution("observe", metadata, raw=observed.raw, now=clock())
        attempt = _read(authority, check_set_id, clock)["attempts"][stage]
        report = _finish(authority, identity, packet, stage, attempt, clock)
    except Exception:
        # No exception body, input text or credential is included in logs/results.
        # Retained observations can be recovered; missing ones require reconcile.
        report = _report(
            "reconciliation_required", reason="check_execution_not_confirmed", stage=stage
        )
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                if report is not None:
                    report["cleanup_failed"] = True
    return report
