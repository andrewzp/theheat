"""GIL-held CI diagnostics replacing the unsafe PG2 and PG8 native timer.

The 300-second observation never terminates, retries or approves a test. Fatal
signal handling and the external job deadline remain separate and unchanged.
Only bounded function names, a test-id hash and its pytest phase reach stderr;
never filenames, arguments, locals, addresses or environment. A GIL-held stall
may prevent this Python observer from running; the external deadline still fails.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from collections.abc import Generator
from typing import Any

import pytest

SECONDS = 300.0
PREFIX = "THEHEAT-CI-WAIT/1 "


def frame_names(frames: dict[int, Any]) -> list[str]:
    """Strong frame references are obtained under the GIL, not a signal handler."""
    records = []
    for index, (_, frame) in enumerate(sorted(frames.items())[:16]):
        for depth in range(32):
            if frame is None:
                break
            name = frame.f_code.co_name
            if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_:<>.~$?+\-]{1,120}", name) is None:
                name = "unknown"
            records.append(f"FRAME {index} {depth} {name}")
            frame = frame.f_back
    return records


class WaitDiagnostic:
    """One owned thread/descriptor, canceled on every test outcome."""

    def __init__(self, descriptor: int, test_hash: str, *, seconds: float = SECONDS):
        self.descriptor = os.dup(descriptor)
        self.test_hash = test_hash
        self.phase = "setup"
        self.seconds = seconds
        self.stopped = threading.Event()
        self.error = False
        self.thread = threading.Thread(target=self._observe, daemon=True, name="theheat-ci-wait")

    def start(self) -> None:
        try:
            self.thread.start()
        except BaseException:
            os.close(self.descriptor)
            raise

    def _observe(self) -> None:
        try:
            if self.stopped.wait(self.seconds):
                return
            body: dict[str, Any] = {"status": "diagnostic", "after_seconds": self.seconds,
                    "test_sha256": self.test_hash, "phase": self.phase,
                    "records": frame_names(sys._current_frames())}
            # Keep the one record bounded, including JSON punctuation. A frame
            # limit alone would still permit more than 64 KiB of log output.
            while len(json.dumps(body)) > 3500:
                body["records"].pop()
            data = (PREFIX + json.dumps(body, sort_keys=True) + "\n").encode("ascii")
            if self.stopped.is_set():
                return
            while data:
                written = os.write(self.descriptor, data)
                if written <= 0:
                    raise OSError("diagnostic_output_unavailable")
                data = data[written:]
        except (OSError, RuntimeError):
            self.error = True
        finally:
            os.close(self.descriptor)

    def stop(self) -> bool:
        self.stopped.set()
        self.thread.join(timeout=1)
        return not self.error and not self.thread.is_alive()


class SafeWaitPlugin:
    def __init__(self, config: Any):
        if float(config.getini("faulthandler_timeout")) != 0:
            raise ValueError("unsafe_native_timer_still_enabled")
        # Same configure-time descriptor ownership as pytest's fatal handler.
        try:
            source = sys.stderr.fileno()
            if source < 0:
                raise ValueError("stderr_unavailable")
        except (AttributeError, ValueError):
            assert sys.__stderr__ is not None
            source = sys.__stderr__.fileno()
        self.descriptor = os.dup(source)
        self.active: WaitDiagnostic | None = None
        self.errors = 0

    @pytest.hookimpl(wrapper=True, trylast=True)
    def pytest_runtest_protocol(self, item: Any) -> Generator[None, object, object]:
        witness = WaitDiagnostic(self.descriptor, hashlib.sha256(item.nodeid.encode()).hexdigest(), seconds=SECONDS)
        witness.start()
        self.active = witness
        try:
            return (yield)
        finally:
            # No catch around the test: assertion, interrupt and exit propagate.
            try:
                if not witness.stop():
                    self.errors += 1
            finally:
                self.active = None

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self) -> None:
        if self.active:
            self.active.phase = "setup"

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self) -> None:
        if self.active:
            self.active.phase = "call"

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_teardown(self) -> None:
        if self.active:
            self.active.phase = "teardown"

    def pytest_unconfigure(self) -> None:
        if self.active:
            self.active.stop()
            self.active = None
        os.close(self.descriptor)

    def pytest_sessionfinish(self, session: Any) -> None:
        # Observation failure must be visible, but must never replace an item's
        # assertion/interrupt/exit with a cleanup exception or turn red green.
        if self.errors and session.exitstatus == 0:
            session.exitstatus = 1

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if self.errors:
            terminalreporter.write_line("THEHEAT-CI-WAIT/1 diagnostic_unavailable")
