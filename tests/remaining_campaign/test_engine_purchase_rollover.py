"""Retained purchases outlive the operator's current-input list."""
from copy import deepcopy

import pytest

from src.commands import postgres_sourced_generation as generation
from src.commands.schema import CommandError
from tests.remaining_campaign.test_w12_engine_boundary import BRIEF


class Rows:
    def __init__(self, identities):
        self.identities = identities

    def execute(self, sql, params):
        assert "theheat_projection.fields" in sql
        return self

    def fetchall(self):
        return [(identity,) for identity in self.identities]


@pytest.mark.parametrize("namespace", [generation.JOB, "sourced-sync-job-v1"])
def test_superseded_brief_cannot_buy_same_purchase_under_another_job(monkeypatch, namespace):
    old, new = deepcopy(BRIEF), deepcopy(BRIEF)
    new["urgent"] = True
    monkeypatch.setattr(generation, "read", lambda c, ns, identity: old)
    monkeypatch.setattr(generation, "jobs_for", lambda c, identity, ns: ["old-job"] if ns == namespace else [])
    with pytest.raises(CommandError) as refused:
        generation.retained_purchase_guard(Rows(["old-brief"]), new, "new-brief", "sourced-sync-job-v1", "new-job")
    assert refused.value.code == "generation_duplicate_engine_purchase"


def test_exact_job_replay_is_allowed_but_context_rollover_is_held(monkeypatch):
    monkeypatch.setattr(generation, "read", lambda c, ns, identity: BRIEF)
    monkeypatch.setattr(generation, "jobs_for", lambda c, identity, ns: ["same-job"] if ns == generation.JOB else [])
    generation.retained_purchase_guard(Rows(["same-brief"]), BRIEF, "same-brief", generation.JOB, "same-job")
    with pytest.raises(CommandError):
        generation.retained_purchase_guard(Rows(["same-brief"]), BRIEF, "same-brief", generation.JOB, "changed-job")


def test_unstarted_brief_and_other_event_do_not_claim_purchase(monkeypatch):
    other = deepcopy(BRIEF)
    other["save"]["event_id"] = "other-event"
    monkeypatch.setattr(generation, "read", lambda c, ns, identity: BRIEF if identity == "unstarted" else other)
    monkeypatch.setattr(generation, "jobs_for", lambda c, identity, ns: [] if identity == "unstarted" else ["other-job"])
    generation.retained_purchase_guard(Rows(["unstarted", "other"]), BRIEF, "current", generation.JOB, "current-job")


def test_excessive_retained_matches_refuse_before_reading_any_artifact(monkeypatch):
    monkeypatch.setattr(generation, "read", lambda *args: pytest.fail("unbounded artifact read"))
    with pytest.raises(CommandError) as refused:
        generation.retained_purchase_guard(Rows(list(map(str, range(65)))), BRIEF, "current", generation.JOB, "current-job")
    assert refused.value.code == "generation_purchase_lookup_bound"
