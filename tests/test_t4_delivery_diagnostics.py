"""INVENTED callback units only: no PG/native/SDK/source/clock or HTTP fixture."""
from __future__ import annotations

import ast
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests import t4_delivery_diagnostics as diagnostic

PRIVATE = "INVENTED PRIVATE BODY /private/credential-path TOKEN=canary-never-log"


class InventedCommandError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(PRIVATE)

    def __str__(self):
        raise AssertionError("Diagnostic must not stringify exceptions")


def modules(before, execute):
    return SimpleNamespace(before_call=before, CommandError=InventedCommandError), SimpleNamespace(execute=execute)


def response(reason="received", status=400, complete=True):
    return {"reason": reason, "http_status": status, "complete": complete, "raw": PRIVATE.encode()}


def emitted(capture, result, *, platform="x", stage="upload"):
    rows: list[dict] = []
    capture.emit(rows.append, platform=platform, stage=stage, result=result)
    assert len(rows) == 1 and diagnostic.valid_row(rows[0])
    assert len(diagnostic._encoded(rows[0])) <= diagnostic.MAX_ROW_BYTES
    assert PRIVATE not in json.dumps(rows)
    return rows[0]


@pytest.mark.parametrize("code", ["delivery_stale_fence", "media_source_not_allowlisted", PRIVATE])
def test_before_call_codes_preserve_exception_identity_and_forward_objects_once(code):
    calls, token, named = [], object(), object()
    failure = InventedCommandError(code)

    def before(*args, **kwargs):
        calls.append((args, kwargs))
        raise failure

    def original_execute(*args, **kwargs):
        return None
    delivery, adapter = modules(before, original_execute)
    with diagnostic.observe_callbacks(delivery, adapter) as capture:
        with pytest.raises(InventedCommandError) as caught:
            delivery.before_call(token, ghcn=named)
    assert caught.value is failure
    assert calls == [((token,), {"ghcn": named})]
    assert delivery.before_call is before and adapter.execute is original_execute
    row = emitted(capture, {"outcome": "not_sent", "body": PRIVATE})
    assert row["before_call"] == {"status": "raised", "code": code if code in diagnostic.BEFORE_CODES else "unclassified"}
    assert row["adapter"]["status"] == "unavailable" and row["observations"] == []


def test_adapter_and_observation_forwarding_preserve_original_objects_and_returns_without_extra_calls():
    calls: list[tuple] = []
    value, saved, begin, check, observed_result = object(), object(), object(), object(), object()
    raw_response = response()
    adapter_result = {"sdk_completed": False, "binding": saved, "reason": "delivery_sdk_unavailable", "raw": PRIVATE}
    before_result = object()

    def before(*args, **kwargs):
        calls.append(("before", args, kwargs))
        return before_result

    def observe(*args, **kwargs):
        calls.append(("observe", args, kwargs))
        return observed_result

    def execute(*args, **kwargs):
        calls.append(("execute", args, kwargs["begin"], kwargs["check"]))
        assert delivery.before_call(saved, ghcn=value) is before_result
        assert kwargs["observe"](saved, raw_response) is observed_result
        return adapter_result

    delivery, adapter = modules(before, execute)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected additional clock/database/network operation")

    with patch("time.time", forbidden), patch("time.monotonic", forbidden), patch("socket.socket.connect", forbidden), \
            patch("sqlite3.connect", forbidden), patch("subprocess.run", forbidden), patch("subprocess.Popen", forbidden), \
            diagnostic.observe_callbacks(delivery, adapter) as capture:
        assert adapter.execute(value, "x", "upload", begin=begin, check=check, observe=observe) is adapter_result
    assert calls == [("execute", (value, "x", "upload"), begin, check),
                     ("before", (saved,), {"ghcn": value}), ("observe", (saved, raw_response), {})]
    assert raw_response["raw"] == PRIVATE.encode()
    row = emitted(capture, {"outcome": "not_sent"})
    assert row["before_call"] == {"status": "returned", "code": None}
    assert row["adapter"] == {"status": "returned", "reason": "delivery_sdk_unavailable", "sdk_completed": False, "binding_present": True}
    assert row["observations"] == [{"metadata": "available", "source": "response", "reason": "received",
        "http_status": 400, "complete": True, "callback": "returned"}]


