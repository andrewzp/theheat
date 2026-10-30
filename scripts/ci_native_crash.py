"""Observe a CI pytest SIGSEGV without replaying it or publishing core memory.

Only the held Linux PG2 and PG8 jobs load this CI plugin. The original pytest command,
output, 300-second diagnostic and original job deadline remain unchanged.
Core files stay in a private runner directory and are deleted after one bounded
GDB read. Only sanitized function names, frame counts and statuses reach stdout;
arguments, locals, addresses, environment and raw debugger output never do.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

CORE_LIMIT = 1024 * 1024 * 1024
DEBUGGER_SECONDS = 30
PREFIX = "THEHEAT-NATIVE-CRASH/1 "
# GDB's Python runs only this reviewed observer, never auto-loaded code from a
# core or a neighbouring checkout. It reads frame names, never values or locals.
GDB_PROGRAM = r"""
set pagination off
set confirm off
set auto-load off
set debuginfod enabled off
python
import gdb, re
# Preserve the core's initially selected faulting thread before switching frames.
try:
    faulting = gdb.selected_thread()
except Exception:
    faulting = None
threads = gdb.selected_inferior().threads()[:16]
fault_index = next((index for index, thread in enumerate(threads) if faulting is not None and thread == faulting), None)
print('OBSERVED_SIGNAL ' + str(int(gdb.parse_and_eval('$_siginfo.si_signo'))))
print('FAULTING_THREAD ' + (str(fault_index) if fault_index is not None else 'unavailable'))
for index, thread in enumerate(threads):
    thread.switch()
    frame = gdb.newest_frame()
    for depth in range(32):
        if frame is None:
            break
        name = frame.name() or 'unknown'
        if re.fullmatch(r'[A-Za-z0-9_:<>.~$?+\-]{1,120}', name) is None:
            name = 'unknown'
        print('FRAME ' + str(index) + ' ' + str(depth) + ' ' + name)
        frame = frame.older()
