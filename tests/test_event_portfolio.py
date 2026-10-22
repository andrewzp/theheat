"""Invented operator judgments; no human calibration or scientific gold labels."""
from copy import deepcopy
from dataclasses import replace

import pytest

from src.editorial.portfolio import (DIMENSIONS, PlanningCandidate, PlanningPolicy,
                                     PortfolioError, plan_portfolio)
from src.editorial.revisions import fingerprint


def candidate(group="first", *, opportunity="one", score=4, hazard="heat", regions=("country:AA",),
              exceptional=None):
    binding = dict(event_group_id=group, event_revision_sha256=fingerprint(group),
        opportunity_id=fingerprint([group, opportunity]), bundle_sha256=fingerprint([group, opportunity, "bundle"]),
        policy_sha256="f" * 64)
    return PlanningCandidate(binding, hazard, regions,
        {key: dict(score=score, reason="Invented operator assessment") for key in DIMENSIONS}, exceptional)


def assessments(row, **scores):
    dims = deepcopy(row.dimensions)
    for key, value in scores.items():
        dims[key] = None if value is None else dict(score=value, reason="Invented comparative judgment")
    return replace(row, dimensions=dims)


def selected_groups(result):
    by_id = {r["candidate_id"]: r for r in result["candidates"]}
    return [by_id[i]["binding"]["event_group_id"] for i in result["selected_candidate_ids"]]


def test_all_dimensions_exact_weighted_vector_reordering_and_no_mutation():
    rows = [candidate("a"), candidate("b", score=3), candidate("c", score=2)]
    before = deepcopy(rows)
    policy = PlanningPolicy(weights=(1, 2, 3, 4, 5, 6, 7, 8))
    result = plan_portfolio(rows, writing_attempts=2, policy=policy)
    assert result == plan_portfolio(list(reversed(rows)), writing_attempts=2, policy=policy)
    assert rows == before and selected_groups(result)[0] == "a"
    assert len(result["candidates"]) == 3
    first = next(r for r in result["candidates"] if r["binding"]["event_group_id"] == "a")
    assert first["base_score"] == 4 * sum(policy.weights)
    assert first["weighted_components"] == {key: 4 * w for key, w in zip(DIMENSIONS, policy.weights)}
    assert result["calibration_status"] == "not_human_calibrated"
    assert result["cost_status"] == "not_evaluated"
    assert not result["publication_approved"] and not result["production_authority"]
    assert result["provider_transport"] == "not_attempted"


def test_unknown_dimensions_are_held_not_zero_and_override_cannot_bypass_them():
    row = assessments(candidate(exceptional="Invented emergency reason"), impact=None)
    result = plan_portfolio([row], writing_attempts=3)
    assert result["selected_candidate_ids"] == []
    held = result["candidates"][0]
    assert held["missing_dimensions"] == ["impact"] and held["base_score"] is None
    assert held["weighted_components"]["impact"] is None
    assert held["disposition"] == "assessment_incomplete"


def test_late_soft_diversity_preserves_every_source_and_budget_spill():
    first = candidate("first")
    repeated = assessments(candidate("repeat"), impact=3)
    other = assessments(candidate("other", hazard="flood", regions=("country:BB",)), impact=2)
    result = plan_portfolio([repeated, other, first], writing_attempts=2)
    assert selected_groups(result) == ["first", "other"]
    assert len(result["candidates"]) == 3 and not result["evidence_discarded"]
    held = next(r for r in result["candidates"] if r["binding"]["event_group_id"] == "repeat")
    assert held["base_score"] == 31 and held["disposition"] == "writing_budget"
    assert held["diversity_penalty"]["applied"] == 16


def test_explicit_exception_can_allow_a_regional_emergency_to_dominate():
    rows = [candidate("first"), assessments(candidate("repeat", exceptional="Invented major emergency"), impact=3),
            assessments(candidate("other", hazard="flood", regions=("country:BB",)), impact=2)]
    result = plan_portfolio(rows, writing_attempts=2)
    assert selected_groups(result) == ["first", "repeat"]
    repeated = next(r for r in result["candidates"] if r["binding"]["event_group_id"] == "repeat")
    assert repeated["diversity_penalty"] == dict(topic_repeat=1, region_repeat=1,
                                                applied=0, exceptional_override=True)
    assert repeated["exceptional_reason"] == "Invented major emergency"
    assert len(plan_portfolio(rows, writing_attempts=1)["selected_candidate_ids"]) == 1


def test_same_event_angles_cluster_before_late_diversity():
    first = candidate("same", opportunity="one")
    alternate = candidate("same", opportunity="two", score=3)
    result = plan_portfolio([first, alternate], writing_attempts=64)
    assert selected_groups(result) == ["same"]
    assert sorted(r["disposition"] for r in result["candidates"]) == ["same_event_alternative", "selected"]


def test_zero_budget_keeps_evidence_and_all_scores_without_writing():
    result = plan_portfolio([candidate("first"), candidate("second")], writing_attempts=0)
    assert result["selected_candidate_ids"] == []
    assert len(result["candidates"]) == 2
    assert all(r["disposition"] == "writing_budget" and r["base_score"] == 32 for r in result["candidates"])


