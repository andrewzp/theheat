"""P00c workflow wiring: offline shape checks, not a GitHub expression interpreter.

Exact-head CI establishes GitHub syntax. These tests recognise only the narrow approved
expression shape ``${{ vars.THEHEAT_GIST_WRITE_ROUTE == 'serialized' && A || B }}`` and
evaluate it for both variable values; they prove legacy keeps every existing default.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
# Released .51 main: the comparison point for "no existing default changed".
BASE = "7d3ad7ce57cd021d7b3919dad42ec402b5c742c2"
WF = ROOT / ".github/workflows"
ROUTE = re.compile(r"\$\{\{ vars\.THEHEAT_GIST_WRITE_ROUTE == 'serialized' && (.+?) \|\| (.+?) \}\}")


def load(text: str) -> dict:
    return yaml.load(text, Loader=yaml.BaseLoader)


def evaluate(expression: str, variable: str) -> str:
    match = ROUTE.fullmatch(expression)
    assert match, f"unexpected route expression shape: {expression}"
    chosen = match[1] if variable == "serialized" else match[2]
    literal = re.fullmatch(r"'([^']*)'", chosen)
    return literal[1] if literal else chosen


def base(path: str) -> dict:
    shown = subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if shown.returncode:
        pytest.skip("released base commit is not in this checkout's history (scratch regeneration copy)")
    return load(shown.stdout)


def test_gist_commands_admits_outside_the_group_and_consumes_inside_it():
    doc = load((WF / "gist-commands.yml").read_text())
    assert set(doc["on"]) == {"workflow_dispatch"} and set(doc["on"]["workflow_dispatch"]["inputs"]) == {"command"}
    assert "concurrency" not in doc and doc["permissions"] == {"contents": "read"}
    admit, consume = doc["jobs"]["admit"], doc["jobs"]["consume"]
    assert "concurrency" not in admit, "admission must never be a cancellable pending group entry"
    step = next(s for s in admit["steps"] if s.get("id") == "admit")
    assert step["env"] == {"THEHEAT_COMMAND_INPUT": "${{ inputs.command }}"} and "inputs." not in step["run"]
    upload = next(s for s in admit["steps"] if s.get("name") == "Upload the immutable admitted command")
    assert upload["with"]["name"] == "theheat-command-${{ steps.admit.outputs.command_id }}"
    assert upload["with"]["retention-days"] == "2" and upload["if"] == "steps.admit.outputs.admitted == 'true'"
    assert consume["needs"] == "admit"
    assert consume["concurrency"] == {"group": "theheat-bot", "cancel-in-progress": "false"}
    assert consume["permissions"] == {"contents": "read", "actions": "write"}
    run = next(s for s in consume["steps"] if s.get("name") == "Consume serially inside theheat-bot")
    assert run["env"]["THEHEAT_SERIALIZED_WRITER"] == "${{ github.run_id }}:consume"
    assert run["env"]["GITHUB_TOKEN"] == "${{ secrets.GH_GIST_TOKEN }}" and run["env"]["GIST_ID"] == "${{ secrets.GIST_ID }}"
    assert run["run"].startswith("node scripts/consume-gist-commands.mjs")
    assert "schedule" not in doc["on"]


def test_bot_drains_only_in_route_mode_and_keeps_every_existing_default():
    doc, old = load((WF / "bot.yml").read_text()), base(".github/workflows/bot.yml")
    for name in ("commands-before", "commands-after"):
        job = doc["jobs"][name]
        assert "vars.THEHEAT_GIST_WRITE_ROUTE == 'serialized'" in job["if"] and "github.event_name != 'pull_request'" in job["if"]
        assert job["permissions"] == {"contents": "read", "actions": "write"}
        assert "concurrency" not in job, "inside bot.yml's workflow-level theheat-bot group"
    assert doc["jobs"]["commands-after"]["needs"] == ["commands-before", "run"]
    assert doc["jobs"]["run"]["needs"] == ["test", "commands-before"]
    assert doc["jobs"]["run"]["if"].startswith("always()")
    # Unchanged: schedules, top-level group, the run job's permissions and every pre-existing env value.
    assert doc["on"]["schedule"] == old["on"]["schedule"] and doc["concurrency"] == old["concurrency"]
    assert doc["jobs"]["run"]["permissions"] == old["jobs"]["run"]["permissions"]
    step = next(s for s in doc["jobs"]["run"]["steps"] if s.get("name") == "Run bot")
    old_step = next(s for s in old["jobs"]["run"]["steps"] if s.get("name") == "Run bot")
    assert {k: v for k, v in step["env"].items() if k in old_step["env"]} == old_step["env"]
    assert set(step["env"]) - set(old_step["env"]) == {"THEHEAT_GIST_WRITE_ROUTE", "THEHEAT_SERIALIZED_WRITER"}
    marker = step["env"]["THEHEAT_SERIALIZED_WRITER"]
    assert evaluate(marker, "") == "" and evaluate(marker, "serialized") == "format('{0}:run', github.run_id)"
    assert set(old["jobs"]) == set(doc["jobs"]) - {"commands-before", "commands-after"}


def test_other_gist_writer_workflows_join_the_group_only_in_route_mode():
    reject, old = load((WF / "reject-all-drafts.yml").read_text()), base(".github/workflows/reject-all-drafts.yml")
    group = reject["concurrency"]["group"]
    assert evaluate(group, "") == old["concurrency"]["group"] == "reject-all-drafts"
    assert evaluate(group, "serialized") == "theheat-bot" and reject["concurrency"]["cancel-in-progress"] == "false"
    assert reject["on"] == old["on"] and reject["jobs"]["reject"]["if"] == old["jobs"]["reject"]["if"]
    from scripts import gen_runtime_report_workflow as generator
    rendered = load(generator.render())
    assert evaluate(rendered["concurrency"]["group"], "") == "theheat-runtime-report"
    assert evaluate(rendered["concurrency"]["group"], "serialized") == "theheat-bot"
    assert rendered["permissions"] == {"contents": "read"}
    # The NHC trial reads the Gist only (no import/PATCH step); it needs no group change.
    trial = (WF / "nhc-advisory-trial.yml").read_text()
    assert "nhc_advisory_import" not in trial and "PATCH" not in trial and "gist edit" not in trial


def test_the_only_new_secret_name_is_the_root_provided_feedback_gist_id():
    secrets = re.compile(r"secrets\.([A-Z0-9_]+)")
    now = set().union(*(set(secrets.findall(path.read_text())) for path in WF.glob("*.yml")))
    listed = subprocess.run(["git", "ls-tree", "--name-only", BASE, ".github/workflows/"], cwd=ROOT, capture_output=True, text=True)
    if listed.returncode:
        pytest.skip("released base commit is not in this checkout's history (scratch regeneration copy)")
    before = set()
    for name in listed.stdout.split():
        before |= set(secrets.findall(subprocess.run(["git", "show", f"{BASE}:{name}"], cwd=ROOT, capture_output=True, text=True).stdout))
    assert now - before == {"THEHEAT_FEEDBACK_GIST_ID"}, "no existing secret renamed; one new root-provided secret"
    assert before <= now
