"""Default-OFF local batch submission. No polling, candidates or publication."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import os
import time
from typing import Protocol, cast

from src.commands.sqlite_authority import SQLiteAuthority

ACK_LIMIT = 65536
LEASE_SECONDS = 60
NETWORK_TIMEOUT = 30
_monotonic = time.monotonic


class BatchTransportError(ValueError):
    """Bounded transport diagnostic; never expose an API exception body."""


class BatchTransport(Protocol):
    def submit(self, requests: list[dict]) -> bytes: ...
    def close(self) -> None: ...


class AnthropicBatchTransport:
    """One SDK HTTP attempt; injected HTTP client is for offline tests only."""

    def __init__(self, *, api_key: str, http_client=None):
        if not isinstance(api_key, str) or not api_key.strip():
            raise BatchTransportError("missing_batch_credential")
        from anthropic import Anthropic
        import httpx

        if http_client is not None and http_client.follow_redirects:
            raise BatchTransportError("batch_redirects_must_be_disabled")
        client = http_client or httpx.Client(follow_redirects=False, timeout=NETWORK_TIMEOUT)
        try:
            self._client = Anthropic(
                api_key=api_key,
                base_url="https://api.anthropic.com",
                max_retries=0,
                timeout=NETWORK_TIMEOUT,
                http_client=client,
            )
        except Exception:
            client.close()
            raise BatchTransportError("batch_client_unavailable") from None

    def submit(self, requests: list[dict]) -> bytes:
        from anthropic.types.messages.batch_create_params import Request

        started = _monotonic()
        chunks = []
        size = 0
        try:
            with self._client.messages.batches.with_streaming_response.create(
                requests=cast(list[Request], requests), timeout=NETWORK_TIMEOUT
            ) as response:
                for chunk in response.iter_bytes(chunk_size=4096):
                    size += len(chunk)
                    if size > ACK_LIMIT or _monotonic() - started > NETWORK_TIMEOUT:
                        raise BatchTransportError("batch_ack_read_bound_exceeded")
                    chunks.append(chunk)
            return b"".join(chunks)
        except Exception:
            # SDK error bodies can contain unpublished inputs. The durable grant
            # remains uncertain regardless of API status or transport exception.
            raise BatchTransportError("batch_submit_response_unavailable") from None

    def close(self) -> None:
        self._client.close()


def _report(outcome, record=None, *, reason=None):
    value = {
        "outcome": outcome,
        "dispatch_granted": False,
        "publication_approved": False,
        "collection_granted": False,
        "provider_access_verified": False,
        "funding_verified": False,
    }
    if record:
        for field in ("job_id", "grant_id", "state", "provider_batch_id", "reservation_state"):
            if field in record:
                value[field] = record[field]
    if reason:
        value["reason"] = reason
    return value


def _uncertain(authority, job, owner, fence, clock, *, reason):
    try:
        record = authority.batch_work(
            "uncertain", dict(job_id=job, owner=owner, fence=fence), now=clock()
        )
        return _report("submission_uncertain", record, reason=reason)
    except Exception:
        # Ownership may have expired while the provider was processing, or the
        # database may be unavailable. Do not reacquire merely to change state.
        try:
            record = authority.batch_work("status", {"job_id": job}, now=clock())
        except Exception:
            record = {"job_id": job}
        outcome = (
            "blocked"
            if "grant_id" in record and record["grant_id"] is None
            else "reconciliation_required"
        )
        return _report(outcome, record, reason=reason)


def _attempt(authority, job, context, owner, clock, transport, requests):
    try:
        leased = authority.batch_work(
            "acquire", dict(job_id=job, owner=owner, ttl_seconds=LEASE_SECONDS), now=clock()
        )
        fence = leased["lease"]["fence"]
    except Exception:
        return _report("blocked", {"job_id": job}, reason="batch_lease_unavailable")
    identity = dict(job_id=job, owner=owner, fence=fence)
    try:
        grant = authority.batch_work("begin", dict(identity, current_context=context), now=clock())
    except Exception:
        # A commit might have succeeded even if its acknowledgment was lost.
        # Never rerun begin or call the provider without a confirmed true grant.
        return _uncertain(authority, job, owner, fence, clock, reason="batch_grant_not_confirmed")
    if not grant["dispatch_granted"]:
        return _report("not_dispatched", grant, reason="batch_attempt_already_recorded")
    try:
        raw = transport.submit(requests)
    except Exception:
        return _uncertain(authority, job, owner, fence, clock, reason="batch_response_unavailable")
    try:
        if type(raw) is not bytes or len(raw) > ACK_LIMIT:
            raise BatchTransportError("invalid_batch_ack_bytes")
        sha = hashlib.sha256(raw).hexdigest()
        observed = authority.batch_work(
            "observe_ack",
            dict(job_id=job, grant_id=grant["grant_id"], receipt_sha256=sha),
            now=clock(),
            raw=raw,
        )
    except Exception:
        return _uncertain(authority, job, owner, fence, clock, reason="batch_receipt_not_retained")
    if observed["invalid_receipt_count"]:
        return _uncertain(
            authority, job, owner, fence, clock, reason="invalid_batch_acknowledgment"
        )
    try:
        accepted = authority.batch_work("adopt", dict(identity, receipt_sha256=sha), now=clock())
    except Exception:
        return _report(
            "acknowledgment_retained", observed, reason="current_owner_reconciliation_required"
        )
    return _report("submitted", accepted)


def submit_batch_once(
    authority: SQLiteAuthority,
    job_id: str,
    *,
    current_context: dict,
    owner: str,
    clock: Callable[[], str],
    enabled: bool = False,
    transport_factory: Callable[[], BatchTransport] | None = None,
) -> dict:
    """Explicit local operation, unwired to production and OFF by default.

    The trusted caller supplies current evidence/context and a real UTC clock.
    Enabling this adapter is not permission to run a paid experiment. Production
    authority, scheduling, collection and required-check integration are separate.
    """
    if type(enabled) is not bool:
        raise BatchTransportError("batch_enabled_requires_boolean")
    if not enabled:
        return _report("disabled")
    from src.editorial.policy import current_editorial_policy
    from src.editorial.revisions import fingerprint
    from src.two_bot.batch_contract import validated_batch_plan
    from src.two_bot.provider_preflight import current_provider_preflight
    from src.commands.spend_journal import _id

    try:
        _id(job_id)
        _id(owner)
    except ValueError:
        return _report("blocked", reason="invalid_batch_identity")
    try:
        registration = authority.batch_status(job_id)
        raw = authority.read_artifact(registration["plan_sha256"])
        plan = validated_batch_plan(raw, expected_plan_sha256=registration["plan_sha256"])
        policy = current_editorial_policy()
        if policy is None or fingerprint(policy) != plan["policy_sha256"]:
            return _report("blocked", registration, reason="changed_runtime_policy")
        preflight = current_provider_preflight(critic_enabled=policy["flags"]["critic_enabled"])
        if preflight["status"] != "configured_unverified":
            return _report("blocked", registration, reason="missing_provider_prerequisite")
    except Exception:
        return _report("blocked", {"job_id": job_id}, reason="batch_plan_unavailable")
    try:
        transport = (
            transport_factory
            or (lambda: AnthropicBatchTransport(api_key=os.environ.get("ANTHROPIC_API_KEY", "")))
        )()
    except Exception:
        return _report("blocked", registration, reason="batch_transport_unavailable")
    report = None
    try:
        report = _attempt(
            authority, job_id, current_context, owner, clock, transport, plan["requests"]
        )
    finally:
        try:
            transport.close()
        except Exception:
            if report is not None:
                report["cleanup_failed"] = True
    return report
