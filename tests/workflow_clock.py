"""Ticking midday clocks for invented multi-process positive workflows only.

Real elapsed clocks and timers are preserved. Production modules receive no
clock hook; the fixture and its explicitly configured children share wall time.
"""
from contextlib import contextmanager
import atexit
import subprocess
from datetime import UTC, datetime, timedelta
import time

from freezegun import api, freeze_time
import pytest

ELAPSED_CLOCKS = ("monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns")


def midday_metadata():
    target = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    return {"fixed_at": target.isoformat(), "real_epoch": api.real_time()}


@contextmanager
def ticking_workflow_clock(metadata):
    target = datetime.fromisoformat(metadata["fixed_at"])
    target += timedelta(seconds=api.real_time() - metadata["real_epoch"])
    elapsed = {name: getattr(time, name) for name in ELAPSED_CLOCKS}
    freezer = freeze_time(target, tick=True)
    freezer.start()
    try:
        for name, clock in elapsed.items():
            setattr(time, name, clock)
        # Freezegun also rewrites the alias captured by subprocess at import.
        # Its real deadlines must use the same preserved elapsed clock.
        setattr(subprocess, "_time", elapsed["monotonic"])
        yield
    finally:
        freezer.stop()
        # A surrounding calendar canary also deliberately preserves these.
        for name, clock in elapsed.items():
            setattr(time, name, clock)
        setattr(subprocess, "_time", elapsed["monotonic"])


def start_child_clock(metadata):
    """Called only by the three credentialless, invented test workers."""
    context = ticking_workflow_clock(metadata)
    context.__enter__()
    # Close before interpreter module teardown, including stderr-merged workers.
    atexit.register(context.__exit__, None, None, None)
    return context


@pytest.fixture
def positive_workflow_clock():
    metadata = midday_metadata()
    with ticking_workflow_clock(metadata):
        yield metadata
