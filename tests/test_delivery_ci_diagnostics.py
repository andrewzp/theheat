"""Offline tests for observational metadata; no application, PG or transport imports."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from tests import delivery_ci_diagnostics as diagnostic


class FakeTimer:
    def __init__(self, seconds, callback):
        self.seconds, self.callback = seconds, callback
        self.actions = []

    def start(self):
        self.actions.append("start")

    def cancel(self):
        self.actions.append("cancel")

    def join(self):
        self.actions.append("join")


def logger(tmp_path, timer_factory=FakeTimer):
    path = tmp_path / "diagnostic.jsonl"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    return diagnostic.DeliveryDiagnostics(fd, diagnostic.CASES[0], timer_factory=timer_factory), path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_exact_builtin_shapes_exclude_keys_values_and_custom_hooks():
    class HostileMeta(type):
        def __hash__(cls):
            raise AssertionError("class hash hook")

        def __eq__(cls, other):
            raise AssertionError("class equality hook")

    class Hostile(dict, metaclass=HostileMeta):
        def __iter__(self):
            raise AssertionError("iterator hook")

        def __len__(self):
            raise AssertionError("length hook")

        def values(self):
            raise AssertionError("values hook")

        def __repr__(self):
            raise AssertionError("repr hook")

        def __sizeof__(self):
            raise AssertionError("size hook")

    class Key:
        def __repr__(self):
            raise AssertionError("key repr hook")

    shape = diagnostic.shape({Key(): [Hostile(), "secret", b"private", (1, 2.0, None, True)]})
    assert shape["counts"] == dict(dict=1, list=1, tuple=1, str=1, bytes=1, scalar=4, other=1)
    assert shape["string_chars"] == shape["scanned_utf8_bytes"] == 6
    assert shape["bytes_length"] == 7 and shape["partial"] is False
    assert "secret" not in json.dumps(shape) and "private" not in json.dumps(shape)


def test_cycle_and_shared_container_are_not_recursively_traversed():
    shared = ["same"]
    value = [shared, shared]
    value.append(value)
    result = diagnostic.shape(value)
    assert result["nodes"] == 5 and result["repeated_containers"] == 2
    assert result["counts"]["str"] == 1 and result["partial"] is False


def test_wide_and_deep_shapes_report_original_caps_as_partial():
    wide = diagnostic.shape([None] * (diagnostic.MAX_NODES + 20))
    assert wide["nodes"] == diagnostic.MAX_NODES and wide["partial"] is True
    deep = value = []
    for _ in range(100):
        child = []
        value.append(child)
        value = child
    result = diagnostic.shape(deep)
    assert result["max_depth"] == diagnostic.MAX_DEPTH and result["partial"] is True


def test_utf8_scan_has_cumulative_character_bound_and_no_value_output():
    result = diagnostic.shape(["\U0001f30e" * 40_000, "\ud800" * 40_000])
    assert result["string_chars"] == 80_000
    assert result["scanned_utf8_bytes"] == 40_000 * 4 + (65_536 - 40_000) * 3
    assert result["partial"] is True


def test_wrapper_preserves_arguments_return_identity_and_call_pair(tmp_path):
    log, path = logger(tmp_path)
    arg, result = object(), object()
    seen = []

    def actual(value, *, named):
        seen.append((value, named))
        return result

    log.start()
    assert log.wrap("park", actual)(arg, named=arg) is result
    log.close()
    assert seen == [(arg, arg)]
    records = rows(path)
    assert [row["event"] for row in records] == ["started", "phase_begin", "phase_return", "closed"]
    assert records[1]["call"] == records[2]["call"] == 1
    assert log.timer.seconds == 110 and log.timer.actions == ["start", "cancel", "join"]


@pytest.mark.parametrize("error", [RuntimeError("secret"), SystemExit(73), KeyboardInterrupt("private")])
def test_wrapper_rethrows_same_base_exception_without_message(tmp_path, error):
    log, path = logger(tmp_path)

    def actual():
        raise error

    log.start()
    with pytest.raises(type(error)) as failure:
        log.wrap("run", actual)()
    assert failure.value is error
    log.close()
    assert "secret" not in path.read_text() and "private" not in path.read_text()
    assert rows(path)[2]["category"] == ("RuntimeError" if type(error) is RuntimeError else
                                        "SystemExit" if type(error) is SystemExit else "other")


def test_shape_failure_and_write_failure_do_not_change_application_result(tmp_path, monkeypatch):
    log, path = logger(tmp_path)
    result = object()
    log.start()

    def fail(*args, **kwargs):
        raise OSError("must not appear")

    with monkeypatch.context() as patch:
        patch.setattr(diagnostic, "shape", fail)
        assert log.wrap("run", lambda: result)() is result
    with monkeypatch.context() as patch:
        patch.setattr(diagnostic.os, "write", fail)
        assert log.wrap("run", lambda: result)() is result
    log.close()
    assert rows(path)[-1]["partial"] is True and rows(path)[-1]["errors"] == 4
    assert "must not appear" not in path.read_text()


def test_concurrent_calls_have_serialized_records_and_matching_ids(tmp_path):
    log, path = logger(tmp_path)
    log.start()
    wrapped = log.wrap("run", lambda value: value)
    values = [object() for _ in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(wrapped, values)) == values
    log.close()
    records = rows(path)
    begin = {row["call"] for row in records if row["event"] == "phase_begin"}
    end = {row["call"] for row in records if row["event"] == "phase_return"}
    assert begin == end == set(range(1, 13))


@pytest.mark.parametrize("limit", ["events", "bytes"])
def test_output_limits_reserve_truthful_partial_close_record(tmp_path, monkeypatch, limit):
    if limit == "events":
        monkeypatch.setattr(diagnostic, "MAX_EVENTS", 4)
    else:
        monkeypatch.setattr(diagnostic, "MAX_TOTAL_BYTES", 1_600)
    log, path = logger(tmp_path)
    log.start()
    for _ in range(10):
        log.wrap("run", lambda: None)()
    log.close()
    record = rows(path)[-1]
    assert record["event"] == "closed" and record["partial"] is True and record["dropped"] > 0
    assert len(rows(path)) <= diagnostic.MAX_EVENTS
    assert path.stat().st_size <= diagnostic.MAX_TOTAL_BYTES


def test_sample_is_bounded_code_locations_only_no_locals(tmp_path):
    class Frame:
        f_code = SimpleNamespace(co_filename="x.py", co_name="actual")
        f_lineno = 123
        f_back = None

        @property
        def f_locals(self):
            raise AssertionError("no local inspection")

    frame = Frame()
    frame.f_back = frame
    sample = diagnostic.frame_sample(frame)
    assert sample["partial"] is True
    assert len(sample["frames"]) <= diagnostic.MAX_FRAMES
    assert all(row == dict(file="x.py", function="actual", line=123) for row in sample["frames"])
    log, path = logger(tmp_path)
    log.start()
    log.timer.callback()
    log.close()
    real = rows(path)[1]
    assert real["event"] == "main_thread_sample" and real["frames"]
    assert all(set(row) == {"file", "function", "line"} for row in real["frames"])


def test_cancel_join_completes_running_callback_before_descriptor_close(tmp_path):
    entered, release, joined = threading.Event(), threading.Event(), threading.Event()

    class RunningTimer(FakeTimer):
        def start(self):
            def callback():
                entered.set()
                assert release.wait(2)
                self.callback()
            self.thread = threading.Thread(target=callback)
            self.thread.start()

        def join(self):
            self.thread.join()
            joined.set()

    log, path = logger(tmp_path, RunningTimer)
    log.start()
    assert entered.wait(2)
    closing = threading.Thread(target=log.close)
    closing.start()
    assert os.fstat(log.fd) and not joined.is_set()
    release.set()
    closing.join(2)
    assert not closing.is_alive() and joined.is_set()
    with pytest.raises(OSError):
        os.fstat(log.fd)
    assert [row["event"] for row in rows(path)] == ["started", "main_thread_sample", "closed"]
    log.close()  # Closing twice must not close a later descriptor reuse.


def test_duplicate_is_once_noninheritable_and_worker_refuses(tmp_path, monkeypatch):
    path = tmp_path / "dup.jsonl"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    real_dup = os.dup
    calls = []

    def duplicate(source):
        calls.append(source)
        return real_dup(fd)

    monkeypatch.setattr(diagnostic.os, "dup", duplicate)
    log = diagnostic.DeliveryDiagnostics.duplicate_stderr(diagnostic.CASES[0])
    assert calls == [2] and os.get_inheritable(log.fd) is False
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="main thread"):
            pool.submit(diagnostic.DeliveryDiagnostics.duplicate_stderr, diagnostic.CASES[0]).result()
    assert calls == [2]
    log.close()  # No timer was started; must not join an unstarted real Timer.
    os.close(fd)


def test_fixture_is_explicit_last_only_for_three_existing_nodes():
    tree = ast.parse(Path(__file__).with_name("test_postgres_delivery.py").read_text())
    users = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and any(arg.arg == "delivery_diagnostics" for arg in node.args.args)]
    assert {node.name for node in users} == {case.split("[")[0] for case in diagnostic.CASES}
    assert all(node.args.args[-1].arg == "delivery_diagnostics" for node in users)
    fixture = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "delivery_diagnostics")
    assert [ast.unparse(item) for item in fixture.decorator_list] == ["pytest.fixture"]
