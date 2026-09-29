"""One bounded local read cycle. Default OFF, separate from paid submission."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from typing import Protocol

from src.commands import batch_worker_journal as worker
from src.commands.batch_result_journal import MAX_RESULT_BYTES
from src.commands.sqlite_authority import SQLiteAuthority
from src.two_bot.batch_transport import (
    ACK_LIMIT, LEASE_SECONDS, AnthropicBatchTransport, BatchDownload, BatchTransportError,
)


class CollectionTransport(Protocol):
    def retrieve(self, provider_id: str) -> BatchDownload: ...
    def results(self, provider_id: str) -> BatchDownload: ...
    def close(self) -> None: ...


def _report(outcome, *, reason=None, receipt_id=None, review=None):
    result = dict(outcome=outcome, publication_approved=False, required_checks_completed=False,
                  dispatch_granted=False, accounting_complete=False, cost_usd=None)
    if reason:
        result["reason"] = reason
    if receipt_id:
        result["receipt_id"] = receipt_id
    if review:
        result["review"] = review
    return result


def _download(value, bound):
    if (not isinstance(value, BatchDownload) or type(value.raw) is not bytes
            or len(value.raw) > bound or type(value.complete) is not bool):
        raise BatchTransportError("invalid_batch_download")
    # Transport reason is deliberately not copied; adapters may hold secrets.
    return value


def _review(authority, identity, receipt_id, context, clock):
    from src.editorial.policy import current_editorial_policy
    from src.editorial.revisions import fingerprint

    try:
        policy = current_editorial_policy()
        if policy is None:
            return _report("retained", reason="runtime_policy_unavailable", receipt_id=receipt_id)
        current = dict(context, policy_sha256=fingerprint(policy))
        reviewed = authority.review_batch_results(
            dict(identity, receipt_id=receipt_id, current_context=current), now=clock()
        )
        return _report("reviewed", receipt_id=receipt_id, review=reviewed)
    except Exception:
        # The review commit may have succeeded; retry uses retained evidence,
        # never another submit or a remembered grant/eligibility decision.
        return _report("retained", reason="current_review_unavailable", receipt_id=receipt_id)


def _retain(authority, identity, grant, metadata, results, context, clock):
    try:
        receipt = authority.record_batch_results(
            dict(job_id=identity["job_id"], grant_id=grant,
                 metadata_sha256=hashlib.sha256(metadata.raw).hexdigest(),
                 results_sha256=hashlib.sha256(results.raw).hexdigest(),
                 complete=metadata.complete and results.complete),
            metadata=metadata.raw, results=results.raw, now=clock(),
        )
    except Exception:
        return _report("reconciliation_required", reason="result_retention_not_confirmed")
    return _review(authority, identity, receipt["receipt_id"], context, clock)


def _read_once(authority, identity, status, plan, context, clock, transport):
    provider_id = status["provider_batch_id"]
    try:
        metadata = _download(transport.retrieve(provider_id), ACK_LIMIT)
    except Exception:
        return _report("read_failed", reason="batch_metadata_unavailable")
    if not metadata.complete or worker._ack_id(metadata.raw, plan["samples"]) != provider_id:
        return _retain(authority, identity, status["grant_id"], metadata,
                       BatchDownload(b"", False), context, clock)
    decoded = json.loads(metadata.raw)
    if decoded["processing_status"] != "ended":
        # Progress is an observation, not terminal evidence. Do not fill the
        # bounded result journal with repeated unchanged polling snapshots.
        return _report("pending")
    try:
        results = _download(transport.results(provider_id), MAX_RESULT_BYTES)
    except Exception:
        # Keep terminal metadata even when the result stream never opens.
        results = BatchDownload(b"", False)
    return _retain(authority, identity, status["grant_id"], metadata, results, context, clock)


def collect_batch_once(
    authority: SQLiteAuthority,
    job_id: str,
    *,
    current_context: dict,
    owner: str,
    clock: Callable[[], str],
    enabled: bool = False,
    refresh: bool = False,
    transport_factory: Callable[[], CollectionTransport] | None = None,
) -> dict:
    """Recover existing work without a submission grant, paid check or draft.

    Default reuse is local, with a fresh fenced review. Explicit refresh performs
    at most two GETs; it is never a polling loop or automatic submission retry.
    Caller supplies current evidence/memory/epoch and a real UTC clock. The loaded
    editorial policy overrides any stale caller policy before a result review.
    """
    if type(enabled) is not bool or type(refresh) is not bool:
        raise BatchTransportError("batch_collection_flags_require_boolean")
    if not enabled:
        return _report("disabled")
    from src.two_bot import batch_contract as contract

    try:
        worker.spend_journal._id(job_id)
        worker.spend_journal._id(owner)
        if not isinstance(current_context, dict) or set(current_context) != contract._CONTEXT:
            raise ValueError("invalid_context")
        context = dict(current_context)
        for key in contract._CONTEXT - {"publication_epoch"}:
            contract._sha(context[key])
        contract._id(context["publication_epoch"])
        leased = authority.batch_work(
            "acquire", dict(job_id=job_id, owner=owner, ttl_seconds=LEASE_SECONDS), now=clock()
        )
        identity = dict(job_id=job_id, owner=owner, fence=leased["lease"]["fence"])
        index = authority.batch_results_status(job_id, now=clock())
    except Exception:
        return _report("blocked", reason="batch_collection_state_unavailable")
    if not refresh:
        receipt_id = index["chosen_receipt_id"]
        if receipt_id is None:
            complete = [r for r in index["receipts"] if r["complete"]]
            if complete:
                receipt_id = max(complete, key=lambda r: (r["recorded_at"], r["receipt_id"]))[
                    "receipt_id"
                ]
        if receipt_id:
            return _review(authority, identity, receipt_id, context, clock)
    status = index["submission"]
    if status["state"] != "submitted" or not status["provider_batch_id"]:
        return _report("blocked", reason="batch_submission_not_confirmed")
    if index["capacity_remaining"] <= 0:
        return _report("blocked", reason="batch_result_capacity_reached")
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return _report("blocked", reason="missing_batch_read_credential")
    try:
        registration = authority.batch_status(job_id)
        plan = contract.validated_batch_plan(
            authority.read_artifact(registration["plan_sha256"]),
            expected_plan_sha256=registration["plan_sha256"],
        )
        transport = (transport_factory or (
            lambda: AnthropicBatchTransport(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        ))()
    except Exception:
        return _report("blocked", reason="batch_collection_transport_unavailable")
    report = None
    try:
        report = _read_once(authority, identity, status, plan, context, clock, transport)
    finally:
        try:
            transport.close()
        except Exception:
            if report is not None:
                report["cleanup_failed"] = True
    return report
