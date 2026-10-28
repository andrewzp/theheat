"""Pure tests for the PG2 phase witness, with invented objects only.

No database, native, network, subprocess or clock call is permitted here: each
is trapped for the whole module, and the witness is driven only through an
injected writer, a local pipe or invented module objects.
"""
import ast
import contextlib
import hashlib
import sys
import os
import socket
import subprocess
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

from tests import parked_media_phase_witness as w

CANARIES = ("/Users/invented/private.json", "https://invented.example/secret", "sk-INVENTED-TOKEN",
            "Traceback", "SECRET-CANARY")


@pytest.fixture(autouse=True)
def _trapped(monkeypatch):
    def refused(*_args, **_kwargs):
        raise AssertionError("trapped call")
    for name in ("time", "time_ns", "monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns",
                 "process_time", "sleep"):
        monkeypatch.setattr(time, name, refused)
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(subprocess.Popen, "__init__", refused)
    for name in ("fork", "system", "execv", "execve", "posix_spawn"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, refused)
    yield
    assert w.current() is None


class Lines:
    def __init__(self, fail_at=None, error=OSError):
        self.lines: list[bytes] = []
        self.calls = 0
        self.fail_at = fail_at
        self.error = error

    def __call__(self, data):
        self.calls += 1
        if self.fail_at is not None and self.calls >= self.fail_at:
            raise self.error()
        self.lines.append(data)

    def text(self):
        return b"".join(self.lines).decode("ascii")

    def events(self):
        return [tuple(line.decode("ascii").split()[2:]) for line in self.lines]


class Plugins:
    """Invented plugin manager recording registration."""

    def __init__(self, fail=None):
        self.calls: list[tuple[str, Any, Any]] = []
        self.fail = fail

    def register(self, plugin, name=None):
        self.calls.append(("register", plugin, name))
        if self.fail == "register":
            raise ValueError("invented")

    def unregister(self, plugin):
        self.calls.append(("unregister", plugin, None))
        if self.fail == "unregister":
            raise ValueError("invented")


class Item:
    def __init__(self, nodeid=w.TARGET_NODEID, plugins=None):
        self.nodeid = nodeid
        self.config = types.SimpleNamespace(pluginmanager=Plugins() if plugins is None else plugins)


def invented_modules(log):
    """Invented stand-ins for the four real target modules, recording calls."""
    sentinel = object()

    def plain(name):
        def function(*args, **kwargs):
            log.append((name, args, kwargs))
            return (name, sentinel)
        return function

    source: Any = types.ModuleType("invented_source")
    source.retained, source.enroll = plain("retained"), plain("enroll")
    temperature: Any = types.ModuleType("invented_temperature")
    temperature.install_revision_protocol = plain("protocol")
    temperature.admit_compact = plain("admit")

    def ghcn_worker(case, operation, identity="", fault=""):
        log.append(("worker", operation))
        return {"operation": operation}

    def submit_command(case, body, role="editor", fault=""):
        log.append(("submit", body))
        return temperature.ghcn_worker(case, "consume", body)

    temperature.ghcn_worker, temperature.submit_command = ghcn_worker, submit_command
    delivery: Any = types.ModuleType("invented_delivery")
    delivery.passive_cost = plain("cost")

    @contextlib.contextmanager
    def ready_delivery(case, tmp_path, *, mode="normal"):
        log.append(("ready-start", mode))
        try:
            yield {"intent": "invented"}
        finally:
            log.append(("ready-finally",))

    delivery.ready_delivery = ready_delivery
    return {"tests.test_postgres_ghcn_source_results": source,
            "tests.test_postgres_temperature_editor_media": temperature,
            "tests.test_postgres_temperature_delivery": delivery}


def test_published_protocol_is_fixed_ascii_and_bounded():
    assert w.PREFIX == "THEHEAT-PG2-WITNESS/1"
    assert len(w.PHASES) == len(set(w.PHASES)) == 27 + len(w.BODY_PHASES) == 47
    assert set(w.BODY_PHASES) <= set(w.PHASES)
    assert set(w.FIXTURE_PHASES.values()) | set(w.WORKER_PHASES.values()) <= set(w.PHASES)
    assert {phase for *_, phase in w.TARGETS} <= set(w.PHASES)
    for kind, words in (("ENTER", w.PHASES), ("ERROR", w.PHASES), ("INVALID", w.TERMINAL_REASONS),
                        ("UNAVAILABLE", w.TERMINAL_REASONS + w.NOTE_REASONS)):
        for word in words:
            line = f"{w.PREFIX} {w.MAX_LINES:03d} {kind} {word}"
            assert line.isascii() and len(line) + 1 <= w.MAX_LINE_BYTES
            assert w.LINE.fullmatch(line)
    assert w.MAX_BYTES == w.MAX_LINES * w.MAX_LINE_BYTES == 16_384


def test_forward_calls_exactly_once_with_identical_arguments_and_result():
    lines = Lines()
    witness = w.Witness(lines)
    first, second, result = object(), {"key": object()}, object()
    seen = []

    def action(*args, **kwargs):
        seen.append((args, kwargs))
        return result

    assert w.forward(witness, "ready_admit", action, (first,), {"named": second}) is result
    assert len(seen) == 1 and seen[0][0][0] is first and seen[0][1]["named"] is second
    assert lines.events() == [("ENTER", "ready_admit"), ("EXIT", "ready_admit")]


@pytest.mark.parametrize("error", [ValueError("x"), KeyboardInterrupt(), GeneratorExit(),
                                   pytest.skip.Exception("invented skip")], ids=["value", "interrupt",
                                                                                 "generator_exit", "skip"])
def test_failed_action_reraises_the_same_object_with_error_and_no_exit(error):
    lines = Lines()
    witness = w.Witness(lines)
    calls = []

    def action():
        calls.append(1)
        raise error

    with pytest.raises(BaseException) as raised:
        w.forward(witness, "ready_command", action, (), {})
    assert raised.value is error and calls == [1]
    assert raised.value.__traceback__ is not None
    assert lines.events() == [("ENTER", "ready_command"), ("ERROR", "ready_command")]


@pytest.mark.parametrize("fail_at", [1, 2])
def test_writer_failure_never_replaces_result_or_exception(fail_at):
    result, error = object(), RuntimeError("invented")
    lines = Lines(fail_at=fail_at)
    witness = w.Witness(lines)
    assert w.forward(witness, "ready_cost", lambda: result, (), {}) is result
    assert witness.writer_failed and witness.stopped
    calls = lines.calls

    def failing():
        raise error

    with pytest.raises(RuntimeError) as raised:
        w.forward(witness, "ready_cost", failing, (), {})
    assert raised.value is error
    assert lines.calls == calls  # stopped: nothing more is attempted


