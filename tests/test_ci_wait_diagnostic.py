"""Pure diagnostic tests: no PostgreSQL, native dumps, crash or source calls."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import types

import pytest

from scripts import ci_wait_diagnostic as diagnostic


def test_observation_is_still_300_seconds_and_never_a_test_deadline():
    assert diagnostic.SECONDS == 300


def test_frame_names_are_bounded_and_do_not_read_values_or_paths():
    frame = types.SimpleNamespace(f_code=types.SimpleNamespace(co_name="private/path\nsecret=value"))
    frame.f_back = frame
    records = diagnostic.frame_names({index: frame for index in range(20)})
    assert len(records) == 16 * 32
    assert records[0] == "FRAME 0 0 unknown" and records[-1] == "FRAME 15 31 unknown"
    assert all("private" not in row and "secret" not in row for row in records)


def test_timer_emits_one_bounded_identity_record_and_closes_only_owned_descriptor(tmp_path, monkeypatch):
    output = tmp_path / "diagnostic"
    with output.open("w+b") as stream:
        frame = types.SimpleNamespace(f_code=types.SimpleNamespace(co_name="a" * 120))
        frame.f_back = frame
        monkeypatch.setattr(diagnostic.sys, "_current_frames", lambda: {i: frame for i in range(20)})
        witness = diagnostic.WaitDiagnostic(stream.fileno(), "a" * 64, seconds=0)
        witness.phase = "call"
        witness.start()
        witness.thread.join(timeout=1)
        assert witness.stop() is True
        os.fstat(stream.fileno())  # The caller's descriptor remains open.
        with pytest.raises(OSError):
            os.fstat(witness.descriptor)
        stream.seek(0)
        data = stream.read()
    assert len(data) < 4096 and len(data.splitlines()) == 1
    body = json.loads(data.decode().removeprefix(diagnostic.PREFIX))
    assert body["phase"] == "call" and body["test_sha256"] == "a" * 64
    assert body["status"] == "diagnostic" and body["after_seconds"] == 0
    assert 0 < len(body["records"]) < 512


def test_canceled_timer_emits_nothing_and_closes_descriptor(tmp_path):
    with (tmp_path / "canceled").open("w+b") as stream:
        witness = diagnostic.WaitDiagnostic(stream.fileno(), "b" * 64)
        witness.stopped.set()
        witness.start()
        assert witness.stop() is True
        with pytest.raises(OSError):
            os.fstat(witness.descriptor)
        stream.seek(0)
        assert stream.read() == b""


def test_cancellation_during_snapshot_cannot_emit_a_late_record(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def snapshot():
        entered.set()
        assert release.wait(2)
        return {}

    monkeypatch.setattr(diagnostic.sys, "_current_frames", snapshot)
    with (tmp_path / "late").open("w+b") as stream:
        witness = diagnostic.WaitDiagnostic(stream.fileno(), "c" * 64, seconds=0)
        witness.start()
        assert entered.wait(1)
        witness.stopped.set()
        release.set()
        assert witness.stop() is True
        stream.seek(0)
        assert stream.read() == b""


def test_output_failure_is_recorded_without_raising_from_cleanup(tmp_path, monkeypatch):
    def broken_write(*args):
        raise OSError("invented private error")

    with (tmp_path / "broken").open("w+b") as stream:
        monkeypatch.setattr(diagnostic.os, "write", broken_write)
        witness = diagnostic.WaitDiagnostic(stream.fileno(), "d" * 64, seconds=0)
        witness.start()
        witness.thread.join(timeout=1)
        assert witness.stop() is False
        assert witness.error is True
        with pytest.raises(OSError):
            os.fstat(witness.descriptor)


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    stream = (tmp_path / "plugin-output").open("w+b")
    monkeypatch.setattr(diagnostic.sys, "stderr", stream)
    config = types.SimpleNamespace(getini=lambda name: 0)
    plugin = diagnostic.SafeWaitPlugin(config)
    witnesses = []

    class Witness:
        def __init__(self, descriptor, test_hash, *, seconds):
            self.test_hash, self.seconds, self.phase = test_hash, seconds, "setup"
            self.stops, self.ok = 0, True
            witnesses.append(self)

        def start(self):
            pass

        def stop(self):
            self.stops += 1
            return self.ok

    monkeypatch.setattr(diagnostic, "WaitDiagnostic", Witness)
    yield plugin, witnesses
    plugin.pytest_unconfigure()
    stream.close()


def test_protocol_forwards_the_exact_result_and_tracks_the_phase_and_item(plugin):
    plugin, witnesses = plugin
    nodeid = "invented/private.py::test_item[private]"
    iterator = plugin.pytest_runtest_protocol(types.SimpleNamespace(nodeid=nodeid))
    next(iterator)
    witness = witnesses[0]
    assert witness.test_hash == hashlib.sha256(nodeid.encode()).hexdigest()
    assert witness.seconds == 300
    plugin.pytest_runtest_setup()
    assert witness.phase == "setup"
    plugin.pytest_runtest_call()
    assert witness.phase == "call"
    plugin.pytest_runtest_teardown()
    assert witness.phase == "teardown"
    result = object()
    with pytest.raises(StopIteration) as stopped:
        iterator.send(result)
    assert stopped.value.value is result and witness.stops == 1 and plugin.active is None
    next_item = plugin.pytest_runtest_protocol(types.SimpleNamespace(nodeid="different"))
    next(next_item)
    assert witnesses[1].test_hash != witness.test_hash and witnesses[1].phase == "setup"
    next_item.close()
    assert witnesses[0].stops == witnesses[1].stops == 1


@pytest.mark.parametrize("exception", [AssertionError("original"), KeyboardInterrupt(), SystemExit(17)])
def test_diagnostic_failure_never_replaces_item_exception_or_interrupt(plugin, exception):
    plugin, witnesses = plugin
    iterator = plugin.pytest_runtest_protocol(types.SimpleNamespace(nodeid="invented"))
    next(iterator)
    witnesses[0].ok = False
    with pytest.raises(type(exception)) as raised:
        iterator.throw(exception)
    assert raised.value is exception and witnesses[0].stops == 1 and plugin.active is None
    assert plugin.errors == 1


@pytest.mark.parametrize("original,expected", [(0, 1), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5)])
def test_observation_failure_fails_a_green_session_but_preserves_all_failure_codes(plugin, original, expected):
    plugin, _ = plugin
    plugin.errors = 1
    session = types.SimpleNamespace(exitstatus=original)
    plugin.pytest_sessionfinish(session)
    assert session.exitstatus == expected
    messages: list[str] = []
    plugin.pytest_terminal_summary(types.SimpleNamespace(write_line=messages.append))
    assert messages == ["THEHEAT-CI-WAIT/1 diagnostic_unavailable"]


def test_replacement_refuses_a_still_armed_native_timeout():
    with pytest.raises(ValueError, match="unsafe_native_timer_still_enabled"):
        diagnostic.SafeWaitPlugin(types.SimpleNamespace(getini=lambda name: 300))
