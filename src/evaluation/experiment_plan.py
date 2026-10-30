"""Optional, default-off experiment plans and their acceptance reader (W16.3).

A plan freezes exact arm identities (code revision, brief/source, editorial
policy and model), a fixed allowance, the required checks, the evidence needed
for promotion and explicit rollback criteria. Preparing or reading a plan never
runs an arm, calls a provider, changes a flag or prompt, or authorizes
publication. Acceptance promotes only when every required piece of supplied
evidence is present, bound to the plan and meets its stated rule; anything
missing or mismatched holds.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from src.editorial.revisions import fingerprint

SCHEMA = "theheat.experiment-plan/v1"
RESULT_SCHEMA = "theheat.experiment-result/v1"
REQUIRED_CHECKS = ("deterministic", "safety", "fact_check", "critic")
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{1,63}")
MAX_ARMS = 4


class PlanError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PlanError(code)


def _arm(value: Any) -> dict:
    _require(isinstance(value, dict) and set(value) == {"arm_id", "code_revision", "brief_sha256", "policy_sha256",
                                                       "model"}, "arm_shape")
    _require(bool(_ID.fullmatch(str(value["arm_id"]))), "arm_id")
    for key in ("code_revision", "brief_sha256", "policy_sha256"):
        _require(isinstance(value[key], str) and bool(_SHA.fullmatch(value[key])), f"arm_{key}")
    _require(isinstance(value["model"], str) and 0 < len(value["model"]) <= 80, "arm_model")
    return deepcopy(value)


def prepare_plan(*, question: str, improvement: dict, arms: list[dict], allowance: dict,
                 minimum_supplied_ratings: int = 20, max_factual_failure_increase: int = 0) -> dict:
    """A frozen plan document; ``improvement`` is the weekly reader's selected issue."""
    _require(isinstance(question, str) and 10 <= len(question) <= 500, "question")
    _require(isinstance(improvement, dict) and improvement.get("kind") in ("local_repair", "source_uncertainty"),
             "improvement_not_experimentable")
    _require(isinstance(arms, list) and 2 <= len(arms) <= MAX_ARMS, "arm_count")
    frozen = [_arm(arm) for arm in arms]
    _require(len({arm["arm_id"] for arm in frozen}) == len(frozen), "duplicate_arm")
    _require(len({fingerprint({k: v for k, v in arm.items() if k != "arm_id"}) for arm in frozen}) == len(frozen),
             "identical_arms")
    _require(isinstance(allowance, dict) and set(allowance) == {"max_candidates", "max_model_calls"}
             and all(type(allowance[k]) is int and 0 < allowance[k] <= 200 for k in allowance), "allowance")
    _require(type(minimum_supplied_ratings) is int and minimum_supplied_ratings >= 1, "minimum_ratings")
    plan = {"schema": SCHEMA, "question": question, "improvement": deepcopy(improvement), "arms": frozen,
            "allowance": {**allowance, "writer_samples": 1, "revisions": 0},
            "required_checks": list(REQUIRED_CHECKS),
            "promotion_rule": {"minimum_supplied_ratings": minimum_supplied_ratings,
                               "max_factual_failure_increase": max_factual_failure_increase,
                               "requires": ["copy_comparison_summary", "factual_failures", "observed_model_calls"]},
            "rollback": {"criteria": ["any required check missing for a delivered candidate",
                                      "factual failures above the incumbent by more than the stated increase",
                                      "observed model calls above the fixed allowance"],
                         "action": "Keep or restore the incumbent arm's code revision and policy; no automatic change."},
            "execution": {"status": "default_off", "authorized": False, "publication_authorized": False}}
    return {**plan, "plan_id": fingerprint(plan)}


