"""Test-only, code-only observations of the original local delivery callbacks.

No production import, clock, source, database, native, network or transport call
is made here. Wrappers forward the original operation once and preserve its
objects, return value and exception. Missing observations remain unavailable.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

KIND = "delivery_refusal_diagnostic/v1"
TAIL_BYTES = 65_536
MAX_ROWS = 8
MAX_ROW_BYTES = 2_048
MAX_OBSERVATIONS = 2
SECTION = "Delivery refusal diagnostics (up to 8 rows / 64 KiB tail)"
BEFORE_CODES = frozenset({
    "delivery_attempt_changed", "delivery_stale_fence", "delivery_window_expired",
    "delivery_configuration_changed", "delivery_draft_missing", "delivery_approval_changed",
    "delivery_parked_approval_required", "delivery_media_changed", "platform_description_required",
    "platform_description_changed", "ghcn_preparation_expired", "ghcn_execution_context_changed",
    "ghcn_baseline_changed", "ghcn_baseline_unavailable", "delivery_claim_changed",
    "delivery_attempt_context_consumed", "delivery_attempt_successor_changed",
    "delivery_request_changed", "media_source_not_allowlisted",
})
ADAPTER_CODES = frozenset({
    "delivery_final_currentness_refused", "delivery_sdk_destination_changed",
    "delivery_sdk_headers_refused", "delivery_sdk_credentials_refused",
    "delivery_request_content_changed", "delivery_upload_bytes_changed",
    "delivery_response_incomplete", "delivery_dispatch_not_granted",
    "delivery_second_request_refused", "delivery_sdk_unavailable",
})
OUTCOMES = frozenset({"disabled", "confirmed", "not_sent", "pending", "unknown", "withheld", "not_dispatched"})
SOURCES = frozenset({"response", "reconciliation", "no_call"})
REASONS = frozenset({"received", "transport_unavailable", "size_exceeded", "time_exceeded", "cleanup_failed", "currentness_refused"})


def _enum(value: Any, allowed: frozenset[str]) -> str | None:
    return value if type(value) is str and value in allowed else None


def _observation(response: Any, source: Any) -> dict:
    empty = dict(metadata="unavailable", source=None, reason=None, http_status=None, complete=None)
    if type(response) is not dict:
        return empty
    reason, status, complete = response.get("reason"), response.get("http_status"), response.get("complete")
    if (_enum(source, SOURCES) is None or _enum(reason, REASONS) is None or type(complete) is not bool
            or not (status is None or type(status) is int and 100 <= status <= 599)
            or complete != (reason == "received") or complete and status is None
            or source == "no_call" and (reason != "currentness_refused" or complete or status is not None)):
        return empty
    return dict(metadata="available", source=source, reason=reason, http_status=status, complete=complete)


class DeliveryDiagnostic:
    def __init__(self) -> None:
        self.before: dict = dict(status="unavailable", code=None)
        self.adapter: dict = dict(status="unavailable", reason=None, sdk_completed=None, binding_present=None)
        self.observations: list[dict] = []
        self.observations_overflow = False
        self._before_count = 0
        self._adapter_count = 0

    def _before(self, original: Callable, command_error: type[BaseException] | None, *args: Any, **kwargs: Any) -> Any:
        self._before_count = min(2, self._before_count + 1)
        try:
            result = original(*args, **kwargs)
        except BaseException as exc:
            try:
                code = vars(exc).get("code") if command_error is not None and isinstance(exc, command_error) else None
                self.before = dict(status="raised", code=_enum(code, BEFORE_CODES) or "unclassified")
            except Exception:
                self.before = dict(status="raised", code="unclassified")
            raise
        else:
            self.before = dict(status="returned", code=None)
            return result
        finally:
            if self._before_count > 1:
                self.before = dict(status="multiple", code=None)

    def _observe(self, original: Callable, *args: Any, **kwargs: Any) -> Any:
        row = None
        try:
            if len(self.observations) < MAX_OBSERVATIONS:
                response = args[1] if len(args) > 1 else kwargs.get("response")
                source = args[2] if len(args) > 2 else kwargs.get("source", "response")
                row = {**_observation(response, source), "callback": "raised"}
                self.observations.append(row)
            else:
                self.observations_overflow = True
        except Exception:
            pass
        result = original(*args, **kwargs)
        if row is not None:
            row["callback"] = "returned"
        return result

    def _execute(self, original: Callable, *args: Any, **kwargs: Any) -> Any:
        self._adapter_count = min(2, self._adapter_count + 1)
        forwarded = dict(kwargs)
        observe = kwargs.get("observe")
        if callable(observe):
            def observed(*values: Any, **named: Any) -> Any:
                return self._observe(observe, *values, **named)
            forwarded["observe"] = observed
        try:
            result = original(*args, **forwarded)
        except BaseException:
            self.adapter["status"] = "raised"
            raise
        else:
            if type(result) is dict:
                self.adapter = dict(status="returned", reason=_enum(result.get("reason"), ADAPTER_CODES)
                    if result.get("reason") is None or _enum(result.get("reason"), ADAPTER_CODES) else "unclassified",
                    sdk_completed=result.get("sdk_completed") if type(result.get("sdk_completed")) is bool else None,
                    binding_present=result["binding"] is not None if "binding" in result else None)
            else:
                self.adapter["status"] = "returned"
            return result
        finally:
            if self._adapter_count > 1:
                self.adapter = dict(status="multiple", reason=None, sdk_completed=None, binding_present=None)

    def emit(self, emit: Callable[[dict], Any], *, platform: Any, stage: Any, result: Any) -> None:
        """Best effort only, after the original call. Never emit its payload or errors."""
        try:
            row = dict(kind=KIND, platform=platform, stage=stage,
                outcome=_enum(result.get("outcome"), OUTCOMES) if type(result) is dict else None,
                before_call=self.before, adapter=self.adapter, observations=self.observations,
                observations_overflow=self.observations_overflow)
            if valid_row(row) and len(_encoded(row)) <= MAX_ROW_BYTES:
                emit(row)
        except Exception:
            pass


@contextmanager
def observe_callbacks(delivery: Any, adapter: Any) -> Iterator[DeliveryDiagnostic]:
    """Install only around the fixture's original delivery_run, then restore."""
    diagnostic = DeliveryDiagnostic()
    before, execute = delivery.before_call, adapter.execute
    command_error = delivery.CommandError

    def observed_before(*args: Any, **kwargs: Any) -> Any:
        return diagnostic._before(before, command_error, *args, **kwargs)

    def observed_execute(*args: Any, **kwargs: Any) -> Any:
        return diagnostic._execute(execute, *args, **kwargs)

    with patch.object(delivery, "before_call", observed_before), patch.object(adapter, "execute", observed_execute):
        yield diagnostic


