"""The scheduled completion cannot become a manual posting shortcut."""
from types import SimpleNamespace
import sys

import pytest
import yaml
from pathlib import Path

from scripts import post_collection_sender as sender


def environment():
    return {sender.FLAG: "1", "GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "andrewzp/theheat",
        "GITHUB_WORKFLOW_REF": "andrewzp/theheat/.github/workflows/bot.yml@refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "12345", "THEHEAT_PRODUCTION_PAUSED": "0",
        "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
        "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1", "THEHEAT_WRITER_SAMPLES": "1",
        "THEHEAT_REFILL_ENABLED": "0", "THEHEAT_CRITIC_REVISE_ENABLED": "0"}


def install(monkeypatch, env):
    for key in environment():
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    events = []
    monkeypatch.setattr(sender.time, "sleep", lambda delay: events.append(("sleep", delay)))
    def run(command, **kwargs):
        events.append(("process", command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(sender.subprocess, "run", run)
    return events


@pytest.mark.parametrize("mode", ["alerts", "both"])
def test_one_scheduled_completion_waits_then_invokes_the_unchanged_sender(monkeypatch, mode):
    events = install(monkeypatch, environment())
    assert sender.main(["--mode", mode]) == 0
    assert events == [("sleep", 65), ("process", [sys.executable, "-m", "src.main", "auto_publish_due"], {"check": False})]


def test_verified_automatic_catchup_finishes_the_same_cycle(monkeypatch):
    env = {**environment(), "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "github-actions[bot]", "GITHUB_TRIGGERING_ACTOR": "github-actions[bot]",
        "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1", "THEHEAT_VERIFIED_AUTOMATIC_CATCHUP": "true"}
    events = install(monkeypatch, env)
    assert sender.main(["--mode", "alerts"]) == 0
    assert events == [("sleep", 65), ("process", [sys.executable, "-m", "src.main", "auto_publish_due"], {"check": False})]


@pytest.mark.parametrize("key,value", [
    ("THEHEAT_VERIFIED_AUTOMATIC_CATCHUP", "false"), ("THEHEAT_VERIFIED_AUTOMATIC_CATCHUP", "1"),
    ("THEHEAT_VERIFIED_AUTOMATIC_CATCHUP", ""), ("GITHUB_ACTOR", "invented-person"),
    ("GITHUB_TRIGGERING_ACTOR", "invented-person"), ("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("THEHEAT_PRODUCTION_PAUSED", "1"),
    ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2"), ("THEHEAT_WRITER_SAMPLES", "2"),
    ("THEHEAT_REFILL_ENABLED", "1"), ("THEHEAT_CRITIC_REVISE_ENABLED", "1"),
])
def test_a_proof_label_cannot_bypass_manual_or_existing_completion_limits(monkeypatch, key, value):
    env = {**environment(), "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "github-actions[bot]", "GITHUB_TRIGGERING_ACTOR": "github-actions[bot]",
        "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1", "THEHEAT_VERIFIED_AUTOMATIC_CATCHUP": "true"}
    env[key] = value
    events = install(monkeypatch, env)
    assert sender.main(["--mode", "alerts"]) == 0 and events == []


def test_automatic_catchup_proof_cannot_expand_to_both_or_survive_revocation_during_wait(monkeypatch):
    env = {**environment(), "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "github-actions[bot]", "GITHUB_TRIGGERING_ACTOR": "github-actions[bot]",
        "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1", "THEHEAT_VERIFIED_AUTOMATIC_CATCHUP": "true"}
    events = install(monkeypatch, env)
    assert sender.main(["--mode", "both"]) == 0 and events == []
    monkeypatch.setattr(sender.time, "sleep", lambda delay: monkeypatch.setenv("THEHEAT_VERIFIED_AUTOMATIC_CATCHUP", "false"))
    assert sender.main(["--mode", "alerts"]) == 0 and events == []


@pytest.mark.parametrize("mode", ["metar_report", "observed_report", "manual_tweet", "auto_publish_due", "leaderboard"])
def test_a_different_role_never_waits_or_starts_a_sender(monkeypatch, mode):
    events = install(monkeypatch, environment())
    assert sender.main(["--mode", mode]) == 0 and events == []


@pytest.mark.parametrize("key,value", [
    (sender.FLAG, None), (sender.FLAG, "0"), (sender.FLAG, "true"),
    ("GITHUB_EVENT_NAME", "workflow_dispatch"), ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_REF", "refs/tags/main"), ("GITHUB_REF", "refs/heads/other"),
    ("GITHUB_REPOSITORY", "someone/theheat"), ("GITHUB_WORKFLOW_REF", "other"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_RUN_ID", "unknown"),
    ("THEHEAT_PRODUCTION_PAUSED", "1"), ("THEHEAT_PRODUCTION_PAUSED", "unknown"),
    ("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0"), ("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0"),
    ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "3"), ("THEHEAT_WRITER_SAMPLES", "3"),
    ("THEHEAT_REFILL_ENABLED", "1"), ("THEHEAT_CRITIC_REVISE_ENABLED", "1"),
])
def test_noneligible_context_cannot_be_used_for_recovery_posting(monkeypatch, key, value):
    env = environment()
    if value is None:
        env.pop(key)
    else:
        env[key] = value
    events = install(monkeypatch, env)
    assert sender.main(["--mode", "alerts"]) == 0 and events == []


def test_pause_during_wait_holds_without_starting_the_child(monkeypatch):
    events = install(monkeypatch, environment())
    monkeypatch.setattr(sender.time, "sleep", lambda delay: monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "1"))
    assert sender.main(["--mode", "alerts"]) == 0 and events == []


def test_failed_child_is_not_retried_or_reported_as_success(monkeypatch):
    events = install(monkeypatch, environment())
    def fail(command, **kwargs):
        events.append(("process", command))
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(sender.subprocess, "run", fail)
    assert sender.main(["--mode", "alerts"]) == 7
    assert len(events) == 2


def test_workflow_places_the_sender_after_saved_collection_and_retains_its_environment():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/bot.yml").read_text())
    steps = workflow["jobs"]["run"]["steps"]
    collect = next(i for i, step in enumerate(steps) if step.get("name") == "Run bot")
    step = steps[collect + 1]
    assert step["name"] == "Service due drafts after scheduled collection"
    assert step["env"] == steps[collect]["env"]
    assert step["run"] == 'python -m scripts.post_collection_sender --mode "${{ steps.mode.outputs.mode }}"'
    for condition in ("success()", "github.event_name == 'schedule'", "github.ref == 'refs/heads/main'",
                      "github.run_attempt == '1'", "vars.THEHEAT_POST_COLLECTION_SENDER == '1'",
                      "steps.catchup-reservation.outputs.confirmed == '1'"):
        assert condition in step["if"]
