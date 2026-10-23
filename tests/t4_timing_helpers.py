"""Opt-in spans for one invented T4 diagnostic; no authority or clock changes."""
from functools import wraps
import json
from pathlib import Path

from freezegun import api


def sample():
    return dict(monotonic=api.real_monotonic(), wall=api.real_time())


def emit(trace, operation, label, started, ended, *, outcome="returned", error_type=None, error_code=None):
    row = dict(kind="t4_diagnostic_span", operation=operation, label=label,
        started=started, ended=ended, monotonic_seconds=ended["monotonic"] - started["monotonic"],
        wall_seconds=ended["wall"] - started["wall"], outcome=outcome, error_type=error_type, error_code=error_code)
    with Path(trace).open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")


def timed(trace, operation, label, call, /, *args, **kwargs):
    started = sample()
    outcome, error_type, error_code = "returned", None, None
    try:
        return call(*args, **kwargs)
    except BaseException as exc:
        outcome, error_type, error_code = "raised", type(exc).__name__, getattr(exc, "code", None)
        raise
    finally:
        emit(trace, operation, label, started, sample(), outcome=outcome, error_type=error_type, error_code=error_code)


def instrument(target, name, trace, operation, label):
    original = getattr(target, name)
    @wraps(original)
    def wrapped(*args, **kwargs):
        return timed(trace, operation, label, original, *args, **kwargs)
    setattr(target, name, wrapped)