def test_writer_exception_during_error_line_keeps_the_original_exception():
    error = LookupError("invented")
    lines = Lines(fail_at=2)
    witness = w.Witness(lines)

    def action():
        raise error

    with pytest.raises(LookupError) as raised:
        w.forward(witness, "ready_admit", action, (), {})
    assert raised.value is error and raised.value.__context__ is None


class Manager:
    """Invented context manager recording exact forwarding."""

    def __init__(self, value, suppress=False, enter_error=None, exit_error=None):
        self.value, self.suppress = value, suppress
        self.enter_error, self.exit_error = enter_error, exit_error
        self.entered, self.exited = 0, []

    def __enter__(self):
        self.entered += 1
        if self.enter_error:
            raise self.enter_error
        return self.value

    def __exit__(self, *triple):
        self.exited.append(triple)
        if self.exit_error:
            raise self.exit_error
        return self.suppress


def test_witnessed_context_forwards_enter_and_exit_exactly_once():
    lines = Lines()
    witness = w.Witness(lines)
    value = object()
    manager = Manager(value)
    with w.WitnessedContext(witness, manager) as target:
        assert target is value
    assert manager.entered == 1 and manager.exited == [(None, None, None)]
    assert lines.events() == [("ENTER", "ready_prepare"), ("EXIT", "ready_prepare"), ("ENTER", "ready_body"),
                              ("EXIT", "ready_body"), ("ENTER", "ready_cleanup"), ("EXIT", "ready_cleanup")]


def test_witnessed_context_passes_the_exact_exception_and_suppression_result():
    error = ValueError("body")
    for suppress in (False, True):
        lines = Lines()
        manager = Manager(object(), suppress=suppress)
        with contextlib.suppress(ValueError) if not suppress else contextlib.nullcontext():
            with w.WitnessedContext(w.Witness(lines), manager):
                raise error
        (triple,) = manager.exited
        assert triple[0] is ValueError and triple[1] is error and triple[2] is not None
        assert lines.events()[3:] == [("ERROR", "ready_body"), ("ENTER", "ready_cleanup"),
                                      ("EXIT", "ready_cleanup")]
    flag, kind, value, traceback = object(), object(), object(), object()  # type: Any, Any, Any, Any
    manager = Manager(object(), suppress=flag)
    assert w.WitnessedContext(w.Witness(Lines()), manager).__exit__(kind, value, traceback) is flag
    assert len(manager.exited) == 1 and all(a is b for a, b in zip(manager.exited[0], (kind, value, traceback)))


def test_failed_enter_has_no_body_or_cleanup_and_failed_exit_keeps_its_exception():
    entering = OSError("enter")
    lines = Lines()
    manager = Manager(object(), enter_error=entering)
    with pytest.raises(OSError) as raised:
        with w.WitnessedContext(w.Witness(lines), manager):
            pytest.fail("body must not run")
    assert raised.value is entering and manager.exited == []
    assert lines.events() == [("ENTER", "ready_prepare"), ("ERROR", "ready_prepare")]
    leaving = RuntimeError("exit")
    lines = Lines()
    manager = Manager(object(), exit_error=leaving)
    with pytest.raises(RuntimeError) as leaving_raised:
        with w.WitnessedContext(w.Witness(lines), manager):
            pass
    assert leaving_raised.value is leaving and len(manager.exited) == 1
    assert lines.events()[-2:] == [("ENTER", "ready_cleanup"), ("ERROR", "ready_cleanup")]


def test_generator_context_cleanup_order_is_preserved():
    order: list[Any] = []
    witness = w.Witness(lambda data: order.append(data.decode().split()[2:]))

    @contextlib.contextmanager
    def invented():
        order.append("generator-start")
        try:
            yield "value"
        finally:
            order.append("generator-finally")

    with pytest.raises(KeyError):
        with w.WitnessedContext(witness, invented()) as value:
            assert value == "value"
            order.append("body")
            raise KeyError("invented")
    assert order == [["ENTER", "ready_prepare"], "generator-start", ["EXIT", "ready_prepare"],
                     ["ENTER", "ready_body"], "body", ["ERROR", "ready_body"], ["ENTER", "ready_cleanup"],
                     "generator-finally", ["EXIT", "ready_cleanup"]]


def test_phase_context_never_suppresses_and_records_outcome():
    lines = Lines()
    witness = w.Witness(lines)
    error = pytest.skip.Exception("invented")
    with pytest.raises(pytest.skip.Exception) as raised:
        with w.Phase(witness, "setup"):
            raise error
    assert raised.value is error
    with w.Phase(witness, "call"):
        pass
    assert lines.events() == [("ENTER", "setup"), ("ERROR", "setup"), ("ENTER", "call"), ("EXIT", "call")]


def test_interposed_targets_nest_forward_once_and_restore_identity():
    log: list[Any] = []
    modules = invented_modules(log)
    originals = {(name, attribute): vars(modules[name])[attribute] for name, attribute, *_ in w.TARGETS}
    lines = Lines()
    witness = w.Witness(lines)
    undo = w.interpose(witness, modules)
    temperature = modules["tests.test_postgres_temperature_editor_media"]
    delivery = modules["tests.test_postgres_temperature_delivery"]
    assert temperature.ghcn_worker.__wrapped__ is originals[("tests.test_postgres_temperature_editor_media",
                                                              "ghcn_worker")]
    body = {"command_id": "invented"}
    with delivery.ready_delivery({}, None, mode="drop") as path:
        temperature.admit_compact("case", "field")
        assert temperature.submit_command("case", body) == {"operation": "consume"}
        for stage in ("deterministic", "safety", "fact_check", "critic", "unlisted"):
            temperature.ghcn_worker("case", stage, "id")
        temperature.ghcn_worker("case", operation="enroll")
        temperature.ghcn_worker("case", object())
    assert path == {"intent": "invented"}
    undo()
    assert all(vars(modules[name])[attribute] is original for (name, attribute), original in originals.items())
    assert log[0] == ("ready-start", "drop") and log[-1] == ("ready-finally",)
    assert [entry for entry in log if entry[0] == "submit"] == [("submit", body)]
    assert ("submit", body) in log and log.count(("worker", "consume")) == 1
    events = lines.events()
    assert events[:5] == [("ENTER", "ready_prepare"), ("EXIT", "ready_prepare"), ("ENTER", "ready_body"),
                          ("ENTER", "ready_admit"), ("EXIT", "ready_admit")]
    assert events[5:9] == [("ENTER", "ready_command"), ("ENTER", "worker_consume"),
                           ("EXIT", "worker_consume"), ("EXIT", "ready_command")]
    assert [phase for event, phase in events if event == "ENTER"][5:-1] == [
        "worker_check_deterministic", "worker_check_safety", "worker_check_fact_check",
        "worker_check_critic", "worker_other", "worker_enroll", "worker_other"]
    assert events[-3:] == [("EXIT", "ready_body"), ("ENTER", "ready_cleanup"), ("EXIT", "ready_cleanup")]


