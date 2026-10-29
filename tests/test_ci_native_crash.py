"""Pure CI observer facades: no kernel changes, debugger or crash execution."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import types

import pytest
import yaml

from scripts import ci_native_crash as observer


@pytest.fixture
def facade(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    environment_file = root / "environment"
    calls = []
    state = {"pattern": "|/invented/collector --option $(literal)",
             "setup_error": False, "restore_error": False, "debugger_timeout": False,
             "limit": (0, observer.resource.RLIM_INFINITY)}
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if str(path) == "/proc/sys/kernel/core_pattern":
            pattern = state["pattern"]
            assert isinstance(pattern, str)
            return pattern + "\n"
        return original_read(path, *args, **kwargs)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ["sudo", "--non-interactive", "apt-get"]:
            state["gdb_ready"] = True
            return subprocess.CompletedProcess(command, 0)
        if command[0] == "sudo":
            restoring = command[-1].startswith("kernel.core_pattern=|")
            state["pattern"] = command[-1].partition("=")[2]
            if state["restore_error"] if restoring else state["setup_error"]:
                raise subprocess.TimeoutExpired(command, 10)
            return subprocess.CompletedProcess(command, 0)
        if state["debugger_timeout"]:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, stdout=(
            b"Unfiltered argument=INVENTED_PRIVATE_VALUE\nOBSERVED_SIGNAL 11\n"
            b"FRAME 0 0 dump_frame\nFRAME 0 1 _Py_DumpASCII\n"
            b"FRAME 16 0 forbidden_thread\nFRAME 0 32 forbidden_depth\n"
            b"FRAME 0 2 argument=INVENTED_PRIVATE_VALUE\n"), stderr=b"private error")

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(observer.shutil, "which", lambda x: "/invented/" + x)
    monkeypatch.setattr(observer.resource, "getrlimit", lambda _: state["limit"])
    monkeypatch.setattr(observer.resource, "setrlimit", lambda *args: calls.append(("limit", args)))
    monkeypatch.setattr(observer.subprocess, "run", run)
    monkeypatch.setattr(observer.subprocess, "Popen", lambda *a, **k: pytest.fail("test subprocess"))
    monkeypatch.setattr(observer.sys, "platform", "linux")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)

    def prepare():
        observer.prepare(root, environment_file)
        directory = Path(environment_file.read_text().splitlines()[0].partition("=")[2])
        monkeypatch.setenv("THEHEAT_CI_CORE_DIR", str(directory))
        return directory

    config = types.SimpleNamespace(getoption=lambda name: {
        "--ci-partition": "postgres", "--ci-postgres-shard": "2"}[name])
    return root, environment_file, calls, state, prepare, config


def rows(capsys):
    lines = capsys.readouterr().out.splitlines()
    assert all(line.startswith(observer.PREFIX) for line in lines)
    assert "INVENTED_PRIVATE_VALUE" not in "\n".join(lines)
    return [json.loads(line[len(observer.PREFIX):]) for line in lines]


def test_uncertain_kernel_write_already_has_restoration_information(facade, monkeypatch, capsys):
    root, environment_file, calls, state, prepare, _ = facade
    state["setup_error"] = True
    with pytest.raises(subprocess.TimeoutExpired):
        prepare()
    directory = Path(environment_file.read_text().splitlines()[0].partition("=")[2])
    assert directory.stat().st_mode & 0o777 == 0o700
    assert observer.finish(directory, "skipped") == 0
    assert state["pattern"] == "|/invented/collector --option $(literal)"
    assert len([command for command, _ in calls if isinstance(command, list)]) == 2
    assert not directory.exists()
    assert rows(capsys)[-1]["test_outcome"] == "skipped"


def test_plugin_records_only_the_real_interpreter_before_any_test(facade, capsys):
    _, _, calls, _, prepare, config = facade
    directory = prepare()
    observer.pytest_configure(config)
    identity = observer._read(directory / "interpreter.json")
    assert identity == {"pid": observer.os.getpid(), "executable": str(Path(sys.executable).resolve())}
    assert (directory / "interpreter.json").stat().st_mode & 0o777 == 0o600
    assert [value for name, value in calls if name == "limit"] == [
        (observer.resource.RLIMIT_CORE, (observer.CORE_LIMIT, observer.resource.RLIM_INFINITY))]
    assert observer.finish(directory, "success") == 0
    assert not directory.exists()
    assert rows(capsys)[-1]["test_outcome"] == "success"


def test_missing_debugger_install_is_bounded_and_only_requests_gdb(facade, monkeypatch, capsys):
    _, _, calls, state, prepare, _ = facade
    monkeypatch.setattr(observer.shutil, "which", lambda _: "/invented/gdb" if state.get("gdb_ready") else None)
    directory = prepare()
    installs = [(command, kwargs) for command, kwargs in calls if isinstance(command, list) and "apt-get" in command]
    assert len(installs) == 1
    command, kwargs = installs[0]
    assert command == ["sudo", "--non-interactive", "apt-get", "-o", "Acquire::Retries=2", "-o", "Acquire::http::Timeout=20", "-o", "Acquire::https::Timeout=20", "install", "-y", "--no-install-recommends", "gdb"]
    assert kwargs["timeout"] == 120 and kwargs["check"] is True
    assert observer.finish(directory, "skipped") == 0
    rows(capsys)


def test_prepare_preserves_existing_plugins_and_exports_only_to_pg2(facade, monkeypatch, capsys):
    # Retain this original PG2 node; the separate PG8 cases cover the new scope.
    _, environment, _, _, prepare, _ = facade
    monkeypatch.setenv("PYTEST_PLUGINS", "invented_existing")
    directory = prepare()
    assert environment.read_text().splitlines() == [
        f"THEHEAT_CI_CORE_DIR={directory}",
        "PYTEST_PLUGINS=invented_existing,scripts.ci_native_crash",
    ]
    assert observer.finish(directory, "skipped") == 0
    rows(capsys)


@pytest.mark.parametrize("outcome", ["success", "cancelled", "skipped"])
def test_nonfailure_never_invokes_debugger_and_removes_all_private_cores(facade, capsys, outcome):
    _, _, calls, _, prepare, config = facade
    directory = prepare()
    observer.pytest_configure(config)
    (directory / f"core.{observer.os.getpid()}").write_bytes(b"invented, not a core")
    (directory / "core.9999").write_bytes(b"unrelated invented core")
    assert observer.finish(directory, outcome) == 0
    assert not any(command[0] == "/invented/gdb" for command, _ in calls if isinstance(command, list))
    assert not directory.exists()
    assert rows(capsys)[-1] == {"status": "finished", "test_outcome": outcome, "cleanup_failed": False}


def test_only_owned_pid_core_is_observed_once_with_no_private_output(facade, capsys):
    _, _, calls, _, prepare, config = facade
    directory = prepare()
    observer.pytest_configure(config)
    owned = directory / f"core.{observer.os.getpid()}"
    owned.write_bytes(b"invented, not a core")
    (directory / "core.9999").write_bytes(b"unrelated")
    assert observer.finish(directory, "failure") == 0
    gdb_calls = [(command, kwargs) for command, kwargs in calls if isinstance(command, list) and command[0] == "/invented/gdb"]
    assert len(gdb_calls) == 1
    command, kwargs = gdb_calls[0]
    assert command[command.index("--core") + 1] == str(owned)
    assert command[command.index("--se") + 1] == str(Path(sys.executable).resolve())
    assert "--nx" in command and "--nh" in command
    assert command.count("set auto-load off") == command.count("set debuginfod enabled off") == 1
    assert kwargs["timeout"] == 30
    emitted = rows(capsys)
    assert emitted[1]["records"] == ["OBSERVED_SIGNAL 11", "FRAME 0 0 dump_frame", "FRAME 0 1 _Py_DumpASCII"]
    assert not directory.exists()


@pytest.mark.parametrize("kind", ["missing", "timeout", "symlink", "hardlink"])
def test_unavailable_or_unsafe_native_evidence_is_explicit_and_not_a_test_pass(facade, capsys, kind):
    root, _, _, state, prepare, config = facade
    directory = prepare()
    observer.pytest_configure(config)
    core = directory / f"core.{observer.os.getpid()}"
    if kind != "missing":
        if kind == "symlink":
            outside = root / "unrelated"
            outside.write_bytes(b"preserve")
            core.symlink_to(outside)
        else:
            core.write_bytes(b"invented")
        if kind == "hardlink":
            observer.os.link(core, directory / "core.other")
        if kind == "timeout":
            state["debugger_timeout"] = True
    assert observer.finish(directory, "failure") == 0
    emitted = rows(capsys)
    assert emitted[1]["status"] == {"missing": "core_unavailable", "timeout": "debugger_timed_out", "symlink": "core_refused", "hardlink": "core_refused"}[kind]
    assert emitted[-1]["test_outcome"] == "failure"
    assert not directory.exists()
    if kind == "symlink":
        assert outside.read_bytes() == b"preserve"


def test_restoration_failure_removes_memory_and_refuses_clean_observer_status(facade, capsys):
    _, _, _, state, prepare, _ = facade
    directory = prepare()
    (directory / "core.9999").write_bytes(b"invented")
    state["restore_error"] = True
    assert observer.finish(directory, "success") == 2
    assert directory.exists() and list(directory.iterdir()) == []
    assert rows(capsys)[-1]["cleanup_failed"] is True


@pytest.mark.parametrize("field,value", [("--ci-partition", "core"), ("--ci-postgres-shard", "3")])
def test_plugin_cannot_run_in_other_jobs(facade, capsys, field, value):
    _, _, _, _, prepare, _ = facade
    directory = prepare()
    config = types.SimpleNamespace(getoption=lambda name: value if name == field else {"--ci-partition": "postgres", "--ci-postgres-shard": "2"}[name])
    observer.pytest_configure(config)
    assert not (directory / "interpreter.json").exists()
    assert observer.finish(directory, "skipped") == 0
    rows(capsys)


def test_inherited_nested_pytest_cannot_replace_the_parent_identity(facade, monkeypatch, capsys):
    _, _, calls, _, prepare, config = facade
    directory = prepare()
    observer.pytest_configure(config)
    original = (directory / "interpreter.json").read_bytes()
    monkeypatch.setattr(observer.os, "getpid", lambda: 987654321)
    observer.pytest_configure(config)
    assert (directory / "interpreter.json").read_bytes() == original
    assert sum(name == "limit" for name, _ in calls) == 1
    assert observer.finish(directory, "success") == 0
    rows(capsys)


def test_zero_hard_limit_is_refused_before_recording_a_test_identity(facade, capsys):
    _, _, _, state, prepare, config = facade
    directory = prepare()
    state["limit"] = (0, 0)
    with pytest.raises(RuntimeError, match="core_limit_unavailable"):
        observer.pytest_configure(config)
    assert not (directory / "interpreter.json").exists()
    assert observer.finish(directory, "failure") == 0
    rows(capsys)


@pytest.mark.parametrize("change", ["pid", "executable"])
def test_changed_interpreter_identity_refuses_debugger_but_still_restores(facade, capsys, change):
    _, _, calls, state, prepare, config = facade
    directory = prepare()
    observer.pytest_configure(config)
    identity = directory / "interpreter.json"
    value = json.loads(identity.read_text())
    value[change] = True if change == "pid" else "/invented/another-python"
    identity.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="interpreter_refused"):
        observer.finish(directory, "failure")
    assert not any(command[0] == "/invented/gdb" for command, _ in calls if isinstance(command, list))
    assert state["pattern"].startswith("|/invented/")
    assert not directory.exists()
    rows(capsys)


def test_private_metadata_symlinks_and_linked_directories_are_refused(facade, capsys):
    root, _, _, _, prepare, _ = facade
    directory = prepare()
    linked = root / "linked"
    linked.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="private_directory_refused"):
        observer.finish(linked, "failure")
    linked.unlink()
    linked.symlink_to(directory / "restore.json")
    with pytest.raises(OSError):
        observer._read(linked)
    assert observer.finish(directory, "skipped") == 0
    rows(capsys)


def test_debugger_program_bounds_every_field_without_arguments(monkeypatch, capsys):
    class Frame:
        def name(self):
            return "private\nFRAME 0 0 injection"

        def older(self):
            return self

    class Thread:
        def switch(self):
            pass

    fake = types.SimpleNamespace(
        selected_inferior=lambda: types.SimpleNamespace(threads=lambda: [Thread()] * 20),
        newest_frame=Frame, parse_and_eval=lambda expression: 11 if expression == "$_siginfo.si_signo" else pytest.fail(expression),
    )
    monkeypatch.setitem(sys.modules, "gdb", fake)
    program = observer.GDB_PROGRAM.split("python\n", 1)[1].rsplit("\nend", 1)[0]
    exec(program, {})
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 513 and lines[0] == "OBSERVED_SIGNAL 11"
    assert lines[-1] == "FRAME 15 31 unknown"
    assert all(line.endswith("unknown") for line in lines[1:])


def test_log_grammar_refuses_values_addresses_paths_and_partial_records():
    data = b"FRAME 0 0 okay\nFRAME 0 1 token=private\nFRAME 0 2 /tmp/path\n0xdeadbeef\n"
    assert observer._debugger_frames(data) == ["FRAME 0 0 okay"]
    assert observer._debugger_frames(b"FRAME 0 0 partial") == []
    assert len(observer._debugger_frames(b"FRAME 0 0 okay\n" * 10000)) == 513


def test_ci_guard_prevents_any_local_replay(monkeypatch, capsys):
    monkeypatch.setattr(observer.sys, "platform", "darwin")
    monkeypatch.setattr(observer, "prepare", lambda *args: pytest.fail("local native preparation"))
    assert observer.main() == 2
    assert rows(capsys) == [{"status": "ci_only"}]


def test_original_suite_string_and_matrix_remain_exact():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/bot.yml").read_text())
    job = workflow["jobs"]["test-partition"]
    assert job["timeout-minutes"] == 35
    assert len(job["strategy"]["matrix"]["include"]) == 14
    suite = next(step for step in job["steps"] if step.get("run", "").startswith("python -m pytest tests/ -v "))
    assert suite["run"] == 'python -m pytest tests/ -v -m "not voice_replay" --ci-partition=${{ matrix.partition }} --ci-postgres-shard=${{ matrix.postgres-shard }} --ci-critical-first --maxfail=1 --durations=20 -o faulthandler_timeout=300'
    assert "continue-on-error" not in suite
    assert suite["env"] == {"THEHEAT_TEST_POSTGRES": "1", "THEHEAT_POSTGRES_BINDIR": "/usr/lib/postgresql/17/bin"}
    prepare = next(step for step in job["steps"] if step.get("name") == "Prepare private PG2/PG8 crash evidence")
    assert prepare["if"] == "matrix.partition == 'postgres' && (matrix.postgres-shard == '2' || matrix.postgres-shard == '8')"
    assert prepare["timeout-minutes"] == 3
    cleanup = next(step for step in job["steps"] if step.get("name") == "Observe and remove private PG2/PG8 crash evidence")
    assert cleanup["if"] == "always() && matrix.partition == 'postgres' && (matrix.postgres-shard == '2' || matrix.postgres-shard == '8') && env.THEHEAT_CI_CORE_DIR != ''"
    assert cleanup["timeout-minutes"] == 2
    assert cleanup["env"]["THEHEAT_CI_TEST_OUTCOME"] == "${{ steps.offline-suite.outcome }}"
    assert workflow["jobs"]["test"]["needs"] == "test-partition"


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_pg8_records_its_owned_interpreter_and_keeps_original_outcome(facade, capsys, outcome):
    _, _, calls, _, prepare, _ = facade
    directory = prepare()
    config = types.SimpleNamespace(getoption=lambda name: {
        "--ci-partition": "postgres", "--ci-postgres-shard": "8"}[name])
    observer.pytest_configure(config)
    identity = observer._read(directory / "interpreter.json")
    assert identity == {"pid": observer.os.getpid(), "executable": str(Path(sys.executable).resolve())}
    (directory / f"core.{identity['pid']}").write_bytes(b"invented, not a core")
    assert observer.finish(directory, outcome) == 0
    debugger = [command for command, _ in calls if isinstance(command, list)
                and command[0] == "/invented/gdb"]
    assert len(debugger) == (1 if outcome == "failure" else 0)
    assert not directory.exists()
    assert rows(capsys)[-1] == {"status": "finished", "test_outcome": outcome, "cleanup_failed": False}


@pytest.mark.parametrize("shard", ["0", "1", "4", "5", "6", "7", "all"])
def test_unselected_postgres_shards_cannot_record_a_crash_identity(facade, capsys, shard):
    _, _, calls, _, prepare, _ = facade
    directory = prepare()
    config = types.SimpleNamespace(getoption=lambda name: {
        "--ci-partition": "postgres", "--ci-postgres-shard": shard}[name])
    observer.pytest_configure(config)
    assert not (directory / "interpreter.json").exists()
    assert not any(name == "limit" for name, _ in calls)
    assert observer.finish(directory, "skipped") == 0
    assert not directory.exists()
    assert rows(capsys)[-1]["test_outcome"] == "skipped"
