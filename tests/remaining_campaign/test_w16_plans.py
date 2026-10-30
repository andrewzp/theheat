"""W16.3 experiment plan mechanics and W16.6 retirement planning (invented inputs; nothing executed)."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.evaluation import experiment_plan as ep
from src.retirement_plan import plan as retirement_plan

ROOT = Path(__file__).resolve().parents[2]
ARMS = [{"arm_id": "incumbent", "code_revision": "a" * 40, "brief_sha256": "b" * 64, "policy_sha256": "c" * 64,
         "model": "invented-writer-model"},
        {"arm_id": "challenger", "code_revision": "d" * 40, "brief_sha256": "b" * 64, "policy_sha256": "e" * 64,
         "model": "invented-writer-model"}]
IMPROVEMENT = {"kind": "local_repair", "issue": "3 candidates were rejected at critic this week."}


def make_plan(**changes):
    return ep.prepare_plan(question="Does the revised brief reduce critic rejections without new factual failures?",
                           improvement=IMPROVEMENT, arms=deepcopy(ARMS),
                           allowance={"max_candidates": 10, "max_model_calls": 40}, **changes)


def result(plan, **arm_changes):
    arms: dict[str, dict[str, Any]] = {"incumbent": {"copy_comparison_summary": {"supplied_ratings": 24, "preferred_arm": "challenger"},
                          "factual_failures": 2, "observed_model_calls": 30, "required_checks_present": True},
            "challenger": {"copy_comparison_summary": {"supplied_ratings": 24, "preferred_arm": "challenger"},
                           "factual_failures": 2, "observed_model_calls": 31, "required_checks_present": True}}
    for arm, change in arm_changes.items():
        arms[arm].update(change)
    return {"schema": ep.RESULT_SCHEMA, "plan_id": plan["plan_id"], "incumbent": "incumbent", "challenger": "challenger",
            "arms": arms}


def test_plan_freezes_identities_allowance_checks_and_stays_default_off():
    plan = make_plan()
    assert plan["allowance"] == {"max_candidates": 10, "max_model_calls": 40, "writer_samples": 1, "revisions": 0}
    assert plan["required_checks"] == ["deterministic", "safety", "fact_check", "critic"]
    assert plan["execution"] == {"status": "default_off", "authorized": False, "publication_authorized": False}
    assert plan["rollback"]["criteria"] and plan["plan_id"]


@pytest.mark.parametrize(("change", "code"), [
    ({"improvement": {"kind": "owner_action"}}, "improvement_not_experimentable"),
    ({"arms": [ARMS[0]]}, "arm_count"),
    ({"arms": [ARMS[0], {**ARMS[0], "arm_id": "copy"}]}, "identical_arms"),
    ({"allowance": {"max_candidates": 0, "max_model_calls": 40}}, "allowance"),
], ids=["owner-action", "one-arm", "identical", "zero-allowance"])
def test_invalid_plans_refuse(change, code):
    args: dict[str, Any] = dict(question="A bounded question about one supported issue.", improvement=IMPROVEMENT,
                                arms=deepcopy(ARMS), allowance={"max_candidates": 10, "max_model_calls": 40})
    args.update(change)
    with pytest.raises(ep.PlanError, match=code):
        ep.prepare_plan(**args)


def test_complete_bound_evidence_can_recommend_promotion_but_changes_nothing():
    plan = make_plan()
    decision = ep.accept(plan, result(plan))
    assert decision["decision"] == "PROMOTE_RECOMMENDED" and decision["automatic_changes"] is False


@pytest.mark.parametrize(("arm", "change", "reason"), [
    ("challenger", {"copy_comparison_summary": None}, "challenger:copy_comparison_summary_missing"),
    ("challenger", {"observed_model_calls": 41}, "challenger:allowance_exceeded"),
    ("challenger", {"required_checks_present": None}, "challenger:required_checks_not_proven"),
    ("challenger", {"factual_failures": 3}, "factual_failures_increased"),
    ("challenger", {"copy_comparison_summary": {"supplied_ratings": 5, "preferred_arm": "challenger"}}, "too_few_supplied_ratings"),
], ids=["missing-summary", "over-allowance", "checks", "factual", "few-ratings"])
def test_missing_or_failing_evidence_holds(arm, change, reason):
    plan = make_plan()
    decision = ep.accept(plan, result(plan, **{arm: change}))
    assert decision["decision"] == "HOLD" and reason in decision["reasons"]


def test_results_for_another_or_changed_plan_hold_or_refuse():
    plan = make_plan()
    assert ep.accept(plan, {**result(plan), "plan_id": "0" * 64})["reasons"] == ["result_not_bound_to_plan"]
    changed = {**plan, "allowance": {**plan["allowance"], "max_model_calls": 400}}
    with pytest.raises(ep.PlanError, match="plan_changed"):
        ep.accept(changed, result(plan))


def test_retirement_planner_refuses_referenced_protected_and_undocumented_targets():
    out = retirement_plan(ROOT, [
        {"kind": "path", "target": "src/operator_onboarding.py", "replacement_evidence": "invented"},
        {"kind": "path", "target": "src/state.py", "replacement_evidence": "invented"},
        {"kind": "flag", "target": "THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "replacement_evidence": "invented"},
        {"kind": "path", "target": "src/data/air_quality.py"},
        {"kind": "branch", "target": "codex/invented-old-branch", "replacement_evidence": "merged elsewhere"},
        {"kind": "path", "target": "src/invented_absent.py", "replacement_evidence": "invented"},
    ])
    reasons = {row["target"]: row["reason"] for row in out["refused"]}
    assert reasons == {"src/operator_onboarding.py": "still_referenced", "src/state.py": "still_needed_production_path",
                       "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "flag_still_read", "src/data/air_quality.py": "no_documented_replacement",
                       "src/invented_absent.py": "target_absent"}
    assert out["eligible"] == [{"kind": "branch", "target": "codex/invented-old-branch", "action": "plan_only",
                                "note": "Branch deletion is never performed here; Root decides after review."}]
    assert out["applied"] is False


def test_unreferenced_target_is_eligible_and_unresolved_receipts_block_publication_paths(tmp_path):
    (tmp_path / "src/posting").mkdir(parents=True)
    (tmp_path / "src/orphan.py").write_text("VALUE = 1\n")
    (tmp_path / "src/posting/old_adapter.py").write_text("X = 2\n")
    state = {"publish_ledger": {"invented-event": {"phase": "unknown", "tweet_id": None}}}
    out = retirement_plan(tmp_path, [{"kind": "path", "target": "src/orphan.py", "replacement_evidence": "invented"},
                                     {"kind": "path", "target": "src/posting/old_adapter.py", "replacement_evidence": "invented"}],
                          state=state)
    assert [row["target"] for row in out["eligible"]] == ["src/orphan.py"]
    assert out["refused"][0]["reason"] in ("still_needed_production_path", "unresolved_state")
    assert (tmp_path / "src/orphan.py").exists()  # Never removed.