def test_existing_window_guard_result_is_preserved_after_returned_check():
    binding, guard_result, events = object(), {"binding": object(), "sdk_completed": False,
        "reason": "delivery_final_currentness_refused"}, []

    def check(*args, **kwargs):
        events.append("check")

    def execute(*args, **kwargs):
        delivery.before_call(binding)
        events.append("original invented window guard")
        kwargs["observe"](binding, response("currentness_refused", None, False), "no_call")
        return guard_result

    delivery, adapter = modules(check, execute)
    with diagnostic.observe_callbacks(delivery, adapter) as capture:
        assert adapter.execute(observe=lambda *args: events.append("original observation")) is guard_result
    assert events == ["check", "original invented window guard", "original observation"]
    row = emitted(capture, {"outcome": "not_sent"})
    assert row["before_call"]["status"] == "returned"
    assert row["adapter"]["reason"] == "delivery_final_currentness_refused"
    assert row["observations"][0]["source"] == "no_call"


@pytest.mark.parametrize("site", ["adapter", "observation"])
def test_original_adapter_and_observation_exceptions_propagate_unchanged(site):
    failure = RuntimeError(PRIVATE)
    calls = []

    def observe(*args, **kwargs):
        calls.append("observe")
        raise failure

    def execute(*args, **kwargs):
        calls.append("execute")
        if site == "observation":
            kwargs["observe"](object(), response())
        raise failure

    delivery, adapter = modules(lambda *args: None, execute)
    with pytest.raises(RuntimeError) as caught:
        with diagnostic.observe_callbacks(delivery, adapter) as capture:
            adapter.execute(observe=observe)
    assert caught.value is failure and adapter.execute is execute
    assert calls == (["execute", "observe"] if site == "observation" else ["execute"])
    row = emitted(capture, {"outcome": "unknown"})
    assert row["adapter"]["status"] == "raised"
    assert row["observations"] == ([] if site == "adapter" else [{"metadata": "available", "source": "response",
        "reason": "received", "http_status": 400, "complete": True, "callback": "raised"}])


def test_missing_malformed_and_unknown_values_are_unavailable_never_inferred():
    capture = diagnostic.DeliveryDiagnostic()
    row = emitted(capture, {"outcome": "pending"})
    assert row["before_call"]["status"] == "unavailable"
    assert row["adapter"] == {"status": "unavailable", "reason": None, "sdk_completed": None, "binding_present": None}
    assert row["observations"] == []
    bad = {"reason": PRIVATE, "complete": True, "http_status": True, "raw": PRIVATE}
    sentinel = object()
    assert capture._observe(lambda *args, **kwargs: sentinel, object(), bad, PRIVATE) is sentinel
    row = emitted(capture, {"outcome": "unknown"})
    assert row["observations"] == [{"metadata": "unavailable", "source": None, "reason": None,
        "http_status": None, "complete": None, "callback": "returned"}]
    result = {"reason": PRIVATE, "binding": None, "sdk_completed": 1}
    assert capture._execute(lambda **kwargs: result) is result
    assert emitted(capture, {"outcome": "unknown"})["adapter"] == {
        "status": "returned", "reason": "unclassified", "sdk_completed": None, "binding_present": False}


def test_observation_and_row_bounds_and_failed_diagnostic_write_preserve_result():
    capture, calls, sentinel = diagnostic.DeliveryDiagnostic(), [], object()
    def observe(*args):
        calls.append(1)
        return sentinel
    for _ in range(10):
        assert capture._observe(observe, object(), response()) is sentinel
    assert len(calls) == 10
    row = emitted(capture, {"outcome": "confirmed"})
    assert len(row["observations"]) == diagnostic.MAX_OBSERVATIONS and row["observations_overflow"] is True

    def write_failure(row):
        raise OSError(PRIVATE)

    # The already completed operation result remains the same after a failed diagnostic write.
    operation_result = {"outcome": "confirmed", "sentinel": sentinel}
    capture.emit(write_failure, platform="x", stage="upload", result=operation_result)
    assert operation_result["sentinel"] is sentinel
    rows: list[dict] = []
    with patch.object(diagnostic, "MAX_ROW_BYTES", 1):
        capture.emit(rows.append, platform="x", stage="upload", result=operation_result)
    capture.emit(rows.append, platform=PRIVATE, stage="upload", result=operation_result)
    assert rows == []


