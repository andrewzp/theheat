"""Invented retained episodes through the real operator and writer projections."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.editorial import hazard_episodes as he
from src.editorial import revisions

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ["2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z"]


def episode(hold=None):
    ledger = he.empty_ledger()
    assertion = {"hazard": "flood", "issuer": "invented", "source_event_id": "F-1",
                 "candidate_id": "invented-a", "historical_hold": hold, "value": 10}
    first = he.assign(ledger, assertion)
    second = he.assign(ledger, {**assertion, "candidate_id": "invented-b", "value": 20})
    return ledger, first["episode_id"], second["source_revision"], assertion


def matched_statement(ledger, key):
    # An explicit offline join input exercises the existing consumer. It is not
    # source evidence, actual weather, a human review or publication authority.
    he.join_report(ledger, episode_id=key, report_sha256="b" * 64, actor="invented",
                   claim={"claim_kind": "flood_occurring", "place_id": "invented-place", "window": WINDOW,
                          "text": "Invented fixture report.", "attribution": "Invented source"},
                   observation={"evidence_type": "gauge_observed", "place_id": "invented-place", "window": WINDOW})


@pytest.mark.parametrize("hold", ["libya", "thailand"])
def test_split_reference_cannot_clear_a_retained_hold_or_make_writer_statements(hold):
    ledger, key, moving, _ = episode(hold)
    result = he.split(ledger, key, [moving], new_source_id="F-2", expected_revision=2,
                      actor="invented", evidence_packet_sha256="a" * 64)
    child = result["to"]
    assert ledger["episodes"][key]["historical_hold"] == hold
    assert ledger["episodes"][child]["historical_hold"] == hold
    assert he.project_binding(ledger, child)["historical_hold"] == hold
    matched_statement(ledger, child)
    assert he.writer_statements(ledger, child) == []
    he.assign(ledger, {"hazard": "flood", "issuer": "invented", "source_event_id": "F-2",
                       "candidate_id": "invented-c", "value": 30})
    later = ledger["episodes"][child]["members"][-1]["source_revision"]
    grandchild = he.split(ledger, child, [later], new_source_id="F-3", expected_revision=2,
                          actor="invented", evidence_packet_sha256="c" * 64)["to"]
    assert he.project_binding(ledger, grandchild)["historical_hold"] == hold


def test_later_hold_is_monotonic_and_conflicting_label_does_not_mutate_ledger():
    ledger, key, _, assertion = episode()
    he.assign(ledger, {**assertion, "historical_hold": "libya", "candidate_id": "invented-c"})
    assert he.project_binding(ledger, key)["historical_hold"] == "libya"
    he.assign(ledger, {**assertion, "candidate_id": "invented-d", "value": 30})
    assert he.project_binding(ledger, key)["historical_hold"] == "libya"
    before = deepcopy(ledger)
    with pytest.raises(ValueError, match="conflicting_historical_holds"):
        he.assign(ledger, {**assertion, "historical_hold": "thailand", "candidate_id": "invented-e"})
    assert ledger == before


def test_legacy_lost_top_level_hold_still_blocks_projection_and_edits_without_rewriting_history():
    ledger, key, moving, assertion = episode("libya")
    ledger["episodes"][key]["historical_hold"] = None  # shape emitted by the old split
    matched_statement(ledger, key)
    before = deepcopy(ledger)
    assert he.project_binding(ledger, key)["historical_hold"] == "libya"
    assert he.writer_statements(ledger, key) == []
    assert he.assign(ledger, assertion)["changed"] is False
    assert ledger == before
    with pytest.raises(ValueError, match="historical_hold:libya"):
        he.split(ledger, key, [moving], new_source_id="F-2", expected_revision=2, actor="invented")
    assert ledger == before


def cli(*args):
    env = {k: os.environ[k] for k in ("PATH",) if k in os.environ}
    env.update(LC_ALL="C", LANG="C", PYTHON_DOTENV_DISABLED="1", PYTHONDONTWRITEBYTECODE="1", no_proxy="*")
    return subprocess.run([sys.executable, str(ROOT / "scripts/hazard_episodes.py"), *map(str, args)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=30, check=False)


def test_real_cli_split_inspect_publish_keeps_hold_and_invalidates_only_pending(tmp_path):
    ledger, key, moving, _ = episode("thailand")
    path, state_path = tmp_path / "ledger.json", tmp_path / "state.json"
    path.write_text(json.dumps(ledger))
    result = cli("--ledger", path, "split", "--episode", key, "--revision", moving,
                 "--new-source-id", "F-2", "--expected", 2, "--evidence-packet-sha256", "a" * 64)
    assert result.returncode == 0, result.stdout + result.stderr
    child = json.loads(result.stdout)["to"]
    ledger = json.loads(path.read_text())
    matched_statement(ledger, child)
    path.write_text(json.dumps(ledger))
    inspected = cli("--ledger", path, "inspect", "--episode", child)
    assert inspected.returncode == 0, inspected.stdout + inspected.stderr
    view = json.loads(inspected.stdout)
    assert view["episode"]["historical_hold"] == "thailand" and view["writer_statements"] == []
    pending = {"id": "invented-pending", "text": "Invented fixture only.", "status": "pending",
               "approval_mode": "auto", "review_context": {"physical_episode": {"episode_id": child}}}
    revisions.initialize_revision(pending)
    revisions.record_human_review(pending)  # invented offline state; never a production fallback
    posted, unknown = deepcopy(pending), deepcopy(pending)
    posted.update(id="invented-posted", status="posted")
    unknown.update(id="invented-unknown", publish_outcome="unknown")
    state_path.write_text(json.dumps({"drafts": [pending, posted, unknown]}))
    saved_before = json.loads(state_path.read_text())
    published = cli("--ledger", path, "--state", state_path, "publish")
    assert published.returncode == 0, published.stdout + published.stderr
    after = json.loads(state_path.read_text())["drafts"]
    assert after[0]["review_context"]["physical_episode"]["historical_hold"] == "thailand"
    assert after[0]["approval_mode"] == "manual" and not revisions.review_is_current(after[0])
    assert after[1:] == saved_before["drafts"][1:]


def test_legacy_hold_is_visible_in_real_inspection_without_rewriting_retained_bytes(tmp_path):
    ledger, key, _, _ = episode("libya")
    ledger["episodes"][key]["historical_hold"] = None
    matched_statement(ledger, key)
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger))
    before = path.read_bytes()
    result = cli("--ledger", path, "inspect", "--episode", key)
    assert result.returncode == 0, result.stdout + result.stderr
    view = json.loads(result.stdout)
    assert view["episode"]["historical_hold"] is None  # original recorded field
    assert view["effective_historical_hold"] == "libya"
    assert view["writer_statements"] == [] and path.read_bytes() == before


def test_conflicting_retained_holds_refuse_projection_and_grant_no_statement(tmp_path):
    ledger, key, _, _ = episode("libya")
    ledger["episodes"][key]["members"][1]["assertion"]["historical_hold"] = "thailand"
    matched_statement(ledger, key)
    before = deepcopy(ledger)
    assert he.writer_statements(ledger, key) == []
    with pytest.raises(ValueError, match="conflicting_historical_holds"):
        he.project_binding(ledger, key)
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger))
    raw = path.read_bytes()
    result = cli("--ledger", path, "inspect", "--episode", key)
    assert result.returncode == 2 and "conflicting_historical_holds" in result.stdout
    assert ledger == before and path.read_bytes() == raw


def test_splitting_the_only_explicitly_held_member_keeps_both_legacy_parts_held():
    ledger, key, moving, _ = episode("libya")
    original = ledger["episodes"][key]
    original["historical_hold"] = None
    original["members"][0]["assertion"]["historical_hold"] = None
    result = he.split(ledger, key, [moving], new_source_id="F-2", expected_revision=2,
                      actor="invented", evidence_packet_sha256="a" * 64)
    assert he.project_binding(ledger, key)["historical_hold"] == "libya"
    assert he.project_binding(ledger, result["to"])["historical_hold"] == "libya"


def test_unheld_split_and_writer_statement_remain_available():
    ledger, key, moving, _ = episode()
    child = he.split(ledger, key, [moving], new_source_id="F-2", expected_revision=2, actor="invented")["to"]
    assert he.project_binding(ledger, child)["historical_hold"] is None
    matched_statement(ledger, child)
    assert he.writer_statements(ledger, child)[0]["statement"] == "Invented fixture report."