end
"""


def _emit(status: str, **fields: object) -> None:
    print(PREFIX + json.dumps({"status": status, **fields}, sort_keys=True), flush=True)


def _debugger_frames(stdout: bytes) -> list[str]:
    """Only the fixed observer grammar may cross the log boundary."""
    import re

    accepted: list[str] = []
    for raw in stdout[:131072].split(b"\n")[:-1]:
        line = raw.decode("ascii", errors="replace")
        if re.fullmatch(r"OBSERVED_SIGNAL (?:[1-9]|[1-5][0-9]|6[0-4])", line):
            accepted.append(line)
        elif re.fullmatch(r"FAULTING_THREAD (?:[0-9]|1[0-5]|unavailable)", line):
            accepted.append(line)
        elif re.fullmatch(r"FRAME (?:[0-9]|1[0-5]) (?:[0-9]|[12][0-9]|3[01]) [A-Za-z0-9_:<>.~$?+\-]{1,120}", line):
            accepted.append(line)
    return accepted[:514]  # Signal + faulting-thread marker + the unchanged 16 * 32 frame maximum.


def _observe(directory: Path, pid: int, executable: str, debugger: str) -> None:
    core = directory / f"core.{pid}"
    try:
        metadata = core.lstat()
    except FileNotFoundError:
        _emit("core_unavailable")
        return
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1 or metadata.st_size > CORE_LIMIT):
        _emit("core_refused")
        return
    program = directory / "observe.gdb"
    program.write_text(GDB_PROGRAM, encoding="ascii")
    try:
        result = subprocess.run(
            [debugger, "--batch", "--nx", "--nh", "-iex", "set auto-load off",
             "-iex", "set debuginfod enabled off", "--se", executable,
             "--core", str(core), "--command", str(program)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=DEBUGGER_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        _emit("debugger_timed_out")
        return
    frames = _debugger_frames(result.stdout)
    _emit("native_frames", debugger_exit=result.returncode, records=frames,
          core_bytes=metadata.st_size)


def _write(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as output:
        json.dump(value, output, ensure_ascii=True)


def _read(path: Path) -> Any:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1 or metadata.st_size > 8192):
            raise ValueError("private_file_refused")
        return json.loads(source.read(8193))


def _directory(path: Path) -> None:
    metadata = path.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o777 != 0o700 or path.resolve() != path):
        raise ValueError("private_directory_refused")


def prepare(runner_temp: Path, environment_file: Path) -> None:
    """Publish restoration information BEFORE attempting a kernel mutation."""
    if shutil.which("gdb") is None:
        # This CI-only prepare step is guarded to PG2/PG8 in the workflow. Keep the
        # original three native dependency steps and their exact gates intact.
        subprocess.run([
            "sudo", "--non-interactive", "apt-get", "-o", "Acquire::Retries=2",
            "-o", "Acquire::http::Timeout=20", "-o", "Acquire::https::Timeout=20",
            "install", "-y", "--no-install-recommends", "gdb",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True)
        if shutil.which("gdb") is None:
            raise ValueError("debugger_unavailable")
    directory = Path(tempfile.mkdtemp(prefix="theheat-native-", dir=runner_temp))
    _directory(directory)
    if any(character in str(directory) for character in "\n\r%"):
        raise ValueError("private_path_refused")
    previous = Path("/proc/sys/kernel/core_pattern").read_text(encoding="ascii").strip()
    _write(directory / "restore.json", {"directory": str(directory), "previous": previous})
    with environment_file.open("a", encoding="ascii") as output:
        output.write(f"THEHEAT_CI_CORE_DIR={directory}\n")
        plugins = os.environ.get("PYTEST_PLUGINS", "")
        if "\n" in plugins or "\r" in plugins:
            raise ValueError("plugin_configuration_refused")
        plugins = plugins + ("," if plugins else "") + "scripts.ci_native_crash"
        output.write(f"PYTEST_PLUGINS={plugins}\n")
    # A timeout/error is uncertain: the later always() step still restores.
    subprocess.run(["sudo", "--non-interactive", "sysctl", "-w",
                    f"kernel.core_pattern={directory}/core.%p"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=10, check=True)
    _emit("prepared")


def pytest_configure(config: Any) -> None:
    """Record only this selected interpreter; never wrap or replay a test."""
    if sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        return
    try:
        selected = (config.getoption("--ci-partition") == "postgres"
                    and config.getoption("--ci-postgres-shard") in {"2", "8"})
    except ValueError:
        return  # A nested pytest need not load this repository's conftest.
    if not selected:
        return
    directory = Path(os.environ["THEHEAT_CI_CORE_DIR"])
    _directory(directory)
    if (directory / "interpreter.json").exists():
        # PYTEST_PLUGINS is inherited by any nested pytest fixtures. They must
        # neither replace the recorded parent nor fail on its exclusive file.
        _read(directory / "interpreter.json")
        return
    limits = resource.getrlimit(resource.RLIMIT_CORE)
    hard = limits[1]
    limit = CORE_LIMIT if hard == resource.RLIM_INFINITY else min(CORE_LIMIT, hard)
    if limit <= 0:
        raise RuntimeError("core_limit_unavailable")
    resource.setrlimit(resource.RLIMIT_CORE, (limit, hard))
    _write(directory / "interpreter.json", {
        "pid": os.getpid(), "executable": str(Path(sys.executable).resolve()),
    })


def finish(directory: Path, outcome: str) -> int:
    """One optional postmortem; never change the earlier pytest step's result."""
    _directory(directory)
    restore = _read(directory / "restore.json")
    if (type(restore) is not dict or set(restore) != {"directory", "previous"}
            or restore["directory"] != str(directory) or type(restore["previous"]) is not str
            or len(restore["previous"]) > 4096 or "\x00" in restore["previous"]):
        raise ValueError("restoration_refused")
    cleanup_failed = False
    try:
        if outcome == "failure" and (directory / "interpreter.json").exists():
            interpreter = _read(directory / "interpreter.json")
            if (type(interpreter) is not dict or set(interpreter) != {"pid", "executable"}
                    or type(interpreter["pid"]) is not int or interpreter["pid"] <= 0
                    or interpreter["executable"] != str(Path(sys.executable).resolve())):
                raise ValueError("interpreter_refused")
            debugger = shutil.which("gdb")
            if debugger is None:
                raise ValueError("debugger_unavailable")
            try:
                _observe(directory, interpreter["pid"], interpreter["executable"], debugger)
            except Exception:
                _emit("observer_failed")
    finally:
        try:
            subprocess.run(["sudo", "--non-interactive", "sysctl", "-w",
                            f"kernel.core_pattern={restore['previous']}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=True)
        except Exception:
            cleanup_failed = True
        # Never upload cores, including any deliberate child-crash fixture's.
        try:
            for entry in directory.iterdir():
                if not entry.is_dir() or entry.is_symlink():
                    entry.unlink()
            if not cleanup_failed:
                directory.rmdir()
        except OSError:
            cleanup_failed = True
        _emit("finished", test_outcome=outcome, cleanup_failed=cleanup_failed)
    return 2 if cleanup_failed else 0


def main() -> int:
    if sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        _emit("ci_only")
        return 2
    try:
        if sys.argv[1:] == ["prepare"]:
            prepare(Path(os.environ["RUNNER_TEMP"]), Path(os.environ["GITHUB_ENV"]))
            return 0
        if sys.argv[1:] == ["finish"] and os.environ.get("THEHEAT_CI_CORE_DIR"):
            outcome = os.environ.get("THEHEAT_CI_TEST_OUTCOME", "skipped")
            if outcome not in {"success", "failure", "cancelled", "skipped"}:
                raise ValueError("outcome_refused")
            return finish(Path(os.environ["THEHEAT_CI_CORE_DIR"]), outcome)
    except Exception:
        _emit("setup_or_cleanup_failed")
        return 2
    _emit("command_or_configuration_required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