def test_multiple_callback_evidence_cannot_masquerade_as_one_call():
    capture = diagnostic.DeliveryDiagnostic()
    for _ in range(3):
        capture._before(lambda: None, InventedCommandError)
        capture._execute(lambda: {"reason": "delivery_sdk_unavailable", "sdk_completed": False, "binding": object()})
    row = emitted(capture, {"outcome": "unknown"})
    assert row["before_call"] == {"status": "multiple", "code": None}
    assert row["adapter"] == {"status": "multiple", "reason": None, "sdk_completed": None, "binding_present": None}


def test_tail_reader_is_strict_bounded_and_never_dumps_generic_trace(tmp_path):
    row = emitted(diagnostic.DeliveryDiagnostic(), {"outcome": "not_sent"})
    path = tmp_path / "trace.jsonl"
    invalid = []
    for change in ({"private": PRIVATE}, {"stage": PRIVATE}, {"outcome": PRIVATE}, {"observations_overflow": 1}):
        invalid.append({**deepcopy(row), **change})
    changed = deepcopy(row)
    changed["before_call"] = {"status": "raised", "code": PRIVATE}
    invalid.append(changed)
    data = [(json.dumps({"kind": "delivery_stage", "result": PRIVATE}) + "\n").encode()]
    data += [json.dumps(value).encode() + b"\n" for value in invalid]
    data += [diagnostic._encoded(row).replace(b'"kind":', b'"kind":"duplicate", "kind":') + b"\n"]
    data += [(b"x" * (diagnostic.MAX_ROW_BYTES + 1)) + b"\n"]
    path.write_bytes(b"".join(data))
    assert diagnostic.last_rows(path) == []
    data += [diagnostic._encoded(row) + b"\n"] * 12
    path.write_bytes(b"".join(data))
    assert diagnostic.last_rows(path) == [row] * 8
    assert PRIVATE not in json.dumps(diagnostic.last_rows(path))
    # A discarded partial first line is not repaired/adopted as diagnostic evidence.
    path.write_bytes(diagnostic._encoded(row) + b"\n" + b"x" * diagnostic.TAIL_BYTES)
    assert diagnostic.last_rows(path) == []


def test_schema_rejects_numeric_bool_status_extra_payload_and_unknown_metadata(tmp_path):
    row = emitted(diagnostic.DeliveryDiagnostic(), {"outcome": "not_sent"})
    bad_cases: list[object] = [[], None, True, {**row, "payload": PRIVATE}]
    for bad in bad_cases:
        assert not diagnostic.valid_row(bad)
    capture = diagnostic.DeliveryDiagnostic()
    capture._observe(lambda *args: None, object(), response())
    row = emitted(capture, {"outcome": "not_sent"})
    for field, value in [("http_status", True), ("http_status", "400"), ("http_status", 99),
                         ("source", PRIVATE), ("reason", PRIVATE), ("complete", 1)]:
        changed = deepcopy(row)
        changed["observations"][0][field] = value
        assert not diagnostic.valid_row(changed)


