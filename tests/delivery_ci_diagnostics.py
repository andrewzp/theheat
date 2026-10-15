"""Bounded, value-free observations for three delivery CI failures; not a fix."""
from collections import deque
from functools import wraps
import json
import os
import sys
import threading
import time


MAX_NODES = 10_000
MAX_DEPTH = 32
MAX_STRING_CHARS = 65_536
MAX_FRAMES = 1_000
HEAD_FRAMES = 8
TAIL_FRAMES = 48
FILENAME_CHARS = 128
FUNCTION_CHARS = 48
MAX_EVENTS = 256
MAX_EVENT_BYTES = 131_072
MAX_TOTAL_BYTES = 1_048_576
SAMPLE_SECONDS = 110
PHASES = ("prepare_and_attach", "complete_revision", "park", "run", "assert_live_senders_refuse")
CASES = (
    "test_atomic_approval_five_stages_and_replay_do_not_change_editorial_state[modis]",
    "test_atomic_approval_five_stages_and_replay_do_not_change_editorial_state[pm25]",
    "test_raw_and_receipt_commit_failures_recover_without_mutation_replay[modis]",
)


def shape(value):
    """Walk exact builtin values only, lazily; dict keys and object hooks are excluded."""
    counts = dict(dict=0, list=0, tuple=0, str=0, bytes=0, scalar=0, other=0)
    result = dict(nodes=0, max_depth=0, repeated_containers=0, string_chars=0,
                  scanned_utf8_bytes=0, bytes_length=0, partial=False, counts=counts)
    seen = set()
    scanned = 0
    stack = [(iter((value,)), 0)]
    while stack:
        if result["nodes"] >= MAX_NODES:
            result["partial"] = True
            break
        iterator, depth = stack[-1]
        try:
            item = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        except RuntimeError:  # An exact dict may change during a worker observation.
            result["partial"] = True
            break
        kind = type(item)
        result["nodes"] += 1
        result["max_depth"] = max(result["max_depth"], depth)
        if kind is dict or kind is list or kind is tuple:
            name = "dict" if kind is dict else "list" if kind is list else "tuple"
            counts[name] += 1
            if id(item) in seen:
                result["repeated_containers"] += 1
                continue
            seen.add(id(item))
            if depth >= MAX_DEPTH:
                result["partial"] = True
            else:
                stack.append((iter(item.values()) if kind is dict else iter(item), depth + 1))
        elif kind is str:
            counts["str"] += 1
            result["string_chars"] += len(item)
            take = min(len(item), MAX_STRING_CHARS - scanned)
            result["scanned_utf8_bytes"] += len(item[:take].encode("utf-8", errors="surrogatepass"))
            scanned += take
            if take < len(item):
                result["partial"] = True
        elif kind is bytes:
            counts["bytes"] += 1
            result["bytes_length"] += len(item)
        elif kind is int or kind is float or kind is bool or kind is type(None):
            counts["scalar"] += 1
        else:
            counts["other"] += 1
    return result


def frame_sample(frame):
    """Scan up to 1,000 locations; retain both ends, never locals or values.

    At most 56 * 176 characters, even at JSON's worst 12 bytes per escaped
    character, leaves over 12 KiB of the 128 KiB event limit for fixed metadata.
    """
    head, tail = [], deque(maxlen=TAIL_FRAMES)
    scanned = 0
    fields_truncated = False
    while frame is not None and scanned < MAX_FRAMES:
        filename, function = frame.f_code.co_filename, frame.f_code.co_name
        fields_truncated |= len(filename) > FILENAME_CHARS or len(function) > FUNCTION_CHARS
        # Retain the path's tail so a long checkout prefix cannot hide its basename.
        location = dict(file=filename[-FILENAME_CHARS:], function=function[:FUNCTION_CHARS], line=frame.f_lineno)
        if scanned < HEAD_FRAMES:
            head.append(location)
        else:
            tail.append(location)
        scanned += 1
        frame = frame.f_back
    frames = head + list(tail)
    omitted = scanned - len(frames)
    truncated = frame is not None
    return dict(frames=frames, scanned=scanned, omitted=omitted, truncated=truncated,
                fields_truncated=fields_truncated, partial=bool(omitted or truncated or fields_truncated))


