"""Detached draft planning shared by synchronous saving and local admission.

No authority, automatic approval, clock lookup, environment lookup or I/O lives
here. A rejected plan cannot remove a weaker draft before a later gate refuses it.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import hashlib
import math

from src.data.fire_identity import legacy_history_reason
from src.data.places import draft_place_id, event_identity, legacy_publication_status
from src.editorial.approval import ApprovalPolicy, recommend_approval_policy
from src.editorial.newsworthiness import detect_impact_citation
from src.editorial.policy import valid_policy
from src.editorial.revisions import initialize_revision
from src.orchestrator.caps import CITY_COOLDOWN_DAYS, ELITE_COPY_SCORE
from src.orchestrator.dedup import _posted_city_within_days, _same_day_already_posted, _same_day_pending_collision


@dataclass(frozen=True)
class AdmissionPlaceFacts:
    """Process-local resolved facts; never a browser-supplied authority object."""
    event_id: str
    state_sha256: str
    place_id: str
    history_status: str
    fire_hold: str | None
    draft_place_ids: tuple[str, ...]


def _state_sha256(state: Mapping[str, Any]) -> str:
    # Process-local binding only, never a persistence format. Existing source
    # bundles may carry date objects until the legacy state writer serializes
    # them. Tag every container to keep those distinct from lookalike JSON.
    def typed(value):
        if type(value) is date:
            return ["date", value.isoformat()]
        if type(value) is datetime:
            return ["datetime", value.isoformat(), value.fold]
        if isinstance(value, dict) and all(isinstance(k, str) for k in value):
            return ["object", [[k, typed(value[k])] for k in sorted(value)]]
        if isinstance(value, list):
            return ["array", [typed(v) for v in value]]
        if value is None or type(value) in (str, int, float, bool):
            return ["scalar", value]
        raise ValueError("unsupported_admission_state_value")
    raw = json.dumps(typed(dict(state)), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def resolve_admission_place_facts(state: Mapping[str, Any], event_id: str) -> AdmissionPlaceFacts:
    """Outer boundary: registry reads are permitted here, never in the planner."""
    return AdmissionPlaceFacts(event_id=event_id, state_sha256=_state_sha256(state),
        place_id=event_identity(event_id).get("place_id", ""), history_status=legacy_publication_status(state, event_id),
        fire_hold=legacy_history_reason(state, event_id),
        draft_place_ids=tuple(draft_place_id(d) for d in state.get("drafts", [])))


@dataclass(frozen=True)
class AdmissionPlan:
    state: dict
    draft: dict | None
    reason: str | None
    suppressions: tuple[dict, ...]
    changed_ids: tuple[str, ...] = ()


def evaluator_fields(value, tweet_type: str) -> dict:
    """The sole existing producer supplies a bounded hot10 row list."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not set(value) <= {"hot10_rows"}:
        raise ValueError("unsupported_evaluator_metadata")
    if "hot10_rows" in value:
        rows = value["hot10_rows"]
        if tweet_type != "hot10" or not isinstance(rows, list) or not 1 <= len(rows) <= 10:
            raise ValueError("invalid_hot10_rows")
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, dict) or set(row) != {"rank", "city", "country", "anomaly_c", "temp_high_c"}:
                raise ValueError("invalid_hot10_rows")
            if type(row["rank"]) is not int or row["rank"] != rank:
                raise ValueError("invalid_hot10_rows")
            if any(not isinstance(row[k], str) or not 1 <= len(row[k]) <= 200 for k in ("city", "country")):
                raise ValueError("invalid_hot10_rows")
            if any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in ("anomaly_c", "temp_high_c")):
                raise ValueError("invalid_hot10_rows")
    if len(json.dumps(value, allow_nan=False).encode()) > 8192:
        raise ValueError("oversized_evaluator_metadata")
    return deepcopy(value)


