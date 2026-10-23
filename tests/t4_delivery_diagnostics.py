"""Test-only, code-only observations of the original local delivery callbacks.

No production import, clock, source, database, native, network or transport call
is made here. Wrappers forward the original operation once and preserve its
objects, return value and exception. Missing observations remain unavailable.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager, ExitStack
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

KIND = "delivery_refusal_diagnostic/v2"
PARENT_KIND = "delivery_parent_http/v1"
FIXTURE_KIND = "delivery_fixture_receipts/v1"
TAIL_BYTES = 65_536
MAX_ROWS = 8
MAX_ROW_BYTES = 2_048
MAX_OBSERVATIONS = 2
SECTION = "Delivery refusal diagnostics (up to 8 rows / 64 KiB tail)"
FIXTURE_SECTION = "Delivery fixture receipt counters (up to 8 rows; in-memory witness only)"
MAX_COMMUNICATE_CALLS = 3
MAX_FIXTURE_RECORDS = 64
# Fixed projection of the existing fixture's five routes, never emitted paths.
FIXTURE_ROUTES = {
    "/1.1/media/upload.json": ("x", "upload"),
    "/1.1/media/metadata/create.json": ("x", "alt"),
    "/2/tweets": ("x", "create"),
    "/xrpc/com.atproto.repo.uploadBlob": ("bluesky", "upload"),
    "/xrpc/com.atproto.repo.createRecord": ("bluesky", "create"),
}
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


def _timeout(value: Any) -> int | float | None:
    return value if type(value) in (int, float) and 0 < value <= 15 and math.isfinite(value) else None


class ParentHttpDiagnostic:
    """Observe existing calls only; never replace the original child object."""
    def __init__(self) -> None:
        self.available = False
        self.popen_calls = 0
        self.communicate_calls = 0
        self.popen_outcome: str | None = None
        self.first_timeout: int | float | None = None
        self.first_outcome: str | None = None
        self._scopes = 0

    def row(self) -> dict:
        return dict(kind=PARENT_KIND, available=self.available, popen_calls=self.popen_calls,
            communicate_calls=self.communicate_calls, popen_outcome=self.popen_outcome,
            first_timeout=self.first_timeout, first_outcome=self.first_outcome)

    @contextmanager
    def observe(self, adapter: Any) -> Iterator[None]:
        reference = getattr(adapter, "subprocess", None)
        if reference is None:
            yield
            return
        self._scopes += 1
        self.available = self._scopes == 1
        capture = self
        original_popen = reference.Popen
        timeout_error = reference.TimeoutExpired
        with ExitStack() as stack:
            class ProcessReference:
                def __getattr__(self, name: str) -> Any:
                    return getattr(reference, name)

                def Popen(self, *args: Any, **kwargs: Any) -> Any:
                    capture.popen_calls = min(2, capture.popen_calls + 1)
                    if capture.popen_calls > 1:
                        capture.available = False
                    try:
                        child = original_popen(*args, **kwargs)
                    except BaseException:
                        capture.popen_outcome = "raised"
                        raise
                    capture.popen_outcome = "returned"
                    try:
                        # patch.object restores an instance value exactly, or
                        # deletes its temporary override of an inherited method.
                        # An unsupported child stays original and unavailable.
                        if type(vars(child)) is not dict:
                            raise TypeError
                        original_communicate = child.communicate

                        def communicate(*values: Any, **named: Any) -> Any:
                            capture.communicate_calls = min(MAX_COMMUNICATE_CALLS + 1, capture.communicate_calls + 1)
                            first = capture.communicate_calls == 1
                            if capture.communicate_calls > MAX_COMMUNICATE_CALLS:
                                capture.available = False
                            if first:
                                supplied = named.get("timeout") if len(values) < 2 else values[1] if "timeout" not in named else None
                                capture.first_timeout = _timeout(supplied)
                            try:
                                result = original_communicate(*values, **named)
                            except BaseException as exc:
                                if first:
                                    capture.first_outcome = "TimeoutExpired" if isinstance(exc, timeout_error) else "raised"
                                raise
                            if first:
                                capture.first_outcome = "returned"
                            return result

                        stack.enter_context(patch.object(child, "communicate", communicate))
                    except (AttributeError, TypeError):
                        capture.available = False
                    return child

            # Replace only this adapter's module reference, never the shared
            # subprocess module or any Popen class/global method.
            stack.enter_context(patch.object(adapter, "subprocess", ProcessReference()))
            yield


def _valid_parent(row: Any) -> bool:
    if (type(row) is not dict or set(row) != {"kind", "available", "popen_calls", "communicate_calls",
            "popen_outcome", "first_timeout", "first_outcome"} or row["kind"] != PARENT_KIND
            or type(row["available"]) is not bool
            or type(row["popen_calls"]) is not int or not 0 <= row["popen_calls"] <= 2
            or type(row["communicate_calls"]) is not int or not 0 <= row["communicate_calls"] <= MAX_COMMUNICATE_CALLS + 1
            or row["popen_outcome"] not in (None, "returned", "raised")
            or row["first_outcome"] not in (None, "returned", "TimeoutExpired", "raised")
            or row["first_timeout"] is not None and _timeout(row["first_timeout"]) is None):
        return False
    if row["available"] and (row["popen_calls"] > 1 or row["communicate_calls"] > MAX_COMMUNICATE_CALLS):
        return False
    if row["popen_calls"] == 0:
        return row["popen_outcome"] is None and row["communicate_calls"] == 0 and row["first_timeout"] is None and row["first_outcome"] is None
    if row["popen_outcome"] is None or row["communicate_calls"] and row["popen_outcome"] != "returned" and row["popen_calls"] == 1:
        return False
    if row["communicate_calls"] == 0:
        return row["first_timeout"] is None and row["first_outcome"] is None
    return row["first_outcome"] is not None and (not row["available"] or row["popen_calls"] == 1 and row["communicate_calls"] <= MAX_COMMUNICATE_CALLS)


class DeliveryDiagnostic:
    def __init__(self) -> None:
        self.before: dict = dict(status="unavailable", code=None)
        self.adapter: dict = dict(status="unavailable", reason=None, sdk_completed=None, binding_present=None)
        self.observations: list[dict] = []
        self.observations_overflow = False
        self._before_count = 0
        self._adapter_count = 0
        self.parent_http = ParentHttpDiagnostic()

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
                observations_overflow=self.observations_overflow, parent_http=self.parent_http.row())
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
        def original_with_parent(*values: Any, **named: Any) -> Any:
            with diagnostic.parent_http.observe(adapter):
                return execute(*values, **named)
        return diagnostic._execute(original_with_parent, *args, **kwargs)

    with patch.object(delivery, "before_call", observed_before), patch.object(adapter, "execute", observed_execute):
        yield diagnostic


def _encoded(row: Any) -> bytes:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def valid_row(row: Any) -> bool:
    """Closed schema shared by the writer and failure-section reader."""
    if (type(row) is not dict or set(row) != {"kind", "platform", "stage", "outcome", "before_call", "adapter",
            "observations", "observations_overflow", "parent_http"} or row["kind"] != KIND
            or _enum(row["platform"], frozenset({"x", "bluesky"})) is None
            or _enum(row["stage"], frozenset({"upload", "alt", "create"})) is None
            or row["platform"] == "bluesky" and row["stage"] == "alt"
            or row["outcome"] is not None and _enum(row["outcome"], OUTCOMES) is None
            or type(row["observations_overflow"]) is not bool or not _valid_parent(row["parent_http"])):
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


def _fixture_counts(objects: Any) -> dict:
    unavailable = dict(kind=FIXTURE_KIND, available=False, full_body_post=None, accepted_records=None)
    try:
        if type(objects) is not tuple or len(objects) != 3:
            return unavailable
        _, trace, accepted = objects
        if (type(trace) is not list or not isinstance(accepted, dict)
                or len(trace) > MAX_FIXTURE_RECORDS or dict.__len__(accepted) > MAX_FIXTURE_RECORDS):
            return unavailable
        posts = {stage: 0 for stage in FIXTURE_ROUTES.values()}
        receipts = dict(posts)
        attempts: dict[str, tuple[str, str]] = {}
        request_hashes: dict[str, str] = {}
        for row in list.copy(trace):
            if type(row) is not dict:
                return unavailable
            if row.get("method") == "GET" and set(row) == {"method", "path"} and type(row["path"]) is str:
                continue
            if (set(row) != {"method", "path", "body", "attempt_id", "request_sha256", "content_type"}
                    or row["method"] != "POST" or type(row["path"]) is not str or row["path"] not in FIXTURE_ROUTES
                    or type(row["body"]) is not bytes or type(row["content_type"]) is not str
                    or not all(type(row[key]) is str and len(row[key]) == 64
                        and all(char in "0123456789abcdef" for char in row[key]) for key in ("attempt_id", "request_sha256"))):
                return unavailable
            stage = FIXTURE_ROUTES[row["path"]]
            if row["attempt_id"] in attempts and (attempts[row["attempt_id"]] != stage or request_hashes[row["attempt_id"]] != row["request_sha256"]):
                return unavailable
            attempts[row["attempt_id"]] = stage
            request_hashes[row["attempt_id"]] = row["request_sha256"]
            posts[stage] += 1
        for identity, proof in list(dict.items(accepted)):
            if (type(identity) is not str or identity not in attempts or type(proof) is not dict
                    or set(proof) != {"kind", "instance_id", "attempt_id", "request_sha256", "status", "body_base64"}
                    or proof["kind"] != "accepted" or proof["attempt_id"] != identity
                    or proof["request_sha256"] != request_hashes[identity]
                    or type(proof["status"]) is not int or not 100 <= proof["status"] <= 599
                    or not all(type(proof[key]) is str for key in ("instance_id", "request_sha256", "body_base64"))):
                return unavailable
            receipts[attempts[identity]] += 1

        def projected(counts: dict) -> list[dict]:
            return [dict(platform=platform, stage=stage, count=count) for (platform, stage), count in counts.items()]

        return dict(kind=FIXTURE_KIND, available=True, full_body_post=projected(posts), accepted_records=projected(receipts))
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return unavailable


class FixtureReceiptDiagnostic:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.overflow = False

    def retain(self, objects: Any) -> None:
        if len(self.rows) < MAX_ROWS:
            self.rows.append(_fixture_counts(objects))
        else:
            self.overflow = True

    def output(self) -> list[dict]:
        if self.overflow or not self.rows or len(self.rows) > MAX_ROWS or not all(_valid_fixture(row) for row in self.rows):
            return [_fixture_counts(None)]
        return self.rows


def _valid_fixture(row: Any) -> bool:
    if (type(row) is not dict or set(row) != {"kind", "available", "full_body_post", "accepted_records"}
            or row["kind"] != FIXTURE_KIND or type(row["available"]) is not bool):
        return False
    if not row["available"]:
        return row["full_body_post"] is None and row["accepted_records"] is None
    stages = list(FIXTURE_ROUTES.values())
    for field in ("full_body_post", "accepted_records"):
        values = row[field]
        if type(values) is not list or len(values) != len(stages):
            return False
        for value, (platform, stage) in zip(values, stages):
            if (type(value) is not dict or set(value) != {"platform", "stage", "count"}
                    or value["platform"] != platform or value["stage"] != stage
                    or type(value["count"]) is not int or not 0 <= value["count"] <= MAX_FIXTURE_RECORDS):
                return False
        if sum(value["count"] for value in values) > MAX_FIXTURE_RECORDS:
            return False
    return all(accepted["count"] <= post["count"] for accepted, post in zip(row["accepted_records"], row["full_body_post"]))


@contextmanager
def observe_fixture_server(owner: Any) -> Iterator[FixtureReceiptDiagnostic]:
    """One original contextmanager, same yielded objects and original teardown."""
    capture = FixtureReceiptDiagnostic()
    original = owner.fixture_server

    @contextmanager
    def observed(*args: Any, **kwargs: Any) -> Iterator[Any]:
        objects = None
        try:
            with original(*args, **kwargs) as objects:
                yield objects
        finally:
            # In-memory projection only, after original teardown, including when
            # the original body/teardown raises. No journal/file reads or probes.
            try:
                capture.retain(objects)
            except Exception:
                pass

    with patch.object(owner, "fixture_server", observed):
        yield capture


def append_fixture_failure_section(item: Any, report: Any) -> None:
    if not report.failed or item.path.name != "test_postgres_temperature_delivery.py":
        return
    try:
        capture = item.funcargs.get("_t4_fixture_receipt_observer")
        rows = capture.output() if type(capture) is FixtureReceiptDiagnostic else [_fixture_counts(None)]
        encoded = _encoded(rows)
        if len(encoded) > MAX_ROWS * MAX_ROW_BYTES:
            encoded = _encoded([_fixture_counts(None)])
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        encoded = _encoded([_fixture_counts(None)])
    report.sections.append((FIXTURE_SECTION, encoded.decode("utf-8")))
