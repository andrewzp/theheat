"""Invented credential selection and real CLI early-work boundaries.

The expression reader recognises only the old and approved fixed forms; it is
not a general GitHub expression engine or provider authorization test.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from src import state
from src.orchestrator import cli
from tests.real_closure.test_route_writers import FakeGist

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows"
MODE = "vars.THEHEAT_GIST_WRITE_ROUTE"
PAIRS = {"GITHUB_TOKEN": ("THEHEAT_GIST_WRITER_TOKEN", "GH_GIST_TOKEN"),
         "TWITTER_API_KEY": ("THEHEAT_X_API_KEY", "TWITTER_API_KEY"),
         "TWITTER_API_SECRET": ("THEHEAT_X_API_SECRET", "TWITTER_API_SECRET"),
         "TWITTER_ACCESS_TOKEN": ("THEHEAT_X_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN"),
         "TWITTER_ACCESS_SECRET": ("THEHEAT_X_ACCESS_SECRET", "TWITTER_ACCESS_SECRET")}


def load(name):
    return yaml.load((WF / name).read_text(), Loader=yaml.BaseLoader)


def step(doc, job, name):
    return next(s for s in doc["jobs"][job]["steps"] if s.get("name") == name)


def selection(new, old):
    return "${{ (" + MODE + " == 'serialized' && secrets." + new + ") || ((" + MODE + " == '' || " + MODE + " == 'legacy') && secrets." + old + ") || '' }}"


def selected(expression, mode, values):
    old = re.fullmatch(r"\$\{\{ secrets\.([A-Z0-9_]+) \|\| secrets\.([A-Z0-9_]+) \}\}", expression)
    if old:
        return values.get(old[1], "") or values.get(old[2], "")
    direct = re.fullmatch(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}", expression)
    if direct:
        return values.get(direct[1], "")
    refs = re.findall(r"secrets\.([A-Z0-9_]+)", expression)
    assert len(refs) == 2 and expression == selection(*refs), "Unapproved expression shape"
    return values.get(refs[0], "") if mode == "serialized" else values.get(refs[1], "") if mode in ("", "legacy") else ""


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


@pytest.mark.parametrize("filename,job,name", [
    ("bot.yml", "run", "Reserve additional catch-up"),
    ("reject-all-drafts.yml", "reject", "Reject all pending drafts"),
    ("runtime-report.yml", "report", "Publish configuration evidence only"),
])
def test_other_mutating_steps_share_the_same_explicit_choice(filename, job, name):
    assert step(load(filename), job, name)["env"]["GITHUB_TOKEN"] == selection(*PAIRS["GITHUB_TOKEN"])


@pytest.mark.parametrize("filename,job,consume", [
    ("bot.yml", "commands-before", "Drain the command inbox before the run"),
    ("bot.yml", "commands-after", "Drain the command inbox after the final save"),
    ("gist-commands.yml", "consume", "Consume serially inside theheat-bot"),
])
def test_route_only_consumers_and_inbox_never_receive_legacy_fallback(filename, job, consume):
    doc = load(filename)
    fetch = step(doc, job, "Fetch every admitted command artifact")["env"]
    consumer = step(doc, job, consume)["env"]
    assert selected(fetch["THEHEAT_GIST_READ_TOKEN"], "serialized", {"GH_GIST_TOKEN": "invented-old"}) == ""
    assert selected(consumer["GITHUB_TOKEN"], "serialized", {"GH_GIST_TOKEN": "invented-old"}) == ""
    assert consumer["GITHUB_TOKEN"] == "${{ secrets.THEHEAT_GIST_WRITER_TOKEN }}"
    assert consumer["THEHEAT_GIST_CREDENTIAL"] == "${{ secrets.THEHEAT_GIST_WRITER_TOKEN != '' && 'route' || '' }}"


def test_mode_detection_keeps_its_current_gate_but_never_borrows_the_wrong_name():
    expression = step(load("bot.yml"), "run", "Determine mode")["env"]["GH_TOKEN"]
    assert selection(*PAIRS["GITHUB_TOKEN"])[4:-3] in expression
    assert "github.event_name == 'schedule'" in expression
    assert "github.event.schedule == '41 * * * *'" in expression


def test_readonly_workflows_and_secret_name_set_are_unchanged():
    names = set()
    old_names = set()
    for p in WF.glob('*.yml'):
        before = subprocess.check_output(['git','show','c54f1311:'+str(p.relative_to(ROOT))],cwd=ROOT,text=True)
        names.update(re.findall(r'secrets\.([A-Z0-9_]+)', p.read_text()))
        old_names.update(re.findall(r'secrets\.([A-Z0-9_]+)', before))
        if p.name in {'source-health-sentinel.yml','voice-regression.yml','fresh-sample-trial.yml','nhc-advisory-trial.yml'}:
            assert p.read_text() == before
    assert names == old_names


def test_every_unrelated_workflow_field_and_resource_reference_is_unchanged():
    mutable = {'GITHUB_TOKEN', 'GH_TOKEN', 'THEHEAT_GIST_READ_TOKEN', 'THEHEAT_GIST_CREDENTIAL', *PAIRS}
    def clear_bindings(value):
        if isinstance(value, dict):
            return {k: ({j:v for j,v in item.items() if j not in mutable} if k == 'env' else clear_bindings(item)) for k,item in value.items()}
        if isinstance(value, list):
            return [clear_bindings(v) for v in value]
        return value
    for name in ('bot.yml','gist-commands.yml','reject-all-drafts.yml','runtime-report.yml'):
        old = subprocess.check_output(['git','show','c54f1311:.github/workflows/'+name],cwd=ROOT,text=True)
        assert clear_bindings(load(name)) == clear_bindings(yaml.load(old,Loader=yaml.BaseLoader))


def test_both_missing_serialized_store_settings_cannot_start_the_real_fresh_state_path(monkeypatch, capsys):
    monkeypatch.setattr(state, '_configured_backend', lambda:'gist')
    monkeypatch.setattr(state, 'GIST_ID', '')
    monkeypatch.setattr(state, 'GITHUB_TOKEN', '')
    monkeypatch.setenv('THEHEAT_GIST_WRITE_ROUTE', 'serialized')
    monkeypatch.setenv('THEHEAT_SERIALIZED_WRITER','77:run')
    monkeypatch.setenv('GITHUB_RUN_ID','77')
    monkeypatch.setattr(sys,'argv',['theheat','alerts'])
    calls=[]
    def work(value,**kwargs):
        calls.append('source_and_paid_work')
        return value
    with pytest.raises(SystemExit) as stopped:
        cli.main({'alerts':work})
    assert stopped.value.code == 1 and calls == []
    assert 'serialized_gist_configuration_missing' in capsys.readouterr().out


@pytest.mark.parametrize("gist,token,marker,mode,code", [
    ("", "", "77:run", "serialized", "serialized_gist_configuration_missing"),
    ("invented-gist", "", "77:run", "serialized", "serialized_gist_configuration_missing"),
    ("", "invented-token", "77:run", "serialized", "serialized_gist_configuration_missing"),
    ("invented-gist", "invented-token", "", "serialized", "direct_write_disabled_by_route"),
    ("invented-gist", "invented-token", "78:run", "serialized", "invalid_serialized_writer_marker"),
    ("invented-gist", "invented-token", "77:run", "invalid", "invalid_gist_write_route"),
])
def test_real_cli_refuses_incomplete_route_before_state_or_any_work(monkeypatch, capsys, gist, token, marker, mode, code):
    calls = []
    monkeypatch.setattr(state, '_configured_backend', lambda:'gist')
    monkeypatch.setattr(state, 'GIST_ID', gist)
    monkeypatch.setattr(state, 'GITHUB_TOKEN', token)
    monkeypatch.setenv('THEHEAT_GIST_WRITE_ROUTE',mode)
    monkeypatch.setenv('THEHEAT_SERIALIZED_WRITER',marker)
    monkeypatch.setenv('GITHUB_RUN_ID','77')
    def forbidden():
        calls.append('state_read')
        raise AssertionError('Configuration must refuse before any state/source/paid work')
    monkeypatch.setattr(state,'read_state',forbidden)
    monkeypatch.setattr(sys,'argv',['theheat','auto_publish_due'])
    with pytest.raises(SystemExit) as stop:
        cli.main({'auto_publish_due':lambda value,**kw:calls.append('work')})
    assert stop.value.code == 1 and calls == []
    output = capsys.readouterr().out
    assert code in output and 'invented-token' not in output and 'invented-gist' not in output


@pytest.mark.parametrize('mode',['legacy','serialized'])
def test_existing_actual_gist_cli_read_and_final_save_remain_valid(monkeypatch, mode):
    original = deepcopy(state.DEFAULT_STATE)
    original['publish_ledger']={'invented-unknown':{'phase':'unknown'}}
    fake = FakeGist({'state.json':json.dumps(original)})
    monkeypatch.setattr(state,'_configured_backend',lambda:'gist')
    monkeypatch.setattr(state,'GIST_ID','invented-gist')
    monkeypatch.setattr(state,'GITHUB_TOKEN','invented-not-a-credential')
    monkeypatch.setattr(state.requests,'get',fake.get)
    monkeypatch.setattr(state.requests,'patch',fake.patch)
    monkeypatch.setenv('THEHEAT_GIST_WRITE_ROUTE',mode)
    monkeypatch.setenv('THEHEAT_SERIALIZED_WRITER','77:run' if mode=='serialized' else '')
    monkeypatch.setenv('GITHUB_RUN_ID','77')
    monkeypatch.setenv('THEHEAT_AUTOMATIC_PUBLICATION_ENABLED','0')
    monkeypatch.setattr(sys,'argv',['theheat','auto_publish_due'])
    work=[]
    def dispatch(value,**kwargs):
        work.append(kwargs['current_run']['mode'])
        return value
    cli.main({'auto_publish_due':dispatch})
    assert work == ['auto_publish_due'] and fake.gets == 2 and fake.patches == [['state.json']]
    saved = json.loads(fake.files['state.json'])
    assert saved['publish_ledger'] == original['publish_ledger'] and saved['drafts'] == original['drafts']
