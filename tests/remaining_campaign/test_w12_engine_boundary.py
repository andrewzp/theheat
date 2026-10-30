"""W12.5 / W12.6 — one purchase per source revision/event across supported engines.

Pure counterexamples; the PostgreSQL join (prepare/project) is exercised by the
existing Linux-only postgres_sourced_generation suites.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.two_bot.engine_boundary import duplicate_purchases, engine_for, purchase_identity

ROOT = Path(__file__).resolve().parents[2]
BRIEF: dict[str, Any] = {"schema_version": 1, "source_key": "invented_source", "source_revision": "rev-0001",
         "captured_at": "2026-10-29T09:00:00Z", "useful_until": "2026-10-29T21:00:00Z", "urgent": False,
         "bundle": {"signal_kind": "invented_heat", "where": "Invented Vale"}, "save": {"event_id": "invented-event-1"}}


def _brief(**changes):
    value = deepcopy(BRIEF)
    for key, item in changes.items():
        if key == "event_id":
            value["save"]["event_id"] = item
        elif key == "where":
            value["bundle"]["where"] = item
        else:
            value[key] = item
    return value


def test_engine_wording_and_window_do_not_create_a_second_purchase():
    base = purchase_identity(BRIEF)
    assert purchase_identity(_brief(urgent=True)) == base
    assert purchase_identity(_brief(useful_until="2026-10-30T09:00:00Z", where="Invented Vale (reworded)")) == base
    assert purchase_identity(_brief(source_revision="rev-0002")) != base
    assert purchase_identity(_brief(event_id="invented-event-2")) != base


def test_an_urgent_twin_of_a_batch_brief_is_held_on_both_engines():
    values = {"a" * 64: BRIEF, "b" * 64: _brief(urgent=True), "c" * 64: _brief(event_id="invented-event-2")}
    assert duplicate_purchases(values) == {"a" * 64, "b" * 64}
    assert duplicate_purchases({"a" * 64: BRIEF}) == set()


def test_the_named_engine_is_never_switched():
    assert engine_for(BRIEF) == "batch" and engine_for(_brief(urgent=True)) == "synchronous"
    with pytest.raises(ValueError, match="generation_input_invalid"):
        engine_for(_brief(urgent="yes"))


def test_postgres_generation_refuses_before_routing_and_projects_duplicates_blocked():
    source = (ROOT / "src/commands/postgres_sourced_generation.py").read_text()
    prepare = source[source.index("def prepare(authority"):source.index("def runner_identity")]
    guard = prepare.index('"generation_duplicate_engine_purchase"')
    assert guard < prepare.index("if value[\"urgent\"]:") < prepare.index("batch.register(")
    project = source[source.index("def project(authority"):source.index("def candidates(authority")]
    assert project.index("duplicate_purchases") < project.index("current(authority, c, identity, policy, now)")
    assert 'status="blocked"' in project and 'reason="generation_duplicate_engine_purchase"' in project
    # No fallback: an unavailable batch lane raises; it never calls the synchronous engine.
    batch_branch = prepare[prepare.index('job = "gs_"+key'):]
    assert "sync." not in batch_branch and "CommandError(\"generation_window_or_request_invalid\"" in batch_branch
