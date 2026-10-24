"""Process-death phase witness for one held PG2 node (test-only).

The P31 PG2 job died with SIGSEGV/exit 139 after printing only the name of
``TARGET_NODEID``. No retained evidence shows whether that node was still in
fixture setup, in the ``ready_delivery`` preparation, in its yielded body or in
cleanup. This module adds the smallest witness that can survive the process
dying, for that single node only:

* Lines are written immediately, with an unbuffered ``os.write``, to a
  duplicate of the process's real stderr descriptor taken while pytest capture
  is suspended. Pytest's per-phase fd capture would otherwise hold them in a
  temporary file that a crashed process never prints. There is no userspace
  buffer to flush.
* The line format is fixed ASCII: ``PREFIX SEQ EVENT WORD``. ``SEQ`` runs from
  001 to ``MAX_LINES``. ``EVENT`` is ENTER/EXIT/ERROR with a ``PHASES`` word, or
  UNAVAILABLE/INVALID with a reason word. Nothing else is ever written: no
  timestamps, stacks, locals, arguments, results, exception text or types,
  paths, URLs, keys or source text.
* Each witnessed call or context is forwarded exactly once with the original
  arguments. The original result, context value, suppression flag and exception
  object are returned or raised unchanged. A failed action gets ERROR, never
  EXIT.
* The witness isolates its own failures. Anything raised inside it, of any
  BaseException type, only disables the witness: the writer, bookkeeping,
  selection, installation and restoration are all covered. The observed call,
  its own exception and its cleanup are never replaced, skipped or retried, and
  no completion is fabricated. An interrupt that arrives while the witness
  itself is writing is absorbed by this boundary and recorded as a writer
  failure.
* Reentrant emission, malformed nesting, a cleanup conflict and overflow end
  the witness with one explicit terminal line. Events from other threads and
  missing targets are not witnessed and are noted once each.
* Fixture boundaries come from a plugin registered only for the selected
  protocol: a ``tests/conftest.py`` hook is never consulted for session-scoped
  fixtures such as ``native_dependencies``.

The witness uses no clock, profiler, subprocess, socket, database or native
call, and it never imports a target module. ``parse`` reads the lines back from
a retained log.
"""

from __future__ import annotations

import functools
import os
import re
import sys
import threading
from collections.abc import Callable, Generator, Mapping
from types import TracebackType
from typing import Any, Literal

import pytest

TARGET_NODEID = (
    "tests/test_postgres_parked_media_inspection.py::"
    "test_compact_owned_get_real_proofs_fresh_operations_and_restored_faults[compact_case0]"
)
PREFIX = "THEHEAT-PG2-WITNESS/1"
EVENTS = ("ENTER", "EXIT", "ERROR")
PHASES = (
    # pytest item protocol and its three phases
    "protocol", "setup", "call", "teardown",
    # fixture setup boundaries of the reused compact case
    "fixture_cluster", "fixture_database", "fixture_clock", "fixture_native", "compact_fixture",
    # inside compact_case: source retention, enrollment command, revision protocol
    "compact_retain", "compact_enrollment", "compact_protocol",
    # ready_delivery: preparation, its helpers, the yielded body and context cleanup
    "ready_prepare", "ready_admit", "ready_command", "ready_cost", "ready_body", "ready_cleanup",
    # invented GHCN worker operations: enrollment, command consumption and check stages
    "worker_enroll", "worker_consume", "worker_write", "worker_capture",
    "worker_check_deterministic", "worker_check_safety", "worker_check_fact_check",
    "worker_check_critic", "worker_other",
)
# A terminal reason is the last line the witness writes.
TERMINAL_REASONS = ("overflow", "reentrant", "malformed", "restore_conflict")
# A note is written at most once per reason; witnessing continues.
NOTE_REASONS = ("foreign_thread", "missing_target")
MAX_LINES = 256
MAX_DEPTH = 32
MAX_LINE_BYTES = 64
MAX_BYTES = MAX_LINES * MAX_LINE_BYTES

