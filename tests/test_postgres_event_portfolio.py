"""Real retained SQL episodes and NHC HTTP fixtures, never paid/provider transport.

Every storm, source response and editorial judgment is explicitly invented.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import uuid

import pytest
import responses

from src.data import nhc
from src.editorial.portfolio import DIMENSIONS, PortfolioError
from src.orchestrator.cyclone_episodes import plan_episode_portfolio
from src.storage.cyclone_supply import CycloneSupplyError, CycloneSupplySession, digest
from src.storage.physical_events import PhysicalEpisodeSession
from tests import test_postgres_projection as pg
from tests import test_postgres_physical_events as fixtures

BASE, EPISODE, NOW = fixtures.BASE, fixtures.EPISODE, fixtures.NOW
advisory, apply, capture, seed = fixtures.advisory, fixtures.apply, fixtures.capture, fixtures.seed
cluster, database, repository, isolated = fixtures.cluster, fixtures.database, fixtures.repository, fixtures.isolated


def judgments(plan, *, score=4, exceptional=None):
    return [dict(binding=deepcopy(row["binding"]),
        dimensions={key: dict(score=score, reason="Invented operator judgment, not human gold") for key in DIMENSIONS},
        exceptional_reason=exceptional) for row in plan["portfolio"]["candidates"]]


def fixture_plan(repo, *, writing_attempts=1):
    episodes, head, _, _ = seed(repo)
    targets = [dict(episode_id=EPISODE, revision_sha256=head)]
    discovery = plan_episode_portfolio(episodes, targets, {}, [], now=NOW, writing_attempts=writing_attempts)
    assert discovery["portfolio"]["candidates"]
    return episodes, targets, judgments(discovery), discovery


@responses.activate
def test_actual_nhc_http_retained_episodes_request_portfolio_no_writes_or_provider(repository):
    repo = repository[1]
    episodes = PhysicalEpisodeSession(repo)
    clock = datetime.now(UTC).replace(microsecond=0)
    now = clock.isoformat().replace("+00:00", "Z")
    heads = {"ep1:cyclone:nhc:AL012026": None, "ep1:cyclone:nhc:EP012026": None}
    sources = []
    for number, hours, wind in [(1, 12, 70), (2, 2, 100)]:
        issued = (clock - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        rows = [dict(id=identifier, name="Invented " + identifier, intensity=str(wind),
                     lastUpdate=issued, publicAdvisory=dict(advNum=str(number), url=f"/text/{identifier}.shtml"))
                for identifier in ("AL012026", "EP012026")]
        responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms": rows})
        for row in rows:
            responses.add(responses.GET, "https://www.nhc.noaa.gov" + row["publicAdvisory"]["url"],
                          body="Invented official source product fixture.")
        observations = []
        parsed = nhc.fetch_active_cyclones(strict=True,
            retention_observer=lambda a, m: observations.append((a, m)))
        supply = CycloneSupplySession(repo, str(uuid.uuid4()), now, BASE)
        receipt, _, _ = supply.capture(parsed, {"status": "success"}, observations=observations)
        outcome = apply(supply, receipt, episodes, heads, now=now)
        heads = {r["episode_id"]: r["revision_sha256"] for r in outcome["episodes"]}
        sources.append(supply.read())
    assert len(responses.calls) == 6
    targets = [dict(episode_id=key, revision_sha256=value) for key, value in heads.items()]
    snapshot = {"drafts": [], "memory": {}}
    original = deepcopy(snapshot)
    before = pg.counts(repository[2])
    discovery = plan_episode_portfolio(episodes, targets, snapshot, [], now=now, writing_attempts=2)
    assert discovery["selected_requests"] == []
    assert len(discovery["portfolio"]["candidates"]) >= 2
    assert all(row["disposition"] == "assessment_incomplete" for row in discovery["portfolio"]["candidates"])
    ratings = judgments(discovery)
    result = plan_episode_portfolio(episodes, targets, snapshot, ratings, now=now, writing_attempts=1)
    again = plan_episode_portfolio(episodes, list(reversed(targets)), snapshot, list(reversed(ratings)),
                                   now=now, writing_attempts=1)
    assert result == again
    assert len(result["selected_requests"]) == 1 and len(responses.calls) == 6
    row = result["selected_requests"][0]
    assert row["writer_request"]["messages"][0]["role"] == "user"
    assert row["evidence_prompt_ready"] and row["provider_transport"] == "not_attempted"
    assert len(result["portfolio"]["candidates"]) == len(discovery["portfolio"]["candidates"])
    assert pg.counts(repository[2]) == before and snapshot == original
    assert not result["publication_approved"] and not result["production_authority"]
    assert result["fresh_dispatch_authority_required"] and not result["operational_state_mutated"]
    for target in targets:
        episodes.read_current(target["episode_id"], expected_head=target["revision_sha256"])


def test_stale_or_foreign_judgment_does_not_borrow_a_current_source(repository):
    episodes, targets, ratings, _ = fixture_plan(repository[1])
    ratings[0]["binding"]["bundle_sha256"] = "a" * 64
    before = pg.counts(repository[2])
    with pytest.raises(PortfolioError, match="portfolio_assessment_binding_mismatch"):
        plan_episode_portfolio(episodes, targets, {}, ratings, now=NOW, writing_attempts=0)
    assert pg.counts(repository[2]) == before


def test_changed_episode_refuses_the_old_portfolio_and_assessment(repository):
    episodes, targets, ratings, _ = fixture_plan(repository[1])
    newer, receipt, _ = capture(repository[1], [advisory(advisory_number="3", issued_at=NOW, wind_kt=115)])
    apply(newer, receipt, episodes, {EPISODE: targets[0]["revision_sha256"]})
    with pytest.raises(CycloneSupplyError, match="episode_head_changed"):
        plan_episode_portfolio(episodes, targets, {}, ratings, now=NOW, writing_attempts=1)


def test_source_failure_after_ranking_refuses_even_an_exceptional_proposal(repository, monkeypatch):
    import src.editorial.portfolio as planner
    episodes, targets, ratings, _ = fixture_plan(repository[1])
    ratings = deepcopy(ratings)
    for row in ratings:
        row["exceptional_reason"] = "Invented emergency; never bypass source failure"
    original = planner.plan_portfolio
    def fail_source(*args, **kwargs):
        result = original(*args, **kwargs)
        newer, receipt, _ = capture(repository[1], [advisory(advisory_number="3", issued_at=NOW)], status="failed")
        apply(newer, receipt, episodes, {EPISODE: targets[0]["revision_sha256"]})
        return result
    monkeypatch.setattr(planner, "plan_portfolio", fail_source)
    with pytest.raises(CycloneSupplyError, match="episode_head_changed"):
        plan_episode_portfolio(episodes, targets, {}, ratings, now=NOW, writing_attempts=1)
    assert episodes.read_current(EPISODE)[1]["state"] == "held"


def test_policy_drift_at_return_refuses_prepared_requests(repository, monkeypatch):
    from src.editorial import policy
    episodes, targets, ratings, _ = fixture_plan(repository[1])
    original = policy.current_editorial_policy
    calls = []
    def changed():
        calls.append(None)
        value = original()
        if len(calls) >= 4:
            value["source_sha256"] = "a" * 64
        return value
    monkeypatch.setattr(policy, "current_editorial_policy", changed)
    with pytest.raises(PortfolioError, match="portfolio_editorial_policy_changed"):
        plan_episode_portfolio(episodes, targets, {}, ratings, now=NOW, writing_attempts=1)


def test_source_age_is_a_gate_even_with_complete_high_judgments(repository):
    episodes, targets, ratings, _ = fixture_plan(repository[1])
    for row in ratings:
        row["exceptional_reason"] = "Invented emergency"
    with pytest.raises(CycloneSupplyError, match="episode_source_not_current"):
        plan_episode_portfolio(episodes, targets, {}, ratings,
                               now="2026-10-14T12:00:00Z", writing_attempts=1)


def test_missing_session_duplicate_targets_and_forged_judgments_are_not_authority(repository):
    with pytest.raises(PortfolioError, match="portfolio_episode_session_required"):
        plan_episode_portfolio(SimpleNamespace(repository=repository[1]), [], {}, [], now=NOW, writing_attempts=1)
    episodes, targets, ratings, _ = fixture_plan(repository[1])
    before = pg.counts(repository[2])
    with pytest.raises(PortfolioError, match="portfolio_duplicate_episode"):
        plan_episode_portfolio(episodes, targets * 2, {}, ratings, now=NOW, writing_attempts=1)
    with pytest.raises(PortfolioError, match="portfolio_duplicate_assessment"):
        plan_episode_portfolio(episodes, targets, {}, ratings + ratings, now=NOW, writing_attempts=1)
    assert pg.counts(repository[2]) == before
