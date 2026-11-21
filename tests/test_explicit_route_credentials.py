"""Invented credential selection and real CLI early-work boundaries.

The expression reader recognises only the old and approved fixed forms; it is
not a general GitHub expression engine or provider authorization test.
"""

from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest
import yaml

from src import state
from src.commands import gist_route
from src.orchestrator import cli
from tests.real_closure.test_route_writers import FakeGist

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows"
MODE = "steps.route-mode.outputs.mode"
PAIRS = {
    "GITHUB_TOKEN": ("THEHEAT_GIST_WRITER_TOKEN", "GH_GIST_TOKEN"),
    "TWITTER_API_KEY": ("THEHEAT_X_API_KEY", "TWITTER_API_KEY"),
    "TWITTER_API_SECRET": ("THEHEAT_X_API_SECRET", "TWITTER_API_SECRET"),
    "TWITTER_ACCESS_TOKEN": ("THEHEAT_X_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN"),
    "TWITTER_ACCESS_SECRET": ("THEHEAT_X_ACCESS_SECRET", "TWITTER_ACCESS_SECRET"),
}


def load(name):
    return yaml.load((WF / name).read_text(), Loader=yaml.BaseLoader)


def step(doc, job, name):
    return next(s for s in doc["jobs"][job]["steps"] if s.get("name") == name)


def selection(new, old):
    return (
        "${{ ("
        + MODE
        + " == 'serialized' && secrets."
        + new
        + ") || ("
        + MODE
        + " == 'legacy' && secrets."
        + old
        + ") || '' }}"
    )


@lru_cache
def validated_mode(raw):
    with TemporaryDirectory() as directory:
        output = Path(directory) / "output"
        result = subprocess.run(
            [sys.executable, "scripts/gist_route_mode.py"],
            cwd=ROOT,
            env={
                "PATH": os.environ["PATH"],
                "THEHEAT_GIST_WRITE_ROUTE": raw,
                "GITHUB_OUTPUT": str(output),
                "PYTHON_DOTENV_DISABLED": "1",
            },
            capture_output=True,
            text=True,
        )
        if result.returncode:
            assert result.returncode == 1 and (not output.exists() or output.read_text() == "")
            return ""
        data = output.read_text()
        assert data in ("mode=legacy\n", "mode=serialized\n")
        return data[5:-1]


def selected(expression, mode, values):
    mode = validated_mode(mode)
    old = re.fullmatch(r"\$\{\{ secrets\.([A-Z0-9_]+) \|\| secrets\.([A-Z0-9_]+) \}\}", expression)
    if old:
        return values.get(old[1], "") or values.get(old[2], "")
    direct = re.fullmatch(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}", expression)
    if direct:
        return values.get(direct[1], "")
    gated = "${{ steps.route-mode.outputs.mode != '' && secrets.THEHEAT_GIST_WRITER_TOKEN || '' }}"
    if expression == gated:
        return values.get("THEHEAT_GIST_WRITER_TOKEN", "") if mode else ""
    refs = re.findall(r"secrets\.([A-Z0-9_]+)", expression)
    assert len(refs) == 2 and expression == selection(*refs), "Unapproved expression shape"
    # GitHub compares strings without case, but these are the real selector's
    # fixed lowercase enum outputs, never the raw input variable.
    return (
        values.get(refs[0], "")
        if mode.casefold() == "serialized"
        else values.get(refs[1], "")
        if mode.casefold() == "legacy"
        else ""
    )


@pytest.mark.parametrize("mode", ["", "legacy", "serialized", "invalid"])
@pytest.mark.parametrize("new_value", ["", "invented-new"])
@pytest.mark.parametrize("old_value", ["", "invented-old"])
@pytest.mark.parametrize("key", list(PAIRS))
def test_ordinary_bot_names_follow_mode_never_value_fallback(mode, new_value, old_value, key):
    env = step(load("bot.yml"), "run", "Run bot")["env"]
    new, old = PAIRS[key]
    result = selected(env[key], mode, {new: new_value, old: old_value})
    expected = new_value if mode == "serialized" else old_value if mode in ("", "legacy") else ""
    assert result == expected
    assert env[key] == selection(new, old)


