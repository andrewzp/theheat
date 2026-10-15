"""GIL-held, once-per-protocol CI diagnostics, never a test timeout or verdict.

One session thread observes the original setup/call/teardown deadline. Python
frame access runs with the GIL; a native operation holding it can delay sampling.
Writes are bounded but blocking: a stalled stderr sink can delay cancellation or
join. The unchanged CI job deadline remains the hard stop. Fatal faulthandler
reporting stays enabled separately; this module never schedules its C dumper.
"""
from collections import deque
from itertools import islice
import hashlib
import json
import math
import os
import sys
import threading
import time
from types import FrameType

MAX_THREADS = 16
MAX_SCAN_FRAMES = 1_000
HEAD_FRAMES = 4
TAIL_FRAMES = 8
FILE_CHARS = 64
FUNCTION_CHARS = 24
MAX_EVENT_BYTES = 262_144
MAX_TOTAL_BYTES = 4_194_304
MAX_SAMPLES = 128
THREAD_NAME = "theheat-ci-traceback"


def checked_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("CI traceback seconds must be finite and nonnegative")
    return seconds


def locations(frame):
    """Bound both scanning and output, keeping the outer caller, never locals."""
    head, tail = [], deque(maxlen=TAIL_FRAMES)
    scanned = 0
    fields_truncated = False
    while type(frame) is FrameType and scanned < MAX_SCAN_FRAMES:
        code = frame.f_code
        filename, function = code.co_filename, code.co_name
        fields_truncated |= len(filename) > FILE_CHARS or len(function) > FUNCTION_CHARS
        row = dict(file=filename[-FILE_CHARS:], function=function[:FUNCTION_CHARS], line=frame.f_lineno)
        if scanned < HEAD_FRAMES:
            head.append(row)
        else:
            tail.append(row)
        scanned += 1
        frame = frame.f_back
    retained = head + list(tail)
    return dict(frames=retained, scanned=scanned, omitted=scanned-len(retained),
                truncated=frame is not None, fields_truncated=fields_truncated,
                partial=bool(frame is not None or scanned > len(retained) or fields_truncated))


def frame_snapshot(main_ident, frames):
    # _current_frames necessarily creates its mapping first; all retained frame
    # references are released after this bounded metadata-only conversion.
    selected = [main_ident] if main_ident in frames else []
    selected.extend(islice((ident for ident in frames if ident != main_ident), MAX_THREADS-len(selected)))
    result = [dict(thread_id=ident, main=ident == main_ident, **locations(frames[ident])) for ident in selected]
    return dict(threads=result, observed_threads=len(frames), omitted_threads=len(frames)-len(result),
                partial=len(frames) > len(result) or any(row["partial"] for row in result))


class Watchdog:
    def __init__(self, fd, seconds, *, clock=time.monotonic, frames=sys._current_frames):
        self.fd, self.seconds = fd, checked_seconds(seconds)
        if self.seconds == 0:
            raise ValueError("A watchdog requires positive seconds")
        self.clock, self.frames = clock, frames
        self.main_ident = threading.main_thread().ident
        self.condition = threading.Condition()
        self.thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self.active = None
        self.sequence = self.samples = self.bytes = self.dropped = self.errors = 0
        self.closed = self.fd_closed = self.started = False

    @classmethod
    def duplicate_stderr(cls, seconds):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Duplicate stderr on the main thread only")
        fd = os.dup(2)
        try:
            os.set_inheritable(fd, False)
            return cls(fd, seconds)
        except BaseException:
            os.close(fd)
            raise

    def _emit(self, event, **fields):
        """Caller holds condition: identity, serialization, write and end are ordered."""
        try:
            data = (json.dumps(dict(diagnostic="ci-python-traceback-v1", event=event, **fields),
                               ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
            reserve = 0 if event == "closed" else 1_024
            if len(data) > MAX_EVENT_BYTES or self.bytes + len(data) > MAX_TOTAL_BYTES-reserve:
                self.dropped += 1
                return
            self.bytes += len(data)
            if os.write(self.fd, data) != len(data):
                self.errors += 1
        except Exception:
            self.errors += 1

    def start(self):
        with self.condition:
            if self.closed or self.started:
                raise RuntimeError("Watchdog may start only once")
            self._emit("started", seconds=self.seconds, fd_inheritable=os.get_inheritable(self.fd),
                       thread_limit=MAX_THREADS, scan_frames=MAX_SCAN_FRAMES, retained_frames=HEAD_FRAMES+TAIL_FRAMES,
                       event_byte_limit=MAX_EVENT_BYTES, total_byte_limit=MAX_TOTAL_BYTES, sample_limit=MAX_SAMPLES)
            self.thread.start()
            self.started = True

    def begin(self, nodeid):
        if type(nodeid) is not str:
            raise TypeError("Expected a pytest node ID")
        raw = nodeid.encode("utf-8", errors="replace")
        with self.condition:
            if self.closed or self.active is not None:
                raise RuntimeError("Overlapping test protocols are unsupported")
            self.sequence += 1
            token = self.sequence
            started = self.clock()
            self.active = dict(token=token, nodeid=raw[:1024].decode("utf-8", errors="replace"),
                nodeid_sha256=hashlib.sha256(raw).hexdigest(), nodeid_truncated=len(raw)>1024,
                started=started, deadline=started+self.seconds, sampled=False)
            self.condition.notify_all()
            return token

    def end(self, token):
        with self.condition:
            if self.active is not None and self.active["token"] == token:
                self.active = None
                self.condition.notify_all()

    def sample_due(self):
        """Same locked operation used by the thread and deterministic clock tests."""
        with self.condition:
            active = self.active
            if self.closed or active is None or active["sampled"] or self.clock() < active["deadline"]:
                return False
            active["sampled"] = True
            if self.samples >= MAX_SAMPLES:
                self.dropped += 1
                return False
            self.samples += 1
            try:
                snapshot = frame_snapshot(self.main_ident, self.frames())
                self._emit("protocol_sample", **{key:value for key,value in active.items() if key != "sampled"},
                           sampled_at=self.clock(), **snapshot)
            except Exception:
                self.errors += 1
            return True

    def _run(self):
        with self.condition:
            while not self.closed:
                active = self.active
                if active is None or active["sampled"]:
                    self.condition.wait()
                else:
                    remaining = active["deadline"]-self.clock()
                    if remaining > 0:
                        self.condition.wait(remaining)
                    else:
                        self.sample_due()

    def close(self):
        with self.condition:
            self.closed = True
            self.active = None
            self.condition.notify_all()
        if self.started:
            self.thread.join()  # No callback may outlive or reuse this descriptor.
        with self.condition:
            if not self.fd_closed:
                self._emit("closed", protocols=self.sequence, samples=self.samples, bytes=self.bytes,
                           dropped=self.dropped, errors=self.errors, partial=bool(self.dropped or self.errors),
                           thread_alive=self.thread.is_alive())
                os.close(self.fd)
                self.fd_closed = True