def test_missing_targets_are_noted_once_and_restore_conflict_is_terminal():
    modules = invented_modules([])
    del modules["tests.test_postgres_ghcn_source_results"]
    lines = Lines()
    witness = w.Witness(lines)
    witness.enter("protocol")
    undo = w.interpose(witness, modules)
    assert lines.events() == [("ENTER", "protocol"), ("UNAVAILABLE", "missing_target")]
    replacement = object()
    modules["tests.test_postgres_temperature_delivery"].passive_cost = replacement
    undo()
    assert modules["tests.test_postgres_temperature_delivery"].passive_cost is replacement
    assert lines.events()[-1] == ("INVALID", "restore_conflict") and witness.stopped
    assert w.parse(lines.text())["status"] == "invalid"


def test_nested_selection_is_inert_and_ends_the_active_witness(monkeypatch):
    read, write = os.pipe()
    monkeypatch.setattr(w.os, "dup", lambda fd: write if fd == 2 else pytest.fail("unexpected dup"))
    log: list[Any] = []
    modules = invented_modules(log)
    with w.selected_protocol(Item(), modules):
        outer = w.current()
        assert outer is not None
        with w.selected_protocol(Item(), modules):
            assert w.current() is outer
        assert outer.stopped
    data = os.read(read, w.MAX_BYTES)
    os.close(read)
    assert w.parse(data.decode("ascii")) == dict(status="invalid", reason="reentrant", lines=2, open=["protocol"],
                                                 last_closed=None, errors=[], notes=[])


def test_reentrant_emission_is_dropped_and_reported_invalid():
    lines = Lines()
    witness = w.Witness(lines)

    def writer(data):
        lines(data)
        if len(lines.lines) == 2:
            witness.enter("worker_other")  # reentry from inside a write
    witness._writer = writer
    witness.enter("protocol")
    witness.enter("setup")
    witness.exit("setup")
    assert lines.events() == [("ENTER", "protocol"), ("ENTER", "setup"), ("INVALID", "reentrant")]
    assert witness.stopped


@pytest.mark.parametrize("calls,reason", [
    ([("exit", "setup")], "malformed"),
    ([("enter", "setup"), ("exit", "call")], "malformed"),
    ([("enter", "not_a_phase")], "malformed"),
    ([("enter", "setup"), ("error", "protocol")], "malformed"),
], ids=["exit_without_enter", "crossed", "unknown_phase", "wrong_error"])
def test_malformed_sequences_are_reported_invalid(calls, reason):
    lines = Lines()
    witness = w.Witness(lines)
    for method, phase in calls:
        getattr(witness, method)(phase)
    assert lines.events()[-1] == ("INVALID", reason) and witness.stopped
    witness.enter("call")
    assert lines.events()[-1] == ("INVALID", reason)


def test_line_count_and_depth_overflow_are_explicit_and_bounded():
    lines = Lines()
    witness = w.Witness(lines)
    witness.enter("protocol")
    for _ in range(w.MAX_LINES):
        witness.enter("call")
        witness.exit("call")
    assert len(lines.lines) == w.MAX_LINES == witness.lines_written
    assert lines.events()[-1] == ("UNAVAILABLE", "overflow")
    assert sum(map(len, lines.lines)) == witness.bytes_written <= w.MAX_BYTES
    assert max(map(len, lines.lines)) <= w.MAX_LINE_BYTES
    assert w.parse(lines.text())["status"] == "unavailable"
    deep = Lines()
    witness = w.Witness(deep)
    for _ in range(w.MAX_DEPTH + 5):
        witness.enter("worker_other")
    assert len(deep.lines) == w.MAX_DEPTH + 1 and deep.events()[-1] == ("UNAVAILABLE", "overflow")


