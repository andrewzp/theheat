"""Report acquisition-to-brief, translation holds, importance and portfolio joins (W08).

Pure and offline: no fetch, translation service, model or paid stage. Ranking is
a decision over qualified evidence (``editorial.portfolio``), never another paid
opinion. Routine production stays one writer sample, revise0; important
alternatives use only the existing explicit allowance (``two_bot.important_variants``).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import hashlib
import json
import os
from pathlib import Path
import re
from itertools import islice

from src.editorial import portfolio

REPORT_SCHEMA = "theheat.retained-report-brief/v1"
RETRIEVAL = frozenset({"full_text_retained", "excerpt_only", "unavailable"})
TRANSLATION = frozenset({"not_needed", "unreviewed", "human_reviewed"})
# Named, record-specific holds that supplied evidence alone may clear.
REPORT_HOLDS = {"brazil_forecast_translation": "Brazil forecast/translation hold: corrected evidence has not been supplied."}


def _text(value: Any, limit: int = 1000) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def translation_state(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic provenance: original text, translation identity, what is unresolved."""
    language = claim.get("original_language")
    raw_translation = claim.get("translation")
    translation: Mapping[str, Any] = raw_translation if isinstance(raw_translation, Mapping) else {}
    status = translation.get("status")
    unresolved = [str(u) for u in claim.get("unresolved") or [] if _text(u, 200)]
    if language == "en" and status in (None, "not_needed"):
        state = "source_language"
    elif status == "human_reviewed" and _text(translation.get("text")) and _text(translation.get("decision_ref"), 200):
        state = "translation_human_reviewed"
    elif status == "unreviewed" and _text(translation.get("text")):
        state = "translation_unreviewed"
    else:
        state = "untranslated"
    return {"state": state, "original_language": language, "original_text": claim.get("quote"),
            "translated_text": translation.get("text"), "translation_identity": translation.get("decision_ref"),
            "unresolved": unresolved,
            # A translation (model or human) is never independent confirmation of the report.
            "independent_confirmation": False}


def brief_items(report: Mapping[str, Any]) -> dict[str, Any]:
    """Retained report → ordinary-brief ``human_impact`` items plus refusals kept for the editor."""
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError("report_schema")
    retrieval = report.get("retrieval_status")
    if retrieval not in RETRIEVAL:
        raise ValueError("report_retrieval_status")
    retained = report.get("retained_text") if retrieval == "full_text_retained" else None
    retained_valid = _text(retained, 4 * 1024 * 1024)
    items, held = [], []
    for claim in report.get("claims") or []:
        reasons = []
        if retrieval == "unavailable" or (retrieval == "full_text_retained" and not retained_valid):
            reasons.append("full_article_unavailable")
        quote = claim.get("quote")
        if not _text(quote, 500):
            reasons.append("quote_missing")
        elif retained_valid and isinstance(retained, str) and quote not in retained:
            reasons.append("excerpt_not_in_retained_text")
        elif retrieval == "excerpt_only" and not claim.get("excerpt_attested"):
            reasons.append("unsupported_excerpt")
        if not _text(claim.get("attribution"), 200):
            reasons.append("attribution_missing")
        if not _text(report.get("source_date"), 40):
            reasons.append("source_date_missing")
        for hold in claim.get("holds") or []:
            if hold in REPORT_HOLDS:
                reasons.append(f"hold:{hold}")
        translation = translation_state(claim)
        if translation["state"] in {"untranslated", "translation_unreviewed"} or translation["unresolved"]:
            reasons.append(f"translation_{translation['state']}" if not translation["unresolved"] else "ambiguity_unresolved")
        if reasons:
            held.append({"claim_id": claim.get("claim_id"), "reasons": reasons, "translation": translation})
            continue
        items.append({
            "claim": translation["translated_text"] if translation["state"] == "translation_human_reviewed" else quote,
            "value": quote, "claim_id": claim.get("claim_id"), "source_name": report.get("source_name"),
            "url": report.get("url"), "as_of": report.get("source_date"), "attribution": claim.get("attribution"),
            "original_language": claim.get("original_language"), "translation": translation,
            "retrieval_status": retrieval, "report_sha256": report.get("report_sha256"),
            "evidence_class": "attributed_report_statement",
        })
    return {"human_impact": items, "held_claims": held,
            "scope": "Attributed report statements only; not observations or adjudicated impacts."}


