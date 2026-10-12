"""Offline eligibility checks, not a full GitHub expression interpreter.

Recognize the exact approved predicates from real BaseLoader-parsed YAML and
exercise their event/pause partition. Exact-head CI must still verify GitHub's
syntax, and an existing schedule must establish runtime skipping separately.
"""
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
DAILY = "17 9 * * 1-6"
WEEKLY = "0 9 * * 0"


@pytest.fixture
def workflow():
    return yaml.load((ROOT / ".github/workflows/voice-regression.yml").read_text(), Loader=yaml.BaseLoader)


def eligible(workflow, job, *, paused, event, schedule=None, opted_in="1", same_repo=True,
             action="synchronize", label=None, writer_paths="true", labels=()):
    expression = " ".join(workflow["jobs"][job]["if"].split())
    if job == "changes":
        assert expression == "github.event_name == 'pull_request'"
        return event == "pull_request"
    if job == "canary":
        assert expression == (
            "vars.THEHEAT_PRODUCTION_PAUSED != '1' && github.event_name == 'schedule'"
            " && github.event.schedule == '17 9 * * 1-6'"
        )
        return paused != "1" and event == "schedule" and schedule == DAILY
    assert job == "replay"
    assert expression == (
        "always() && vars.THEHEAT_PRODUCTION_PAUSED != '1' && ("
        " github.event_name == 'workflow_dispatch' ||"
        " (github.event_name == 'schedule' && github.event.schedule == '0 9 * * 0') ||"
        " (github.event_name == 'pull_request' &&"
        " vars.THEHEAT_PAID_PR_REPLAY_ENABLED == '1' &&"
        " github.event.pull_request.head.repo.full_name == github.repository &&"
        " (github.event.action != 'labeled' || github.event.label.name == 'voice-check') &&"
        " (needs.changes.outputs.writer_paths == 'true' ||"
        " contains(github.event.pull_request.labels.*.name, 'voice-check'))) )"
    )
    return paused != "1" and (
        event == "workflow_dispatch"
        or (event == "schedule" and schedule == WEEKLY)
        or (event == "pull_request" and opted_in == "1" and same_repo
            and (action != "labeled" or label == "voice-check")
            and (writer_paths == "true" or "voice-check" in labels))
    )


@pytest.mark.parametrize("paused", [None, "0", "1"])
@pytest.mark.parametrize("context,replay,canary", [
    ({"event": "schedule", "schedule": DAILY}, False, True),
    ({"event": "schedule", "schedule": WEEKLY}, True, False),
    ({"event": "schedule", "schedule": "unrelated schedule"}, False, False),
    ({"event": "workflow_dispatch"}, True, False),
    ({"event": "push"}, False, False),
    ({"event": "pull_request"}, True, False),
    ({"event": "pull_request", "opted_in": "0"}, False, False),
    ({"event": "pull_request", "opted_in": None}, False, False),
    ({"event": "pull_request", "same_repo": False}, False, False),
    ({"event": "pull_request", "writer_paths": "false"}, False, False),
    ({"event": "pull_request", "writer_paths": "false", "labels": ["voice-check"]}, True, False),
    ({"event": "pull_request", "action": "labeled", "label": "voice-check",
      "writer_paths": "false", "labels": ["voice-check"]}, True, False),
    ({"event": "pull_request", "action": "labeled", "label": "unrelated",
      "labels": ["voice-check", "unrelated"]}, False, False),
])
def test_paid_jobs_obey_pause_without_changing_existing_eligibility(workflow, paused, context, replay, canary):
    assert eligible(workflow, "replay", paused=paused, **context) is (replay and paused != "1")
    assert eligible(workflow, "canary", paused=paused, **context) is (canary and paused != "1")
    assert eligible(workflow, "changes", paused=paused, **context) is (context["event"] == "pull_request")


def test_schedule_and_keyless_gate_remain_independent(workflow):
    assert workflow["on"]["schedule"] == [{"cron": DAILY}, {"cron": WEEKLY}]
    assert workflow["on"]["workflow_dispatch"] == {}
    assert workflow["on"]["pull_request"]["types"] == ["opened", "synchronize", "reopened", "labeled"]
    assert workflow["jobs"]["replay"]["needs"] == ["changes"]
    changes = workflow["jobs"]["changes"]
    assert "THEHEAT_PRODUCTION_PAUSED" not in str(changes)
    assert "secrets." not in str(changes)
    assert len(changes["steps"]) == 1
    assert changes["steps"][0]["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "writer_paths=" in changes["steps"][0]["run"]
    assert workflow["concurrency"] == {
        "group": "voice-regression-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}",
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }
    bot = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    assert "THEHEAT_PRODUCTION_PAUSED" not in bot["jobs"]["test-partition"]["if"]


@pytest.mark.parametrize("job", ["replay", "canary"])
def test_pause_guard_precedes_every_step_including_always_canary_gate(workflow, job):
    paid = workflow["jobs"][job]
    assert "vars.THEHEAT_PRODUCTION_PAUSED != '1'" in paid["if"]
    assert paid["steps"][0] == {"uses": "actions/checkout@v6"}
    assert any("secrets.ANTHROPIC_API_KEY" in str(step) for step in paid["steps"])
    assert all("THEHEAT_PRODUCTION_PAUSED" not in str(step) for step in paid["steps"])
    if job == "canary":
        assert paid["steps"][-1]["if"] == "always()"
