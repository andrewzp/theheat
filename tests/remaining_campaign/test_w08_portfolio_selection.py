"""W08.3/08.4: the importance vector and portfolio planner on the ordinary triage drain.

Invented slates only; the writer dispatch is a recording fake (no model, no network).
``THEHEAT_PORTFOLIO_SELECTION`` is default off: off, the drain's selection is exactly
the legacy ``triage.select_survivors`` result. On, the same cap and the existing caps
apply; missing dimensions stay absent; a ranking failure buys no writer.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import cast

import pytest

from src.editorial import report_supply
from src.editorial.scoring._shared import EditorialScore
from src.orchestrator import common, portfolio_selection, triage
from src.state import DEFAULT_STATE
from src.state_schema import BotState
from src.two_bot.types import StoryBundle, TriageCandidateBundle
from tests.live_content_harness import trap_network

IMPACT = {"claim": "Invented: 40 homes evacuated in Ficta.", "value": 40, "source_name": "Invented Civil Agency",
          "url": "https://invented.example/notice", "as_of": "2026-10-29"}


def candidate(event_id, *, total=80, kind="flood", country="FX", complete=True, created="2026-10-29T06:00:00Z",
              places=2, rp=30.0, days=4.0):
    raw = {"evidence_type": "official_event_report"}
    if complete:
        raw.update(return_period_years=rp, duration_days=days)
    bundle = StoryBundle(signal_kind=kind, where=f"Ficta {event_id}", when="2026-10-29", event_id=event_id,
                         headline_metric={"label": "area", "value": 10}, current_facts=[],
                         human_impact=[dict(IMPACT)] if complete else [], raw_signal_dump=raw, country=country)
    review = {"physical_episode": {"episode_id": f"ep1:{kind}:gdacs:{event_id}", "source_revision": "a" * 64,
                                   "hazard": kind, "evidence_type": "official_event_report",
                                   "material": {"places": [f"P{i}" for i in range(places)]},
                                   "eligibility": ["new_episode"]}}
    score = EditorialScore(category=kind, severity=80, novelty=80, timeliness=80, confidence=80, shareability=80,
                           sensitivity=0, total=total, threshold=60, reasons=[])
    return TriageCandidateBundle(bundle=bundle, score=score, event_id=event_id, source="gdacs", review_context=review,
                                 city="", tweet_date="2026-10-29", cooldown_exempt=False, legacy_type="global_disaster",
                                 created_at=created)


def slate():
    return [candidate("loud-incomplete", total=99, complete=False), candidate("rare-flood", total=70, rp=200.0),
            candidate("long-fire", total=75, kind="fire", days=9.0, country="EX"),
            candidate("small-flood", total=72, rp=6.0, days=2.0, places=1), candidate("quake", total=90, kind="earthquake")]


@pytest.fixture
def drain(monkeypatch):
    trap_network(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.delenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", raising=False)
    monkeypatch.delenv(portfolio_selection.FLAG, raising=False)

    def run(queue):
        state: dict = deepcopy(dict(DEFAULT_STATE))
        state["_triage_queue"] = queue
        written: list[str] = []

        def fake_try(bundle, bot_state, score, **kwargs):
            written.append(bundle.event_id)
            return True

        monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
        current_run = {"id": "invented-run-w08", "sources": []}
        common._drain_and_write_triage_queue(cast(BotState, state), current_run)
        return written, state, current_run
    run.patch = monkeypatch  # type: ignore[attr-defined]
    return run


def _legacy(queue):
    state = deepcopy(DEFAULT_STATE)
    return [c.event_id for c in triage.select_survivors(state, queue, global_cap=triage.MAX_DRAFTS_PER_CYCLE)]


def test_flag_off_selection_is_exactly_the_legacy_selector(drain):
    drain.patch.setattr(portfolio_selection, "select", lambda *a, **k: pytest.fail("portfolio must not run when off"))
    written, state, _ = drain(slate())
    assert written == _legacy(slate()) == ["loud-incomplete", "quake", "long-fire"]
    assert not any(s["stage"] == "portfolio_not_selected" for s in state["suppressions"])


def test_flag_on_ranks_complete_vectors_within_the_same_cap(drain):
    drain.patch.setenv(portfolio_selection.FLAG, "1")
    written, state, _ = drain(slate())
    assert len(written) <= triage.MAX_DRAFTS_PER_CYCLE  # the existing cap and budget are unchanged
    assert "loud-incomplete" not in written and written[0] == "rare-flood"
    misses = {s["event_id"]: s["reasons"][0] for s in state["suppressions"] if s["stage"] == "portfolio_not_selected"}
    # The loudest legacy score has no rarity/impact/persistence evidence: absent, not a low score.
    assert misses["loud-incomplete"].startswith("assessment_incomplete; absent dimensions: impact, rarity")
    assert set(misses) | set(written) == {c.event_id for c in slate()}


def test_missing_dimensions_stay_absent_and_there_is_no_regional_quota(drain):
    vector = report_supply.importance_vector(portfolio_selection.evidence_for(candidate("x", complete=False)))
    assert vector["impact"] is None and vector["rarity"] is None and vector["persistence"] is None
    assert all(v is None or v["score"] > 0 for v in vector.values())  # nothing became a zero
    drain.patch.setenv(portfolio_selection.FLAG, "1")
    same_place = [candidate(f"fx-{kind}", kind=kind, country="FX") for kind in ("flood", "fire", "earthquake")]
    written, _, _ = drain(same_place)
    assert sorted(written) == ["fx-earthquake", "fx-fire", "fx-flood"]  # one country fills the allowance: no quota
    # The existing per-category cap still binds the plan's choice (two floods of three are kept).
    floods = [candidate(f"fl-{i}", rp=30.0 + i) for i in range(3)]
    assert len(drain(floods)[0]) == triage._per_category_cap()


def test_ranking_failure_holds_the_slate_with_a_visible_reason(drain):
    drain.patch.setenv(portfolio_selection.FLAG, "1")
    oversized = [candidate(f"c{i:03d}") for i in range(129)]  # above the planner's bounded slate
    written, state, current_run = drain(oversized)
    assert written == []
    row = next(r for r in current_run["sources"] if r["source"] == "triage")
    assert row["status"] == "partial_failure" and "portfolio_ranking_failed" in row["note"]
    assert row["error"] == "portfolio_ranking_failed:portfolio_candidates_invalid"
    assert any(s["stage"] == "triage_error" for s in state["suppressions"])


def test_refill_drain_uses_the_portfolio_order_and_holds_on_failure(drain):
    drain.patch.setenv("THEHEAT_REFILL_ENABLED", "1")
    drain.patch.setenv(portfolio_selection.FLAG, "1")
    written, _, _ = drain(slate())
    assert written and written[0] == "rare-flood" and "loud-incomplete" not in written
    written, _, current_run = drain([candidate(f"c{i:03d}") for i in range(129)])
    assert written == [] and any(r.get("error", "").startswith("portfolio_ranking_failed")
                                 for r in current_run["sources"])


def test_plan_is_deterministic_and_reports_no_quota(drain):
    first = portfolio_selection.plan(slate(), allowance=3)
    second = portfolio_selection.plan(list(reversed(slate())), allowance=3)
    chosen = [[plan["candidates"][cid].event_id for cid in plan["selected"]] for plan in (first, second)]
    assert chosen[0] == chosen[1] and first["quota"] is None
    assert json.dumps(first["missing_dimensions"], sort_keys=True) == json.dumps(second["missing_dimensions"],
                                                                                 sort_keys=True)
