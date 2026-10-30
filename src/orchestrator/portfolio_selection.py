"""Importance-vector portfolio selection over the ordinary triage slate (W08.3/08.4).

Default off: ``THEHEAT_PORTFOLIO_SELECTION`` must be exactly ``"1"``. Off, the drain
calls ``triage.select_survivors`` exactly as before. On, the same slate is ranked by
``report_supply.rank`` (the existing ``editorial.portfolio`` planner) within the same
cap, and the existing per-category, pending-type and country caps still apply to the
chosen rows. Ranking is a decision over retained qualified evidence, never a paid
opinion stage.

* Importance dimensions come only from retained bundle/review fields. A dimension
  with no supporting field stays absent (``None``), never zero; an incomplete vector
  is ``assessment_incomplete`` and is not selected.
* There is no continent or regional quota: the planner's soft diversity penalty is
  the only spread rule, and the country code is its region.
* A ranking failure raises ``PortfolioRankingFailed``: the drain holds the slate with
  zero writer attempts and a visible reason.
* Every candidate the plan does not choose keeps its reason in the existing
  suppression ledger (stage ``portfolio_not_selected``).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from typing import Any

FLAG = "THEHEAT_PORTFOLIO_SELECTION"
POLICY = "theheat.triage-portfolio-selection/v1"
POLICY_SHA256 = hashlib.sha256(POLICY.encode()).hexdigest()
_OBSERVED = {"official_event_report", "thermal_detection", "satellite_derived", "observed", "gauge_observed"}


class PortfolioRankingFailed(RuntimeError):
    """A fixed planner code; the slate is held with zero writer attempts."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def enabled() -> bool:
    return os.environ.get(FLAG) == "1"


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def _number(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) else None


def evidence_for(candidate: Any) -> dict[str, Any]:
    """Importance evidence from retained qualified fields only; an absent field stays absent."""
    bundle = getattr(candidate, "bundle", None)
    raw = getattr(bundle, "raw_signal_dump", None) or {}
    review = getattr(candidate, "review_context", None) or {}
    found = review.get("physical_episode")
    episode: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    evidence: dict[str, Any] = {}
    evidence_type = episode.get("evidence_type") or raw.get("evidence_type")
    if evidence_type:
        # Observed/official evidence vs forecast/warning stays explicit; it is never inferred.
        evidence["evidence_type"] = "observed" if evidence_type in _OBSERVED else evidence_type
    impacts = [row for row in getattr(bundle, "human_impact", None) or []
               if isinstance(row, Mapping) and row.get("claim") and row.get("source_name") and row.get("as_of")]
    if impacts:
        evidence["sourced_consequences"] = [row["claim"] for row in impacts]
    for key, field in (("return_period_years", "return_period_years"), ("magnitude_percentile", "percentile"),
                       ("magnitude_percentile", "magnitude_percentile"), ("duration_days", "duration_days")):
        value = _number(raw.get(field))
        if value is not None:
            evidence[key] = value
    places = (episode.get("material") or {}).get("places") if episode else None
    if isinstance(places, list) and places:
        evidence["affected_places"] = len(places)
    if episode.get("eligibility"):
        evidence["novel"] = True  # admitted this run as a new episode or a material update
        evidence["current"] = True  # its source revision was retrieved by this run's poll
    if getattr(bundle, "headline_metric", None):
        evidence["headline"] = True
    return evidence


def _rows(pool: Sequence[Any]) -> tuple[list[dict[str, Any]], list[Any]]:
    unique = list({id(candidate): candidate for candidate in pool}.values())  # a copy is selected once
    def group(candidate: Any) -> str:
        episode = (getattr(candidate, "review_context", None) or {}).get("physical_episode")
        return str((episode or {}).get("episode_id") or getattr(candidate, "event_id", "") or "unidentified")[:200]
    revisions: dict[str, list[str]] = {}
    for candidate in unique:
        episode = (getattr(candidate, "review_context", None) or {}).get("physical_episode") or {}
        revisions.setdefault(group(candidate), []).append(str(episode.get("source_revision") or candidate.event_id))
    rows: list[dict[str, Any]] = []
    seen: dict[tuple[Any, ...], int] = {}
    for candidate in unique:
        handle = (candidate.event_id, candidate.source, candidate.created_at)
        seen[handle] = seen.get(handle, 0) + 1  # order-independent handle; equal copies stay distinct
        bundle: Any = getattr(candidate, "bundle", None)
        payload = bundle.to_dict() if hasattr(bundle, "to_dict") else repr(bundle)
        episode = (getattr(candidate, "review_context", None) or {}).get("physical_episode") or {}
        country = str(getattr(bundle, "country", "") or "").strip()
        rows.append({
            "binding": {"event_group_id": group(candidate) or "unidentified",
                        "event_revision_sha256": _sha(sorted(revisions[group(candidate)])),
                        "opportunity_id": _sha([*handle, seen[handle]]),
                        "bundle_sha256": _sha(payload), "policy_sha256": POLICY_SHA256},
            "hazard": str(episode.get("hazard") or getattr(bundle, "signal_kind", "") or candidate.legacy_type
                          or "unknown")[:80],
            "regions": (country[:120],) if country else (),
            "evidence": evidence_for(candidate), "source_status": "qualified",
        })
    return rows, unique


def plan(pool: Sequence[Any], *, allowance: int) -> dict[str, Any]:
    """The portfolio plan over this slate (pure)."""
    from src.editorial import portfolio, report_supply

    rows, unique = _rows(pool)
    allowance = max(0, min(int(allowance), portfolio.MAX_CHOICES))
    result = report_supply.rank(rows, allowance=allowance)
    ids = {portfolio.fingerprint(row["binding"]): candidate for row, candidate in zip(rows, unique)}
    return {**result, "candidates": ids}


def select(bot_state: Any, pool: list, *, cap: int | None, full: bool = False) -> list:
    """Portfolio order within the cap (``full`` = the refill drain's whole ordered slate)."""
    from src.orchestrator import triage as _triage
    from src.orchestrator.suppression import _current_suppression_ctx, _record_downstream_suppression

    if not pool:
        return []
    allowance = len(pool) if full or cap is None else cap
    result = plan(pool, allowance=allowance)
    if result["status"] != "planned":
        raise PortfolioRankingFailed(f"portfolio_ranking_failed:{result.get('reason', 'unknown')}")
    by_id = result["candidates"]
    chosen = [by_id[candidate_id] for candidate_id in result["selected"]]
    run_id = (_current_suppression_ctx() or {}).get("run_id")
    for candidate_id, candidate in by_id.items():
        disposition = result["dispositions"].get(candidate_id)
        if disposition == "selected":
            continue
        missing = result["missing_dimensions"].get(candidate_id) or []
        _record_downstream_suppression(
            bot_state=bot_state, source=candidate.source, run_id=run_id, event_id=candidate.event_id,
            score=candidate.score, kill_stage="portfolio_not_selected",
            kill_reason=str(disposition) + (f"; absent dimensions: {', '.join(missing)}" if missing else ""),
            summary=getattr(candidate.bundle, "where", None) or candidate.city or None)
    if full:
        return chosen
    # The existing per-category / pending-type / country caps still bind the chosen rows; order is the plan's.
    kept = {id(candidate) for candidate in _triage.select_survivors(
        bot_state, list(chosen), global_cap=cap if cap is not None else len(chosen))}
    return [candidate for candidate in chosen if id(candidate) in kept]


__all__ = ["FLAG", "PortfolioRankingFailed", "enabled", "evidence_for", "plan", "select"]
