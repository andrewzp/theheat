"""One explicitly enabled local delivery phase; live publication stays disabled."""
from __future__ import annotations

import argparse
import json
import time

from src.commands import postgres_delivery as domain
from src.commands.postgres_authority import _clock
from src.commands.schema import utc_datetime, utc_text
from src.posting import delivery_transport as transport
from src.posting.delivery_receipts import digest
from src.posting.local_delivery import clean_environment, PHASE_SECONDS


def report(status, **values):
    return dict(outcome=status, scope=domain.SCOPE, publication_approved=False, **values)


def instant(clock):
    value = clock()
    return utc_datetime(value) if type(value) is str else _clock(value)


def execute_delivery_once(authority, intent_id, platform, stage, resolve_principal, *, owner,
                          clock, enabled=False, reconcile=False):
    if type(enabled) is not bool or type(reconcile) is not bool:
        raise ValueError("delivery_boolean_required")
    if not enabled:
        return report("disabled")
    clean_environment()

    def transaction(operation, *, current=False):
        ghcn = domain.prepare_context(authority, intent_id=intent_id) if current else None
        with authority.projections._connection(writing=operation is not read_only) as c:
            authority._validate(c)
            domain.validate(c, authority.environment)
            authority._pointer(c, lock=True)
            value = domain.read(c, intent_id)
            return operation(c, value, ghcn) if current else operation(c, value)

    def read_only(c, value):
        config, digest = domain.configuration(authority)
        domain.refuse(config == value["fixture"] and digest == value["configuration_sha256"], "delivery_configuration_changed")
        return value, domain.attempt(c, value, platform, stage)

    def finish(c, value):
        saved = domain.attempt(c, value, platform, stage)
        return domain.finish(c, value, saved) if saved else dict(status="pending", result=None)

    def retain(saved, response, source="response"):
        observation = dict(attempt_id=saved["attempt_id"], request_sha256=saved["request_sha256"],
            source=source, reason=response["reason"], http_status=response["http_status"], complete=response["complete"],
            raw_sha256=digest(response["raw"]), recorded_at=utc_text(instant(clock)))
        return transaction(lambda c,value: domain.observe(c, value, saved, observation, response["raw"]))

    try:
        value, saved = transaction(read_only)
        if saved is not None:
            recovered = transaction(finish)
            if not reconcile or recovered["status"] != "unknown":
                return report(recovered["status"], result=recovered["result"], network_mutation=False)
            response = transport.bounded_http(value["fixture"], method="GET", path="/__fixture/receipts/" + saved["attempt_id"],
                body=b"", content_type="application/json", attempt_id=saved["attempt_id"], request_sha256=saved["request_sha256"], deadline=time.monotonic()+PHASE_SECONDS)
            retain(saved, response, "reconciliation")
            recovered = transaction(finish)
            return report(recovered["status"], result=recovered["result"], network_mutation=False, reconciled=True)
        if reconcile:
            return report("pending", network_mutation=False)
        # Capture both clocks before the acquisition transaction. Delays in DB,
        # serialization, grant acknowledgement or a suspended parent consume
        # this original lifetime; they never create a later eligibility window.
        anchor, acquired_at = time.monotonic(), instant(clock)
        prepared = transaction(lambda c,value,ghcn: domain.acquire(authority, c, value, platform, stage,
            owner, resolve_principal, acquired_at, ghcn=ghcn), current=True)
        if "attempt" in prepared:
            return report("unknown", network_mutation=False)
        prepared["eligibility_deadline"] = anchor + (utc_datetime(prepared["lease"]["expires_at"])-acquired_at).total_seconds()

        dispatch_context = None
        def begin(request, body):
            nonlocal dispatch_context
            def grant(c, value, ghcn):
                result = domain.begin(authority, c, value, platform, stage, prepared["lease"],
                    request, body, resolve_principal, instant(clock), ghcn=ghcn)
                successor = domain.attempt_successor(authority, c, value, ghcn, result["binding"], request, body) \
                    if result.get("dispatch_granted") and ghcn is not None else None
                return result, successor
            result, successor = transaction(grant, current=True)
            # Expose the private one-use proof only after the barrier COMMIT.
            dispatch_context = successor
            return result

        def check(saved):
            return transaction(lambda c,value: domain.before_call(authority, c, value, saved,
                resolve_principal, instant(clock), ghcn=dispatch_context))

        result = transport.execute(value, platform, stage, prepared, begin=begin, observe=retain, check=check)
        if result["binding"] is None:
            # Serialization or uncertain barrier acknowledgement can fail before
            # the adapter received its grant. Read the original ID once; never
            # call transport again, even if the barrier is now visible.
            _, saved = transaction(read_only)
            return report("unknown" if saved else "not_dispatched", network_mutation=False)
        outcome = transaction(finish)
        return report(outcome["status"], result=outcome["result"], sdk_completed=result["sdk_completed"])
    except Exception as exc:
        code = getattr(exc, "code", None)
        return report("withheld" if code else "unknown", reason=code or "delivery_unavailable")


def main():
    from src.commands.preview_ingress import adapter, arguments
    parser = argparse.ArgumentParser(description=__doc__)
    arguments(parser)
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--platform", choices=("x", "bluesky"), required=True)
    parser.add_argument("--stage", choices=("upload", "alt", "create"), required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(report("disabled")))
        return 0
    try:
        authority, operators = adapter(args)
        result = execute_delivery_once(authority, args.intent_id, args.platform, args.stage, operators.resolve,
            owner=args.owner, clock=lambda: utc_text(_clock(None)), enabled=True, reconcile=args.reconcile)
        print(json.dumps(result))
        return 0 if result["outcome"] in {"confirmed", "not_sent", "pending"} else 1
    except Exception:
        print(json.dumps(report("unknown", reason="delivery_unavailable")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
