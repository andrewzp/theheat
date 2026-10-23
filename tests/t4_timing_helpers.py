"""Opt-in spans for one invented T4 diagnostic; no authority or clock changes."""
from functools import wraps
from contextlib import contextmanager
import json
import marshal
import math
import os
from pathlib import Path
import re
import sysconfig
import tempfile

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


PROFILE_BYTES = 32_768
PROFILE_STAGE = "saved_revision_deterministic"
ROOT = Path(__file__).resolve().parents[1]
STDLIB = Path(sysconfig.get_path("stdlib")).resolve()
SITE = Path(sysconfig.get_path("purelib")).resolve()
VENDOR_FILES = {"psycopg/connection.py", "psycopg/cursor.py", "psycopg/_connection_base.py",
                "psycopg/_cursor_base.py", "psycopg/waiting.py"}
LIBRARY_FILES = {"copy.py", "dataclasses.py", "contextlib.py", "json/encoder.py", "json/decoder.py"}


def _profile_label(filename, line, function):
    if type(filename) is not str or len(filename) > 512 or type(line) is not int or not 0 <= line <= 1_000_000:
        return None
    if type(function) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}|<(?:module|lambda|listcomp|dictcomp|setcomp|genexpr)>", function):
        return None
    path = Path(filename)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if path.is_relative_to(ROOT):
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith(("src/", "tests/")) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}\.py", relative):
            return None
    elif path.is_relative_to(STDLIB) and path.relative_to(STDLIB).as_posix() in LIBRARY_FILES:
        relative = "stdlib/" + path.relative_to(STDLIB).as_posix()
    elif path.is_relative_to(SITE) and path.relative_to(SITE).as_posix() in VENDOR_FILES:
        relative = "site/" + path.relative_to(SITE).as_posix()
    else:
        return None
    if not path.is_file() or path.stat().st_size > 1_048_576:
        return None
    if not function.startswith("<"):
        lines = path.read_text().splitlines()
        if not any(re.match(r"\s*(?:async\s+)?def\s+" + re.escape(function) + r"\b", text)
                   for text in lines[max(0, line - 1):line + 8]):
            return None
    return relative


def _profile_summary(status, rows=()):
    return dict(status=status, stage=PROFILE_STAGE, profiling_overhead=True, rows=list(rows))


def safe_profile_stats(stats):
    """Only known code locations and finite counters, never caller data or repr."""
    if type(stats) is not dict or len(stats) > 20_000:
        return _profile_summary("unavailable")
    rows = []
    for key, value in stats.items():
        if type(key) is not tuple or len(key) != 3 or type(value) is not tuple or len(value) != 5:
            return _profile_summary("unavailable")
        primitive, calls, own, cumulative = value[:4]
        if any(type(number) is not int or not 0 <= number <= 10**12 for number in (primitive, calls)):
            return _profile_summary("unavailable")
        if any(type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 86_400
               for number in (own, cumulative)):
            return _profile_summary("unavailable")
        label = _profile_label(*key)
        if label is not None:
            rows.append(dict(file=label, line=key[1], function=key[2], primitive_calls=primitive,
                             calls=calls, self_seconds=own, cumulative_seconds=cumulative))
    rows.sort(key=lambda row: (-row["cumulative_seconds"], -row["self_seconds"], row["file"], row["line"]))
    # Include hot leaves as well as nested cumulative callers.
    hot = rows[:20] + sorted(rows, key=lambda row: (-row["self_seconds"], -row["cumulative_seconds"]))[:20]
    selected = {(row["file"], row["line"], row["function"]): row for row in hot}
    result = _profile_summary("available" if selected else "unavailable", sorted(selected.values(),
        key=lambda row: (-row["cumulative_seconds"], -row["self_seconds"], row["file"], row["line"])))
    if len(json.dumps(result, allow_nan=False).encode()) > PROFILE_BYTES:
        return _profile_summary("unavailable")
    return result


@contextmanager
def saved_revision_profile(case, directory):
    """One ephemeral-job attempt; diagnostics never replace the worker outcome."""
    profile = None
    destination = None
    try:
        if os.environ.get("THEHEAT_T4_STAGE_PROFILE") == "1":
            destination = Path(os.environ["THEHEAT_T4_PROFILE_ROOT"])
            if not destination.is_absolute() or destination.is_symlink():
                raise ValueError("fixed diagnostic directory required")
            destination.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (destination / "attempt").open("x") as marker:
                marker.write("consumed\n")
                marker.flush()
                os.fsync(marker.fileno())
            fd, name = tempfile.mkstemp(prefix="saved-revision-deterministic-", suffix=".prof", dir=directory)
            os.close(fd)
            profile = Path(name)
            case["_t4_saved_revision_profile"] = profile
    except Exception:
        destination = None  # Consumed attempts are never reopened or overwritten.
    try:
        yield
    finally:
        case.pop("_t4_saved_revision_profile", None)
        if destination is not None:
            summary = _profile_summary("unavailable")
            try:
                if profile is not None and profile.stat().st_size <= 8_388_608:
                    summary = safe_profile_stats(marshal.loads(profile.read_bytes()))
            except Exception:
                pass  # Missing data remains explicitly unavailable.
            try:
                with (destination / "summary.json").open("x") as stream:
                    json.dump(summary, stream, allow_nan=False)
            except Exception:
                pass  # Preserve the original assertion/timeout/worker exception.


def print_saved_revision_profile():
    """CI prints only a revalidated small summary from its fixed job directory."""
    result = _profile_summary("unavailable")
    try:
        destination = Path(os.environ["THEHEAT_T4_PROFILE_ROOT"])
        if (destination / "attempt").is_file():
            result = _profile_summary("consumed")
        path = destination / "summary.json"
        if path.stat().st_size <= PROFILE_BYTES:
            value = json.loads(path.read_bytes())
            if type(value) is dict and set(value) == {"status", "stage", "profiling_overhead", "rows"} and value["status"] in {"available", "unavailable"} and value["stage"] == PROFILE_STAGE and value["profiling_overhead"] is True and type(value["rows"]) is list and len(value["rows"]) <= 40:
                stats: dict[tuple[str, int, str], tuple[int, int, float, float, dict]] = {}
                for row in value["rows"]:
                    if type(row) is not dict or set(row) != {"file", "line", "function", "primitive_calls", "calls", "self_seconds", "cumulative_seconds"} or type(row["file"]) is not str:
                        raise ValueError("invalid summary")
                    label = row["file"]
                    source = (STDLIB / label[7:] if label.startswith("stdlib/") else
                              SITE / label[5:] if label.startswith("site/") else ROOT / label)
                    if _profile_label(str(source), row["line"], row["function"]) != label:
                        raise ValueError("invalid label")
                    stats[str(source), row["line"], row["function"]] = (row["primitive_calls"], row["calls"], row["self_seconds"], row["cumulative_seconds"], {})
                if len(stats) != len(value["rows"]):
                    raise ValueError("duplicate summary")
                checked = safe_profile_stats(stats)
                if checked["status"] == "available":
                    result = checked if value["status"] == "available" else _profile_summary("unavailable")
    except Exception:
        pass
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    print_saved_revision_profile()