PYTEST_PHASES = {"setup": "setup", "call": "call", "teardown": "teardown"}
FIXTURE_PHASES = {
    "cluster": "fixture_cluster",
    "database": "fixture_database",
    "positive_workflow_clock": "fixture_clock",
    "native_dependencies": "fixture_native",
    "compact_case": "compact_fixture",
}
WORKER_PHASES = {
    "enroll": "worker_enroll",
    "consume": "worker_consume",
    "write": "worker_write",
    "capture": "worker_capture",
    "deterministic": "worker_check_deterministic",
    "safety": "worker_check_safety",
    "fact_check": "worker_check_fact_check",
    "critic": "worker_check_critic",
}
# (module, attribute, kind, phase); every module is looked up, never imported.
TARGETS = (
    ("tests.test_postgres_ghcn_source_results", "retained", "call", "compact_retain"),
    ("tests.test_postgres_ghcn_source_results", "enroll", "call", "compact_enrollment"),
    ("tests.test_postgres_temperature_editor_media", "install_revision_protocol", "call",
     "compact_protocol"),
    ("tests.test_postgres_temperature_editor_media", "ghcn_worker", "worker", "worker_other"),
    ("tests.test_postgres_temperature_editor_media", "admit_compact", "call", "ready_admit"),
    ("tests.test_postgres_temperature_editor_media", "submit_command", "call", "ready_command"),
    ("tests.test_postgres_temperature_delivery", "passive_cost", "call", "ready_cost"),
    ("tests.test_postgres_temperature_delivery", "ready_delivery", "context", "ready_prepare"),
)

_WORD = re.compile(r"[a-z][a-z_]{0,31}")
LINE = re.compile(
    re.escape(PREFIX) + r" (\d{3}) (ENTER|EXIT|ERROR|UNAVAILABLE|INVALID) ([a-z][a-z_]{0,31})"
)
assert len(set(PHASES + TERMINAL_REASONS + NOTE_REASONS)) == len(PHASES + TERMINAL_REASONS + NOTE_REASONS)
assert all(_WORD.fullmatch(word) for word in PHASES + TERMINAL_REASONS + NOTE_REASONS)
assert max(len(f"{PREFIX} {MAX_LINES:03d} {kind} {word}\n")
           for kind, words in (("ERROR", PHASES), ("UNAVAILABLE", TERMINAL_REASONS + NOTE_REASONS))
           for word in words) <= MAX_LINE_BYTES