def test_original_check_window_hook_ast_output_and_new_pluggy_hook_contract_are_preserved(tmp_path):
    from tests import conftest as shared
    source = Path(shared.__file__).read_text()
    expected = {"_last_check_windows": "e2e246563003831b2acc4140def015dd2e2102032c6fcae8ef8a9e07a3e2d5e9",
        "pytest_runtest_makereport": "5c61d0ff34f0d79976283713418c81f409509825c4f38464495669ac82a3e131"}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in expected:
            assert hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest() == expected[node.name]
    path = tmp_path / "trace.jsonl"
    window = {"kind": "check_window", "now": "2026-10-23T12:00:00Z", "lease_expires_at": "2026-10-23T12:03:00Z",
        "useful_until": "2026-10-23T13:00:00Z", "lease_remaining_seconds": 180, "available": True,
        "operation": "critic", "fault": ""}
    row = emitted(diagnostic.DeliveryDiagnostic(), {"outcome": "not_sent"})
    path.write_text(json.dumps(window) + "\n" + json.dumps(row) + "\n")
    item = SimpleNamespace(path=Path("test_postgres_temperature_delivery.py"), funcargs={"tmp_path": tmp_path,
        "compact_case": {"config": {"trace": str(path)}}})
    report = SimpleNamespace(failed=True, sections=[])
    manager = pytest.PytestPluginManager()
    manager.register(SimpleNamespace(pytest_runtest_makereport=lambda item, call: report), "invented-report")
    manager.register(SimpleNamespace(pytest_runtest_makereport=shared.pytest_runtest_makereport), "original-check-hook")
    manager.register(SimpleNamespace(pytest_delivery_refusal_report=shared.pytest_delivery_refusal_report), "new-delivery-hook")
    manager.register(SimpleNamespace(pytest_delivery_fixture_receipt_report=shared.pytest_delivery_fixture_receipt_report), "fixture-counter-hook")
    assert manager.hook.pytest_runtest_makereport(item=item, call=None) is report
    sections = dict(report.sections)
    assert sections["Last check windows (up to 8 rows / 64 KiB tail)"] == json.dumps([
        {key: value for key, value in window.items() if key != "kind"}], sort_keys=True, allow_nan=False)
    assert json.loads(sections[diagnostic.SECTION]) == [row]
    assert json.loads(sections[diagnostic.FIXTURE_SECTION]) == [diagnostic._fixture_counts(None)]
    assert PRIVATE not in json.dumps(sections)


def test_failure_hook_ownership_pass_other_file_missing_and_symlink(tmp_path):
    row = emitted(diagnostic.DeliveryDiagnostic(), {"outcome": "unknown"})
    owned = tmp_path / "owned"
    owned.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps(row) + "\n")
    link = owned / "link.jsonl"
    link.symlink_to(outside)
    item = SimpleNamespace(path=Path("test_postgres_temperature_delivery.py"), funcargs={"tmp_path": owned,
        "compact_case": {"config": {"trace": str(link)}}})
    report = SimpleNamespace(failed=True, sections=[])
    diagnostic.append_failure_section(item, report)
    assert report.sections == []
    item.funcargs["compact_case"]["config"]["trace"] = str(owned / "missing.jsonl")
    diagnostic.append_failure_section(item, report)
    assert report.sections == [(diagnostic.SECTION, "Delivery refusal diagnostics unavailable.")]
    report.sections.clear()
    report.failed = False
    diagnostic.append_failure_section(item, report)
    item.path = Path("some_other_test.py")
    report.failed = True
    diagnostic.append_failure_section(item, report)
    assert report.sections == []


@contextmanager
def no_new_operations():
    def forbidden(*args, **kwargs):
        raise AssertionError("Invented diagnostics must not add clocks/process/network/database/file/native calls")
    with ExitStack() as stack:
        for name in ("time.time", "time.monotonic", "time.monotonic_ns", "time.perf_counter", "time.perf_counter_ns", "time.sleep",
                     "socket.socket.connect", "sqlite3.connect", "subprocess.run", "subprocess.Popen",
                     "pathlib.Path.open", "pathlib.Path.read_bytes", "socket.socket", "os.system"):
            stack.enter_context(patch(name, forbidden))
        yield


