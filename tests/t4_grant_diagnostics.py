"""Bounded fixture observations of existing grant calls; no new execution reads."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager, ExitStack
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Iterator
from unittest.mock import patch

from tests.t4_delivery_diagnostics import BEFORE_CODES

KIND = "delivery_grant_diagnostic/v1"
SECTION = "Delivery grant diagnostics (up to 8 rows / 64 KiB tail)"
MAX_ROWS, MAX_ROW_BYTES, TAIL_BYTES = 8, 2048, 65536
MAX_ACQUIRES, MAX_CONTEXTS, MAX_SECONDS = 2, 2, 86400
CODES = BEFORE_CODES | {"delivery_window_insufficient", "delivery_clock_regressed",
    "delivery_lease_busy", "delivery_dependency_unconfirmed", "stale_revision_check_owner"}
_UTC_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?Z")


def _utc(value: Any) -> datetime:
    if type(value) is str and _UTC_TEXT.fullmatch(value):
        value = datetime.fromisoformat(value[:-1] + "+00:00")
    if not isinstance(value, datetime) or value.tzinfo is not UTC or not 1900 <= value.year <= 2200:
        raise ValueError("unavailable")
    return value


def _now(value: Any) -> str:
    return datetime.isoformat(_utc(value), timespec="microseconds").replace("+00:00", "Z")


def _seconds(later: Any, earlier: Any) -> float:
    value = (_utc(later) - _utc(earlier)).total_seconds()
    if not math.isfinite(value) or abs(value) > MAX_SECONDS:
        raise ValueError("unavailable")
    return value


def _arg(args: tuple, kwargs: dict, index: int, name: str) -> Any:
    return args[index] if len(args) > index else kwargs[name]


def _empty(overflow: bool = False) -> dict:
    return dict(kind=KIND, available=False, overflow=overflow, begin=None, acquires=[])


class GrantDiagnostic:
    def __init__(self, command_error: type[BaseException] | None = None) -> None:
        self.command_error = command_error
        self.bad = self.overflow = self.active = False
        self.begin: dict | None = None
        self.acquires: list[dict] = []
        self.begin_calls = self.acquire_calls = self.context_calls = 0

    def _safe(self, operation: Callable[[], Any]) -> None:
        try:
            operation()
        except BaseException:
            self.bad = True

    def _code(self, exc: BaseException) -> str:
        code = vars(exc).get("code") if self.command_error is not None and isinstance(exc, self.command_error) else None
        return code if type(code) is str and code in CODES else "unclassified"

    def call(self, name: str, original: Callable, args: tuple, kwargs: dict) -> Any:
        row: dict | None = None
        owns_begin = name == "begin" and self.begin_calls == 0
        if name == "begin":
            self.begin_calls = min(2, self.begin_calls + 1)
            if not owns_begin:
                self.bad = self.overflow = True
            else:
                self.active = True

                def start_begin():
                    nonlocal row
                    now = _arg(args, kwargs, 9, "now")
                    lease = _arg(args, kwargs, 5, "lease")
                    if type(lease) is not dict:
                        raise ValueError("unavailable")
                    row = dict(status="pending", code=None, now=_now(now),
                        lease_remaining_seconds=_seconds(lease["expires_at"], now), context_remaining_seconds=[])
                    self.begin = row
                self._safe(start_begin)
        elif name == "acquire":
            self.acquire_calls = min(MAX_ACQUIRES + 1, self.acquire_calls + 1)
            if self.acquire_calls > MAX_ACQUIRES:
                self.bad = self.overflow = True
            else:

                def start_acquire():
                    nonlocal row
                    row = dict(scope="begin" if self.active else "initial", status="pending", code=None,
                        now=_now(_arg(args, kwargs, 7, "now")), lease_remaining_seconds=None)
                    self.acquires.append(row)
                self._safe(start_acquire)
        elif self.active:
            self.context_calls = min(MAX_CONTEXTS + 1, self.context_calls + 1)
            if self.context_calls > MAX_CONTEXTS:
                self.bad = self.overflow = True
        try:
            result = original(*args, **kwargs)
        except BaseException as exc:
            def raised(error: BaseException = exc):
                if row is not None:
                    row.update(status="raised", code=self._code(error))
            self._safe(raised)
            raise
        else:
            def returned():
                if row is not None:
                    row["status"] = "returned"
                    if name == "acquire":
                        if type(result) is not dict:
                            raise ValueError("unavailable")
                        if "lease" in result:
                            lease = result["lease"]
                            if type(lease) is not dict:
                                raise ValueError("unavailable")
                            row["lease_remaining_seconds"] = _seconds(lease["expires_at"], row["now"])
                elif name == "context" and self.active and self.context_calls <= MAX_CONTEXTS:
                    if type(result) is not tuple or len(result) != 2 or self.begin is None:
                        raise ValueError("unavailable")
                    self.begin["context_remaining_seconds"].append(_seconds(result[1], _arg(args, kwargs, 4, "now")))
            self._safe(returned)
            return result
        finally:
            if owns_begin:
                self.active = False

    def row(self) -> dict:
        if self.bad or self.active or not (self.begin is not None or self.acquires):
            return _empty(self.overflow)
        value = dict(kind=KIND, available=True, overflow=False, begin=self.begin, acquires=self.acquires)
        return value if valid_row(value) else _empty(self.overflow)

    def emit(self, log: Callable[[dict], Any]) -> None:
        try:
            value = self.row()
            if len(_encoded(value)) <= MAX_ROW_BYTES:
                log(value)
        except BaseException:
            pass


@contextmanager
def observe_grant(delivery: Any) -> Iterator[GrantDiagnostic]:
    capture = GrantDiagnostic()
    stack = ExitStack()
    try:
        if type(delivery) not in (ModuleType, SimpleNamespace):
            raise ValueError("unavailable")
        error = delivery.CommandError
        if not isinstance(error, type) or not issubclass(error, BaseException):
            raise ValueError("unavailable")
        capture.command_error = error
        for name in ("begin", "acquire", "context"):
            original = getattr(delivery, name)
            if not callable(original):
                raise ValueError("unavailable")

            def wrapper(key: str, function: Callable) -> Callable:
                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    return capture.call(key, function, args, kwargs)
                return wrapped
            stack.enter_context(patch.object(delivery, name, wrapper(name, original)))
    except BaseException:
        capture.bad = True
        stack.close()
    with stack:
        yield capture


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and abs(value) <= MAX_SECONDS


def valid_row(value: Any) -> bool:
    try:
        if (type(value) is not dict or set(value) != {"kind", "available", "overflow", "begin", "acquires"}
                or value["kind"] != KIND or type(value["available"]) is not bool or type(value["overflow"]) is not bool):
            return False
        if not value["available"]:
            return value == _empty(value["overflow"])
        begin, acquires = value["begin"], value["acquires"]
        if value["overflow"] or type(acquires) is not list or len(acquires) > MAX_ACQUIRES or not (begin or acquires):
            return False
        for row in ([begin] if begin is not None else []) + acquires:
            expected = {"status", "code", "now", "lease_remaining_seconds"} | ({"context_remaining_seconds"} if row is begin else {"scope"})
            if type(row) is not dict or set(row) != expected or row["status"] not in ("returned", "raised"):
                return False
            if (row["code"] not in CODES | {"unclassified"} if row["status"] == "raised" else row["code"] is not None):
                return False
            if type(row["now"]) is not str or _now(row["now"]) != row["now"]:
                return False
            if row is begin:
                contexts = row["context_remaining_seconds"]
                if not _number(row["lease_remaining_seconds"]) or type(contexts) is not list or len(contexts) > MAX_CONTEXTS or not all(_number(x) for x in contexts):
                    return False
            elif row["scope"] not in ("initial", "begin") or not (row["lease_remaining_seconds"] is None or _number(row["lease_remaining_seconds"])):
                return False
        return True
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique(pairs: list) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_key")
        value[key] = item
    return value


def last_rows(path: Path) -> list[dict]:
    with path.open("rb") as stream:
        offset = max(0, stream.seek(0, 2) - TAIL_BYTES)
        stream.seek(offset)
        tail = stream.read(TAIL_BYTES)
    if offset:
        tail = tail.partition(b"\n")[2]
    rows: deque[dict] = deque(maxlen=MAX_ROWS)
    for line in tail.splitlines():
        if len(line) <= MAX_ROW_BYTES:
            try:
                value = json.loads(line, object_pairs_hook=_unique)
                if valid_row(value):
                    rows.append(value)
            except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
                pass
    return list(rows)


def append_failure_section(item: Any, report: Any) -> None:
    if not report.failed or item.path.name != "test_postgres_temperature_delivery.py":
        return
    try:
        trace = Path(item.funcargs["compact_case"]["config"]["trace"])
        if trace.is_symlink() or trace.parent.resolve() != item.funcargs["tmp_path"].resolve():
            return
        rows = last_rows(trace)
        text = _encoded(rows).decode("utf-8") if rows else "Delivery grant diagnostics unavailable."
    except (KeyError, TypeError, ValueError, OSError, AttributeError):
        text = "Delivery grant diagnostics unavailable."
    report.sections.append((SECTION, text))