@pytest.mark.parametrize(
    "filename,job,name",
    [
        ("bot.yml", "run", "Reserve additional catch-up"),
        ("reject-all-drafts.yml", "reject", "Reject all pending drafts"),
        ("runtime-report.yml", "report", "Publish configuration evidence only"),
    ],
)
def test_other_mutating_steps_share_the_same_explicit_choice(filename, job, name):
    assert step(load(filename), job, name)["env"]["GITHUB_TOKEN"] == selection(
        *PAIRS["GITHUB_TOKEN"]
    )


@pytest.mark.parametrize(
    "filename,job,consume",
    [
        ("bot.yml", "commands-before", "Drain the command inbox before the run"),
        ("bot.yml", "commands-after", "Drain the command inbox after the final save"),
        ("gist-commands.yml", "consume", "Consume serially inside theheat-bot"),
    ],
)
def test_route_only_consumers_and_inbox_never_receive_legacy_fallback(filename, job, consume):
    doc = load(filename)
    fetch = step(doc, job, "Fetch every admitted command artifact")["env"]
    consumer = step(doc, job, consume)["env"]
    assert (
        selected(fetch["THEHEAT_GIST_READ_TOKEN"], "serialized", {"GH_GIST_TOKEN": "invented-old"})
        == ""
    )
    assert selected(consumer["GITHUB_TOKEN"], "serialized", {"GH_GIST_TOKEN": "invented-old"}) == ""
    assert (
        consumer["GITHUB_TOKEN"]
        == "${{ steps.route-mode.outputs.mode != '' && secrets.THEHEAT_GIST_WRITER_TOKEN || '' }}"
    )
    assert (
        consumer["THEHEAT_GIST_CREDENTIAL"]
        == "${{ steps.route-mode.outputs.mode != '' && secrets.THEHEAT_GIST_WRITER_TOKEN != '' && 'route' || '' }}"
    )
    assert (
        selected(consumer["GITHUB_TOKEN"], "legacy", {"THEHEAT_GIST_WRITER_TOKEN": "invented-new"})
        == "invented-new"
    ), "Authenticated deactivation retains its route credential source"


def test_mode_detection_keeps_its_current_gate_but_never_borrows_the_wrong_name():
    expression = step(load("bot.yml"), "run", "Determine mode")["env"]["GH_TOKEN"]
    assert selection(*PAIRS["GITHUB_TOKEN"])[4:-3] in expression
    assert "github.event_name == 'schedule'" in expression
    assert "github.event.schedule == '41 * * * *'" in expression


@pytest.mark.parametrize(
    "filename,jobs",
    [
        ("bot.yml", ["run", "commands-before", "commands-after"]),
        ("gist-commands.yml", ["consume"]),
        ("reject-all-drafts.yml", ["reject"]),
        ("runtime-report.yml", ["report"]),
    ],
)
def test_preflight_is_nonsecret_and_precedes_all_owned_privileged_steps(filename, jobs):
    doc = load(filename)
    for job in jobs:
        steps = doc["jobs"][job]["steps"]
        index = next(i for i, s in enumerate(steps) if s.get("id") == "route-mode")
        validator = steps[index]
        assert validator["env"] == {
            "THEHEAT_GIST_WRITE_ROUTE": "${{ vars.THEHEAT_GIST_WRITE_ROUTE }}"
        }
        assert validator["run"] == "python scripts/gist_route_mode.py"
        assert not {"if", "continue-on-error"} & validator.keys()
        assert "secrets." not in str(validator)
        for i, s in enumerate(steps):
            for key in ("GITHUB_TOKEN", "GH_TOKEN", "THEHEAT_GIST_READ_TOKEN", *PAIRS):
                if key in s.get("env", {}):
                    assert i > index
                    binding = s["env"][key]
                    if binding == "${{ github.token }}":
                        # The repository-scoped artifact token cannot write the
                        # Gist or call X; its existing binding is unchanged.
                        continue
                    assert "steps.route-mode.outputs.mode" in binding


@pytest.mark.parametrize("mode", ["Serialized", "LEGACY", "invalid", "serialized\n"])
def test_unvalidated_mode_never_yields_a_token_in_any_owned_credential_binding(mode):
    env = step(load("bot.yml"), "run", "Run bot")["env"]
    for key, (new, old) in PAIRS.items():
        assert selected(env[key], mode, {new: "invented-new", old: "invented-old"}) == ""


