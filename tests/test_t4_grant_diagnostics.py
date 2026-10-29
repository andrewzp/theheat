"""Invented grant callbacks only; no PG, native, SDK or HTTP fixture execution."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests import t4_grant_diagnostics as diagnostic
from tests.test_t4_delivery_diagnostics import InventedCommandError, PRIVATE, no_new_operations

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
LEASE = {"expires_at": "2026-10-29T12:00:30.000000Z", "private": PRIVATE}


def calls(now=NOW, lease=LEASE):
    acquire = (object(), object(), {"private": PRIVATE}, "x", "create", "owner", object(), now)
    begin = (*acquire[:5], lease, {"private": PRIVATE}, PRIVATE.encode(), acquire[6], now)
    context = (acquire[0], acquire[1], acquire[2], acquire[6], now)
    return acquire, begin, context


def owner(begin=lambda *a, **k: None, acquire=lambda *a, **k: {}, context=lambda *a, **k: (None, NOW)):
    return SimpleNamespace(begin=begin, acquire=acquire, context=context, CommandError=InventedCommandError)


def emitted(capture):
    rows: list[dict] = []
    with no_new_operations():
        capture.emit(rows.append)
    assert len(rows) == 1 and diagnostic.valid_row(rows[0])
    assert len(diagnostic._encoded(rows[0])) <= diagnostic.MAX_ROW_BYTES
    assert PRIVATE not in json.dumps(rows)
    return rows[0]


def test_forwarding_identity_context_scope_and_method_cleanup():
    args, begin_args, context_args = calls()
    token, result, package = object(), {"lease": LEASE}, {"private": PRIVATE}
    seen: list[tuple] = []

    def context(*a, **k):
        seen.append(("context", a, k))
        return package, NOW + timedelta(seconds=40)

    def acquire(*a, **k):
        seen.append(("acquire", a, k))
        return result

    def begin(*a, **k):
        seen.append(("begin", a, k))
        assert delivery.context(*context_args) == (package, NOW + timedelta(seconds=40))
        assert delivery.acquire(*args, ghcn=token) is result
        assert delivery.context(*context_args)[0] is package
        return token

    delivery = owner(begin, acquire, context)
    original = vars(delivery).copy()
    with no_new_operations(), diagnostic.observe_grant(delivery) as capture:
        assert delivery.context(*context_args)[0] is package
        assert delivery.acquire(*args, _name=token, _original=token) is result
        assert delivery.begin(*begin_args, ghcn=token, _name=token, _original=token) is token
    assert vars(delivery) == original
    assert [x[0] for x in seen] == ["context", "acquire", "begin", "context", "acquire", "context"]
    assert seen[1][1] == args and seen[1][2] == {"_name": token, "_original": token}
    assert seen[2][1] == begin_args and seen[2][2] == {"ghcn": token, "_name": token, "_original": token}
    row = emitted(capture)
    assert row["begin"] == dict(status="returned", code=None, now="2026-10-29T12:00:00.000000Z",
        lease_remaining_seconds=30.0, context_remaining_seconds=[40.0, 40.0])
    assert [a["scope"] for a in row["acquires"]] == ["initial", "begin"]
    assert all(a["lease_remaining_seconds"] == 30 for a in row["acquires"])


@pytest.mark.parametrize("code", ["delivery_window_insufficient", "delivery_stale_fence", "ghcn_preparation_expired", PRIVATE])
def test_nested_acquire_refusal_preserves_exact_exception_and_redacts_unknown(code):
    args, begin_args, context_args = calls()
    failure, seen = InventedCommandError(code), []

    def acquire(*a, **k):
        seen.append((a, k))
        raise failure

    def begin(*a, **k):
        delivery.context(*context_args)
        return delivery.acquire(*args)

    delivery = owner(begin, acquire, lambda *a, **k: (PRIVATE, NOW + timedelta(seconds=16)))
    with no_new_operations(), diagnostic.observe_grant(delivery) as capture:
        with pytest.raises(InventedCommandError) as caught:
            delivery.begin(*begin_args)
    assert caught.value is failure and seen == [(args, {})]
    row = emitted(capture)
    expected = code if code in diagnostic.CODES else "unclassified"
    assert row["begin"]["code"] == row["acquires"][0]["code"] == expected
    assert row["begin"]["context_remaining_seconds"] == [16.0]
    assert row["acquires"][0]["status"] == "raised"


def test_pre_context_refusal_and_initial_acquire_refusal_remain_distinct():
    args, begin_args, _ = calls()
    failure = InventedCommandError("delivery_stale_fence")

    def refuse(*a, **k):
        raise failure

    delivery = owner(refuse, refuse)
    with no_new_operations(), diagnostic.observe_grant(delivery) as capture:
        for function, original_args in ((delivery.acquire, args), (delivery.begin, begin_args)):
            with pytest.raises(InventedCommandError) as caught:
                function(*original_args)
            assert caught.value is failure
    row = emitted(capture)
    assert row["begin"]["context_remaining_seconds"] == []
    assert row["begin"]["status"] == "raised" and row["acquires"][0]["scope"] == "initial"


@pytest.mark.parametrize("microseconds", [-1, 0, 1])
def test_seventeen_second_remainders_preserve_microseconds_without_gate_changes(microseconds):
    _, args, context_args = calls()
    deadline = NOW + timedelta(seconds=17, microseconds=microseconds)
    args = (*args[:5], {"expires_at": deadline.isoformat().replace("+00:00", "Z")}, *args[6:])

    def begin(*a, **k):
        return delivery.context(*context_args)

    delivery = owner(begin, context=lambda *a, **k: (PRIVATE, deadline))
    with no_new_operations(), diagnostic.observe_grant(delivery) as capture:
        assert delivery.begin(*args) == (PRIVATE, deadline)
    row = emitted(capture)
    expected = 17 + microseconds / 1_000_000
    assert row["begin"]["lease_remaining_seconds"] == expected
    assert row["begin"]["context_remaining_seconds"] == [expected]


@pytest.mark.parametrize("fault", ["now", "lease", "deadline", "context_shape", "acquire_shape", "range"])
def test_malformed_projection_is_unavailable_without_changing_result(fault):
    args, begin_args, context_args = calls()
    token = object()
    if fault == "now":
        begin_args = (*begin_args[:9], datetime(2026, 10, 29))
    if fault == "lease":
        begin_args = (*begin_args[:5], {"expires_at": PRIVATE}, *begin_args[6:])
    context_result: object = (PRIVATE, PRIVATE if fault == "deadline" else NOW + timedelta(days=2) if fault == "range" else NOW)
    if fault == "context_shape":
        context_result = [PRIVATE, NOW]

    def begin(*a, **k):
        delivery.context(*context_args)
        if fault == "acquire_shape":
            delivery.acquire(*args)
        return token

    delivery = owner(begin, acquire=lambda *a, **k: token, context=lambda *a, **k: context_result)
    with no_new_operations(), diagnostic.observe_grant(delivery) as capture:
        assert delivery.begin(*begin_args) is token
    assert emitted(capture) == diagnostic._empty()


@pytest.mark.parametrize("boundary", ["begin", "acquire", "context"])
def test_overflow_is_bounded_and_forwards_every_original_once(boundary):
    args, begin_args, context_args = calls()
    seen: list[str] = []

    def acquire(*a, **k):
        seen.append("acquire")
        return {"lease": LEASE}

    def context(*a, **k):
        seen.append("context")
        return PRIVATE, NOW

    def begin(*a, **k):
        seen.append("begin")
        if boundary == "context":
            for _ in range(5):
                delivery.context(*context_args)

    delivery = owner(begin, acquire, context)
    with no_new_operations(), diagnostic.observe_grant(delivery) as capture:
        if boundary == "acquire":
            for _ in range(5):
                delivery.acquire(*args)
        else:
            for _ in range(2 if boundary == "begin" else 1):
                delivery.begin(*begin_args)
    assert seen.count(boundary) == (2 if boundary == "begin" else 5)
    assert len(capture.acquires) <= 2
    assert emitted(capture) == diagnostic._empty(True)


def test_observer_projection_and_emission_failure_do_not_change_return_or_exception():
    _, args, _ = calls()
    token, failure = object(), InventedCommandError("delivery_stale_fence")
    delivery = owner(lambda *a, **k: token)
    with no_new_operations(), patch.object(diagnostic, "_seconds", side_effect=RuntimeError(PRIVATE)), diagnostic.observe_grant(delivery) as capture:
        assert delivery.begin(*args) is token
    assert emitted(capture) == diagnostic._empty()

    def refuse(*a, **k):
        raise failure

    delivery.begin = refuse
    with no_new_operations(), patch.object(diagnostic.GrantDiagnostic, "_code", side_effect=RuntimeError(PRIVATE)), diagnostic.observe_grant(delivery) as capture:
        with pytest.raises(InventedCommandError) as caught:
            delivery.begin(*args)
    assert caught.value is failure and delivery.begin is refuse
    with no_new_operations():
        capture.emit(refuse)


def test_partial_install_cleanup_and_unsupported_owner():
    delivery = owner()
    original = delivery.begin
    delivery.acquire = None
    with no_new_operations(), diagnostic.observe_grant(delivery) as capture:
        assert delivery.begin is original
    assert emitted(capture) == diagnostic._empty()
    with no_new_operations(), diagnostic.observe_grant(object()) as capture:
        pass
    assert emitted(capture) == diagnostic._empty()


def test_closed_rows_tail_bounds_redaction_and_failure_section_ownership(tmp_path):
    _, args, _ = calls()
    with diagnostic.observe_grant(owner()) as capture:
        capture.call("begin", lambda *a: None, args, {})
    row = emitted(capture)
    invalid = deepcopy(row)
    invalid["begin"]["private"] = PRIVATE
    assert not diagnostic.valid_row(invalid)
    for value in [float("nan"), float("inf"), True, 86401]:
        invalid = deepcopy(row)
        invalid["begin"]["lease_remaining_seconds"] = value
        assert not diagnostic.valid_row(invalid)
    trace = tmp_path / "trace.jsonl"
    duplicate = diagnostic._encoded(row).replace(b'"kind":', b'"kind":"duplicate","kind":')
    trace.write_bytes(duplicate + b"\n" + json.dumps(invalid).encode() + b"\n" + b"x" * (diagnostic.MAX_ROW_BYTES + 1) + b"\n")
    assert diagnostic.last_rows(trace) == []
    trace.write_bytes(b"x" * diagnostic.TAIL_BYTES + b"\n" + duplicate + b"\n" + (diagnostic._encoded(row) + b"\n") * 12)
    assert diagnostic.last_rows(trace) == [row] * 8
    item = SimpleNamespace(path=Path("test_postgres_temperature_delivery.py"),
        funcargs={"compact_case": {"config": {"trace": str(trace)}}, "tmp_path": tmp_path})
    report = SimpleNamespace(failed=True, sections=[])
    diagnostic.append_failure_section(item, report)
    assert json.loads(dict(report.sections)[diagnostic.SECTION]) == [row] * 8
    assert PRIVATE not in json.dumps(report.sections)
    report.sections.clear()
    link = tmp_path / "link.jsonl"
    link.symlink_to(trace)
    item.funcargs["compact_case"]["config"]["trace"] = str(link)
    diagnostic.append_failure_section(item, report)
    assert report.sections == []
    item.funcargs["compact_case"]["config"]["trace"] = str(tmp_path.parent / "unowned.jsonl")
    diagnostic.append_failure_section(item, report)
    assert report.sections == []
    item.funcargs = {}
    diagnostic.append_failure_section(item, report)
    assert report.sections == [(diagnostic.SECTION, "Delivery grant diagnostics unavailable.")]
