"""Offline observer tests; the subprocess deliberately contains one failing test."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import threading
from types import SimpleNamespace

import pytest

from tests import ci_traceback as diagnostic
from tests import conftest as hooks


@pytest.fixture
def observer(tmp_path):
    now = [10.0]
    path = tmp_path / "trace.jsonl"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    watchdog = diagnostic.Watchdog(fd, 120, clock=lambda: now[0], frames=lambda: {})
    yield watchdog, now, path
    watchdog.close()


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_original_deadline_once_only_and_successor_identity(observer):
    watchdog, now, path = observer
    first = watchdog.begin("test_original")
    assert watchdog.active["deadline"] == 130
    now[0] = 129.9
    assert not watchdog.sample_due()
    assert watchdog.active["deadline"] == 130
    now[0] = 130
    assert watchdog.sample_due()
    assert not watchdog.sample_due()
    watchdog.end(first)
    second = watchdog.begin("test_successor")
    watchdog.end(first)
    assert watchdog.active["token"] == second
    assert watchdog.active["deadline"] == 250
    watchdog.end(second)
    now[0] = 500
    assert not watchdog.sample_due()
    assert [row["nodeid"] for row in events(path)] == ["test_original"]


def test_overlapping_protocol_refused_and_long_id_bounded(observer):
    watchdog, _, _ = observer
    token = watchdog.begin("🌪" * 1000)
    assert watchdog.active["nodeid_truncated"]
    assert len(watchdog.active["nodeid"].encode()) <= 1026
    assert len(watchdog.active["nodeid_sha256"]) == 64
    with pytest.raises(RuntimeError, match="Overlapping"):
        watchdog.begin("replacement")
    watchdog.end(token)
    with pytest.raises(TypeError):
        watchdog.begin(object())


def test_invalid_intervals_and_conflicting_native_configuration():
    assert diagnostic.checked_seconds(0) == 0
    for value in (-1, math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            diagnostic.checked_seconds(value)
    for native, plugin, match in ((120, True, "combine"), (0, False, "fatal")):
        config = SimpleNamespace(
            getoption=lambda name: 120,
            getini=lambda name: native,
            pluginmanager=SimpleNamespace(hasplugin=lambda name: plugin),
        )
        with pytest.raises(pytest.UsageError, match=match):
            hooks.pytest_configure(config)


def test_absent_flag_creates_no_thread_or_descriptor(monkeypatch):
    def forbidden(*args):
        raise AssertionError("inactive diagnostics acquired a descriptor")
    monkeypatch.setattr(diagnostic.Watchdog, "duplicate_stderr", forbidden)
    config = SimpleNamespace(getoption=lambda name: 0)
    hooks.pytest_sessionstart(SimpleNamespace(config=config))
    assert not hasattr(config, "_theheat_ci_traceback")
    hooks.pytest_sessionfinish(SimpleNamespace(config=config))
    hooks.pytest_unconfigure(config)


def test_full_protocol_wrapper_preserves_result_and_exception(observer):
    watchdog, _, _ = observer
    item = SimpleNamespace(config=SimpleNamespace(_theheat_ci_traceback=watchdog), nodeid="test_call")
    wrapper = hooks.pytest_runtest_protocol(item)
    assert next(wrapper) is None
    assert watchdog.active["nodeid"] == item.nodeid
    with pytest.raises(StopIteration) as result:
        wrapper.send("original result")
    assert result.value.value == "original result"
    assert watchdog.active is None
    original = RuntimeError("deliberate original failure")
    wrapper = hooks.pytest_runtest_protocol(item)
    next(wrapper)
    with pytest.raises(RuntimeError) as raised:
        wrapper.throw(original)
    assert raised.value is original
    assert watchdog.active is None


def test_bounded_frame_tail_retains_outer_caller_and_never_reads_objects():
    observed = []
    def repeated_copy_like(depth):
        if depth:
            return repeated_copy_like(depth-1)
        observed.append(diagnostic.locations(sys._getframe()))
    def outer_application_caller():
        repeated_copy_like(150)
    thread = threading.Thread(target=outer_application_caller)
    thread.start()
    thread.join()
    row = observed[0]
    assert row["scanned"] > 150
    assert len(row["frames"]) == diagnostic.HEAD_FRAMES + diagnostic.TAIL_FRAMES
    assert any(frame["function"] == "outer_application_caller" for frame in row["frames"])
    assert row["partial"] and row["omitted"] > 100 and not row["truncated"]
    class Hostile:
        def __getattribute__(self, name):
            raise AssertionError("read an untrusted object")
    assert diagnostic.locations(Hostile())["frames"] == []


def test_scan_thread_and_escaped_unicode_event_bounds(observer, monkeypatch):
    watchdog, now, path = observer
    namespace = {"sys": sys}
    # Real frame/code objects with adversarial-sized metadata, never mocked frames.
    name = "𐀀" * 100
    source = f"def {name}():\n    return sys._getframe()\nframe = {name}()\n"
    exec(compile(source, "/" + "𐀀" * 1000 + "/outer.py", "exec"), namespace)
    frame = namespace["frame"]
    frames = {i: frame for i in range(diagnostic.MAX_THREADS + 10)}
    watchdog.main_ident = 9
    watchdog.frames = lambda: frames
    monkeypatch.setattr(diagnostic, "MAX_SCAN_FRAMES", 1)
    watchdog.begin("🌪" * 1000)
    now[0] = 130
    assert watchdog.sample_due()
    raw = path.read_bytes()
    row = events(path)[0]
    assert len(raw) < diagnostic.MAX_EVENT_BYTES
    assert row["threads"][0]["main"]
    assert row["omitted_threads"] == 10 and row["partial"]
    assert all(item["truncated"] and item["fields_truncated"] for item in row["threads"])
    assert all(set(location) == {"file", "function", "line"}
               for item in row["threads"] for location in item["frames"])
    # Worst-sized legal snapshot, including JSON's 12-byte non-BMP escaping.
    large = dict(row)
    location = dict(file="𐀀" * diagnostic.FILE_CHARS,
                    function="𐀀" * diagnostic.FUNCTION_CHARS, line=10**9)
    large["threads"] = [dict(item, frames=[location] * (diagnostic.HEAD_FRAMES + diagnostic.TAIL_FRAMES))
                        for item in row["threads"]]
    assert len(json.dumps(large, ensure_ascii=True).encode()) + 1 < diagnostic.MAX_EVENT_BYTES


def test_sample_callback_and_output_failures_are_diagnostic_only(observer, monkeypatch):
    watchdog, now, path = observer
    def broken_frames():
        raise RuntimeError("secret must not be emitted")
    watchdog.frames = broken_frames
    first = watchdog.begin("test_callback")
    now[0] = 130
    assert watchdog.sample_due()
    assert not watchdog.sample_due()
    assert watchdog.errors == 1
    watchdog.end(first)
    watchdog.frames = lambda: {}
    watchdog.begin("test_write")
    now[0] = 250
    with monkeypatch.context() as patch:
        patch.setattr(diagnostic.os, "write", lambda fd, data: 0)
        assert watchdog.sample_due()
    assert watchdog.errors == 2
    watchdog.close()
    assert "secret" not in path.read_text()
    assert events(path)[-1]["errors"] == 2
    assert events(path)[-1]["partial"]


def test_sample_and_total_output_caps_leave_a_closed_receipt(observer, monkeypatch):
    watchdog, now, path = observer
    monkeypatch.setattr(diagnostic, "MAX_SAMPLES", 1)
    first = watchdog.begin("test_first")
    now[0] = 130
    assert watchdog.sample_due()
    watchdog.end(first)
    watchdog.begin("test_second")
    now[0] = 250
    assert not watchdog.sample_due()
    assert watchdog.dropped == 1
    watchdog.bytes = diagnostic.MAX_TOTAL_BYTES - 1024
    with watchdog.condition:
        watchdog._emit("would_exceed_total")
    assert watchdog.dropped == 2
    watchdog.close()
    assert events(path)[-1]["event"] == "closed"
    assert events(path)[-1]["dropped"] == 2


def test_close_waits_for_sample_then_joins_before_fd_close(tmp_path):
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()
    path = tmp_path / "thread.jsonl"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    def frames():
        entered.set()
        assert release.wait(1)
        return {}
    watchdog = diagnostic.Watchdog(fd, .01, frames=frames)
    watchdog.start()
    watchdog.begin("test_active")
    assert entered.wait(1)
    def close():
        watchdog.close()
        ended.set()
    closer = threading.Thread(target=close)
    closer.start()
    assert not ended.wait(.01)
    os.fstat(fd)
    release.set()
    closer.join(1)
    assert ended.is_set() and not watchdog.thread.is_alive()
    with pytest.raises(OSError):
        os.fstat(fd)
    watchdog.close()
    assert [row["event"] for row in events(path)] == ["started", "protocol_sample", "closed"]
    assert not events(path)[0]["fd_inheritable"]


def test_owned_pytest_real_timer_preserves_failure_and_fatal_handler(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "conftest.py").write_bytes((root / "tests/conftest.py").read_bytes())
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "diagnostic_guard.py").write_text(textwrap.dedent('''
        import faulthandler, json, os, threading
        from pathlib import Path
        import pytest
        calls = []
        def forbidden(*args, **kwargs):
            calls.append("native timer")
            raise AssertionError("native timed dumper called")
        faulthandler.dump_traceback_later = forbidden
        @pytest.hookimpl(wrapper=True, tryfirst=True)
        def pytest_sessionfinish(session):
            result = yield
            watchdog = session.config._theheat_ci_traceback
            try:
                os.fstat(watchdog.fd)
                closed = False
            except OSError:
                closed = True
            Path("guard.json").write_text(json.dumps(dict(
                native_calls=calls, fatal_enabled=faulthandler.is_enabled(), fd_closed=closed,
                watchdog_alive=watchdog.thread.is_alive(), samples=watchdog.samples,
                remaining_threads=sum(t.name == "theheat-ci-traceback" for t in threading.enumerate()))))
            return result
    '''))
    (tmp_path / "test_protocol.py").write_text(textwrap.dedent('''
        import faulthandler, json, os, subprocess, sys, time
        from pathlib import Path
        import pytest
        @pytest.fixture
        def phases(request):
            watchdog = request.config._theheat_ci_traceback
            assert faulthandler.is_enabled()
            assert not os.get_inheritable(watchdog.fd)
            child = subprocess.run([sys.executable, "-c", "import os,sys;\\ntry: os.fstat(int(sys.argv[1])); sys.exit(1)\\nexcept OSError: sys.exit(0)", str(watchdog.fd)], close_fds=False)
            assert child.returncode == 0
            time.sleep(.06)
            Path("setup.json").write_text(json.dumps(dict(finished=time.monotonic())))
            yield
            time.sleep(.06)
        def test_slow(phases):
            time.sleep(.06)
        def test_genuine_failure():
            assert faulthandler.is_enabled()
            assert False, "intentional assertion remains failing"
        def test_successor():
            time.sleep(.06)
    '''))
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(tmp_path), str(root))),
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    environment.pop("THEHEAT_TIME_TRAVEL_DAYS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-c", str(tmp_path / "pytest.ini"),
         "-p", "diagnostic_guard", "--ci-traceback-seconds=.025", "test_protocol.py"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed, 2 passed" in result.stdout
    guard = json.loads((tmp_path / "guard.json").read_text())
    assert guard == dict(native_calls=[], fatal_enabled=True, fd_closed=True,
                         watchdog_alive=False, samples=2, remaining_threads=0)
    rows = [json.loads(line) for line in result.stderr.splitlines() if line.startswith('{"diagnostic":')]
    assert [row["event"] for row in rows] == ["started", "protocol_sample", "protocol_sample", "closed"]
    samples = [row for row in rows if row["event"] == "protocol_sample"]
    assert [row["nodeid"] for row in samples] == ["test_protocol.py::test_slow", "test_protocol.py::test_successor"]
    for row in samples:
        assert row["deadline"] == row["started"] + .025
        assert row["sampled_at"] >= row["deadline"]
    assert samples[0]["sampled_at"] < json.loads((tmp_path / "setup.json").read_text())["finished"]
    assert rows[-1]["protocols"] == 3 and not rows[-1]["partial"]