def test_foreign_thread_calls_forward_once_and_are_noted_once():
    lines = Lines()
    witness = w.Witness(lines)
    witness.enter("protocol")
    calls, results = [], []
    def recorded(value):
        calls.append(value)
        return value

    wrapped = w.wrap_call(witness, "ready_cost", recorded)
    marker = object()
    threads = [threading.Thread(target=lambda: results.append(wrapped(marker))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == [marker, marker] and all(result is marker for result in results)
    assert lines.events() == [("ENTER", "protocol")]
    witness.exit("protocol")
    assert lines.events() == [("ENTER", "protocol"), ("UNAVAILABLE", "foreign_thread"), ("EXIT", "protocol")]
    assert w.parse(lines.text())["notes"] == ["foreign_thread"]


def _complete_run():
    lines = Lines()
    witness = w.Witness(lines)
    witness.enter("protocol")
    with w.Phase(witness, "setup"):
        with w.Phase(witness, "compact_fixture"):
            pass
    with contextlib.suppress(ZeroDivisionError):
        with w.Phase(witness, "call"):
            with w.WitnessedContext(witness, Manager(object())):
                w.forward(witness, "worker_check_critic", lambda: None, (), {})
                raise ZeroDivisionError
    with w.Phase(witness, "teardown"):
        pass
    witness.exit("protocol")
    return lines.text()


def test_parse_reports_complete_incomplete_truncated_and_absent():
    text = _complete_run()
    complete = w.parse(text)
    assert complete["status"] == "complete" and complete["open"] == []
    assert complete["errors"] == ["ready_body", "call"] and complete["last_closed"] == "protocol"
    lines = text.splitlines(keepends=True)
    # A process death inside the check stage: no later line exists.
    cut = next(i for i, line in enumerate(lines) if line.split()[2:] == ["ENTER", "worker_check_critic"])
    crashed = w.parse("".join(lines[:cut + 1]))
    assert crashed["status"] == "incomplete"
    assert crashed["open"] == ["protocol", "call", "ready_body", "worker_check_critic"]
    assert crashed["last_closed"] == "ready_prepare"
    partial = w.parse("".join(lines[:cut]) + lines[cut][:30])
    assert partial["status"] == "truncated" and partial["open"] == ["protocol", "call", "ready_body"]
    # CI log columns and other stderr lines around witness lines are ignored.
    framed = "\n".join(f"test-partition (postgres, 2)\tRun\t2026-10-23T19:45:47Z {line.rstrip()}"
                       for line in lines) + "\nTimeout (0:05:00)!\n"
    assert w.parse("unrelated\n" + framed) == complete
    assert w.parse("no witness here\n")["status"] == "absent"
    assert w.parse("")["status"] == "absent"


@pytest.mark.parametrize("mutate,reason", [
    (lambda lines: lines[:2] + lines[3:], "sequence"),
    (lambda lines: lines[:3] + [lines[2]] + lines[3:], "sequence"),
    (lambda lines: [line.replace("ENTER setup", "ENTER sideways") for line in lines], "phase"),
    (lambda lines: [line.replace("EXIT setup", "EXIT call") for line in lines], "nesting"),
    (lambda lines: lines[1:], "sequence"),
    (lambda lines: [lines[0].replace(" 001 ", " 1 ")] + lines[1:], "format"),
    (lambda lines: lines + [f"{w.PREFIX} {len(lines) + 1:03d} UNAVAILABLE dragons\n"], "status"),
    (lambda lines: lines[:2] + [f"{w.PREFIX} 003 INVALID malformed\n",
                                f"{w.PREFIX} 004 EXIT setup\n"], "after_terminal"),
    (lambda lines: lines[:1] + [f"{w.PREFIX} 002 UNAVAILABLE missing_target\n",
                                f"{w.PREFIX} 003 UNAVAILABLE missing_target\n"], "duplicate_note"),
    (lambda lines: [lines[0].rstrip("\n") + " " + "x" * 64 + "\n"] + lines[1:], "format"),
], ids=["gap", "duplicate", "unknown_phase", "nesting", "start", "format", "status", "after_terminal",
        "duplicate_note", "long_line"])
def test_parse_rejects_malformed_sequences(mutate, reason):
    lines = _complete_run().splitlines(keepends=True)
    result = w.parse("".join(mutate(lines)))
    assert result["status"] == "invalid" and result["reason"] == reason


def test_parse_bounds_the_line_count():
    text = "".join(f"{w.PREFIX} {i:03d} ENTER call\n" for i in range(1, w.MAX_LINES + 2))
    assert w.parse(text)["status"] == "invalid" and w.parse(text)["reason"] == "count"


def test_privacy_canaries_never_reach_the_output():
    lines = Lines()
    witness = w.Witness(lines)
    canary_error = RuntimeError(" ".join(CANARIES))

    def leaky(*args, **kwargs):
        raise canary_error

    witness.enter("protocol")
    wrapped = w.wrap_worker(witness, leaky)
    for operation in (CANARIES[0], "consume"):
        with pytest.raises(RuntimeError):
            wrapped({"path": CANARIES[0], "url": CANARIES[1]}, operation, CANARIES[2], fault=CANARIES[4])
    w.wrap_call(witness, "ready_cost", lambda *a, **k: CANARIES)(*CANARIES, key=CANARIES[2])
    with contextlib.suppress(RuntimeError):
        with w.WitnessedContext(witness, Manager(CANARIES)):
            raise canary_error
    witness.exit("protocol")
    raw = b"".join(lines.lines)
    assert raw.isascii()
    for canary in CANARIES:
        assert canary.encode() not in raw
    assert all(w.LINE.fullmatch(line.decode().rstrip("\n")) for line in lines.lines)
    assert w.parse(raw.decode())["status"] == "complete"


def test_nonselected_items_have_zero_effect(monkeypatch):
    def refused(*_args, **_kwargs):
        raise AssertionError("no descriptor work for an unselected item")
    for name in ("dup", "write", "close"):
        monkeypatch.setattr(w.os, name, refused)
    log: list[Any] = []
    modules = invented_modules(log)
    before = {name: dict(vars(module)) for name, module in modules.items()}
    for nodeid in (w.TARGET_NODEID.replace("compact_case0", "compact_case1"),
                   w.TARGET_NODEID.split("[")[0], "tests/test_other.py::test_x", None):
        item = Item(nodeid)
        with w.selected_protocol(item, modules):
            assert w.current() is None
            assert w.pytest_phase(item, "setup") is w.NULL
            assert w.fixture_phase("compact_case") is w.NULL
    assert {name: dict(vars(module)) for name, module in modules.items()} == before
    assert all(vars(modules[name])[key] is value for name, values in before.items() for key, value in values.items())
    assert log == []


def test_selected_protocol_writes_to_a_duplicate_of_stderr_and_restores(monkeypatch):
    read, write = os.pipe()
    closed = []
    real_close = os.close
    monkeypatch.setattr(w.os, "dup", lambda fd: write if fd == 2 else pytest.fail("unexpected dup"))
    def recorded_close(fd):
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(w.os, "close", recorded_close)
    log: list[Any] = []
    modules = invented_modules(log)
    originals = {key: dict(vars(module)) for key, module in modules.items()}
    item = Item()
    with w.selected_protocol(item, modules):
        witness = w.current()
        assert isinstance(witness, w.Witness)
        with w.pytest_phase(item, "setup"):
            with w.fixture_phase("cluster"):
                pass
            with w.fixture_phase("compact_case"):
                modules["tests.test_postgres_ghcn_source_results"].retained("case")
        with w.pytest_phase(item, "call"):
            with modules["tests.test_postgres_temperature_delivery"].ready_delivery({}, None):
                pass
        with w.pytest_phase(item, "teardown"):
            pass
    assert w.current() is None and closed == [write]
    assert {key: dict(vars(module)) for key, module in modules.items()} == originals
    (registered, unregistered) = item.config.pluginmanager.calls
    assert registered[0] == "register" and registered[2] == w.PLUGIN_NAME
    assert isinstance(registered[1], w.FixtureWitnessPlugin) and unregistered == ("unregister", registered[1], None)
    data = os.read(read, w.MAX_BYTES)
    os.close(read)
    result = w.parse(data.decode("ascii"))
    assert result == dict(status="complete", reason=None, lines=20, open=[], last_closed="protocol",
                          errors=[], notes=[])
    assert [line.split()[2:] for line in data.decode().splitlines()][:6] == [
        ["ENTER", "protocol"], ["ENTER", "setup"], ["ENTER", "fixture_cluster"], ["EXIT", "fixture_cluster"],
        ["ENTER", "compact_fixture"], ["ENTER", "compact_retain"]]


def test_unavailable_stderr_duplicate_forwards_without_witness(monkeypatch):
    def unavailable(fd):
        raise OSError()
    monkeypatch.setattr(w.os, "dup", unavailable)
    modules = invented_modules([])
    before = {key: dict(vars(module)) for key, module in modules.items()}
    error = ValueError("invented")
    with pytest.raises(ValueError) as raised:
        with w.selected_protocol(Item(), modules):
            assert w.current() is None
            raise error
    assert raised.value is error
    assert {key: dict(vars(module)) for key, module in modules.items()} == before


def test_selected_protocol_reraises_the_protocol_exception(monkeypatch):
    read, write = os.pipe()
    monkeypatch.setattr(w.os, "dup", lambda fd: write)
    error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as raised:
        with w.selected_protocol(Item(), invented_modules([])):
            raise error
    assert raised.value is error
    data = os.read(read, w.MAX_BYTES).decode()
    os.close(read)
    assert w.parse(data)["errors"] == ["protocol"] and w.parse(data)["status"] == "complete"


def test_fd_writer_completes_partial_writes(monkeypatch):
    chunks = []

    def partial(fd, view):
        chunk = bytes(view[:7])
        chunks.append(chunk)
        return len(chunk)

    monkeypatch.setattr(w.os, "write", partial)
    w.FdWriter(99)(b"0123456789abcdefghij")
    assert b"".join(chunks) == b"0123456789abcdefghij"
    monkeypatch.setattr(w.os, "write", lambda fd, view: 0)
    with pytest.raises(OSError):
        w.FdWriter(99)(b"x")


def test_conftest_hooks_delegate_and_forward_hook_results_unchanged():
    from tests import conftest
    result = object()
    for hook, args in ((conftest.pytest_runtest_protocol, (Item("tests/other.py::t"), None)),
                       (conftest.pytest_runtest_setup, (Item(),)),
                       (conftest.pytest_runtest_call, (Item(),)),
                       (conftest.pytest_runtest_teardown, (Item(), None)),
                       (w.FixtureWitnessPlugin().pytest_fixture_setup,
                        (types.SimpleNamespace(argname="compact_case"), None))):
        generator = hook(*args)
        next(generator)
        with pytest.raises(StopIteration) as stopped:
            generator.send(result)
        assert stopped.value.value is result
        error = RuntimeError("invented")
        generator = hook(*args)
        next(generator)
        with pytest.raises(RuntimeError) as raised:
            generator.throw(error)
        assert raised.value is error


def test_witness_module_imports_no_clock_process_network_database_or_native_code():
    source = Path(w.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {"__future__", "functools", "os", "re", "sys", "threading", "collections", "types",
                        "typing", "pytest"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not names & {"time", "datetime", "monotonic", "perf_counter", "subprocess", "socket", "ctypes",
                        "psycopg", "faulthandler", "traceback", "inspect", "open", "environ", "getenv",
                        "import_module", "__import__", "format_exc", "repr"}


def test_fixture_plugin_witnesses_every_scope_and_preserves_outcomes(monkeypatch):
    read, write = os.pipe()
    monkeypatch.setattr(w.os, "dup", lambda fd: write)
    plugin = w.FixtureWitnessPlugin()
    result, error = object(), AssertionError("invented native profile refusal")
    with w.selected_protocol(Item(), invented_modules([])):
        generator = plugin.pytest_fixture_setup(types.SimpleNamespace(argname="native_dependencies"), None)
        next(generator)
        with pytest.raises(StopIteration) as stopped:
            generator.send(result)
        assert stopped.value.value is result
        generator = plugin.pytest_fixture_setup(types.SimpleNamespace(argname="database"), None)
        next(generator)
        with pytest.raises(AssertionError) as raised:
            generator.throw(error)
        assert raised.value is error
        generator = plugin.pytest_fixture_setup(types.SimpleNamespace(argname="tmp_path"), None)
        next(generator)
        with pytest.raises(StopIteration):
            generator.send(None)
    data = os.read(read, w.MAX_BYTES).decode()
    os.close(read)
    assert [line.split()[2:] for line in data.splitlines()] == [
        ["ENTER", "protocol"], ["ENTER", "fixture_native"], ["EXIT", "fixture_native"],
        ["ENTER", "fixture_database"], ["ERROR", "fixture_database"], ["EXIT", "protocol"]]


@pytest.mark.parametrize("fail,expected", [("register", ("UNAVAILABLE", "missing_target")),
                                           ("unregister", ("INVALID", "restore_conflict"))])
def test_plugin_registration_failures_are_explicit(monkeypatch, fail, expected):
    read, write = os.pipe()
    monkeypatch.setattr(w.os, "dup", lambda fd: write)
    with w.selected_protocol(Item(plugins=Plugins(fail=fail)), invented_modules([])):
        pass
    data = os.read(read, w.MAX_BYTES).decode()
    os.close(read)
    assert tuple(data.splitlines()[1].split()[2:]) == expected


# --- F1: the witness's own failures, of any BaseException type, stay inside it ---

class DiagnosticAbort(BaseException):
    """Invented: raised only by the witness's own writer or installation step."""


class OriginalStop(BaseException):
    """Invented: raised only by the observed operation itself."""


DIAGNOSTIC_FAILURES = pytest.mark.parametrize("failure", [DiagnosticAbort, KeyboardInterrupt, SystemExit, GeneratorExit],
                                              ids=["custom", "interrupt", "system_exit", "generator_exit"])
ORIGINAL_ERRORS = pytest.mark.parametrize("make_error", [OriginalStop, KeyboardInterrupt, lambda: SystemExit(3), GeneratorExit,
                                                          lambda: ValueError("x")],
                                          ids=["custom", "interrupt", "system_exit", "generator_exit", "value"])


@DIAGNOSTIC_FAILURES
def test_writer_failure_on_enter_still_calls_the_original_exactly_once(failure):
    lines, marker, result, calls = Lines(fail_at=1, error=failure), object(), object(), []
    witness = w.Witness(lines)

    def original(argument, *, named):
        calls.append((argument, named))
        return result

    assert w.forward(witness, "ready_admit", original, (marker,), {"named": marker}) is result
    assert calls == [(marker, marker)] and calls[0][0] is marker
    assert witness.stopped and lines.lines == [] and lines.calls == 1


@DIAGNOSTIC_FAILURES
def test_writer_failure_on_exit_returns_the_result_and_never_fabricates_completion(failure):
    lines, result, calls = Lines(fail_at=2, error=failure), object(), []
    witness = w.Witness(lines)

    def original(mark):
        calls.append(mark)
        return result

    assert w.forward(witness, "ready_cost", original, (1,), {}) is result
    assert w.forward(witness, "ready_cost", original, (2,), {}) is result
    assert calls == [1, 2] and witness.stopped
    assert lines.events() == [("ENTER", "ready_cost")] and lines.calls == 2


@DIAGNOSTIC_FAILURES
@ORIGINAL_ERRORS
def test_writer_failure_on_error_keeps_the_original_exception(failure, make_error):
    lines, error, calls = Lines(fail_at=2, error=failure), make_error(), []
    witness = w.Witness(lines)

    def original():
        calls.append(1)
        raise error

    with pytest.raises(BaseException) as raised:
        w.forward(witness, "ready_command", original, (), {})
    assert raised.value is error and calls == [1]
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert lines.events() == [("ENTER", "ready_command")] and witness.stopped


@DIAGNOSTIC_FAILURES
@pytest.mark.parametrize("body_raises", [False, True], ids=["body_returns", "body_raises"])
def test_ready_body_report_failure_still_runs_manager_exit_once(failure, body_raises):
    # Lines: 1 ENTER ready_prepare, 2 EXIT ready_prepare, 3 ENTER ready_body, 4 EXIT/ERROR ready_body fails.
    lines, value, flag, error = Lines(fail_at=4, error=failure), object(), object(), OriginalStop()
    manager = Manager(value, suppress=False if body_raises else flag)
    context = w.WitnessedContext(w.Witness(lines), manager)
    if body_raises:
        with pytest.raises(OriginalStop) as raised:
            with context as target:
                assert target is value
                raise error
        assert raised.value is error
        (triple,) = manager.exited
        assert triple[0] is OriginalStop and triple[1] is error and triple[2] is not None
    else:
        assert context.__enter__() is value
        assert context.__exit__(None, None, None) is flag
        assert manager.exited == [(None, None, None)]
    assert manager.entered == 1 and len(manager.exited) == 1
    assert lines.events() == [("ENTER", "ready_prepare"), ("EXIT", "ready_prepare"), ("ENTER", "ready_body")]


@DIAGNOSTIC_FAILURES
@pytest.mark.parametrize("fail_at", [5, 6], ids=["cleanup_enter", "cleanup_error"])
def test_cleanup_report_failure_keeps_the_managers_own_exit_exception(failure, fail_at):
    leaving, lines = OriginalStop(), Lines(fail_at=fail_at, error=failure)
    manager = Manager(object(), exit_error=leaving)
    with pytest.raises(OriginalStop) as raised:
        with w.WitnessedContext(w.Witness(lines), manager):
            pass
    assert raised.value is leaving and manager.entered == 1 and len(manager.exited) == 1
    assert lines.events()[:4] == [("ENTER", "ready_prepare"), ("EXIT", "ready_prepare"), ("ENTER", "ready_body"),
                                  ("EXIT", "ready_body")]
    assert ("EXIT", "ready_cleanup") not in lines.events()


@DIAGNOSTIC_FAILURES
def test_phase_report_failures_never_change_the_phase_outcome(failure):
    error = OriginalStop()
    for fail_at in (1, 2):
        ran = []
        with pytest.raises(OriginalStop) as raised:
            with w.Phase(w.Witness(Lines(fail_at=fail_at, error=failure)), "call"):
                ran.append(1)
                raise error
        assert raised.value is error and ran == [1]
    witness = w.Witness(Lines(fail_at=1, error=failure))
    with w.Phase(witness, "setup"):
        ran.append(2)
    assert ran == [1, 2] and witness.stopped


class GuardedModule(types.ModuleType):
    """Invented module whose attribute writes raise for one name, from a given call onward."""

    def __init__(self, name, failing, failure, after=0):
        super().__init__(name)
        object.__setattr__(self, "_failing", failing)
        object.__setattr__(self, "_failure", failure)
        object.__setattr__(self, "_writes", after)

    def __setattr__(self, key, value):
        if key == self._failing:
            object.__setattr__(self, "_writes", self._writes - 1)
            if self._writes < 0:
                raise self._failure()
        object.__setattr__(self, key, value)


def public(module):
    """Module attributes without the invented guard's own bookkeeping."""
    return {key: value for key, value in vars(module).items() if not key.startswith("_")}


def _protocol_with(monkeypatch, modules, plugins):
    read, write = os.pipe()
    monkeypatch.setattr(w.os, "dup", lambda fd: write)
    ran = []
    with w.selected_protocol(Item(plugins=plugins), modules):
        ran.append(w.current())
    assert len(ran) == 1 and w.current() is None
    data = os.read(read, w.MAX_BYTES).decode("ascii")
    os.close(read)
    return data


@DIAGNOSTIC_FAILURES
@pytest.mark.parametrize("fail", ["register", "unregister"])
def test_plugin_installation_and_removal_failures_never_block_the_protocol(monkeypatch, failure, fail):
    class Failing(Plugins):
        def register(self, plugin, name=None):
            self.calls.append(("register", plugin, name))
            if fail == "register":
                raise failure()

        def unregister(self, plugin):
            self.calls.append(("unregister", plugin, None))
            if fail == "unregister":
                raise failure()
    modules = invented_modules([])
    before = {key: dict(vars(module)) for key, module in modules.items()}
    data = _protocol_with(monkeypatch, modules, Failing())
    assert {key: dict(vars(module)) for key, module in modules.items()} == before
    assert data.splitlines()[0].split()[2:] == ["ENTER", "protocol"]


@DIAGNOSTIC_FAILURES
def test_interposition_failure_restores_installed_wrappers_and_runs_the_protocol(monkeypatch, failure):
    modules = invented_modules([])
    original = modules["tests.test_postgres_temperature_editor_media"]
    guarded = GuardedModule("tests.test_postgres_temperature_editor_media", "submit_command", failure)
    for key, value in vars(original).items():
        if not key.startswith("__"):
            object.__setattr__(guarded, key, value)
    modules["tests.test_postgres_temperature_editor_media"] = guarded
    before = {key: public(module) for key, module in modules.items()}
    data = _protocol_with(monkeypatch, modules, Plugins())
    assert {key: public(module) for key, module in modules.items()} == before
    assert all(public(module)[key] is value for name, module in modules.items() for key, value in before[name].items())
    assert w.parse(data) == dict(status="invalid", reason="malformed", lines=2, open=["protocol"], last_closed=None,
                                 errors=[], notes=[])


@DIAGNOSTIC_FAILURES
def test_restoration_failure_still_restores_every_other_target(monkeypatch, failure):
    modules = invented_modules([])
    original = modules["tests.test_postgres_temperature_editor_media"]
    # The install write succeeds; the restore write of the same attribute raises.
    guarded = GuardedModule("tests.test_postgres_temperature_editor_media", "submit_command", failure, after=1)
    for key, value in vars(original).items():
        if not key.startswith("__"):
            object.__setattr__(guarded, key, value)
    modules["tests.test_postgres_temperature_editor_media"] = guarded
    originals = {(name, key): value for name, module in modules.items() for key, value in public(module).items()}
    data = _protocol_with(monkeypatch, modules, Plugins())
    for (name, key), value in originals.items():
        if key != "submit_command":
            assert public(modules[name])[key] is value
    assert data.splitlines()[-1].split()[2:] == ["INVALID", "restore_conflict"]



# --- G1: fixed body spans inside the selected target's ready_body ---

TARGET_FILE = Path(w.__file__).with_name("test_postgres_parked_media_inspection.py")
# ast.dump (Python 3.12) of the target module at 29a8811, before any span existed.
ORIGINAL_TARGET_AST_SHA256 = "9fb6b94e01277aa0032a3fe6d5e47a03cf7cd1cbc3683aa5bafc74cc24e240ed"
EXPECTED_SPANS = ["body_clock", "body_draft", "body_binding", "body_protocol", "body_binding", "body_rows",
                  "body_history", "body_config", "body_node", "body_node_checks", "body_passive_check",
                  "body_passive_reads", "body_intent_controls", "body_fault_matrix", "body_refusal_order",
                  "body_delivery_file", "body_generation_file", "body_exception_cleanup", "body_standalone",
                  "body_restore_matrix", "body_passive_history"]
# The retained 29a8811 PG2 sequence (run 40067247758), fixed words only: +ENTER, -EXIT.
RETAINED_81 = ("+protocol +setup +fixture_native -fixture_native +fixture_cluster -fixture_cluster +fixture_database "
    "-fixture_database +fixture_clock -fixture_clock +compact_fixture +compact_retain -compact_retain +compact_enrollment "
    "-compact_enrollment +compact_protocol -compact_protocol +worker_enroll -worker_enroll -compact_fixture -setup +call "
    "+ready_prepare +ready_admit +ready_command +worker_consume -worker_consume -ready_command +worker_write -worker_write "
    "+worker_capture -worker_capture +ready_command +worker_consume -worker_consume -ready_command "
    "+worker_check_deterministic -worker_check_deterministic +worker_check_safety -worker_check_safety "
    "+worker_check_fact_check -worker_check_fact_check +worker_check_critic -worker_check_critic +worker_other "
    "-worker_other +ready_command +worker_consume -worker_consume -ready_command -ready_admit +ready_cost -ready_cost "
    "+ready_command +worker_consume -worker_consume -ready_command +ready_command +worker_consume -worker_consume "
    "-ready_command +ready_command +worker_consume -worker_consume -ready_command +worker_check_deterministic "
    "-worker_check_deterministic +worker_check_safety -worker_check_safety +worker_check_fact_check "
    "-worker_check_fact_check +worker_check_critic -worker_check_critic +ready_command +worker_consume -worker_consume "
    "-ready_command +ready_cost -ready_cost -ready_prepare +ready_body").split()


def render(events):
    return "".join(f"{w.PREFIX} {i:03d} {'ENTER' if e[0] == '+' else 'EXIT'} {e[1:]}\n" for i, e in enumerate(events, 1))


def strip_spans(tree):
    """Remove ONLY the body_phase import and exact body_phase(...) with-wrappers."""
    removed: dict[str, Any] = {"imports": 0, "spans": []}

    def is_span(statement):
        if not isinstance(statement, ast.With) or len(statement.items) != 1:
            return False
        item, call = statement.items[0], statement.items[0].context_expr
        return (item.optional_vars is None and isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "body_phase" and len(call.args) == 1 and not call.keywords
                and isinstance(call.args[0], ast.Constant) and call.args[0].value in w.BODY_PHASES)

    def flatten(body):
        out = []
        for statement in body:
            if (isinstance(statement, ast.ImportFrom) and statement.module == "tests.parked_media_phase_witness"
                    and [alias.name for alias in statement.names] == ["body_phase"]):
                removed["imports"] += 1
                continue
            if is_span(statement):
                removed["spans"].append(statement.items[0].context_expr.args[0].value)
                out.extend(flatten(statement.body))
                continue
            for field in ("body", "orelse", "finalbody"):
                if isinstance(getattr(statement, field, None), list):
                    setattr(statement, field, flatten(getattr(statement, field)))
            for handler in getattr(statement, "handlers", []):
                handler.body = flatten(handler.body)
            out.append(statement)
        return out

    tree.body = flatten(tree.body)
    return tree, removed


def restore_isolated_standalone_proof(tree):
    """Reverse exactly one reviewed relocation, preserving its full proof AST."""
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "standalone_delivery_proof"]
    assert len(helpers) == 1
    helper = helpers[0]
    signature = ast.parse('def standalone_delivery_proof(case, path, monkeypatch): pass').body[0]
    assert ast.dump(helper.args) == ast.dump(signature.args)
    assert helper.returns is None and not helper.decorator_list and helper.type_comment is None
    setup = ast.parse('authority, resolve = case["authority"], case["operators"].resolve').body[0]
    result = ast.parse('return dict(draft_id=case["draft_id"], intent_id=path["intent"], standalone_proof="verified")').body[0]
    assert ast.dump(helper.body[0]) == ast.dump(setup)
    assert ast.dump(helper.body[-1]) == ast.dump(result)
    tree.body.remove(helper)
    seam = ast.parse('result = temperature.ghcn_worker(case, "delivery_standalone_proof", path["intent"], '
        'case["inspection_at"].isoformat())\n'
        'assert result == dict(draft_id=case["draft_id"], intent_id=path["intent"], standalone_proof="verified")').body
    expected = [ast.dump(node) for node in seam]
    targets = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "test_compact_owned_get_real_proofs_fresh_operations_and_restored_faults"]
    assert len(targets) == 1
    replacements = 0
    for node in ast.walk(targets[0]):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            for index in range(len(body) - 1):
                if [ast.dump(item) for item in body[index:index + 2]] == expected:
                    body[index:index + 2] = helper.body[1:-1]
                    replacements += 1
    assert replacements == 1
    return tree


@pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason="the pinned AST digest is Python 3.12 ast.dump output")
def test_target_test_is_the_original_after_removing_only_the_diagnostic_spans():
    tree, removed = strip_spans(ast.parse(TARGET_FILE.read_text(encoding="utf-8")))
    assert removed == {"imports": 1, "spans": EXPECTED_SPANS}
    assert set(EXPECTED_SPANS) == set(w.BODY_PHASES)
    # The original four owner-corruption connections inherited autocommit=True,
    # so SET LOCAL expired before each write. Reverse ONLY the reviewed explicit
    # transaction setup when comparing with the unchanged historical AST digest.
    original = ast.parse('psycopg.connect(**case["params"])', mode="eval").body
    repaired = ast.parse('psycopg.connect(**dict(case["params"], autocommit=False))', mode="eval").body
    connections = [item for node in ast.walk(tree) if isinstance(node, ast.With)
                   for item in node.items if ast.dump(item.context_expr) == ast.dump(repaired)]
    assert len(connections) == 4
    for item in connections:
        item.context_expr = original
    tree = restore_isolated_standalone_proof(tree)
    assert hashlib.sha256(ast.dump(tree).encode()).hexdigest() == ORIGINAL_TARGET_AST_SHA256


@contextlib.contextmanager
def active(lines):
    witness = w.Witness(lines)
    w._current = witness
    try:
        yield witness
    finally:
        w._current = None


def test_body_phase_is_inert_unless_the_selected_witness_is_active():
    assert w.current() is None
    for name in (*w.BODY_PHASES, "setup", "not_a_phase", None, 7):
        assert w.body_phase(name) is w.NULL
    calls = []
    with w.body_phase("body_node"):
        calls.append(1)
    assert calls == [1]


def test_body_spans_record_in_order_inside_ready_body_and_run_each_operation_once():
    lines, calls = Lines(), []
    with active(lines) as witness:
        witness.enter("protocol")
        witness.enter("call")
        with w.WitnessedContext(witness, Manager(object())):
            for name in w.BODY_PHASES:
                with w.body_phase(name):
                    calls.append(name)
        witness.exit("call")
        witness.exit("protocol")
    assert calls == list(w.BODY_PHASES)
    events = lines.events()
    assert events[:5] == [("ENTER", "protocol"), ("ENTER", "call"), ("ENTER", "ready_prepare"), ("EXIT", "ready_prepare"),
                          ("ENTER", "ready_body")]
    assert events[5:5 + 2 * len(w.BODY_PHASES)] == [pair for name in w.BODY_PHASES for pair in (("ENTER", name), ("EXIT", name))]
    assert w.parse(lines.text())["status"] == "complete"


@ORIGINAL_ERRORS
def test_body_span_keeps_the_operations_own_exception_and_records_error(make_error):
    lines, error, calls = Lines(), make_error(), []
    with active(lines) as witness:
        witness.enter("protocol")
        with pytest.raises(BaseException) as raised:
            with w.body_phase("body_node"):
                calls.append(1)
                raise error
        assert raised.value is error and calls == [1]
        assert raised.value.__context__ is None
    assert lines.events() == [("ENTER", "protocol"), ("ENTER", "body_node"), ("ERROR", "body_node")]


@DIAGNOSTIC_FAILURES
@pytest.mark.parametrize("fail_at,raises", [(2, False), (3, False), (2, True), (3, True)],
                         ids=["enter-returns", "exit-returns", "enter-raises", "error-raises"])
def test_body_span_writer_failures_never_skip_repeat_or_replace_the_operation(failure, fail_at, raises):
    lines, error, calls = Lines(fail_at=fail_at, error=failure), OriginalStop(), []
    with active(lines) as witness:
        witness.enter("protocol")
        context = pytest.raises(OriginalStop) if raises else contextlib.nullcontext()
        with context as raised:
            with w.body_phase("body_draft"):
                calls.append(1)
                if raises:
                    raise error
        if raises:
            assert raised is not None and raised.value is error
        assert calls == [1] and witness.stopped
        with w.body_phase("body_binding"):
            calls.append(2)
        assert calls == [1, 2]
    assert ("EXIT", "body_draft") not in lines.events()[fail_at - 1:]


@pytest.mark.parametrize("name", ["setup", "ready_body", "body_unknown", None])
def test_a_wrong_body_phase_is_reported_invalid_never_silently_accepted(name):
    lines, calls = Lines(), []
    with active(lines) as witness:
        witness.enter("protocol")
        with w.body_phase(name):
            calls.append(1)
        assert witness.stopped
    assert calls == [1]
    assert lines.events() == [("ENTER", "protocol"), ("INVALID", "malformed")]
    assert w.parse(lines.text())["status"] == "invalid"


def test_the_retained_29a8811_sequence_keeps_its_original_incomplete_reading():
    assert len(RETAINED_81) == 81
    assert w.parse(render(RETAINED_81)) == dict(status="incomplete", reason=None, lines=81,
                                                open=["protocol", "call", "ready_body"], last_closed="ready_prepare",
                                                errors=[], notes=[])


def test_truncation_at_every_body_boundary_names_the_open_span():
    spans = [event for name in EXPECTED_SPANS for event in (f"+{name}", f"-{name}")]
    for index in range(0, len(spans), 2):
        name = spans[index][1:]
        cut = RETAINED_81 + spans[:index + 1]
        result = w.parse(render(cut))
        assert result["status"] == "incomplete"
        assert result["open"] == ["protocol", "call", "ready_body", name]
        for chop in (3, 12, 20):  # inside the word, inside the event, inside the sequence number
            assert w.parse(render(cut)[:-chop])["status"] == "truncated", (name, chop)
    # A complete line that is also a prefix of a longer phase is NOT truncation.
    complete = w.parse(render(RETAINED_81 + ["+body_node"]))
    assert complete["status"] == "incomplete" and complete["open"][-1] == "body_node"


def test_a_full_body_sequence_fits_the_fixed_budget_with_room_to_spare():
    lines = Lines()
    witness = w.Witness(lines)
    for event in RETAINED_81:
        (witness.enter if event[0] == "+" else witness.exit)(event[1:])
    for name in EXPECTED_SPANS:
        witness.enter(name)
        witness.exit(name)
    for name in ("ready_body",):
        witness.exit(name)
    for event in ("+ready_cleanup", "-ready_cleanup", "-call", "+teardown", "-teardown", "-protocol"):
        (witness.enter if event[0] == "+" else witness.exit)(event[1:])
    assert not witness.stopped and witness.lines_written == 81 + 2 * 21 + 7 == 130
    assert witness.lines_written <= w.MAX_LINES - 1 and witness.bytes_written <= w.MAX_BYTES
    assert max(map(len, lines.lines)) <= w.MAX_LINE_BYTES
    assert w.parse(lines.text())["status"] == "complete"
