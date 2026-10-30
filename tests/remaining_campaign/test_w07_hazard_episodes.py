"""W07: source-scoped episodes for non-cyclone hazards, operator corrections and dependent invalidation.

Invented assertions only. The dependent-draft journey uses the real W05 runner,
drain and pipeline (offline model fakes) and the real approval revocation.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.editorial import hazard_episodes as he, revisions
from tests.remaining_campaign.test_w05_regional_observed import _produce, aemet_packet
from tests.remaining_campaign.test_w05_regional_observed import offline as offline  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
WINDOW = ["2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z"]


def fire(source_id, **extra):
    return {"hazard": "fire", "issuer": "nifc", "source_event_id": source_id, "candidate_id": f"cand-{source_id}",
            "evidence_type": "official_flood_report", "value": 100.0, **extra}


# --- 07.1 identity ------------------------------------------------------------------------
def test_identity_layers_are_distinct_and_names_never_collide():
    a = {"hazard": "flood", "issuer": "gdacs", "source_event_id": "FL-1001", "name": "Ficta River flood",
         "candidate_id": "cand-1"}
    b = {**a, "source_event_id": "FL-2002", "country_code": "BR"}
    assert he.episode_key(a) != he.episode_key(b)  # same display name, other issuer ID
    anon_x = {"hazard": "fire", "issuer": "firms", "country_code": "AU", "place_id": "ux1", "start_date": "2026-10-28"}
    anon_y = {**anon_x, "country_code": "US"}
    assert he.episode_key(anon_x) != he.episode_key(anon_y)
    with pytest.raises(ValueError, match="episode_identity_unsupported"):
        he.episode_key({"hazard": "fire", "issuer": "firms", "name": "Ficta Fire"})
    lin = he.lineage(a, publication_id="draft-9")
    assert len({lin["candidate_id"], lin["source_revision"], lin["episode_id"], lin["publication_id"]}) == 4
    ledger = he.empty_ledger()
    first = he.assign(ledger, a)
    revised = he.assign(ledger, {**a, "value": 3.0})
    assert first["episode_id"] == revised["episode_id"] and revised["changed"]
    history = ledger["episodes"][first["episode_id"]]["history"]
    assert [h["added"] for h in history] == [first["source_revision"], revised["source_revision"]]
    assert history[1]["supersedes_member"] == first["source_revision"]  # old revision kept, not erased


# --- 07.2 conservative joins --------------------------------------------------------------
def test_cross_border_joins_need_identifiers_or_geometry_and_time():
    ledger = he.empty_ledger()
    x = he.assign(ledger, {"hazard": "flood", "issuer": "gdacs", "source_event_id": "FL-1"})["episode_id"]
    y = he.assign(ledger, {"hazard": "flood", "issuer": "copernicus_ems", "source_event_id": "EMSR900"})["episode_id"]
    z = he.assign(ledger, {"hazard": "fire", "issuer": "nifc", "source_event_id": "F-1"})["episode_id"]
    assert he.propose_join(ledger, x, y, geometry_overlap=True)["decision"] == "proposed_only"
    joined = he.propose_join(ledger, x, y, geometry_overlap=True, time_overlap=True)
    assert joined["decision"] == "joined" and joined["impacts_combined"] is False
    assert set(joined["contributors"]) == {"gdacs", "copernicus_ems"}
    assert he.propose_join(ledger, x, z, shared_identifier="GLIDE-X")["reason"] == "different_hazards_never_merge"


# --- 07.3 split / reassign / supersede ----------------------------------------------------
def test_operator_corrections_need_expected_revision_and_keep_origin():
    ledger = he.empty_ledger()
    ep = he.assign(ledger, fire("F-77"))["episode_id"]
    second = he.assign(ledger, fire("F-77", value=140.0, candidate_id="cand-b"))["source_revision"]
    with pytest.raises(ValueError, match="expected_revision_mismatch"):
        he.split(ledger, ep, [second], new_source_id="F-77b", expected_revision=1, actor="op")
    result = he.split(ledger, ep, [second], new_source_id="F-77b", expected_revision=2, actor="op")
    new = ledger["episodes"][result["to"]]
    assert new["history"][0]["split_from"] == ep and new["members"][0]["source_revision"] == second
    other = he.assign(ledger, fire("F-88"))["episode_id"]
    he.assign(ledger, fire("F-88", value=1.0, candidate_id="c2"))
    moved = ledger["episodes"][other]["members"][1]["source_revision"]
    he.reassign(ledger, moved, source_episode=other, target_episode=ep, actor="op",
                expected_revisions={other: 2, ep: 3})
    he.supersede(ledger, other, ep, expected_revision=3, actor="op")
    assert ledger["episodes"][other]["status"] == "superseded"
    assert [op["kind"] for op in ledger["operations"]][-3:] == ["assign", "reassign", "supersede"]


def test_libya_and_thailand_stay_held_without_supplied_evidence():
    ledger = he.empty_ledger()
    ep = he.assign(ledger, fire("HOLD-1", historical_hold="libya"))["episode_id"]
    rev = he.assign(ledger, fire("HOLD-1", value=9.0, historical_hold="libya", candidate_id="x"))["source_revision"]
    with pytest.raises(ValueError, match="historical_hold:libya"):
        he.split(ledger, ep, [rev], new_source_id="HOLD-1b", expected_revision=2, actor="op")
    assert set(he.HISTORICAL_HOLDS) == {"libya", "thailand"}


# --- 07.4 / 07.5 lifecycle and material updates -------------------------------------------
def test_repeated_polls_buy_no_writer_and_tier_or_retrieval_alone_is_not_material():
    ledger = he.empty_ledger()
    base = {"hazard": "disaster", "issuer": "gdacs", "source_event_id": "EQ-5", "value": 6.1, "tier": "orange",
            "places": ["ux1"], "retrieved_at": "2026-10-28T06:00:00Z"}
    assert he.poll(ledger, base)["writer_opportunity"] is True
    assert he.poll(ledger, base)["writer_opportunity"] is False  # identical revision
    tier_only = he.poll(ledger, {**base, "tier": "red", "list_length": 9})
    assert tier_only["changed"] and not tier_only["writer_opportunity"]
    assert tier_only["eligibility"]["reasons"] == ["no_new_material_facts"]
    assert set(tier_only["eligibility"]["ignored_changes"]) == {"tier", "list_length"}
    assert he.poll(ledger, {**base, "value": 7.4})["writer_opportunity"] is True
    assert he.material_update(base, {**base, "value": 9.0}, delivery="unknown")["reasons"] == ["unknown_delivery_fence"]


# --- 07.6 report↔physical joins -------------------------------------------------------------
def test_report_joins_feed_only_matched_statements_and_are_removable():
    ledger = he.empty_ledger()
    ep = he.assign(ledger, {"hazard": "flood", "issuer": "gdacs", "source_event_id": "FL-7"})["episode_id"]
    claim = {"claim_kind": "flood_occurring", "place_id": "ux9", "window": WINDOW, "text": "Streets flooded in Ficta",
             "attribution": "Ficta civil protection"}
    matched = he.join_report(ledger, report_sha256="a" * 64, claim=claim, episode_id=ep, actor="op",
                             observation={"evidence_type": "gauge_observed", "place_id": "ux9", "window": WINDOW})
    unmatched = he.join_report(ledger, report_sha256="b" * 64, claim={**claim, "claim_kind": "vegetation_fire"},
                               observation={"evidence_type": "thermal_detection", "place_id": "ux9", "window": WINDOW},
                               episode_id=ep, actor="op")
    assert matched["status"] == "matched" and unmatched["status"] == "report_claim_only"
    statements = he.writer_statements(ledger, ep)
    assert statements == [{"statement": "Streets flooded in Ficta", "attribution": "Ficta civil protection",
                           "time": WINDOW, "evidence_class": "report_claim_matched_to_observation"}]
    he.remove_join(ledger, matched["join_id"], actor="op")
    assert he.writer_statements(ledger, ep) == [] and ledger["report_joins"][0]["report_sha256"] == "a" * 64


# --- consumer journey: real drafts, CLI split, real approval revocation ---------------------
def test_split_through_the_cli_revokes_pending_dependents_but_keeps_delivered(offline, tmp_path):  # noqa: F811
    state, _run, _details, _sent = _produce(offline, [aemet_packet()])
    drafts = [d for d in state["drafts"] if (d.get("review_context") or {}).get("source_key") == "regional_observed"]
    # The registered-point station saves; the distinct nearby point is refused at save (unregistered place).
    assert len(drafts) == 1
    binding = drafts[0]["review_context"]["physical_episode"]
    assert binding["episode_id"].startswith("ep1:heat:aemet:anon:ES:pl0322:")
    revisions.initialize_revision(drafts[0])
    revisions.record_human_review(drafts[0])
    drafts[0]["approval_mode"] = "auto"
    delivered = deepcopy(drafts[0])  # an already delivered snapshot bound to the same episode
    delivered.update(id="delivered-snapshot", status="posted")
    state["drafts"].append(delivered)
    drafts.append(delivered)
    ledger = he.empty_ledger()
    for draft in drafts:
        he.assign(ledger, {"hazard": "heat", "issuer": "aemet", "country_code": "ES",
                           "place_id": binding["episode_id"].split(":")[5], "start_date": "2026-10-28",
                           "candidate_id": draft["id"], "station_revision": draft["id"]})
    (tmp_path / "ledger.json").write_text(json.dumps(ledger))
    (tmp_path / "state.json").write_text(json.dumps(state, default=str))
    moving = ledger["episodes"][binding["episode_id"]]["members"][1]["source_revision"]
    result = subprocess.run([sys.executable, str(ROOT / "scripts/hazard_episodes.py"), "--ledger",
                             str(tmp_path / "ledger.json"), "--state", str(tmp_path / "state.json"), "split",
                             "--episode", binding["episode_id"], "--revision", moving, "--new-source-id", "corr-1",
                             "--expected", "2"], capture_output=True, text=True, cwd=ROOT,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    assert out["dependents"] == {"invalidated": [drafts[0]["id"]], "preserved_delivered": [drafts[1]["id"]]}
    saved = {d["id"]: d for d in json.loads((tmp_path / "state.json").read_text())["drafts"]}
    assert saved[drafts[0]["id"]]["approval_mode"] == "manual" and not revisions.review_is_current(saved[drafts[0]["id"]])
    assert saved[drafts[1]["id"]]["status"] == "posted" and saved[drafts[1]["id"]]["approval_mode"] == "auto"
    stale = subprocess.run([sys.executable, str(ROOT / "scripts/hazard_episodes.py"), "--ledger",
                            str(tmp_path / "ledger.json"), "split", "--episode", binding["episode_id"], "--revision",
                            moving, "--new-source-id", "corr-2", "--expected", "2"], capture_output=True, text=True,
                           cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, timeout=60, check=False)
    assert stale.returncode == 2 and "expected_revision_mismatch" in stale.stdout