PACKET_DIRECTORY_ENV = "THEHEAT_RETAINED_REPORT_PACKETS"
MAX_PACKET_BYTES = 4 * 1024 * 1024
MAX_PACKET_FILES = 16


def _packet_items(packet: Mapping[str, Any], candidate: Any) -> list[dict[str, Any]]:
    """Exact explicit joins; neither geographic resemblance nor report text is authority."""
    from src.editorial.hazard_episodes import writer_statements, SCHEMA
    from src.two_bot.bundle_capture import capture_bundle

    bundle = candidate.bundle
    raw = bundle.raw_signal_dump or {}
    if bundle.signal_kind in {"nhc_advisory", "official_warning", "severe_weather"} or "physical_episode" in raw:
        raise ValueError("report_immutable_bundle")
    digest = hashlib.sha256(capture_bundle(bundle).serialized.encode()).hexdigest()
    if packet.get("bundle_sha256") != digest:
        raise ValueError("report_candidate_changed")
    report = packet.get("report")
    if not isinstance(report, dict):
        raise ValueError("report_missing")
    text = report.get("retained_text")
    if (report.get("retrieval_status") != "full_text_retained" or not isinstance(text, str) or not _text(text, MAX_PACKET_BYTES)
            or report.get("retained_text_sha256") != hashlib.sha256(text.encode()).hexdigest()):
        raise ValueError("report_retained_text_identity")
    if (not re.fullmatch(r"[0-9a-f]{64}", str(report.get("report_sha256")))
            or not _text(report.get("source_name"), 200) or not _text(report.get("url"), 2000)):
        raise ValueError("report_source_identity")
    selected = packet.get("selected_claim_ids")
    if (not isinstance(selected, list) or not selected or len(selected) > 5
            or any(not _text(value, 100) for value in selected) or len(set(selected)) != len(selected)):
        raise ValueError("report_claim_selection")
    claims = report.get("claims")
    if not isinstance(claims, list) or any(not isinstance(c, dict) for c in claims):
        raise ValueError("report_claims")
    ids = [c.get("claim_id") for c in claims]
    if any(not _text(value, 100) for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("report_claim_identity")
    qualified = brief_items(report)
    items = [item for item in qualified["human_impact"] if item["claim_id"] in selected]
    if len(items) != len(selected):
        raise ValueError("report_selected_claim_held")
    episode = (candidate.review_context or {}).get("physical_episode") or {}
    joins = packet.get("join_ids") or []
    if episode or joins:
        ledger = packet.get("episode_ledger")
        if (not isinstance(ledger, dict) or ledger.get("schema") != SCHEMA or not isinstance(joins, list)
                or not joins or len(joins) != len(set(joins))):
            raise ValueError("report_join_unavailable")
        statements = [row for row in writer_statements(ledger, str(episode.get("episode_id") or ""))
                      if row["join_id"] in joins and row["report_sha256"] == report["report_sha256"]]
        if len(statements) != len(joins):
            raise ValueError("report_join_unavailable")
        for item in items:
            matches = [row for row in statements if row["statement"] == item["value"]
                       and row["attribution"] == item["attribution"] and row["claim_id"] == item["claim_id"]]
            if len(matches) != 1:
                raise ValueError("report_claim_join_mismatch")
            item["physical_join_id"] = matches[0]["join_id"]
            item["physical_episode_id"] = episode["episode_id"]
            item["claim_window"] = matches[0]["time"]
    for item in items:
        item["retained_text_sha256"] = report["retained_text_sha256"]
        item["target_bundle_sha256"] = digest
    return items


def attach_supplied_reports(queue: Sequence[Any], *, max_items: int) -> set[int]:
    """Ordinary enrichment consumer of bounded, locally supplied retained report packets.

    Called under the existing news-enrichment controls. Absent directory means no
    reads. The supplied report hash is a reference, not authentication; the separate
    retained-text digest binds the quotes. No fetch, inference, or independent confirmation.
    """
    directory = os.environ.get(PACKET_DIRECTORY_ENV)
    if not directory:
        return set()
    enriched: set[int] = set()
    # Re-enrichment starts from the original supplied-fact-free queue bundle.
    # This also withdraws a previously attached claim when its join is removed.
    for candidate in queue:
        candidate.bundle.human_impact = [item for item in candidate.bundle.human_impact or []
            if not (isinstance(item, dict) and item.get("target_bundle_sha256")
                    and item.get("evidence_class") == "attributed_report_statement")]
    try:
        paths = list(islice(Path(directory).iterdir(), MAX_PACKET_FILES + 1))
        if len(paths) > MAX_PACKET_FILES:
            raise ValueError("report_packet_count_limit")
        total, packets = 0, []
        for path in sorted(paths):
            if path.suffix != ".json" or path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as handle:
                content = handle.read(MAX_PACKET_BYTES + 1)
            total += len(content)
            if len(content) > MAX_PACKET_BYTES or total > 2 * MAX_PACKET_BYTES:
                raise ValueError("report_packet_byte_limit")
            packet = json.loads(content)
            if isinstance(packet, dict):
                packets.append(packet)
        for candidate in queue:
            matches = [p for p in packets if p.get("target_event_id") == candidate.event_id]
            if not matches:
                continue
            try:
                if len(matches) != 1 or sum(c.event_id == candidate.event_id for c in queue) != 1:
                    raise ValueError("report_target_ambiguous")
                items = _packet_items(matches[0], candidate)
                existing = list(candidate.bundle.human_impact or [])
                if len(existing) + len(items) > max_items:
                    raise ValueError("report_fact_limit")
                candidate.bundle.human_impact = [*existing, *items]
                enriched.add(id(candidate))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                candidate.review_context.setdefault("retained_report_holds", []).append(str(exc))
    except (OSError, ValueError, TypeError) as exc:
        for candidate in queue:
            candidate.review_context.setdefault("retained_report_holds", []).append(str(exc))
    return enriched


# --- 08.3 importance vector ----------------------------------------------------------------
def importance_vector(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Supported dimensions in the existing portfolio schema; missing stays None, never 0.

    ``evidence`` carries already-qualified facts: ``magnitude_percentile`` (local
    baseline), ``duration_days``, ``affected_places``, ``return_period_years``,
    ``sourced_consequences`` (attributed statements), ``evidence_type``, ``novel``.
    """
    def dim(score: int | None, reason: str) -> dict[str, Any] | None:
        return None if score is None else {"score": max(0, min(4, score)), "reason": reason}

    observed = evidence.get("evidence_type") in {"observed", "official_event_report", "satellite_derived"}
    pct = evidence.get("magnitude_percentile")
    rp = evidence.get("return_period_years")
    places = evidence.get("affected_places")
    days = evidence.get("duration_days")
    consequences = evidence.get("sourced_consequences")
    return {
        # Impact needs a sourced consequence; a forecast alone cannot supply one.
        "impact": dim(min(4, len(consequences)) if isinstance(consequences, list) and consequences and observed
                      else None, "attributed consequence statements"),
        "rarity": _rarity(rp, pct, dim),
        "spatial_scale": _band(places if type(places) is int else None, (20, 5, 2), dim, "qualified affected places"),
        "persistence": _band(days if type(days) in {int, float} else None, (7, 3, 2), dim, "duration in days"),
        "novelty": dim(None if evidence.get("novel") is None else (3 if evidence["novel"] else 0), "new material facts"),
        "urgency": dim(3, "forecast or warning lead time") if evidence.get("evidence_type") in {
            "forecast", "official_warning"} else dim(2 if evidence.get("current") is True else None,
                                                     "current qualified observation"),
        "evidence_quality": dim(3 if observed else 2 if evidence.get("evidence_type") else None, "evidence type"),
        "clear_angle": dim(2 if evidence.get("headline") else None, "single clear headline fact"),
    }


def _band(value: float | None, edges: tuple[float, float, float], dim, reason: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return dim(4 if value >= edges[0] else 3 if value >= edges[1] else 2 if value >= edges[2] else 1, reason)


def _rarity(rp: Any, pct: Any, dim) -> dict[str, Any] | None:
    """Rarity against the place's own record or baseline; no single floor across climates."""
    if type(rp) in {int, float}:
        return dim(4 if rp >= 100 else 3 if rp >= 25 else 2 if rp >= 5 else 1, "return period against the local record")
    if type(pct) in {int, float}:
        return dim(4 if pct >= 99.9 else 3 if pct >= 99 else 2 if pct >= 95 else 1, "percentile against the local baseline")
    return None


def rank(candidates: Sequence[Mapping[str, Any]], *, allowance: int) -> dict[str, Any]:
    """Portfolio selection over qualified candidates within the existing allowance.

    A source/error status is never turned into a low score: such candidates are
    excluded with their reason. A ranking failure selects nothing (no paid stage).
    """
    planning, excluded = [], []
    for row in candidates:
        if row.get("source_status") not in (None, "qualified"):
            excluded.append({"candidate": (row.get("binding") or {}).get("opportunity_id"),
                             "disposition": "source_not_qualified",
                             "reason": row.get("source_status")})
            continue
        planning.append(portfolio.PlanningCandidate(
            binding=dict(row["binding"]), hazard=str(row["hazard"]), regions=tuple(row.get("regions") or ()),
            dimensions=importance_vector(row.get("evidence") or {}),
            exceptional_reason=row.get("exceptional_reason"),
            required_dimensions=("urgency", "evidence_quality", "clear_angle")
            if (row.get("evidence") or {}).get("qualified_warning") is True else portfolio.DIMENSIONS))
    try:
        plan = portfolio.plan_portfolio(planning, writing_attempts=allowance)
    except portfolio.PortfolioError as exc:
        return {"status": "ranking_failed", "reason": str(exc), "selected": [], "paid_selection": False,
                "excluded": excluded}
    return {"status": "planned", "selected": plan["selected_candidate_ids"], "paid_selection": bool(
        plan["selected_candidate_ids"]), "plan_sha256": plan["plan_sha256"], "excluded": excluded,
        "dispositions": {row["candidate_id"]: row["disposition"] for row in plan["candidates"]},
        "missing_dimensions": {row["candidate_id"]: row["missing_dimensions"] for row in plan["candidates"]},
        "quota": None}


# --- 08.5 important alternatives -------------------------------------------------------------
def alternative_eligible(vector: Mapping[str, Any], *, allowance_document: Mapping[str, Any] | None) -> dict[str, Any]:
    """Two angles only with the existing explicit allowance and a complete importance basis."""
    if allowance_document is None:
        return {"eligible": False, "reason": "no_explicit_allowance", "routine": "one_sample_revise0"}
    missing = [key for key in ("impact", "rarity") if vector.get(key) is None]
    if missing:
        return {"eligible": False, "reason": "importance_basis_incomplete", "missing": missing}
    return {"eligible": True, "reason": "explicit_allowance_and_importance_basis"}


def select_alternative(draft: dict[str, Any], chosen_text: str) -> dict[str, Any]:
    """Choosing either angle is a text revision: stale review, approval and media are invalidated."""
    from datetime import UTC, datetime

    from src.editorial.revisions import invalidate_media_attachment, invalidate_text

    at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if "media_attachment" in draft:
        invalidate_media_attachment(draft, None, at=at)  # the old graphic described the other angle
    return invalidate_text(draft, chosen_text, at=at)


__all__ = ["REPORT_HOLDS", "REPORT_SCHEMA", "alternative_eligible", "brief_items", "importance_vector", "rank",
           "select_alternative", "translation_state"]
