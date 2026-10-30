"""W08: retained report → brief, translation holds, importance vector and portfolio selection.

Invented reports and candidates only; no fetch, translation service or model call.
The brief items are checked by the real evidence contract; alternatives use the
real text/media invalidation.
"""
from __future__ import annotations

import hashlib

import pytest

from src.editorial import report_supply as rsup, revisions
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.types import StoryBundle

RETAINED = ("Ficta Civil Protection said 120 households were evacuated along the Ficta River on Tuesday. "
            "Roads to Puerto Inventado remain closed.")


def report(**change):
    base = {"schema": rsup.REPORT_SCHEMA, "retrieval_status": "full_text_retained", "retained_text": RETAINED,
            "source_name": "Ficta Daily (invented)", "url": "https://example.invalid/ficta/flood",
            "source_date": "2026-10-28", "report_sha256": "c" * 64, "claims": [
                {"claim_id": "c1", "quote": "120 households were evacuated", "attribution": "Ficta Civil Protection",
                 "original_language": "en", "translation": {"status": "not_needed"},
                 "summary": "120 households evacuated"},
                {"claim_id": "c2", "quote": "Las carreteras siguen cerradas", "attribution": "Ficta municipality",
                 "original_language": "es", "translation": {"status": "unreviewed", "text": "Roads remain closed"}},
            ]}
    base.update(change)
    return base


def test_report_reaches_brief_with_quote_language_attribution_and_date():
    out = rsup.brief_items(report())
    assert [i["value"] for i in out["human_impact"]] == ["120 households were evacuated"]
    item = out["human_impact"][0]
    assert (item["attribution"], item["original_language"], item["as_of"]) == ("Ficta Civil Protection", "en", "2026-10-28")
    held = {h["claim_id"]: h["reasons"] for h in out["held_claims"]}
    assert held == {"c2": ["excerpt_not_in_retained_text", "translation_translation_unreviewed"]}
    bundle = StoryBundle(signal_kind="global_flood", where="Ficta", when="2026-10-28",
                         event_id="report_invented_ficta_2026-10-28",
                         headline_metric={"label": "households_evacuated", "value": 120},
                         current_facts=[{"label": "source_name", "value": "Ficta Daily (invented)"}],
                         raw_signal_dump={"source": "Ficta Daily (invented)"},
                         human_impact=out["human_impact"])
    assert not [i for i in audit_story_bundle(bundle).issues if i.code == "impact_entry_unwarranted"]


def test_unavailable_article_and_unsupported_excerpt_are_refused():
    out = rsup.brief_items(report(retrieval_status="unavailable"))
    assert out["human_impact"] == [] and all("full_article_unavailable" in h["reasons"] for h in out["held_claims"])
    out = rsup.brief_items(report(retrieval_status="excerpt_only"))
    assert {h["claim_id"]: h["reasons"][0] for h in out["held_claims"]}["c1"] == "unsupported_excerpt"


def test_translation_provenance_and_brazil_hold():
    reviewed = {"original_language": "pt", "quote": "Chuva forte", "translation": {
        "status": "human_reviewed", "text": "Heavy rain", "decision_ref": "review-7"}}
    state = rsup.translation_state(reviewed)
    assert state["state"] == "translation_human_reviewed" and state["independent_confirmation"] is False
    assert rsup.translation_state({"original_language": "pt", "quote": "x", "translation": {}})["state"] == "untranslated"
    ambiguous = rsup.translation_state({**reviewed, "unresolved": ["which municipality"]})
    assert ambiguous["unresolved"] == ["which municipality"]
    retained = "Chuva forte em Ficta."
    brazil = report(retained_text=retained, claims=[{**reviewed, "claim_id": "b1", "attribution": "Ficta agency",
                                                     "holds": ["brazil_forecast_translation"]}])
    assert rsup.brief_items(brazil)["held_claims"][0]["reasons"] == ["hold:brazil_forecast_translation"]


def _binding(i: int) -> dict:
    sha = hashlib.sha256(str(i).encode()).hexdigest()
    return {"event_group_id": f"group-{i}", "event_revision_sha256": sha,
            "opportunity_id": hashlib.sha256(f"opp-{i}".encode()).hexdigest(),
            "bundle_sha256": sha, "policy_sha256": "d" * 64}


def test_importance_vector_keeps_missing_dimensions_absent():
    vector = rsup.importance_vector({"evidence_type": "forecast", "return_period_years": 30})
    assert vector["impact"] is None and vector["rarity"]["score"] == 3 and vector["urgency"]["score"] == 3
    assert vector["spatial_scale"] is None and vector["persistence"] is None  # absent, never zero
    observed = rsup.importance_vector({"evidence_type": "observed", "sourced_consequences": ["a", "b"],
                                       "magnitude_percentile": 99.5})
    assert observed["impact"]["score"] == 2 and observed["rarity"]["reason"].startswith("percentile")


def test_ranking_selects_within_allowance_and_failure_buys_nothing():
    full = {"evidence_type": "observed", "sourced_consequences": ["x"], "return_period_years": 50, "affected_places": 3,
            "duration_days": 2, "novel": True, "headline": True, "current": True}
    candidates = [
        {"binding": _binding(1), "hazard": "flood", "regions": ("Ficta",), "evidence": full},
        {"binding": _binding(2), "hazard": "heat", "regions": ("Inventia",), "evidence": {**full, "return_period_years": 6}},
        {"binding": _binding(3), "hazard": "fire", "regions": ("Ficta",), "evidence": {"evidence_type": "forecast"}},
        {"binding": _binding(4), "hazard": "fire", "regions": ("Ficta",), "evidence": full, "source_status": "endpoint_missing"},
    ]
    result = rsup.rank(candidates, allowance=1)
    assert result["status"] == "planned" and len(result["selected"]) == 1 and result["quota"] is None
    assert result["excluded"] == [{"candidate": _binding(4)["opportunity_id"], "disposition": "source_not_qualified",
                                   "reason": "endpoint_missing"}]
    assert "assessment_incomplete" in result["dispositions"].values()
    broken = rsup.rank([{**candidates[0], "binding": {**_binding(1), "policy_sha256": "nothex"}}], allowance=1)
    assert broken == {"status": "ranking_failed", "reason": "portfolio_binding_invalid", "selected": [],
                      "paid_selection": False, "excluded": []}


def test_alternatives_need_the_explicit_allowance_and_selection_invalidates_review():
    vector = rsup.importance_vector({"evidence_type": "observed", "sourced_consequences": ["x"], "return_period_years": 40})
    assert rsup.alternative_eligible(vector, allowance_document=None)["routine"] == "one_sample_revise0"
    assert rsup.alternative_eligible(rsup.importance_vector({}), allowance_document={})["reason"] == "importance_basis_incomplete"
    assert rsup.alternative_eligible(vector, allowance_document={"kind": "important_event_two_angles_v1"})["eligible"]
    draft = {"id": "d1", "text": "Angle one text about Ficta flooding.", "event_id": "e1", "type": "global_flood",
             "status": "pending", "review_context": {}}
    revisions.initialize_revision(draft)
    revisions.record_human_review(draft)
    assert revisions.review_is_current(draft)
    draft["media_attachment"] = {"kind": "invented_graphic_for_angle_one"}
    before = revisions.draft_identity(draft)
    rsup.select_alternative(draft, "Angle two text about Ficta evacuations.")
    assert "media_attachment" not in draft and not revisions.review_is_current(draft)
    assert revisions.draft_identity(draft)["content_revision"] > before["content_revision"]
    with pytest.raises(ValueError):
        rsup.select_alternative(draft, "")