def _encoded(row: Any) -> bytes:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def valid_row(row: Any) -> bool:
    """Closed schema shared by the writer and failure-section reader."""
    if (type(row) is not dict or set(row) != {"kind", "platform", "stage", "outcome", "before_call", "adapter",
            "observations", "observations_overflow"} or row["kind"] != KIND
            or _enum(row["platform"], frozenset({"x", "bluesky"})) is None
            or _enum(row["stage"], frozenset({"upload", "alt", "create"})) is None
            or row["platform"] == "bluesky" and row["stage"] == "alt"
            or row["outcome"] is not None and _enum(row["outcome"], OUTCOMES) is None
            or type(row["observations_overflow"]) is not bool):
        return False
    before, adapter = row["before_call"], row["adapter"]
    if (type(before) is not dict or set(before) != {"status", "code"}
            or before["status"] not in ("unavailable", "returned", "raised", "multiple")
            or (_enum(before["code"], BEFORE_CODES | {"unclassified"}) is None if before["status"] == "raised" else before["code"] is not None)
            or type(adapter) is not dict or set(adapter) != {"status", "reason", "sdk_completed", "binding_present"}
            or adapter["status"] not in ("unavailable", "returned", "raised", "multiple")
            or adapter["reason"] is not None and _enum(adapter["reason"], ADAPTER_CODES | {"unclassified"}) is None
            or any(value is not None and type(value) is not bool for value in (adapter["sdk_completed"], adapter["binding_present"]))):
        return False
    if adapter["status"] != "returned" and any(adapter[key] is not None for key in ("reason", "sdk_completed", "binding_present")):
        return False
    observations = row["observations"]
    if type(observations) is not list or len(observations) > MAX_OBSERVATIONS:
        return False
    for item in observations:
        if (type(item) is not dict or set(item) != {"metadata", "source", "reason", "http_status", "complete", "callback"}
                or item["callback"] not in ("returned", "raised")):
            return False
        expected = _observation(item, item["source"])
        if {key: value for key, value in item.items() if key != "callback"} != expected:
            return False
    return True


def _unique(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def last_rows(path: Path) -> list[dict]:
    """Read at most the existing 64 KiB tail; never expose generic trace rows."""
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        offset = max(0, size - TAIL_BYTES)
        stream.seek(offset)
        tail = stream.read(TAIL_BYTES)
    if offset:
        tail = tail.partition(b"\n")[2]
    rows: deque[dict] = deque(maxlen=MAX_ROWS)
    for line in tail.splitlines():
        if len(line) > MAX_ROW_BYTES:
            continue
        try:
            row = json.loads(line, object_pairs_hook=_unique)
            if valid_row(row):
                rows.append(row)
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            continue
    return list(rows)


def append_failure_section(item: Any, report: Any) -> None:
    """Separate additive report hook; no change to the original check-window hook."""
    if not report.failed or item.path.name != "test_postgres_temperature_delivery.py":
        return
    try:
        trace = Path(item.funcargs["compact_case"]["config"]["trace"])
        if trace.is_symlink() or trace.parent.resolve() != item.funcargs["tmp_path"].resolve():
            return
        rows = last_rows(trace)
        text = _encoded(rows).decode("utf-8") if rows else "Delivery refusal diagnostics unavailable."
    except (KeyError, TypeError, ValueError, OSError, AttributeError):
        text = "Delivery refusal diagnostics unavailable."
    report.sections.append((SECTION, text))
