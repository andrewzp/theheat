"""Pin installed queue admission; do not simulate GitHub's scheduler.

GitHub validates the expressions in exact-head PR CI. Provider documentation
defines max's 100-pending limit; these offline checks establish which policy our
actual workflows request, not live capacity, cancellation history or an SLA.
"""
from pathlib import Path

import yaml

from scripts import gen_runtime_report_workflow


ROOT = Path(__file__).resolve().parents[1]
BOT_QUEUE = "${{ github.event_name == 'pull_request' && 'single' || 'max' }}"
EXPECTED = {
    ("bot.yml", "workflow"),
    ("gist-commands.yml", "consume"),
    ("reject-all-drafts.yml", "workflow"),
    ("runtime-report.yml", "workflow"),
}


def _load(path):
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def _producers():
    producers = {}
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = _load(path)
        choices = [("workflow", workflow.get("concurrency", {}))]
        choices.extend((name, job.get("concurrency", {})) for name, job in workflow.get("jobs", {}).items())
        for name, policy in choices:
            if isinstance(policy, dict) and "theheat-bot" in policy.get("group", ""):
                producers[path.name, name] = policy
    return producers


def test_every_installed_shared_producer_has_a_pending_preservation_policy():
    producers = _producers()
    assert set(producers) == EXPECTED, "Review any newly joined or missing producer"
    for identity, policy in producers.items():
        if identity == ("bot.yml", "workflow"):
            assert policy["queue"] == BOT_QUEUE
            assert policy["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
        else:
            assert policy["queue"] == "max", identity
            assert policy["cancel-in-progress"] == "false", identity


def test_generated_report_keeps_the_same_shared_queue_policy():
    rendered = gen_runtime_report_workflow.render()
    assert rendered == (ROOT / ".github/workflows/runtime-report.yml").read_text()
    policy = yaml.load(rendered, Loader=yaml.BaseLoader)["concurrency"]
    assert policy == {
        "group": "${{ vars.THEHEAT_GIST_WRITE_ROUTE == 'serialized' && 'theheat-bot' || 'theheat-runtime-report' }}",
        "cancel-in-progress": "false",
        "queue": "max",
    }
