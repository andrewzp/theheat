"""Worker-role adapter over the existing trusted authority methods.

The local SQLite authority (and the same method surface on the PostgreSQL
authority) exposes trusted job methods that take no operator principal. This
adapter binds one in-process ``ServiceIdentity`` to them:

* a worker role may call only the methods its role is bound to
  (``command_roles.SERVICE_OPERATIONS``); a cross-role write is refused before
  any transaction opens;
* a lease owner named in a payload must be the identity's own owner, so a
  caller-chosen label cannot take or commit another worker's lease;
* an optional writer-generation registry refuses retired/unauthorized
  producer generations (inactive unless a registry is supplied);
* unstarted job acquisition is refused for obsolete input (policy/useful-until
  or an explicit currentness callback);
* an optional ``OperationAllowance`` reserves a call slot strictly before a
  grant and releases it when the durable journal replays an existing grant, so
  re-acquisition never spends twice.

No provider, Gist, X or network access happens here; executors keep their own
transports. Durable state stays in the existing journals.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Any

from src.commands.command_roles import SERVICE_ROLES, RoleError, service_operation
from src.commands.schema import utc_datetime

_OWNER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}")
_GENERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}")
_SETTLE = {"passed": "returned", "rejected": "returned", "stale": "returned",
           "error": "malformed", "unavailable": "unavailable"}


@dataclass(frozen=True)
class ServiceIdentity:
    """A worker's role, lease owner and producer generation, created in code.

    It is never parsed from a request or operator file: ``Principal`` refuses
    service roles and this class refuses human roles.
    """
    role: str
    owner: str
    generation: str = "unversioned"

    def __post_init__(self):
        if self.role not in SERVICE_ROLES:
            raise RoleError("invalid_service_role", "Unknown worker role")
        if not isinstance(self.owner, str) or not _OWNER.fullmatch(self.owner):
            raise RoleError("invalid_service_owner", "Worker owner must be a bounded identifier")
        if not isinstance(self.generation, str) or not _GENERATION.fullmatch(self.generation):
            raise RoleError("invalid_writer_generation", "Writer generation must be a bounded identifier")

    @property
    def writer(self) -> str:
        return f"command_authority:{self.role}"


class RoleBoundAuthority:
    def __init__(self, inner: Any, identity: ServiceIdentity, *, allowance: Any = None,
                 currentness: Callable[[dict, dict], str | None] | None = None,
                 writer_registry: Any = None):
        if not isinstance(identity, ServiceIdentity):
            raise RoleError("invalid_service_identity", "A code-constructed worker identity is required")
        self.inner, self.identity = inner, identity
        self.allowance, self.currentness, self.writer_registry = allowance, currentness, writer_registry
        self._settled: set[str] = set()
        self.refusals: list[dict] = []  # Bounded codes for Operations; no payloads.

    @property
    def environment(self) -> str:
        return self.inner.environment

    # -- binding -----------------------------------------------------------
    def _bind(self, surface: str, action: str, payload: Any = None) -> None:
        try:
            self._check(surface, action, payload)
        except RoleError as exc:
            self._refused(surface, action, exc)
            raise

    def _check(self, surface: str, action: str, payload: Any) -> None:
        row = service_operation(self.identity.role, surface, action)
        if row.writes and self.writer_registry is not None:
            self.writer_registry.check(self.identity.writer, self.identity.generation)
        if isinstance(payload, dict) and "owner" in payload and payload["owner"] != self.identity.owner:
            raise RoleError("lease_owner_mismatch", "A worker may only name its own lease owner")

    def _admit_acquisition(self, job_id: Any, now: str) -> None:
        """Unstarted work must still match current policy and its useful window."""
        from src.editorial.policy import current_editorial_policy
        from src.editorial.revisions import fingerprint
        from src.two_bot.batch_contract import validated_batch_plan
        registration = self.inner.batch_status(job_id)
        status = self.inner.batch_work("status", {"job_id": job_id}, now=now)
        if status.get("grant_id") is not None:
            return  # Started work stays collectable; its grant can never replay.
        plan = validated_batch_plan(self.inner.read_batch_plan(job_id),
                                    expected_plan_sha256=registration["plan_sha256"])
        policy = current_editorial_policy()
        if policy is None or fingerprint(policy) != plan["policy_sha256"]:
            raise RoleError("obsolete_job_input_refused", "This unstarted job was planned under a superseded policy")
        if utc_datetime(now) >= utc_datetime(plan["useful_until"]):
            raise RoleError("job_input_expired", "This unstarted job is past its useful window")
        if self.currentness is not None:
            code = self.currentness(dict(registration), plan)
            if code is not None:
                raise RoleError("obsolete_job_input_refused", "This unstarted job's source input is no longer current")

    def _refused(self, surface: str, action: str, exc: RoleError) -> None:
        if len(self.refusals) < 50:
            self.refusals.append({"surface": surface, "action": action, "code": exc.code})

    def _granted(self, stage: str, call: Callable[[], dict], *, already_granted: Callable[[], bool]) -> dict:
        if self.allowance is None or already_granted():
            # A durable grant replays without a new request: nothing to reserve.
            return call()
        before = self.allowance.physical_attempts[stage]
        if not self.allowance.reserve(stage):
            exc = RoleError("job_allowance_exhausted", "No call allowance remains for this operation")
            self._refused(stage, "begin", exc)
            raise exc
        try:
            result = call()
        except BaseException:
            # The journal rolled back: no grant exists, so the slot was never started.
            self.allowance.release_unstarted(stage, physical_attempts_before=before)
            raise
        if result.get("dispatch_granted") is True:
            self.allowance.attempt(stage)
        else:
            # A replayed durable grant authorizes no second request.
            self.allowance.release_unstarted(stage, physical_attempts_before=before)
        return result

    def _settle(self, stage: str, grant: Any, outcome: str) -> None:
        if self.allowance is not None and isinstance(grant, str) and grant not in self._settled:
            self._settled.add(grant)
            self.allowance.settle(stage, outcome)

    # -- producer surface --------------------------------------------------
    def batch_status(self, job_id):
        self._bind("batch_status", "read")
        return self.inner.batch_status(job_id)

    def read_batch_plan(self, job_id):
        self._bind("read_batch_plan", "read")
        return self.inner.read_batch_plan(job_id)

    def prepare_batch(self, plan_bytes, *, expected_plan_sha256, reservation, now, **options):
        self._bind("prepare_batch", "register")
        return self.inner.prepare_batch(plan_bytes, expected_plan_sha256=expected_plan_sha256,
                                        reservation=reservation, now=now, **options)

    def batch_work(self, action, payload, *, now, raw=None, **options):
        self._bind("batch_work", action, payload)
        if action == "acquire":
            try:
                self._admit_acquisition(payload.get("job_id"), now)
            except RoleError as exc:
                self._refused("batch_work", action, exc)
                raise
        if action == "begin":
            return self._granted("batch_writer", lambda: self.inner.batch_work(action, payload, now=now, raw=raw, **options),
                already_granted=lambda: self.inner.batch_work("status", {"job_id": payload.get("job_id")}, now=now).get("grant_id") is not None)
        result = self.inner.batch_work(action, payload, now=now, raw=raw, **options)
        if action == "observe_ack":
            self._settle("batch_writer", payload.get("grant_id"), "returned" if result.get("invalid_receipt_count", 0) < result.get("receipt_count", 0) else "malformed")
        elif action == "uncertain":
            self._settle("batch_writer", result.get("grant_id"), "unknown")
        return result

    def record_batch_results(self, payload, *, metadata, results, now, **options):
        self._bind("batch_results", "record", payload)
        return self.inner.record_batch_results(payload, metadata=metadata, results=results, now=now, **options)

    def batch_results_status(self, job_id, *, now):
        self._bind("batch_results", "index")
        return self.inner.batch_results_status(job_id, now=now)

    def review_batch_results(self, payload, *, now, **options):
        self._bind("batch_results", "review", payload)
        return self.inner.review_batch_results(payload, now=now, **options)

    # -- checker surface ---------------------------------------------------
    def acquire_check_lease(self, check_set_id, owner, ttl_seconds, *, now):
        self._bind("check_lease", "acquire", {"owner": owner})
        return self.inner.acquire_check_lease(check_set_id, owner, ttl_seconds, now=now)

    def candidate_checks(self, action, payload, *, now, request=None, receipt=None, **options):
        self._bind("candidate_checks", action, payload)
        call = lambda: self.inner.candidate_checks(action, payload, now=now, request=request, receipt=receipt, **options)  # noqa: E731
        if payload.get("stage") == "deterministic":
            # The journal still validates roles, leases, input identity and the
            # required null reservation. Its local grant authorizes no provider
            # request, so neither beginning nor completing it spends a call slot.
            return call()
        if action == "begin":
            base = {k: payload[k] for k in ("check_set_id", "owner", "fence", "current_context", "checker_state_sha256") if k in payload}
            return self._granted("local_required_check", call, already_granted=lambda: self.inner.candidate_checks(
                "status", base, now=now).get("stages", {}).get(payload.get("stage")) not in (None, "pending"))
        result = call()
        if action == "complete" and isinstance(result, dict) and not result.get("reused"):
            grant = receipt.get("grant_id") if isinstance(receipt, dict) else None
            key = grant if isinstance(grant, str) else f"{payload.get('check_set_id')}:{payload.get('stage')}"
            self._settle("local_required_check", key, _SETTLE.get(str(result.get("disposition")), "unknown"))
        return result

    def check_execution(self, action, payload, *, now, raw=None, **options):
        self._bind("check_execution", action, payload)
        return self.inner.check_execution(action, payload, now=now, raw=raw, **options)

    def read_check_request(self, check_set_id, stage, grant_id):
        self._bind("check_artifact", "read")
        return self.inner.read_check_request(check_set_id, stage, grant_id)

    def read_check_response(self, check_set_id, stage, grant_id):
        self._bind("check_artifact", "read")
        return self.inner.read_check_response(check_set_id, stage, grant_id)

    # -- shared/maintenance surface ---------------------------------------
    def spending(self, action, payload, *, now, **options):
        self._bind("spending", action, payload)
        return self.inner.spending(action, payload, now=now, **options)

    def import_snapshot(self, raw, *, import_id, now=None):
        self._bind("domain", "import_snapshot")
        return self.inner.import_snapshot(raw, import_id=import_id, now=now)

    def domain_status(self, *, verify=False):
        self._bind("domain", "status")
        return self.inner.domain_status(verify=verify)