def plan_draft_admission(state: Mapping[str, Any], *, text: str, tweet_type: str, event_id: str,
                         draft_id: str, at: datetime, editorial_policy: dict | None, place_facts: AdmissionPlaceFacts,
                         score: dict | None = None, candidates: list | None = None,
                         candidate_score: dict | None = None, review_context: dict | None = None,
                         evaluator_metadata: dict | None = None, city: str = "",
                         tweet_date: str = "", cooldown_exempt: bool = False) -> AdmissionPlan:
    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise ValueError("aware_utc_clock_required")
    if (not isinstance(place_facts, AdmissionPlaceFacts) or place_facts.event_id != event_id
            or place_facts.state_sha256 != _state_sha256(state)
            or len(place_facts.draft_place_ids) != len(state.get("drafts", []))):
        raise ValueError("stale_admission_place_facts")
    metadata = evaluator_fields(evaluator_metadata, tweet_type)
    proposed = deepcopy(dict(state))
    drafts = proposed.get("drafts", [])
    if not isinstance(drafts, list):
        raise ValueError("invalid_drafts")
    context = deepcopy(review_context)
    suppressions = []

    def refusal(reason, message=None, summary=None):
        rows = () if message is None else ({"event_id": event_id, "score": deepcopy(score),
            "kill_stage": reason, "kill_reason": message, "summary": summary or text[:120] or event_id},)
        return AdmissionPlan(deepcopy(dict(state)), None, reason, rows)

    fire_hold = place_facts.fire_hold
    if fire_hold:
        return refusal(fire_hold)
    place_id = place_facts.place_id
    history = place_facts.history_status
    if history in ("duplicate", "unresolved", "unregistered"):
        return refusal({"duplicate": "duplicate_posted", "unresolved": "legacy_publish_unresolved", "unregistered": "unregistered_place"}[history])
    if event_id and any(d.get("event_id") == event_id for d in drafts):
        return refusal("duplicate_draft", "Event already has a draft")
    # Repeat the pre-writer durable event check inside the transaction.
    if event_id and event_id in state.get("posted_events", []):
        return refusal("duplicate_posted")
    collision = None
    if city and tweet_date:
        if _same_day_already_posted(drafts, city, tweet_date, place_id=place_id, resolved_place_ids=place_facts.draft_place_ids):
            return refusal("same_day_posted", f"Already posted for {city} on {tweet_date}", city)
        collision = _same_day_pending_collision(drafts, city, tweet_date, place_id=place_id, resolved_place_ids=place_facts.draft_place_ids)
        if collision:
            _, other = collision
            old, new = (other.get("score") or {}).get("total", 0), (score or {}).get("total", 0)
            if new <= old:
                return refusal("same_day_dedup", f"Weaker same-day signal for {city} ({new} <= {old})", city)
            suppressions.append({"event_id": other.get("event_id", ""), "score": deepcopy(other.get("score")),
                "kill_stage": "same_day_superseded", "kill_reason": f"Superseded by stronger same-day signal ({new} > {old})", "summary": city})
    elite = bool(candidate_score and candidate_score.get("total", 0) >= ELITE_COPY_SCORE)
    if city and not cooldown_exempt and not elite and _posted_city_within_days(drafts, city, CITY_COOLDOWN_DAYS, place_id=place_id, at=at, resolved_place_ids=place_facts.draft_place_ids):
        return refusal("city_cooldown", f"{city} in {CITY_COOLDOWN_DAYS}-day cooldown", city)

    stamp = at.isoformat().replace("+00:00", "Z")
    draft: dict[str, Any] = {"id": draft_id, "text": text, "type": tweet_type, "event_id": event_id,
             "created_at": stamp, "updated_at": stamp, "status": "pending"}
    for name, value in (("city", city), ("tweet_date", tweet_date), ("candidates", candidates),
                        ("candidate_score", candidate_score), ("review_context", context)):
        if value:
            draft[name] = deepcopy(value)
    if score is not None:
        draft["score"] = deepcopy(score)
    draft.update(metadata)
    policy = recommend_approval_policy(tweet_type, signal_total=(score or {}).get("total", 0), candidate_score=candidate_score)
    citation = detect_impact_citation(text, context)
    if citation.forced:
        policy = ApprovalPolicy(key="impact_citation_manual", mode="manual_only", recommended_delay_minutes=None,
            can_auto_approve=False, reason="Draft cites a sourced human-impact fact. Impact-carrying tweets always get a human review (Bet A decision 4).")
        draft["forced_manual"] = "cited_impact"
    if history == "ambiguous":
        policy = ApprovalPolicy(key="identity_history_manual", mode="manual_only", recommended_delay_minutes=None,
            can_auto_approve=False, reason="Legacy publication identity cannot be attributed. Review the old publication before approving this place.")
        draft["forced_manual"] = "ambiguous_legacy_place"
        draft.setdefault("review_context", {})["identity_history_status"] = "ambiguous"
    draft["approval_policy"] = policy.as_dict()
    draft["approval_mode"] = "manual"
    initialize_revision(draft, at=stamp, policy=editorial_policy if valid_policy(editorial_policy) else None)
    removed: tuple[str, ...] = ()
    if collision:
        index, other = collision
        removed = (other["id"],)
        drafts.pop(index)
    drafts.append(draft)
    proposed["drafts"] = drafts
    return AdmissionPlan(proposed, draft, None, tuple(suppressions), (*removed, draft_id))
