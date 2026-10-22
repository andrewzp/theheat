"""Read-only, evidence-bound editorial planning; never a scientific or spend grant.

Ordinal operator judgments remain distinct from physical measurements and from
independent human calibration. Unknown dimensions cannot acquire a default score.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from src.editorial.revisions import fingerprint

DIMENSIONS = ("impact", "rarity", "spatial_scale", "persistence", "novelty",
              "urgency", "evidence_quality", "clear_angle")
BINDING_KEYS = {"event_group_id", "event_revision_sha256", "opportunity_id",
                "bundle_sha256", "policy_sha256"}
MAX_CANDIDATES = 128
MAX_CHOICES = 64


class PortfolioError(ValueError):
    """Bounded planning refusal without evidence, credentials or connection text."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PortfolioError(code)


def _text(value: Any, maximum: int = 400) -> bool:
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            return False
    return (type(value) is str and 0 < len(value) <= maximum and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _sha(value: Any) -> bool:
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def validate_binding(value: Any) -> dict:
    require(type(value) is dict and set(value) == BINDING_KEYS, "portfolio_binding_invalid")
    require(_text(value["event_group_id"], 200), "portfolio_binding_invalid")
    require(all(_sha(value[k]) for k in BINDING_KEYS - {"event_group_id"}),
            "portfolio_binding_invalid")
    return dict(value)


@dataclass(frozen=True)
class PlanningPolicy:
    """Explicit uncalibrated planning choices; no runtime settings are changed."""
    weights: tuple[int, ...] = (1,) * len(DIMENSIONS)
    topic_repeat_penalty: int = 8
    region_repeat_penalty: int = 8
    minimum_score: int = 1

    def validated(self) -> dict:
        require(type(self.weights) is tuple and len(self.weights) == len(DIMENSIONS)
                and all(type(w) is int and 1 <= w <= 10 for w in self.weights),
                "portfolio_weights_invalid")
        require(all(type(v) is int and 0 <= v <= 320 for v in
                    (self.topic_repeat_penalty, self.region_repeat_penalty, self.minimum_score)),
                "portfolio_planning_policy_invalid")
        return dict(weights=dict(zip(DIMENSIONS, self.weights)),
                    topic_repeat_penalty=self.topic_repeat_penalty,
                    region_repeat_penalty=self.region_repeat_penalty, minimum_score=self.minimum_score)


@dataclass(frozen=True)
class PlanningCandidate:
    binding: dict
    hazard: str
    regions: tuple[str, ...]
    dimensions: dict
    exceptional_reason: str | None = None

    def validated(self) -> dict:
        binding = validate_binding(self.binding)
        require(_text(self.hazard, 80), "portfolio_hazard_invalid")
        require(type(self.regions) is tuple and len(self.regions) <= 64
                and all(_text(v, 120) for v in self.regions)
                and len(set(self.regions)) == len(self.regions), "portfolio_regions_invalid")
        require(type(self.dimensions) is dict and set(self.dimensions) == set(DIMENSIONS),
                "portfolio_dimensions_invalid")
        dimensions = {}
        for key in DIMENSIONS:
            value = self.dimensions[key]
            require(value is None or (type(value) is dict and set(value) == {"score", "reason"}
                    and type(value["score"]) is int and 0 <= value["score"] <= 4
                    and _text(value["reason"])), "portfolio_dimension_invalid")
            dimensions[key] = None if value is None else dict(value)
        require(self.exceptional_reason is None or _text(self.exceptional_reason),
                "portfolio_exception_reason_invalid")
        return dict(binding=binding, candidate_id=fingerprint(binding), hazard=self.hazard,
                    regions=sorted(self.regions), dimensions=dimensions,
                    exceptional_reason=self.exceptional_reason)


def plan_portfolio(candidates: list[PlanningCandidate], *, writing_attempts: int,
                   policy: PlanningPolicy | None = None) -> dict:
    """Retain all rows, cluster, then apply soft diversity within an attempt budget.

    Every candidate must already have passed its source-specific preparation.
    This pure function cannot establish that preparation or authorize transport.
    """
    require(type(candidates) is list and len(candidates) <= MAX_CANDIDATES
            and all(type(c) is PlanningCandidate for c in candidates), "portfolio_candidates_invalid")
    require(type(writing_attempts) is int and 0 <= writing_attempts <= MAX_CHOICES,
            "portfolio_writing_budget_invalid")
    if policy is None:
        policy = PlanningPolicy()
    require(type(policy) is PlanningPolicy, "portfolio_planning_policy_invalid")
    settings = policy.validated()
    rows = sorted((c.validated() for c in candidates), key=lambda row: row["candidate_id"])
    require(len({r["candidate_id"] for r in rows}) == len(rows), "portfolio_duplicate_candidate")
    require(len({(r["binding"]["event_group_id"], r["binding"]["opportunity_id"])
                 for r in rows}) == len(rows), "portfolio_duplicate_opportunity")
    require(len({r["binding"]["policy_sha256"] for r in rows}) <= 1, "portfolio_policy_mismatch")
    heads: dict[str, str] = {}
    groups: dict[str, list[dict]] = {}
    for row in rows:
        binding = row["binding"]
        group = binding["event_group_id"]
        require(group not in heads or heads[group] == binding["event_revision_sha256"],
                "portfolio_group_revision_conflict")
        heads[group] = binding["event_revision_sha256"]
        missing = [key for key in DIMENSIONS if row["dimensions"][key] is None]
        row["missing_dimensions"] = missing
        row["weighted_components"] = {key: None if row["dimensions"][key] is None
            else row["dimensions"][key]["score"] * weight
            for key, weight in zip(DIMENSIONS, policy.weights)}
        row["base_score"] = None if missing else sum(row["weighted_components"].values())
        row.update(disposition="assessment_incomplete" if missing else "writing_budget",
                   selection_rank=None, diversity_penalty=None, adjusted_score=None,
                   evaluated_after_selections=None)
        if not missing:
            if row["base_score"] < policy.minimum_score:
                row["disposition"] = "below_planning_minimum"
            else:
                groups.setdefault(group, []).append(row)

    # One episode is one portfolio item, even when it supports several angles.
    remaining = []
    for members in groups.values():
        members.sort(key=lambda row: (-row["base_score"], row["candidate_id"]))
        remaining.append(members[0])
        for alternative in members[1:]:
            alternative["disposition"] = "same_event_alternative"
    topics: dict[str, int] = {}
    regions: dict[str, int] = {}
    chosen: list[str] = []
    while remaining and len(chosen) < writing_attempts:
        for row in remaining:
            row["evaluated_after_selections"] = len(chosen)
            topic_repeat = topics.get(row["hazard"], 0)
            region_repeat = max((regions.get(r, 0) for r in row["regions"]), default=0)
            penalty = (0 if row["exceptional_reason"] else
                topic_repeat * policy.topic_repeat_penalty + region_repeat * policy.region_repeat_penalty)
            row["diversity_penalty"] = dict(topic_repeat=topic_repeat, region_repeat=region_repeat,
                applied=penalty, exceptional_override=row["exceptional_reason"] is not None)
            row["adjusted_score"] = row["base_score"] - penalty
        remaining.sort(key=lambda row: (-row["adjusted_score"], -row["base_score"], row["candidate_id"]))
        winner = remaining.pop(0)
        winner["disposition"] = "selected"
        winner["selection_rank"] = len(chosen) + 1
        chosen.append(winner["candidate_id"])
        topics[winner["hazard"]] = topics.get(winner["hazard"], 0) + 1
        for region in winner["regions"]:
            regions[region] = regions.get(region, 0) + 1
    result = dict(schema_version=1, contract="manual-portfolio-v1", candidates=rows,
        selected_candidate_ids=chosen, writing_attempts=writing_attempts,
        planning_policy=settings, planning_policy_sha256=fingerprint(settings),
        assessment_origin="operator_supplied_not_scientific_adjudication",
        calibration_status="not_human_calibrated", cost_status="not_evaluated",
        provider_transport="not_attempted", publication_approved=False,
        production_authority=False, evidence_discarded=False)
    result["plan_sha256"] = fingerprint(result)
    return result