class InventedChild:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[tuple] = []

    def communicate(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def poll(self):
        raise AssertionError("Diagnostic must not add poll")


def process_adapter(execute, popen):
    reference = SimpleNamespace(Popen=popen, TimeoutExpired=subprocess.TimeoutExpired, private=PRIVATE)
    delivery, adapter = modules(lambda *args: None, execute)
    adapter.subprocess = reference
    return delivery, adapter, reference


@pytest.mark.parametrize("first", ["returned", "TimeoutExpired", "raised"])
def test_parent_original_child_first_communicate_and_cleanup_identity_calls_and_restoration(first):
    token, launch_named, first_result, cleanup_result = object(), object(), object(), object()
    timeout = subprocess.TimeoutExpired(PRIVATE, 12.75, output=PRIVATE, stderr=PRIVATE)
    failure = InventedCommandError(PRIVATE)
    reply = first_result if first == "returned" else timeout if first == "TimeoutExpired" else failure
    child = InventedChild([reply, cleanup_result])
    inherited = InventedChild.communicate
    launches: list[tuple] = []
    adapter_result = dict(binding=object(), sdk_completed=False, reason="delivery_sdk_unavailable")

    def popen(*args, **kwargs):
        launches.append((args, kwargs))
        return child

    def execute(*args, **kwargs):
        assert adapter.subprocess is not reference and reference.Popen is popen
        original = adapter.subprocess.Popen(token, hidden=launch_named)
        assert original is child
        try:
            assert original.communicate(input=token, timeout=12.75) is first_result
        except (subprocess.TimeoutExpired, InventedCommandError) as caught:
            assert caught is reply
        assert original.communicate(token, 0.5) is cleanup_result
        return adapter_result

    delivery, adapter, reference = process_adapter(execute, popen)
    with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
        assert adapter.execute() is adapter_result
    assert adapter.subprocess is reference and reference.Popen is popen and adapter.execute is execute
    assert "communicate" not in vars(child) and InventedChild.communicate is inherited
    assert getattr(child.communicate, "__func__") is inherited and getattr(child.communicate, "__self__") is child
    assert launches == [((token,), {"hidden": launch_named})]
    assert child.calls == [((), {"input": token, "timeout": 12.75}), ((token, 0.5), {})]
    row = emitted(capture, {"outcome": "unknown"})["parent_http"]
    assert row == dict(kind=diagnostic.PARENT_KIND, available=True, popen_calls=1, communicate_calls=2,
        popen_outcome="returned", first_timeout=12.75, first_outcome=first)


def test_parent_prelaunch_zero_is_available_only_instrumented_and_popen_exception_unchanged():
    sentinel = object()
    def unused(*args, **kwargs):
        raise AssertionError("Original invented no-child branch")
    delivery, adapter, reference = process_adapter(lambda: sentinel, unused)
    with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
        assert adapter.execute() is sentinel
    parent = emitted(capture, {"outcome": "unknown"})["parent_http"]
    assert parent == dict(kind=diagnostic.PARENT_KIND, available=True, popen_calls=0,
        communicate_calls=0, popen_outcome=None, first_timeout=None, first_outcome=None)
    assert adapter.subprocess is reference
    assert emitted(diagnostic.DeliveryDiagnostic(), {"outcome": "unknown"})["parent_http"]["available"] is False
    failure = InventedCommandError(PRIVATE)
    def fails(*args, **kwargs):
        raise failure
    def execute():
        adapter.subprocess.Popen(PRIVATE)
    delivery, adapter, reference = process_adapter(execute, fails)
    with pytest.raises(InventedCommandError) as caught:
        with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
            adapter.execute()
    assert caught.value is failure and adapter.subprocess is reference and adapter.execute is execute
    assert emitted(capture, {"outcome": "unknown"})["parent_http"]["popen_outcome"] == "raised"


@pytest.mark.parametrize("timeout", [None, True, float("nan"), float("inf"), -1, 0, 15.01, 10**1000, PRIVATE],
    ids=["missing", "bool", "nan", "infinite", "negative", "zero", "outside-bound", "huge", "private-string"])
def test_parent_malformed_timeout_unavailable_without_changing_original_argument(timeout):
    sentinel = object()
    child = InventedChild([sentinel])
    def execute():
        assert adapter.subprocess.Popen().communicate(timeout=timeout) is sentinel
        return {"binding": None, "sdk_completed": False}
    delivery, adapter, reference = process_adapter(execute, lambda: child)
    with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
        adapter.execute()
    assert child.calls[0][1]["timeout"] is timeout and adapter.subprocess is reference
    assert emitted(capture, {"outcome": "unknown"})["parent_http"]["first_timeout"] is None


def test_parent_restores_original_instance_callable_after_uncaught_exception_and_bounds_counts():
    failure = InventedCommandError(PRIVATE)
    child = InventedChild([])
    calls = []
    def communicate(*args, **kwargs):
        calls.append((args, kwargs))
        raise failure
    setattr(child, "communicate", communicate)
    def execute():
        return adapter.subprocess.Popen().communicate(PRIVATE, timeout=0.01)
    delivery, adapter, reference = process_adapter(execute, lambda: child)
    with pytest.raises(InventedCommandError) as caught:
        with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
            adapter.execute()
    assert caught.value is failure and child.communicate is communicate and adapter.subprocess is reference
    assert calls == [((PRIVATE,), {"timeout": 0.01})]
    assert emitted(capture, {"outcome": "unknown"})["parent_http"]["first_outcome"] == "raised"

    child = InventedChild([None] * 10)
    def many():
        original = adapter.subprocess.Popen()
        for _ in range(10):
            original.communicate(timeout=1)
        return {"binding": None, "sdk_completed": False}
    delivery, adapter, _ = process_adapter(many, lambda: child)
    with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
        adapter.execute()
    parent = emitted(capture, {"outcome": "unknown"})["parent_http"]
    assert len(child.calls) == 10 and parent["available"] is False
    assert parent["communicate_calls"] == diagnostic.MAX_COMMUNICATE_CALLS + 1


def test_parent_unsupported_child_is_unchanged_unavailable_and_closed_schema_rejects_payloads():
    class SlottedChild:
        __slots__ = ()
        def communicate(self, **kwargs):
            return None
    child = SlottedChild()
    def execute():
        assert adapter.subprocess.Popen() is child
        return {"binding": None, "sdk_completed": False}
    delivery, adapter, _ = process_adapter(execute, lambda: child)
    with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
        adapter.execute()
    row = emitted(capture, {"outcome": "unknown"})
    assert row["parent_http"]["available"] is False
    for change in ({"argv": PRIVATE}, {"popen_calls": True}, {"communicate_calls": 1000},
                   {"first_timeout": float("nan")}, {"popen_outcome": PRIVATE}, {"available": 1}):
        changed = deepcopy(row)
        changed["parent_http"].update(change)
        assert not diagnostic.valid_row(changed)


def invented_fixture_objects():
    identity, request_hash = "a" * 64, "b" * 64
    trace = [dict(method="POST", path="/1.1/media/upload.json", body=PRIVATE.encode(),
        attempt_id=identity, request_sha256=request_hash, content_type=PRIVATE)]
    class Witnesses(dict):
        journal_path = property(lambda self: (_ for _ in ()).throw(AssertionError("No journal lookup")))
    accepted = Witnesses({identity: dict(kind="accepted", instance_id=PRIVATE, attempt_id=identity,
        request_sha256=request_hash, status=200, body_base64=PRIVATE)})
    return ({"private": PRIVATE}, trace, accepted)


@pytest.mark.parametrize("site", ["normal", "body", "enter", "teardown", "suppressed"])
def test_fixture_observer_original_tuple_objects_context_exception_and_teardown_once(site):
    objects, token, named, failure = invented_fixture_objects(), object(), object(), InventedCommandError(PRIVATE)
    events: list[object] = []
    @contextmanager
    def original(*args, **kwargs):
        events.append(("enter", args, kwargs))
        if site == "enter":
            raise failure
        try:
            yield objects
        except InventedCommandError as caught:
            assert caught is failure
            events.append("body error")
            if site != "suppressed":
                raise
        finally:
            events.append("teardown")
            if site == "teardown":
                raise failure
    owner = SimpleNamespace(fixture_server=original)
    try:
        with no_new_operations(), diagnostic.observe_fixture_server(owner) as capture:
            with owner.fixture_server(token, hidden=named) as yielded:
                assert yielded is objects and all(left is right for left, right in zip(yielded, objects))
                if site in ("body", "suppressed"):
                    raise failure
    except InventedCommandError as caught:
        assert caught is failure and site in ("body", "enter", "teardown")
    else:
        assert site in ("normal", "suppressed")
    assert owner.fixture_server is original
    assert events == [("enter", (token,), {"hidden": named})] + ([] if site == "enter" else
        (["body error"] if site in ("body", "suppressed") else []) + ["teardown"])
    rows = capture.output()
    assert len(rows) == 1 and PRIVATE not in json.dumps(rows)
    assert rows[0]["available"] is (site != "enter")
    if site != "enter":
        assert rows[0]["full_body_post"][0] == {"platform": "x", "stage": "upload", "count": 1}
        assert rows[0]["accepted_records"][0]["count"] == 1


def test_fixture_missing_malformed_overflow_and_unmatched_records_stay_unavailable():
    objects = invented_fixture_objects()
    malformed: list[object] = [None, (None, [], {}), (None, [], {"unmatched": {}}), (None, [None], {}),
        (None, [*objects[1]] * 65, {}), (None, [{**objects[1][0], "path": PRIVATE}], {}),
        (None, [{**objects[1][0], "body": PRIVATE}], {}),
        (None, objects[1], {"a" * 64: {**objects[2]["a" * 64], "status": True}}),
        (None, objects[1], {"a" * 64: {**objects[2]["a" * 64], "request_sha256": "c" * 64}})]
    # The complete empty fixed fixture is available and has actual zero counts.
    assert diagnostic._fixture_counts(malformed.pop(1))["available"] is True
    for value in malformed:
        assert diagnostic._fixture_counts(value) == {"kind": diagnostic.FIXTURE_KIND, "available": False,
            "full_body_post": None, "accepted_records": None}
    capture = diagnostic.FixtureReceiptDiagnostic()
    for _ in range(9):
        capture.retain(objects)
    assert len(capture.rows) == diagnostic.MAX_ROWS and capture.overflow
    assert capture.output() == [diagnostic._fixture_counts(None)]
    changes: list[dict] = [{"path": PRIVATE}, {"available": 1}, {"accepted_records": []}]
    for change in changes:
        row = {**diagnostic._fixture_counts(objects), **change}
        assert not diagnostic._valid_fixture(row)
    row = diagnostic._fixture_counts(objects)
    row["full_body_post"][0]["count"] = True
    assert not diagnostic._valid_fixture(row)


def test_fixture_projection_counts_existing_full_posts_and_convenience_records_only():
    config, trace, accepted = invented_fixture_objects()
    trace.append(dict(trace[0]))
    trace.append(dict(method="GET", path=PRIVATE))
    row = diagnostic._fixture_counts((config, trace, accepted))
    assert diagnostic._valid_fixture(row)
    assert row["full_body_post"][0]["count"] == 2 and row["accepted_records"][0]["count"] == 1
    assert all(value["count"] == 0 for value in row["full_body_post"][1:] + row["accepted_records"][1:])
    assert PRIVATE not in json.dumps(row) and len(diagnostic._encoded(row)) <= diagnostic.MAX_ROW_BYTES


def test_additive_fixture_autouse_scope_report_and_original_hook_contract(tmp_path):
    from tests import conftest as shared
    import tests
    objects, calls = invented_fixture_objects(), []
    @contextmanager
    def original():
        calls.append("enter")
        try:
            yield objects
        finally:
            calls.append("exit")
    owner = SimpleNamespace(fixture_server=original)
    selected = SimpleNamespace(node=SimpleNamespace(path=Path("test_postgres_temperature_delivery.py")))
    unrelated = SimpleNamespace(node=SimpleNamespace(path=Path("test_other.py")))
    with patch.object(tests, "test_postgres_delivery", owner, create=True), no_new_operations():
        generator = getattr(shared._t4_fixture_receipt_observer, "__wrapped__")(unrelated)
        assert next(generator) is None and owner.fixture_server is original
        with pytest.raises(StopIteration):
            next(generator)
        generator = getattr(shared._t4_fixture_receipt_observer, "__wrapped__")(selected)
        capture = next(generator)
        with owner.fixture_server() as yielded:
            assert yielded is objects
        with pytest.raises(StopIteration):
            next(generator)
    assert calls == ["enter", "exit"] and owner.fixture_server is original
    item = SimpleNamespace(path=selected.node.path, funcargs={"_t4_fixture_receipt_observer": capture})
    report = SimpleNamespace(failed=True, sections=[])
    manager = pytest.PytestPluginManager()
    manager.register(SimpleNamespace(pytest_runtest_makereport=lambda item, call: report), "invented-report")
    manager.register(SimpleNamespace(pytest_delivery_fixture_receipt_report=shared.pytest_delivery_fixture_receipt_report), "fixture-counter-hook")
    with no_new_operations():
        assert manager.hook.pytest_runtest_makereport(item=item, call=None) is report
    assert json.loads(dict(report.sections)[diagnostic.FIXTURE_SECTION]) == capture.output()
    assert PRIVATE not in json.dumps(report.sections)
    for failed, filename in ((False, "test_postgres_temperature_delivery.py"), (True, "test_other.py")):
        report.failed, item.path, report.sections = failed, Path(filename), []
        diagnostic.append_fixture_failure_section(item, report)
        assert report.sections == []


def test_fixture_diagnostic_failure_never_changes_original_context_result_or_exception():
    objects, events, failure = invented_fixture_objects(), [], InventedCommandError(PRIVATE)
    @contextmanager
    def original():
        try:
            yield objects
        finally:
            events.append("original teardown")
    owner = SimpleNamespace(fixture_server=original)
    def bad_write(objects):
        raise OSError(PRIVATE)
    with pytest.raises(InventedCommandError) as caught:
        with no_new_operations(), diagnostic.observe_fixture_server(owner) as capture:
            setattr(capture, "retain", bad_write)
            with owner.fixture_server() as yielded:
                assert yielded is objects
                raise failure
    assert caught.value is failure and events == ["original teardown"] and owner.fixture_server is original
    assert capture.output() == [diagnostic._fixture_counts(None)]
    capture.rows = [{"private": PRIVATE}]
    assert capture.output() == [diagnostic._fixture_counts(None)]


def test_multiple_parent_launches_cannot_masquerade_as_one_and_leave_both_children_original():
    children = [InventedChild([None]), InventedChild([None])]
    launches: list[InventedChild] = []
    def popen():
        child = children[len(launches)]
        launches.append(child)
        return child
    def execute():
        for expected in children:
            child = adapter.subprocess.Popen()
            assert child is expected
            child.communicate(timeout=1)
        return {"binding": None, "sdk_completed": False}
    delivery, adapter, reference = process_adapter(execute, popen)
    with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
        adapter.execute()
    parent = emitted(capture, {"outcome": "unknown"})["parent_http"]
    assert parent["available"] is False and parent["popen_calls"] == 2 and parent["communicate_calls"] == 2
    assert launches == children and all("communicate" not in vars(child) for child in children)
    assert adapter.subprocess is reference


def test_both_original_cleanup_communicates_forward_and_cannot_overwrite_first_timeout():
    first = subprocess.TimeoutExpired(PRIVATE, 13)
    cleanup = subprocess.TimeoutExpired(PRIVATE, 0.5)
    sentinel = object()
    child = InventedChild([first, cleanup, sentinel])
    def execute():
        original = adapter.subprocess.Popen()
        for expected, timeout in ((first, 13), (cleanup, 0.5)):
            with pytest.raises(subprocess.TimeoutExpired) as caught:
                original.communicate(input=PRIVATE, timeout=timeout)
            assert caught.value is expected
        assert original.communicate(timeout=0.01) is sentinel
        return {"binding": None, "sdk_completed": False}
    delivery, adapter, reference = process_adapter(execute, lambda: child)
    with no_new_operations(), diagnostic.observe_callbacks(delivery, adapter) as capture:
        adapter.execute()
    parent = emitted(capture, {"outcome": "unknown"})["parent_http"]
    assert parent["available"] is True and parent["communicate_calls"] == 3
    assert parent["first_timeout"] == 13 and parent["first_outcome"] == "TimeoutExpired"
    assert child.calls == [((), {"input": PRIVATE, "timeout": 13}), ((), {"input": PRIVATE, "timeout": 0.5}),
                           ((), {"timeout": 0.01})]
    assert "communicate" not in vars(child) and adapter.subprocess is reference