class Witness:
    """Bounded, nesting-checked writer of fixed protocol lines.

    ``writer`` receives each complete line as ASCII bytes. Only the thread that
    created the witness records events.
    """

    def __init__(self, writer: Callable[[bytes], object]) -> None:
        self._writer = writer
        self._owner = threading.get_ident()
        self._stack: list[str] = []
        self._writing = False
        self._reentered = False
        self._pending_notes: list[str] = []
        self._noted: set[str] = set()
        self.stopped = False
        self.writer_failed = False
        self.failed = False
        self.lines_written = 0
        self.bytes_written = 0

    def enter(self, phase: str) -> None:
        self._contain(lambda: self._event("ENTER", phase))

    def exit(self, phase: str) -> None:
        self._contain(lambda: self._event("EXIT", phase))

    def error(self, phase: str) -> None:
        self._contain(lambda: self._event("ERROR", phase))

    def note(self, reason: str) -> None:
        """Queue a once-only non-terminal note; written with the next owner event."""
        self._contain(lambda: self._note(reason))

    def invalid(self, reason: str) -> None:
        """End the witness explicitly (owner thread only)."""
        self._contain(lambda: self._invalid(reason))

    def _contain(self, action: Callable[[], None]) -> None:
        """The isolation boundary: the witness's own failure only disables the witness."""
        try:
            action()
        except BaseException:
            self.stopped = True
            self.failed = True

    def _note(self, reason: str) -> None:
        if reason in NOTE_REASONS and reason not in self._noted and reason not in self._pending_notes:
            self._pending_notes.append(reason)
        if threading.get_ident() == self._owner and not self._writing:
            self._event(None, None)

    def _invalid(self, reason: str) -> None:
        if threading.get_ident() != self._owner:
            self._note("foreign_thread")
        elif self._writing:
            self._reentered = True
        else:
            self._guarded(lambda: self._terminal("INVALID", reason if reason in TERMINAL_REASONS else "malformed"))

    def _event(self, event: str | None, phase: str | None) -> None:
        if threading.get_ident() != self._owner:
            self._note("foreign_thread")
            return
        if self._writing:
            self._reentered = True
            return
        self._guarded(lambda: self._record(event, phase))
        if self._reentered and not self.stopped:
            self._guarded(lambda: self._terminal("INVALID", "reentrant"))

    def _guarded(self, action: Callable[[], None]) -> None:
        self._writing = True
        try:
            action()
        except BaseException:
            # Bookkeeping must never replace the witnessed outcome.
            self.stopped = True
            self.failed = True
        finally:
            self._writing = False

    def _record(self, event: str | None, phase: str | None) -> None:
        if self.stopped:
            return
        if self._reentered:
            self._terminal("INVALID", "reentrant")
            return
        while self._pending_notes and not self.stopped:
            reason = self._pending_notes.pop(0)
            if reason not in self._noted:
                self._noted.add(reason)
                self._write("UNAVAILABLE", reason)
        if event is None or self.stopped:
            return
        if event not in EVENTS or phase not in PHASES:
            self._terminal("INVALID", "malformed")
            return
        if event == "ENTER":
            if len(self._stack) >= MAX_DEPTH:
                self._terminal("UNAVAILABLE", "overflow")
                return
            self._stack.append(phase)
        elif not self._stack or self._stack[-1] != phase:
            self._terminal("INVALID", "malformed")
            return
        else:
            self._stack.pop()
        self._write(event, phase)

    def _terminal(self, kind: str, reason: str) -> None:
        self._write(kind, reason, terminal=True)
        self.stopped = True

    def _write(self, kind: str, word: str, *, terminal: bool = False) -> None:
        if self.stopped:
            return
        # One line is always reserved for a terminal status.
        if not terminal and self.lines_written >= MAX_LINES - 1:
            self._terminal("UNAVAILABLE", "overflow")
            return
        line = f"{PREFIX} {self.lines_written + 1:03d} {kind} {word}\n".encode("ascii")
        if len(line) > MAX_LINE_BYTES or self.bytes_written + len(line) > MAX_BYTES:
            self.stopped = True
            return
        try:
            self._writer(line)
        except BaseException:
            self.writer_failed = True
            self.stopped = True
            return
        self.lines_written += 1
        self.bytes_written += len(line)