def accept(plan: dict, result: dict) -> dict:
    """Promotion decision for supplied results bound to this exact plan; missing evidence holds."""
    _require(isinstance(plan, dict) and plan.get("schema") == SCHEMA, "plan_schema")
    body = {k: v for k, v in plan.items() if k != "plan_id"}
    _require(plan.get("plan_id") == fingerprint(body), "plan_changed")
    reasons: list[str] = []
    if not isinstance(result, dict) or result.get("schema") != RESULT_SCHEMA or result.get("plan_id") != plan["plan_id"]:
        return {"decision": "HOLD", "reasons": ["result_not_bound_to_plan"], "plan_id": plan["plan_id"]}
    arms = {arm["arm_id"] for arm in plan["arms"]}
    supplied = result.get("arms")
    per_arm: dict[str, Any] = supplied if isinstance(supplied, dict) else {}
    if set(per_arm) != arms:
        reasons.append("arm_results_incomplete")
    rule = plan["promotion_rule"]
    for arm_id in sorted(arms & set(per_arm)):
        row = per_arm[arm_id] if isinstance(per_arm[arm_id], dict) else {}
        for key in rule["requires"]:
            if row.get(key) is None:
                reasons.append(f"{arm_id}:{key}_missing")
        checks = row.get("required_checks_present")
        if checks is not True:
            reasons.append(f"{arm_id}:required_checks_not_proven")
        calls = row.get("observed_model_calls")
        if type(calls) is int and calls > plan["allowance"]["max_model_calls"]:
            reasons.append(f"{arm_id}:allowance_exceeded")
    incumbent, challenger = str(result.get("incumbent")), str(result.get("challenger"))
    if incumbent not in arms or challenger not in arms or incumbent == challenger:
        reasons.append("incumbent_or_challenger_unknown")
    if not reasons:
        summary = per_arm[challenger]["copy_comparison_summary"]
        ratings = summary.get("supplied_ratings") if isinstance(summary, dict) else None
        if type(ratings) is not int or ratings < rule["minimum_supplied_ratings"]:
            reasons.append("too_few_supplied_ratings")
        elif summary.get("preferred_arm") != challenger:
            reasons.append("challenger_not_preferred")
        if per_arm[challenger]["factual_failures"] - per_arm[incumbent]["factual_failures"] > rule["max_factual_failure_increase"]:
            reasons.append("factual_failures_increased")
    decision = "PROMOTE_RECOMMENDED" if not reasons else "HOLD"
    return {"decision": decision, "reasons": reasons, "plan_id": plan["plan_id"], "automatic_changes": False,
            "rollback": plan["rollback"] if decision == "PROMOTE_RECOMMENDED" else None}


WEEKLY_REVIEW_KIND = "weekly_retained_outcome_review"
_SPEC_KEYS = {"question", "arms", "allowance"}
_SPEC_OPTIONAL = {"minimum_supplied_ratings", "max_factual_failure_increase"}


def plan_from_weekly_review(review: Any, spec: Any) -> dict:
    """Freeze a plan for the weekly review's own selected improvement.

    The improvement is copied from the supplied review, never from the spec, so
    an experiment cannot drift from what the weekly reader selected. Owner
    actions (expired access, missing inputs) are not experimentable and refuse.
    """
    _require(isinstance(review, dict) and review.get("kind") == WEEKLY_REVIEW_KIND
             and isinstance(review.get("report_id"), str) and bool(_SHA.fullmatch(review["report_id"])), "weekly_review")
    improvement = review.get("improvement")
    _require(isinstance(improvement, dict), "weekly_review_improvement")
    _require(isinstance(spec, dict) and _SPEC_KEYS <= set(spec) <= _SPEC_KEYS | _SPEC_OPTIONAL, "spec_shape")
    selected = {**deepcopy(improvement), "weekly_review_id": review["report_id"]}
    return prepare_plan(question=spec["question"], improvement=selected, arms=spec["arms"], allowance=spec["allowance"],
                        **{key: spec[key] for key in _SPEC_OPTIONAL if key in spec})


__all__ = ["PlanError", "REQUIRED_CHECKS", "RESULT_SCHEMA", "SCHEMA", "WEEKLY_REVIEW_KIND", "accept",
           "plan_from_weekly_review", "prepare_plan"]