def test_unknown_geography_does_not_inherit_a_country_penalty():
    first = candidate("a", hazard="heat")
    unknown = assessments(candidate("b", regions=(), hazard="flood"), impact=3)
    result = plan_portfolio([first, unknown], writing_attempts=2)
    selected = next(r for r in result["candidates"] if r["binding"]["event_group_id"] == "b")
    assert selected["regions"] == [] and selected["diversity_penalty"]["region_repeat"] == 0


def test_multicountry_region_penalty_uses_overlap_without_multiplying_the_footprint():
    first = candidate("first", regions=("country:AA", "country:BB"))
    second = assessments(candidate("second", regions=("country:AA", "country:BB")), impact=3)
    result = plan_portfolio([first, second], writing_attempts=2)
    row = next(r for r in result["candidates"] if r["binding"]["event_group_id"] == "second")
    assert row["diversity_penalty"]["region_repeat"] == 1
    assert row["diversity_penalty"]["applied"] == 16


def test_below_minimum_is_a_planning_disposition_not_a_scientific_pass():
    result = plan_portfolio([candidate(score=0, exceptional="Invented exception")], writing_attempts=3)
    assert result["selected_candidate_ids"] == []
    assert result["candidates"][0]["disposition"] == "below_planning_minimum"


@pytest.mark.parametrize("value", [True, -1, 65, 1.0, "2", None])
def test_writing_budget_is_a_bounded_integer(value):
    with pytest.raises(PortfolioError, match="portfolio_writing_budget_invalid"):
        plan_portfolio([candidate()], writing_attempts=value)


@pytest.mark.parametrize("value", [True, -1, 5, 2.0, float("nan"), float("inf"), "3"])
def test_judgment_is_ordinal_not_physical_magnitude_or_coercion(value):
    row = candidate()
    row.dimensions["impact"]["score"] = value
    with pytest.raises(PortfolioError, match="portfolio_dimension_invalid"):
        plan_portfolio([row], writing_attempts=1)


@pytest.mark.parametrize("change", ["missing", "extra", "score-key", "empty-reason", "control-reason", "bool-override", "duplicate-region", "bad-sha"])
def test_strict_judgment_and_binding_schemas(change):
    row = candidate()
    if change == "missing":
        row.dimensions.pop("impact")
    if change == "extra":
        row.dimensions["viral"] = None
    if change == "score-key":
        row.dimensions["impact"]["automatic_pass"] = True
    if change == "empty-reason":
        row.dimensions["impact"]["reason"] = ""
    if change == "control-reason":
        row.dimensions["impact"]["reason"] = "invented\nclaim"
    if change == "bool-override":
        row = replace(row, exceptional_reason=True)
    if change == "duplicate-region":
        row = replace(row, regions=("country:AA", "country:AA"))
    if change == "bad-sha":
        row.binding["bundle_sha256"] = "not-a-hash"
    with pytest.raises(PortfolioError):
        plan_portfolio([row], writing_attempts=1)


def test_duplicate_current_heads_and_policy_conflicts_refuse():
    first = candidate()
    with pytest.raises(PortfolioError, match="portfolio_duplicate_candidate"):
        plan_portfolio([first, first], writing_attempts=2)
    second = candidate(opportunity="two")
    second.binding["event_revision_sha256"] = "a" * 64
    with pytest.raises(PortfolioError, match="portfolio_group_revision_conflict"):
        plan_portfolio([first, second], writing_attempts=2)
    second = candidate("second")
    second.binding["policy_sha256"] = "a" * 64
    with pytest.raises(PortfolioError, match="portfolio_policy_mismatch"):
        plan_portfolio([first, second], writing_attempts=2)


def test_same_opportunity_cannot_claim_conflicting_bundle_bindings():
    first = candidate()
    other = deepcopy(first)
    other.binding["bundle_sha256"] = "a" * 64
    with pytest.raises(PortfolioError, match="portfolio_duplicate_opportunity"):
        plan_portfolio([first, other], writing_attempts=2)


def test_non_utf8_judgment_is_a_bounded_refusal():
    row = candidate()
    row.dimensions["impact"]["reason"] = "\ud800"
    with pytest.raises(PortfolioError, match="portfolio_dimension_invalid"):
        plan_portfolio([row], writing_attempts=1)


@pytest.mark.parametrize("policy", [PlanningPolicy(weights=(1,)), PlanningPolicy(weights=(True,) * 8),
    PlanningPolicy(topic_repeat_penalty=-1), PlanningPolicy(minimum_score=True)])
def test_invalid_planning_policy_does_not_silently_fall_back(policy):
    with pytest.raises(PortfolioError):
        plan_portfolio([candidate()], writing_attempts=1, policy=policy)


def test_empty_inventory_does_not_certify_quiet_weather_or_zero_account_spend():
    result = plan_portfolio([], writing_attempts=0)
    assert result["candidates"] == [] and result["selected_candidate_ids"] == []
    assert result["cost_status"] == "not_evaluated"
    assert "quiet_weather" not in result and not result["production_authority"]
