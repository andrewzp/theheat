"""P00c workflow wiring: offline shape checks, not a GitHub expression interpreter.

Exact-head CI establishes GitHub syntax. These tests recognise only the narrow approved
expression shape ``${{ vars.THEHEAT_GIST_WRITE_ROUTE == 'serialized' && A || B }}`` and
evaluate it for both variable values; they prove legacy keeps every existing default.

v2 (ROUTE-CONTRACT-v2, deliberate expectation changes): the Gist writer and sender credentials are
read from route-era secret names first (``secrets.NEW || secrets.OLD``, identical to today while NEW is
unset); consume/drain jobs export the writer-name and legacy-name-presence booleans and the seal key;
bot.yml titles manual_tweet runs by publish intent; admission refusal markers use an exact name.
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
# Legacy secret name -> its route-era name (ROUTE-CONTRACT-v2 §6).
RENAMED = {"GH_GIST_TOKEN": "THEHEAT_GIST_WRITER_TOKEN", "TWITTER_API_KEY": "THEHEAT_X_API_KEY",
           "TWITTER_API_SECRET": "THEHEAT_X_API_SECRET", "TWITTER_ACCESS_TOKEN": "THEHEAT_X_ACCESS_TOKEN",
           "TWITTER_ACCESS_SECRET": "THEHEAT_X_ACCESS_SECRET", "BLUESKY_HANDLE": "THEHEAT_BLUESKY_HANDLE",
           "BLUESKY_APP_PASSWORD": "THEHEAT_BLUESKY_APP_PASSWORD"}
PRESENCE = "${{ " + " || ".join(f"secrets.{name} != ''" for name in RENAMED) + " }}"
ROUTE_DRAIN_ENV = {
    "GITHUB_TOKEN": "${{ secrets.THEHEAT_GIST_WRITER_TOKEN || secrets.GH_GIST_TOKEN }}",
    "THEHEAT_GIST_CREDENTIAL": "${{ secrets.THEHEAT_GIST_WRITER_TOKEN != '' && 'route' || 'legacy' }}",
    "THEHEAT_LEGACY_CREDENTIALS_PRESENT": PRESENCE,
    "THEHEAT_COMMAND_SEAL_KEY": "${{ secrets.THEHEAT_COMMAND_SEAL_KEY }}",
    "THEHEAT_ROUTE_CONTROL_KEY": "${{ secrets.THEHEAT_ROUTE_CONTROL_KEY }}",
}


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
    # Review P3-1/P2-1: admission also receives the configured key ids (non-secret variables).
    assert step["env"] == {"THEHEAT_COMMAND_INPUT": "${{ inputs.command }}", "THEHEAT_COMMAND_SEAL_KID": "${{ vars.THEHEAT_COMMAND_SEAL_KID }}",
                           "THEHEAT_ROUTE_CONTROL_KID": "${{ vars.THEHEAT_ROUTE_CONTROL_KID }}"} and "inputs." not in step["run"]
    upload = next(s for s in admit["steps"] if s.get("name") == "Upload the immutable admitted command")
    assert upload["with"]["name"] == "theheat-command-${{ steps.admit.outputs.command_id }}"
    marker = next(s for s in admit["steps"] if s.get("name") == "Upload the admission refusal marker")
    assert marker["with"]["name"] == "theheat-admission-refused-${{ steps.admit.outputs.command_id }}", "exact-name status lookup"
    assert all("secrets." not in str(step) for step in admit["steps"]), "admission holds no key or token"
    assert upload["with"]["retention-days"] == "2" and upload["if"] == "steps.admit.outputs.admitted == 'true'"
    assert consume["needs"] == "admit"
    assert consume["concurrency"] == {"group": "theheat-bot", "cancel-in-progress": "false"}
    assert consume["permissions"] == {"contents": "read", "actions": "write"}
    fetch = next(s for s in consume["steps"] if s.get("name") == "Fetch every admitted command artifact")
    # Root checkpoint R1 (deliberate): the inbox reads the consumer's settled-run continuation (read only).
    assert fetch["env"] == {"GH_TOKEN": "${{ github.token }}", "THEHEAT_REPOSITORY": "${{ github.repository }}",
                            "GIST_ID": "${{ secrets.GIST_ID }}",
                            "THEHEAT_GIST_READ_TOKEN": "${{ secrets.THEHEAT_GIST_WRITER_TOKEN || secrets.GH_GIST_TOKEN }}"}
    run = next(s for s in consume["steps"] if s.get("name") == "Consume serially inside theheat-bot")
    assert run["env"]["THEHEAT_SERIALIZED_WRITER"] == "${{ github.run_id }}:consume"
    assert {key: run["env"][key] for key in ROUTE_DRAIN_ENV} == ROUTE_DRAIN_ENV and run["env"]["GIST_ID"] == "${{ secrets.GIST_ID }}"
    assert run["run"].startswith("node scripts/consume-gist-commands.mjs")
    assert "schedule" not in doc["on"]


def test_bot_drains_only_in_route_mode_and_keeps_every_existing_default():
    doc, old = load((WF / "bot.yml").read_text()), base(".github/workflows/bot.yml")
    for name in ("commands-before", "commands-after"):
        job = doc["jobs"][name]
        assert "vars.THEHEAT_GIST_WRITE_ROUTE == 'serialized'" in job["if"] and "github.event_name != 'pull_request'" in job["if"]
        assert job["permissions"] == {"contents": "read", "actions": "write"}
        assert "concurrency" not in job, "inside bot.yml's workflow-level theheat-bot group"
        drain = job["steps"][-1]
        assert drain["run"].startswith("node scripts/consume-gist-commands.mjs")
        assert {key: drain["env"][key] for key in ROUTE_DRAIN_ENV} == ROUTE_DRAIN_ENV
    assert doc["jobs"]["commands-after"]["needs"] == ["commands-before", "run"]
    assert doc["jobs"]["run"]["needs"] == ["test", "commands-before"]
    assert doc["jobs"]["run"]["if"].startswith("always()")
    # The schedule stagger changes only minutes. Keep every slot and all other cron fields.
    expected_schedules = [
        {**entry, "cron": f"{minute} {entry['cron'].split(' ', 1)[1]}"}
        for entry, minute in zip(old["on"]["schedule"], ("41", "11", "11"), strict=True)
    ]
    assert doc["on"]["schedule"] == expected_schedules
    assert doc["concurrency"] == old["concurrency"]
    assert doc["jobs"]["run"]["permissions"] == old["jobs"]["run"]["permissions"]
    step = next(s for s in doc["jobs"]["run"]["steps"] if s.get("name") == "Run bot")
    old_step = next(s for s in old["jobs"]["run"]["steps"] if s.get("name") == "Run bot")
    # Every pre-existing value is unchanged except the seven credentials, which read the route-era
    # NAME first and otherwise exactly the old secret (identical while the new name is unset).
    renamed = {"GITHUB_TOKEN": "GH_GIST_TOKEN", **{name: name for name in RENAMED if name != "GH_GIST_TOKEN"}}
    for env_key, legacy in renamed.items():
        assert old_step["env"][env_key] == "${{ secrets.%s }}" % legacy
        assert step["env"][env_key] == "${{ secrets.%s || secrets.%s }}" % (RENAMED[legacy], legacy)
    # The opt-in station selector retains the exact old default.
    assert old_step["env"]["THEHEAT_SIGNALS_PROVIDER"] == "both"
    assert step["env"]["THEHEAT_SIGNALS_PROVIDER"] == "${{ vars.THEHEAT_SIGNALS_PROVIDER || 'both' }}"
    checked = {*renamed, "THEHEAT_SIGNALS_PROVIDER"}
    assert {k: v for k, v in step["env"].items() if k in old_step["env"] and k not in checked} == \
        {k: v for k, v in old_step["env"].items() if k not in checked}
    assert doc["run-name"] == ("${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'manual_tweet' && "
                               "format('theheat-bot manual_tweet {0}', inputs.publish_intent_id) || ' ' }}") and "run-name" not in old
    # Composed candidate: the route adds exactly its two keys; the Hot10 product selector is the
    # supply stream's own mirror (legacy default, asserted by its own tests). Nothing else is new.
    # Root checkpoint R2 (deliberate): + the route sender's text source (references-only dispatch).
    assert set(step["env"]) - set(old_step["env"]) == {"THEHEAT_GIST_WRITE_ROUTE", "THEHEAT_SERIALIZED_WRITER",
                                                       "THEHEAT_HOT10_NORMALS_PRODUCT", "THEHEAT_SENDER_TEXT_SOURCE"}
    assert step["env"]["THEHEAT_SENDER_TEXT_SOURCE"] == "${{ github.event.inputs.text_source }}"
    assert set(doc["on"]["workflow_dispatch"]["inputs"]) - set(old["on"]["workflow_dispatch"]["inputs"]) == {"text_source"}
    assert step["env"]["THEHEAT_HOT10_NORMALS_PRODUCT"] == "${{ vars.THEHEAT_HOT10_NORMALS_PRODUCT || 'meteostat-normals-point-v1' }}"
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


def test_new_secret_names_are_exactly_the_root_provided_route_era_names():
    secrets = re.compile(r"secrets\.([A-Z0-9_]+)")
    now = set().union(*(set(secrets.findall(path.read_text())) for path in WF.glob("*.yml")))
    listed = subprocess.run(["git", "ls-tree", "--name-only", BASE, ".github/workflows/"], cwd=ROOT, capture_output=True, text=True)
    if listed.returncode:
        pytest.skip("released base commit is not in this checkout's history (scratch regeneration copy)")
    before = set()
    for name in listed.stdout.split():
        before |= set(secrets.findall(subprocess.run(["git", "show", f"{BASE}:{name}"], cwd=ROOT, capture_output=True, text=True).stdout))
    assert now - before == {"THEHEAT_FEEDBACK_GIST_ID", "THEHEAT_COMMAND_SEAL_KEY", "THEHEAT_ROUTE_CONTROL_KEY", *RENAMED.values()}, \
        "root-provided: feedback Gist id, seal key, route-control key and the route-era names of the seven legacy credentials"
    assert before <= now
    # Every remaining legacy reference is a NEW || OLD fallback or a presence boolean (never alone),
    # except the generated runtime-report workflow, which the generator rebuilds from bot.yml.
    for path in WF.glob("*.yml"):
        if path.name == "runtime-report.yml":
            continue
        for line in path.read_text().splitlines():
            for name in RENAMED:
                if f"secrets.{name}" in line:
                    assert f"secrets.{RENAMED[name]} || secrets.{name}" in line or f"secrets.{name} != ''" in line, (path.name, line)