class DeliveryDiagnostics:
    """Own one noninherited stderr duplicate; writes never replace a test outcome."""

    def __init__(self, fd, case, *, timer_factory=threading.Timer):
        if type(case) is not str or case not in CASES:
            raise ValueError("unsupported delivery diagnostic case")
        self.fd, self.case = fd, case
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.main_ident = threading.main_thread().ident
        self.events = self.bytes = self.dropped = self.errors = self.calls = 0
        self.closed = False
        self.timer_started = False
        self.timer = timer_factory(SAMPLE_SECONDS, self.sample)
        self.timer.daemon = True

    @classmethod
    def duplicate_stderr(cls, case):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("duplicate stderr on the main thread only")
        fd = os.dup(2)
        try:
            os.set_inheritable(fd, False)
            return cls(fd, case)
        except BaseException:
            os.close(fd)
            raise

    def emit(self, event, **metadata):
        try:
            with self.lock:
                if self.closed:
                    return
                row = dict(diagnostic="delivery-ci-v1", case=self.case, event=event,
                           elapsed_seconds=round(time.monotonic() - self.started, 6), **metadata)
                data = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
                closing = event == "closed"
                if (self.events >= MAX_EVENTS - (0 if closing else 1)
                        or len(data) > MAX_EVENT_BYTES
                        or self.bytes + len(data) > MAX_TOTAL_BYTES - (0 if closing else 1_024)):
                    self.dropped += 1
                    return
                self.events += 1
                self.bytes += len(data)
                # One bounded write; a short/error write is diagnostic loss, not a test failure.
                if os.write(self.fd, data) != len(data):
                    self.errors += 1
        except Exception:
            self.errors += 1

    def start(self):
        self.emit("started", sample_seconds=SAMPLE_SECONDS, node_limit=MAX_NODES,
                  depth_limit=MAX_DEPTH, string_scan_limit=MAX_STRING_CHARS,
                  frame_limit=MAX_FRAMES, event_limit=MAX_EVENTS,
                  event_byte_limit=MAX_EVENT_BYTES, total_byte_limit=MAX_TOTAL_BYTES)
        self.timer.start()
        self.timer_started = True

    def sample(self):
        try:
            frame = sys._current_frames().get(self.main_ident)
            self.emit("main_thread_sample", **frame_sample(frame))
        except Exception:
            self.errors += 1

    def wrap(self, phase, function):
        if type(phase) is not str or phase not in PHASES:
            raise ValueError("unsupported diagnostic phase")

        @wraps(function)
        def observed(*args, **kwargs):
            with self.lock:
                self.calls += 1
                call = self.calls
            try:
                self.emit("phase_begin", phase=phase, call=call, shape=shape((args, kwargs)))
            except Exception:
                self.errors += 1
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                kind = type(error)
                category = ("SystemExit" if kind is SystemExit else
                            "AssertionError" if kind is AssertionError else
                            "RuntimeError" if kind is RuntimeError else "other")
                self.emit("phase_error", phase=phase, call=call, category=category)
                raise
            try:
                self.emit("phase_return", phase=phase, call=call, shape=shape(result))
            except Exception:
                self.errors += 1
            return result
        return observed

    def close(self):
        self.timer.cancel()
        if self.timer_started:
            self.timer.join()  # Callback must finish before its descriptor can be reused.
        self.emit("closed", events=self.events, emitted_bytes=self.bytes,
                  partial=bool(self.dropped or self.errors), dropped=self.dropped, errors=self.errors)
        with self.lock:
            if not self.closed:
                self.closed = True
                os.close(self.fd)