def test_both_missing_serialized_store_settings_cannot_start_the_real_fresh_state_path(
    monkeypatch, capsys
):
    monkeypatch.setattr(state, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(state, "GIST_ID", "")
    monkeypatch.setattr(state, "GITHUB_TOKEN", "")
    monkeypatch.setenv("THEHEAT_GIST_WRITE_ROUTE", "serialized")
    monkeypatch.setenv("THEHEAT_SERIALIZED_WRITER", "77:run")
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    monkeypatch.setattr(sys, "argv", ["theheat", "alerts"])
    calls = []

    def work(value, **kwargs):
        calls.append("source_and_paid_work")
        return value

    with pytest.raises(SystemExit) as stopped:
        cli.main({"alerts": work})
    assert stopped.value.code == 1 and calls == []
    assert "serialized_gist_configuration_missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "gist,token,marker,mode,code",
    [
        ("", "", "77:run", "serialized", "serialized_gist_configuration_missing"),
        ("invented-gist", "", "77:run", "serialized", "serialized_gist_configuration_missing"),
        ("", "invented-token", "77:run", "serialized", "serialized_gist_configuration_missing"),
        ("invented-gist", "invented-token", "", "serialized", "direct_write_disabled_by_route"),
        (
            "invented-gist",
            "invented-token",
            "78:run",
            "serialized",
            "invalid_serialized_writer_marker",
        ),
        ("invented-gist", "invented-token", "77:run", "invalid", "invalid_gist_write_route"),
    ],
)
def test_real_cli_refuses_incomplete_route_before_state_or_any_work(
    monkeypatch, capsys, gist, token, marker, mode, code
):
    calls = []
    monkeypatch.setattr(state, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(state, "GIST_ID", gist)
    monkeypatch.setattr(state, "GITHUB_TOKEN", token)
    monkeypatch.setenv("THEHEAT_GIST_WRITE_ROUTE", mode)
    monkeypatch.setenv("THEHEAT_SERIALIZED_WRITER", marker)
    monkeypatch.setenv("GITHUB_RUN_ID", "77")

    def forbidden():
        calls.append("state_read")
        raise AssertionError("Configuration must refuse before any state/source/paid work")

    monkeypatch.setattr(state, "read_state", forbidden)
    monkeypatch.setattr(sys, "argv", ["theheat", "auto_publish_due"])
    with pytest.raises(SystemExit) as stop:
        cli.main({"auto_publish_due": lambda value, **kw: calls.append("work")})
    assert stop.value.code == 1 and calls == []
    output = capsys.readouterr().out
    assert code in output and "invented-token" not in output and "invented-gist" not in output


@pytest.mark.parametrize("mode", ["legacy", "serialized"])
def test_existing_actual_gist_cli_read_and_final_save_remain_valid(monkeypatch, mode):
    original = deepcopy(state.DEFAULT_STATE)
    original["publish_ledger"] = {"invented-unknown": {"phase": "unknown"}}
    fake = FakeGist({"state.json": json.dumps(original)})
    monkeypatch.setattr(state, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(state, "GIST_ID", "invented-gist")
    monkeypatch.setattr(state, "GITHUB_TOKEN", "invented-not-a-credential")
    monkeypatch.setattr(state.requests, "get", fake.get)
    monkeypatch.setattr(state.requests, "patch", fake.patch)
    monkeypatch.setenv("THEHEAT_GIST_WRITE_ROUTE", mode)
    monkeypatch.setenv("THEHEAT_SERIALIZED_WRITER", "77:run" if mode == "serialized" else "")
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    monkeypatch.setattr(sys, "argv", ["theheat", "auto_publish_due"])
    work = []

    def dispatch(value, **kwargs):
        work.append(kwargs["current_run"]["mode"])
        return value

    cli.main({"auto_publish_due": dispatch})
    assert work == ["auto_publish_due"] and fake.gets == 2 and fake.patches == [["state.json"]]
    saved = json.loads(fake.files["state.json"])
    assert (
        saved["publish_ledger"] == original["publish_ledger"]
        and saved["drafts"] == original["drafts"]
    )


@pytest.mark.parametrize(
    "raw", ["Serialized", "SERIALIZED", "LEGACY", "Legacy", "invalid", " legacy", "serialized\n"]
)
def test_actual_workflow_selector_refuses_unsupported_spellings_before_credentials(raw, tmp_path):
    doc = load("bot.yml")
    bindings = step(doc, "run", "Run bot")["env"]
    expression = bindings["GITHUB_TOKEN"]
    if "vars.THEHEAT_GIST_WRITE_ROUTE" in expression:
        # Model only the documented string equality operator, which ignores case.
        selected_value = (
            "invented-new"
            if raw.casefold() == "serialized"
            else "invented-old"
            if raw.casefold() in ("", "legacy")
            else ""
        )
        assert selected_value == "", (
            "Raw case-insensitive workflow comparison exposed a privileged name"
        )
    preflight = next((s for s in doc["jobs"]["run"]["steps"] if s.get("id") == "route-mode"), None)
    assert preflight is not None, "Missing exact enum preflight"
    output = tmp_path / "step-output"
    output.write_text("")
    result = subprocess.run(
        [sys.executable, "scripts/gist_route_mode.py"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "THEHEAT_GIST_WRITE_ROUTE": raw,
            "GITHUB_OUTPUT": str(output),
            "PYTHON_DOTENV_DISABLED": "1",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and output.read_text() == ""
    assert "invalid_gist_write_route" in result.stderr


@pytest.mark.parametrize(
    "filename,job",
    [
        ("bot.yml", "commands-before"),
        ("bot.yml", "commands-after"),
        ("gist-commands.yml", "consume"),
    ],
)
def test_consumer_validates_exact_mode_before_inbox_without_disabling_legacy_deactivation(
    filename, job
):
    steps = load(filename)["jobs"][job]["steps"]
    index = next((i for i, s in enumerate(steps) if s.get("id") == "route-mode"), None)
    fetch_index = next(
        i for i, s in enumerate(steps) if s.get("name") == "Fetch every admitted command artifact"
    )
    assert index is not None and index < fetch_index
    preflight = steps[index]
    assert preflight["run"] == "python scripts/gist_route_mode.py"
    assert "continue-on-error" not in preflight and "if" not in preflight
    assert preflight["env"] == {"THEHEAT_GIST_WRITE_ROUTE": "${{ vars.THEHEAT_GIST_WRITE_ROUTE }}"}
    assert "if" not in steps[fetch_index], "Inbox must retain default success-only ordering"
    assert "steps.route-mode.outputs.mode" in steps[fetch_index]["env"]["THEHEAT_GIST_READ_TOKEN"]


def test_invalid_backend_keeps_the_existing_bounded_cli_error(monkeypatch, capsys):
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "invented-backend")
    monkeypatch.setattr(sys, "argv", ["theheat", "alerts"])
    with pytest.raises(SystemExit) as stopped:
        cli.main({"alerts": lambda *a, **k: pytest.fail("No work for an invalid backend")})
    assert stopped.value.code == 1
    assert "Unsupported state backend" in capsys.readouterr().out


@pytest.mark.parametrize(
    "raw,expected", [("", "legacy"), ("legacy", "legacy"), ("serialized", "serialized")]
)
def test_exact_mode_helper_emits_only_fixed_runner_output(raw, expected, tmp_path):
    output = tmp_path / "step-output"
    result = subprocess.run(
        [sys.executable, "scripts/gist_route_mode.py"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "THEHEAT_GIST_WRITE_ROUTE": raw,
            "GITHUB_OUTPUT": str(output),
            "PYTHON_DOTENV_DISABLED": "1",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    assert output.read_text() == f"mode={expected}\n"


@pytest.mark.parametrize("output_kind", ["missing", "unavailable"])
def test_mode_helper_refuses_unusable_runner_output(output_kind, tmp_path):
    env = {
        "PATH": os.environ["PATH"],
        "THEHEAT_GIST_WRITE_ROUTE": "serialized",
        "PYTHON_DOTENV_DISABLED": "1",
    }
    if output_kind == "unavailable":
        env["GITHUB_OUTPUT"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "scripts/gist_route_mode.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert f"step_output_{output_kind}" in result.stderr


def test_absent_validated_output_cannot_select_either_credential_arm():
    for new, old in PAIRS.values():
        expression = selection(new, old)
        assert "outputs.mode == 'legacy'" in expression
        assert "outputs.mode == ''" not in expression
        assert "vars.THEHEAT_GIST_WRITE_ROUTE" not in expression
    assert gist_route.configured_mode({"THEHEAT_GIST_WRITE_ROUTE": "legacy"}) == "legacy"