def forward(witness: Witness, phase: str, function: Callable[..., Any],
            args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Call ``function`` exactly once; ENTER, then EXIT on return or ERROR on raise."""
    witness.enter(phase)
    try:
        result = function(*args, **kwargs)
    except BaseException:
        witness.error(phase)
        raise
    witness.exit(phase)
    return result


class Phase:
    """Context manager for one witnessed phase; never suppresses an exception."""

    __slots__ = ("_witness", "_phase")

    def __init__(self, witness: Witness, phase: str) -> None:
        self._witness = witness
        self._phase = phase

    def __enter__(self) -> None:
        self._witness.enter(self._phase)

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        if exc_type is None:
            self._witness.exit(self._phase)
        else:
            self._witness.error(self._phase)
        return False


class _Null:
    """Shared inert context for every unselected item, phase and fixture."""

    __slots__ = ()

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        return False


NULL = _Null()


class WitnessedContext:
    """Forward one context manager's ``__enter__``/``__exit__`` exactly once.

    ``__enter__`` is ready_prepare, the with-block is ready_body and
    ``__exit__`` is ready_cleanup. The with-target and the suppression result are
    the original objects.
    """

    __slots__ = ("_witness", "_context")

    def __init__(self, witness: Witness, context: Any) -> None:
        self._witness = witness
        self._context = context

    def __enter__(self) -> Any:
        manager = self._context
        value = forward(self._witness, "ready_prepare", type(manager).__enter__, (manager,), {})
        self._witness.enter("ready_body")
        return value

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Any:
        if exc_type is None:
            self._witness.exit("ready_body")
        else:
            self._witness.error("ready_body")
        manager = self._context
        return forward(self._witness, "ready_cleanup", type(manager).__exit__,
                       (manager, exc_type, exc, tb), {})


def wrap_call(witness: Witness, phase: str, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def witnessed(*args: Any, **kwargs: Any) -> Any:
        return forward(witness, phase, original, args, kwargs)
    return witnessed


def worker_phase(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> str:
    """Map the worker operation to a closed phase; the value itself is never written."""
    try:
        operation = args[1] if len(args) > 1 else kwargs.get("operation")
        if type(operation) is str and operation in WORKER_PHASES:
            return WORKER_PHASES[operation]
    except BaseException:
        pass
    return "worker_other"


def wrap_worker(witness: Witness, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def witnessed(*args: Any, **kwargs: Any) -> Any:
        return forward(witness, worker_phase(args, kwargs), original, args, kwargs)
    return witnessed


def wrap_context(witness: Witness, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def witnessed(*args: Any, **kwargs: Any) -> WitnessedContext:
        return WitnessedContext(witness, original(*args, **kwargs))
    return witnessed


def _restore(installed: list[tuple[Any, str, Any, Any]]) -> bool:
    """Restore every installed attribute in reverse; True if any could not be restored."""
    conflict = False
    for module, attribute, original, wrapper in reversed(installed):
        try:
            if vars(module).get(attribute) is wrapper:
                setattr(module, attribute, original)
            else:
                conflict = True
        except BaseException:
            conflict = True
    installed.clear()
    return conflict


def interpose(witness: Witness, modules: Mapping[str, Any]) -> Callable[[], None]:
    """Replace each loaded target attribute; return an undo restoring originals in reverse.

    Installation never raises. A failure part-way restores what was installed,
    ends the witness explicitly and leaves the observed protocol untouched.
    """
    installed: list[tuple[Any, str, Any, Any]] = []
    try:
        for module_name, attribute, kind, phase in TARGETS:
            module = modules.get(module_name)
            original = getattr(module, attribute, None) if module is not None else None
            if not callable(original):
                witness.note("missing_target")
                continue
            if kind == "worker":
                wrapper = wrap_worker(witness, original)
            elif kind == "context":
                wrapper = wrap_context(witness, original)
            else:
                wrapper = wrap_call(witness, phase, original)
            setattr(module, attribute, wrapper)
            installed.append((module, attribute, original, wrapper))
    except BaseException:
        witness.invalid("restore_conflict" if _restore(installed) else "malformed")

    def undo() -> None:
        if _restore(installed):
            witness.invalid("restore_conflict")
    return undo


class FixtureWitnessPlugin:
    """Fixture-setup boundaries of every scope, registered for the selected protocol only."""

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef: Any, request: Any) -> Generator[None, Any, Any]:
        with fixture_phase(getattr(fixturedef, "argname", None)):
            return (yield)


PLUGIN_NAME = "theheat-pg2-phase-witness"


class FdWriter:
    """Unbuffered complete write of one line to a file descriptor."""

    __slots__ = ("_fd",)

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def __call__(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(self._fd, view)
            if written <= 0:
                raise OSError()
            view = view[written:]


_current: Witness | None = None


def current() -> Witness | None:
    return _current


class SelectedProtocol:
    """Owns the witness for the exact selected node's whole pytest protocol."""

    __slots__ = ("_modules", "_plugins", "_plugin", "_witness", "_undo", "_fd")

    def __init__(self, modules: Mapping[str, Any], plugins: Any) -> None:
        self._modules = modules
        self._plugins = plugins
        self._plugin: FixtureWitnessPlugin | None = None
        self._witness: Witness | None = None
        self._undo: Callable[[], None] | None = None
        self._fd: int | None = None

    def __enter__(self) -> None:
        global _current
        if _current is not None:
            # Nested selection: the active witness ends explicitly; this one stays inert.
            _current.invalid("reentrant")
            return
        try:
            # Taken between pytest phases, when capture is suspended and fd 2 is real.
            self._fd = os.dup(2)
        except BaseException:
            self._fd = None
            return
        witness = Witness(FdWriter(self._fd))
        self._witness = witness
        _current = witness
        witness.enter("protocol")
        self._undo = interpose(witness, self._modules)
        plugin = FixtureWitnessPlugin()
        try:
            self._plugins.register(plugin, name=PLUGIN_NAME)
            self._plugin = plugin
        except BaseException:
            witness.note("missing_target")

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        global _current
        witness = self._witness
        if witness is None:
            return False
        try:
            if self._plugin is not None:
                try:
                    self._plugins.unregister(self._plugin)
                except BaseException:
                    witness.invalid("restore_conflict")
            if self._undo is not None:
                self._undo()
            if exc_type is None:
                witness.exit("protocol")
            else:
                witness.error("protocol")
        except BaseException:
            witness.stopped = True
            witness.failed = True
        finally:
            _current = None
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except BaseException:
                    pass
        return False


def _is_target(item: Any) -> bool:
    try:
        return getattr(item, "nodeid", None) == TARGET_NODEID
    except BaseException:
        return False


def selected_protocol(item: Any, modules: Mapping[str, Any] | None = None) -> SelectedProtocol | _Null:
    if not _is_target(item):
        return NULL
    try:
        plugins = getattr(getattr(item, "config", None), "pluginmanager", None)
    except BaseException:
        plugins = None
    return SelectedProtocol(sys.modules if modules is None else modules, plugins)


def pytest_phase(item: Any, when: str) -> Phase | _Null:
    witness = _current
    if witness is None or when not in PYTEST_PHASES or not _is_target(item):
        return NULL
    return Phase(witness, PYTEST_PHASES[when])


def fixture_phase(argname: Any) -> Phase | _Null:
    witness = _current
    if witness is None or type(argname) is not str or argname not in FIXTURE_PHASES:
        return NULL
    return Phase(witness, FIXTURE_PHASES[argname])


def parse(text: str) -> dict[str, Any]:
    """Read one retained witness sequence from arbitrary log text.

    Only text from ``PREFIX`` to the end of each line is considered, so CI log
    columns and timestamps before it are ignored.
    """
    candidates = [line[line.index(PREFIX):].rstrip("\r") for line in text.splitlines() if PREFIX in line]
    result: dict[str, Any] = dict(status="absent", reason=None, lines=len(candidates), open=[],
                                  last_closed=None, errors=[], notes=[])
    if not candidates:
        return result
    if len(candidates) > MAX_LINES:
        return dict(result, status="invalid", reason="count")
    stack: list[str] = []
    terminal: tuple[str, str] | None = None
    for index, line in enumerate(candidates):
        final = index == len(candidates) - 1
        match = LINE.fullmatch(line) if len(line) < MAX_LINE_BYTES else None
        if match is None:
            if final and index > 0:
                return dict(result, status="truncated", reason="last_line", open=list(stack))
            return dict(result, status="invalid", reason="format", open=list(stack))
        if terminal is not None:
            return dict(result, status="invalid", reason="after_terminal", open=list(stack))
        sequence, kind, word = int(match.group(1)), match.group(2), match.group(3)
        if sequence != index + 1:
            return dict(result, status="invalid", reason="sequence", open=list(stack))
        if index == 0 and (kind, word) != ("ENTER", "protocol"):
            return dict(result, status="invalid", reason="start", open=list(stack))
        if kind in EVENTS:
            if word not in PHASES:
                return dict(result, status="invalid", reason="phase", open=list(stack))
            if kind == "ENTER":
                stack.append(word)
            elif not stack or stack[-1] != word:
                return dict(result, status="invalid", reason="nesting", open=list(stack))
            else:
                stack.pop()
                result["last_closed"] = word
                if kind == "ERROR":
                    result["errors"].append(word)
        elif kind == "UNAVAILABLE" and word in NOTE_REASONS:
            if word in result["notes"]:
                return dict(result, status="invalid", reason="duplicate_note", open=list(stack))
            result["notes"].append(word)
        elif word in TERMINAL_REASONS:
            terminal = (kind, word)
        else:
            return dict(result, status="invalid", reason="status", open=list(stack))
    result["open"] = list(stack)
    if terminal is not None:
        return dict(result, status=terminal[0].lower(), reason=terminal[1])
    if not stack and result["last_closed"] == "protocol":
        return dict(result, status="complete")
    return dict(result, status="incomplete")
