"""INVENTED callback units only: no PG/native/SDK/source/clock or HTTP fixture."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
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
    assert manager.hook.pytest_runtest_makereport(item=item, call=None) is report
    sections = dict(report.sections)
    assert sections["Last check windows (up to 8 rows / 64 KiB tail)"] == json.dumps([
        {key: value for key, value in window.items() if key != "kind"}], sort_keys=True, allow_nan=False)
    assert json.loads(sections[diagnostic.SECTION]) == [row]
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
