"""Offline tests for observational metadata; no application, PG or transport imports."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests import delivery_ci_diagnostics as diagnostic
from tests.conftest import _last_check_windows


def check_window():
    return dict(kind="check_window", now="2026-10-22T12:02:01Z",
                lease_expires_at="2026-10-22T12:04:00Z", useful_until="2026-10-23T00:00:00Z",
                lease_remaining_seconds=119.0, available=False, operation="critic", fault="")


def test_check_window_tail_retains_actual_tuple_and_excludes_other_trace_content(tmp_path):
    path = tmp_path / "trace.jsonl"
    windows = [dict(check_window(), lease_remaining_seconds=float(i)) for i in range(12)]
    records = [{"kind": "model_post", "text": "private-text", "token": "private-token"},
               *(dict(row, raw_config="private-config", text="private-text") for row in windows)]
    path.write_text("\n".join(json.dumps(row) for row in records))
    actual = _last_check_windows(path)
    assert actual == [{key: value for key, value in row.items() if key != "kind"} for row in windows[-8:]]
    assert actual[-1]["now"] == "2026-10-22T12:02:01Z" and actual[-1]["available"] is False
    assert "private" not in json.dumps(actual)


def test_check_window_tail_is_byte_bounded_and_skips_malformed_or_unlisted_fields(tmp_path):
    path = tmp_path / "trace.jsonl"
    invalid = [[], dict(check_window(), operation="private-token"), dict(check_window(), fault="private-token"),
               dict(check_window(), now="private-config"), dict(check_window(), available="false"),
               dict(check_window(), lease_remaining_seconds=float("nan")),
               dict(check_window(), lease_remaining_seconds=True)]
    path.write_bytes((json.dumps(dict(check_window(), private="x" * 70_000)) + "\nnot-json\n").encode()
                     + b"\xff\n" + "\n".join(json.dumps(row) for row in [*invalid, check_window()]).encode())
    assert _last_check_windows(path) == [{key: value for key, value in check_window().items() if key != "kind"}]


def test_actual_failed_pytest_report_preserves_failure_and_only_prints_window_whitelist(tmp_path):
    folder = tmp_path / "invented"
    folder.mkdir()
    module = folder / "test_postgres_temperature_delivery.py"
    row = dict(check_window(), raw_config="private-config", text="private-text", token="private-token")
    module.write_text("import json\nimport pytest\n\n@pytest.fixture\ndef compact_case(tmp_path):\n"
                      "    trace = tmp_path / 'trace.jsonl'\n"
                      + "    trace.write_text(" + repr(json.dumps(row) + "\n") + ")\n"
                      "    return {'config': {'trace': str(trace)}}\n\n"
                      "def test_invented_refusal(compact_case):\n    assert False, 'invented refusal'\n")
    result = subprocess.run([sys.executable, "-m", "pytest", str(module), "-q", "--tb=short",
                             "-p", "tests.conftest", "-p", "no:cacheprovider"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
    assert result.returncode == 1 and "1 failed" in result.stdout
    assert "Last check windows" in result.stdout
    assert json.dumps({key: value for key, value in check_window().items() if key != "kind"}, sort_keys=True) in result.stdout
    assert not any(value in result.stdout + result.stderr for value in ("private-config", "private-text", "private-token"))


class FakeTimer:
    def __init__(self, seconds, callback):
        self.seconds, self.callback = seconds, callback
        self.actions = []

    def start(self):
        self.actions.append("start")

    def cancel(self):
        self.actions.append("cancel")

    def join(self):
        self.actions.append("join")


def logger(tmp_path, timer_factory=FakeTimer):
    path = tmp_path / "diagnostic.jsonl"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    return diagnostic.DeliveryDiagnostics(fd, diagnostic.CASES[0], timer_factory=timer_factory), path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_exact_builtin_shapes_exclude_keys_values_and_custom_hooks():
    class HostileMeta(type):
        def __hash__(cls):
            raise AssertionError("class hash hook")

        def __eq__(cls, other):
            raise AssertionError("class equality hook")

    class Hostile(dict, metaclass=HostileMeta):
        def __iter__(self):
            raise AssertionError("iterator hook")

        def __len__(self):
            raise AssertionError("length hook")

        def values(self):
            raise AssertionError("values hook")

        def __repr__(self):
            raise AssertionError("repr hook")

        def __sizeof__(self):
            raise AssertionError("size hook")

    class Key:
        def __repr__(self):
            raise AssertionError("key repr hook")

    shape = diagnostic.shape({Key(): [Hostile(), "secret", b"private", (1, 2.0, None, True)]})
    assert shape["counts"] == dict(dict=1, list=1, tuple=1, str=1, bytes=1, scalar=4, other=1)
    assert shape["string_chars"] == shape["scanned_utf8_bytes"] == 6
    assert shape["bytes_length"] == 7 and shape["partial"] is False
    assert "secret" not in json.dumps(shape) and "private" not in json.dumps(shape)


def test_cycle_and_shared_container_are_not_recursively_traversed():
    shared = ["same"]
    value = [shared, shared]
    value.append(value)
    result = diagnostic.shape(value)
    assert result["nodes"] == 5 and result["repeated_containers"] == 2
    assert result["counts"]["str"] == 1 and result["partial"] is False


def test_wide_and_deep_shapes_report_original_caps_as_partial():
    wide = diagnostic.shape([None] * (diagnostic.MAX_NODES + 20))
    assert wide["nodes"] == diagnostic.MAX_NODES and wide["partial"] is True
    deep = value = []
    for _ in range(100):
        child = []
        value.append(child)
        value = child
    result = diagnostic.shape(deep)
    assert result["max_depth"] == diagnostic.MAX_DEPTH and result["partial"] is True


def test_utf8_scan_has_cumulative_character_bound_and_no_value_output():
    result = diagnostic.shape(["\U0001f30e" * 40_000, "\ud800" * 40_000])
    assert result["string_chars"] == 80_000
    assert result["scanned_utf8_bytes"] == 40_000 * 4 + (65_536 - 40_000) * 3
    assert result["partial"] is True


def test_wrapper_preserves_arguments_return_identity_and_call_pair(tmp_path):
    log, path = logger(tmp_path)
    arg, result = object(), object()
    seen = []

    def actual(value, *, named):
        seen.append((value, named))
        return result

    log.start()
    assert log.wrap("park", actual)(arg, named=arg) is result
    log.close()
    assert seen == [(arg, arg)]
    records = rows(path)
    assert [row["event"] for row in records] == ["started", "phase_begin", "phase_return", "closed"]
    assert records[1]["call"] == records[2]["call"] == 1
    assert log.timer.seconds == 110 and log.timer.actions == ["start", "cancel", "join"]


@pytest.mark.parametrize("error", [RuntimeError("secret"), SystemExit(73), KeyboardInterrupt("private")])
def test_wrapper_rethrows_same_base_exception_without_message(tmp_path, error):
    log, path = logger(tmp_path)

    def actual():
        raise error

    log.start()
    with pytest.raises(type(error)) as failure:
        log.wrap("run", actual)()
    assert failure.value is error
    log.close()
    assert "secret" not in path.read_text() and "private" not in path.read_text()
    assert rows(path)[2]["category"] == ("RuntimeError" if type(error) is RuntimeError else
                                        "SystemExit" if type(error) is SystemExit else "other")


def test_shape_failure_and_write_failure_do_not_change_application_result(tmp_path, monkeypatch):
    log, path = logger(tmp_path)
    result = object()
    log.start()

    def fail(*args, **kwargs):
        raise OSError("must not appear")

    with monkeypatch.context() as patch:
        patch.setattr(diagnostic, "shape", fail)
        assert log.wrap("run", lambda: result)() is result
    with monkeypatch.context() as patch:
        patch.setattr(diagnostic.os, "write", fail)
        assert log.wrap("run", lambda: result)() is result
    log.close()
    assert rows(path)[-1]["partial"] is True and rows(path)[-1]["errors"] == 4
    assert "must not appear" not in path.read_text()


def test_concurrent_calls_have_serialized_records_and_matching_ids(tmp_path):
    log, path = logger(tmp_path)
    log.start()
    wrapped = log.wrap("run", lambda value: value)
    values = [object() for _ in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(wrapped, values)) == values
    log.close()
    records = rows(path)
    begin = {row["call"] for row in records if row["event"] == "phase_begin"}
    end = {row["call"] for row in records if row["event"] == "phase_return"}
    assert begin == end == set(range(1, 13))


@pytest.mark.parametrize("limit", ["events", "bytes"])
def test_output_limits_reserve_truthful_partial_close_record(tmp_path, monkeypatch, limit):
    if limit == "events":
        monkeypatch.setattr(diagnostic, "MAX_EVENTS", 4)
    else:
        monkeypatch.setattr(diagnostic, "MAX_TOTAL_BYTES", 1_600)
    log, path = logger(tmp_path)
    log.start()
    for _ in range(10):
        log.wrap("run", lambda: None)()
    log.close()
    record = rows(path)[-1]
    assert record["event"] == "closed" and record["partial"] is True and record["dropped"] > 0
    assert len(rows(path)) <= diagnostic.MAX_EVENTS
    assert path.stat().st_size <= diagnostic.MAX_TOTAL_BYTES


def test_sample_is_bounded_code_locations_only_no_locals(tmp_path):
    class Frame:
        f_code = SimpleNamespace(co_filename="x.py", co_name="actual")
        f_lineno = 123
        f_back = None

        @property
        def f_locals(self):
            raise AssertionError("no local inspection")

    frame = Frame()
    frame.f_back = frame
    sample = diagnostic.frame_sample(frame)
    assert sample["partial"] is True
    assert len(sample["frames"]) <= diagnostic.MAX_FRAMES
    assert all(row == dict(file="x.py", function="actual", line=123) for row in sample["frames"])
    log, path = logger(tmp_path)
    log.start()
    log.timer.callback()
    log.close()
    real = rows(path)[1]
    assert real["event"] == "main_thread_sample" and real["frames"]
    assert all(set(row) == {"file", "function", "line"} for row in real["frames"])


def test_cancel_join_completes_running_callback_before_descriptor_close(tmp_path):
    entered, release, joined = threading.Event(), threading.Event(), threading.Event()

    class RunningTimer(FakeTimer):
        def start(self):
            def callback():
                entered.set()
                assert release.wait(2)
                self.callback()
            self.thread = threading.Thread(target=callback)
            self.thread.start()

        def join(self):
            self.thread.join()
            joined.set()

    log, path = logger(tmp_path, RunningTimer)
    log.start()
    assert entered.wait(2)
    closing = threading.Thread(target=log.close)
    closing.start()
    assert os.fstat(log.fd) and not joined.is_set()
    release.set()
    closing.join(2)
    assert not closing.is_alive() and joined.is_set()
    with pytest.raises(OSError):
        os.fstat(log.fd)
    assert [row["event"] for row in rows(path)] == ["started", "main_thread_sample", "closed"]
    log.close()  # Closing twice must not close a later descriptor reuse.


def test_duplicate_is_once_noninheritable_and_worker_refuses(tmp_path, monkeypatch):
    path = tmp_path / "dup.jsonl"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    real_dup = os.dup
    calls = []

    def duplicate(source):
        calls.append(source)
        return real_dup(fd)

    monkeypatch.setattr(diagnostic.os, "dup", duplicate)
    log = diagnostic.DeliveryDiagnostics.duplicate_stderr(diagnostic.CASES[0])
    assert calls == [2] and os.get_inheritable(log.fd) is False
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="main thread"):
            pool.submit(diagnostic.DeliveryDiagnostics.duplicate_stderr, diagnostic.CASES[0]).result()
    assert calls == [2]
    log.close()  # No timer was started; must not join an unstarted real Timer.
    os.close(fd)


def test_fixture_is_explicit_last_only_for_three_existing_nodes():
    tree = ast.parse(Path(__file__).with_name("test_postgres_delivery.py").read_text())
    users = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and any(arg.arg == "delivery_diagnostics" for arg in node.args.args)]
    assert {node.name for node in users} == {case.split("[")[0] for case in diagnostic.CASES}
    assert all(node.args.args[-1].arg == "delivery_diagnostics" for node in users)
    fixture = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "delivery_diagnostics")
    assert [ast.unparse(item) for item in fixture.decorator_list] == ["pytest.fixture"]


def test_sample_retains_outer_application_and_test_callers_after_long_copy_stack():
    def frame(filename, function, outer):
        return SimpleNamespace(f_code=SimpleNamespace(co_filename=filename, co_name=function),
                               f_lineno=123, f_back=outer)

    outer_path = "/long-checkout-prefix" * 40 + "/tests/test_postgres_delivery.py"
    stack = frame(outer_path, "test_atomic_approval_five_stages", None)
    stack = frame("src/commands/postgres_editor_media.py", "park", stack)
    for _ in range(180):
        stack = frame("/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/copy.py", "_deepcopy_dict", stack)
    sample = diagnostic.frame_sample(stack)
    assert sample["scanned"] == 182 and sample["omitted"] == 126
    assert sample["truncated"] is False and sample["partial"] is True
    assert sample["fields_truncated"] is True
    assert len(sample["frames"]) == diagnostic.HEAD_FRAMES + diagnostic.TAIL_FRAMES
    assert all(row["function"] == "_deepcopy_dict" for row in sample["frames"][:8])
    assert sample["frames"][-2]["file"] == "src/commands/postgres_editor_media.py"
    assert sample["frames"][-1]["file"].endswith("/tests/test_postgres_delivery.py")
    assert sample["frames"][-1]["function"] == "test_atomic_approval_five_stages"


def test_oversize_worst_escaped_unicode_sample_fits_actual_event_budget(tmp_path):
    frame = SimpleNamespace(f_code=SimpleNamespace(co_filename="\U0001f30e" * 1_000,
                                                  co_name="\U0001f30e" * 1_000),
                            f_lineno=2_147_483_647, f_back=None)
    frame.f_back = frame
    sample = diagnostic.frame_sample(frame)
    assert sample["scanned"] == 1_000 and sample["omitted"] == 944
    assert sample["truncated"] is True and sample["fields_truncated"] is True and sample["partial"] is True
    assert len(sample["frames"]) == 56
    assert all(len(row["file"]) == 128 and len(row["function"]) == 48 for row in sample["frames"])
    log, path = logger(tmp_path)
    log.emit("main_thread_sample", **sample)
    log.close()
    emitted = path.read_bytes().splitlines(keepends=True)
    assert len(emitted) == 2 and len(emitted[0]) <= diagnostic.MAX_EVENT_BYTES
    assert rows(path)[0]["frames"] == sample["frames"]
    assert rows(path)[-1]["dropped"] == 0 and rows(path)[-1]["errors"] == 0


# The profile is a test-only diagnostic, never a source/check acceptance shortcut.
def test_one_actual_profile_child_is_safe_and_consumed_once(tmp_path, monkeypatch, capsys):
    from tests import t4_timing_helpers as timing
    destination = tmp_path / "job"
    monkeypatch.setenv("THEHEAT_T4_STAGE_PROFILE", "1")
    monkeypatch.setenv("THEHEAT_T4_PROFILE_ROOT", str(destination))
    case: dict[str, object] = {}
    with timing.saved_revision_profile(case, tmp_path):
        profile = case.pop("_t4_saved_revision_profile")
        script = tmp_path / "invented-profile-child.py"
        script.write_text("from src.editorial.revisions import fingerprint\n"
            "for _ in range(500): fingerprint({'invented': list(range(50)), 'payload': 'private_payload'})\n"
            "exec(compile('def private_token(): return 1\\nprivate_token()', '/private/private-config.py', 'exec'))\n")
        environment = {"HOME": str(tmp_path), "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
                       "PYTHONPATH": str(timing.ROOT), "LC_ALL": "C", "LANG": "C",
                       "PYTHON_DOTENV_DISABLED": "1", "NETRC": "/dev/null", "no_proxy": "*", "NO_PROXY": "*"}
        child = subprocess.run([sys.executable, "-m", "cProfile", "-o", str(profile), str(script)],
                               cwd=timing.ROOT, env=environment, capture_output=True, text=True, timeout=15)
        assert child.returncode == 0, child.stderr
    value = json.loads((destination / "summary.json").read_text())
    assert value["status"] == "available" and value["profiling_overhead"] is True
    assert any(row["file"] == "src/editorial/revisions.py" and row["function"] == "fingerprint" for row in value["rows"])
    assert 0 < len(value["rows"]) <= 40
    assert not any(private in json.dumps(value) for private in ("private_payload", "private_token", "/private/", str(tmp_path)))
    saved = (destination / "summary.json").read_bytes()
    with timing.saved_revision_profile({}, tmp_path) as ignored:
        assert ignored is None
    assert (destination / "summary.json").read_bytes() == saved
    assert len(list(tmp_path.glob("*.prof"))) == 1
    timing.print_saved_revision_profile()
    assert json.loads(capsys.readouterr().out) == value


def test_profile_flag_off_has_no_effect_and_failure_is_never_swallowed(tmp_path, monkeypatch):
    from tests import t4_timing_helpers as timing
    destination = tmp_path / "job"
    monkeypatch.delenv("THEHEAT_T4_STAGE_PROFILE", raising=False)
    monkeypatch.setenv("THEHEAT_T4_PROFILE_ROOT", str(destination))
    case: dict[str, object] = {}
    with timing.saved_revision_profile(case, tmp_path):
        assert not case and not destination.exists()
    monkeypatch.setenv("THEHEAT_T4_STAGE_PROFILE", "1")
    with pytest.raises(RuntimeError, match="original worker failure"):
        with timing.saved_revision_profile(case, tmp_path):
            assert "_t4_saved_revision_profile" in case
            raise RuntimeError("original worker failure")
    assert "_t4_saved_revision_profile" not in case
    assert (destination / "attempt").read_text() == "consumed\n"
    assert json.loads((destination / "summary.json").read_text())["status"] == "unavailable"


@pytest.mark.parametrize("fault", ["nan", "boolean_count", "negative_time", "extra_summary", "private_label", "oversize"])
def test_profile_print_refuses_malformed_or_private_metadata(tmp_path, monkeypatch, capsys, fault):
    from tests import t4_timing_helpers as timing
    monkeypatch.setenv("THEHEAT_T4_PROFILE_ROOT", str(tmp_path))
    (tmp_path / "attempt").write_text("consumed\n")
    value = timing._profile_summary("available", [{"file": "src/editorial/revisions.py", "line": 45,
        "function": "fingerprint", "primitive_calls": 1, "calls": 1,
        "self_seconds": 0.01, "cumulative_seconds": 0.02}])
    row = value["rows"][0]
    if fault == "nan":
        row["self_seconds"] = float("nan")
    elif fault == "boolean_count":
        row["calls"] = True
    elif fault == "negative_time":
        row["cumulative_seconds"] = -1
    elif fault == "extra_summary":
        value["private_config"] = "private-token"
    elif fault == "private_label":
        row["file"] = "/private/private-token.py"
        row["function"] = "private_token"
    else:
        value["rows"] = [row] * 2000
    (tmp_path / "summary.json").write_text(json.dumps(value))
    timing.print_saved_revision_profile()
    printed = capsys.readouterr().out
    result = json.loads(printed)
    assert result["status"] == "consumed" and result["rows"] == []
    assert "private" not in printed and "NaN" not in printed


def test_profile_keeps_hot_leaves_and_only_known_vendor_labels():
    from tests import t4_timing_helpers as timing
    import inspect
    from src.editorial.revisions import fingerprint
    line = inspect.getsourcelines(fingerprint)[1]
    source = str(timing.ROOT / "src/editorial/revisions.py")
    stats: dict[tuple[str, int, str], tuple[int, int, float, float, dict]] = {(source, line, "fingerprint"): (1, 1, 0.5, 1.0, {}),
             ("/private/private-token.py", 1, "private_token"): (1, 1, 3.0, 3.0, {})}
    result = timing.safe_profile_stats(stats)
    assert result["status"] == "available" and len(result["rows"]) == 1
    assert result["rows"][0]["function"] == "fingerprint"
    assert "private" not in json.dumps(result)
