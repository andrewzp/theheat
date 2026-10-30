"""W07.2/07.3/07.6: the operator ledger reaches the drafts the normal editor reviews, and back.

Invented episodes only. The dashboard side (inspection, remove-join, split, supersede on
the real route) is dashboard/tests/remaining-campaign-w07-episode-joins.test.js; it uses
the same producer (tests/remaining_campaign/w07_editor_child.py).
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.editorial import hazard_episodes as he
from tests.remaining_campaign import w07_editor_child as child

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def produced(monkeypatch):
    monkeypatch.setenv(he.FLAG, "1")
    return child.build()


def _drafts(raw):
    return {d["id"]: d for d in json.loads(raw)["drafts"]}


def test_projection_explains_joins_and_keeps_delivered_snapshots(produced):
    drafts = _drafts(produced["raw_state"])
    river = drafts["d-river"]["review_context"]["physical_episode"]
    assert {(r["decision"], r["reason"]) for r in river["relationships"]} == {
        ("joined", "shared_identifier"), ("proposed_only", "insufficient_join_evidence")}
    assert all(r["impacts_combined"] is False for r in river["relationships"])
    assert [(j["status"], j["reason"]) for j in river["report_joins"]] == [("matched", "matched"),
                                                                         ("report_claim_only", "place_mismatch")]
    assert child.REPORT_BYTES.decode() not in json.dumps(drafts)  # a hash, never the report bytes
    assert all(j["report_sha256"] == produced["report_sha256"] for j in river["report_joins"])
    assert drafts["d-river"]["episode_invalidated"] is True and "review_binding" not in drafts["d-river"]
    assert produced["published"]["preserved_delivered"] == ["d-posted"]
    assert "relationships" not in drafts["d-posted"]["review_context"]["physical_episode"]


def test_cli_publish_is_idempotent_and_an_editor_removal_withdraws_the_ledger_join(produced, tmp_path):
    state_path, ledger_path = tmp_path / "state.json", tmp_path / "ledger.json"
    state_path.write_text(produced["raw_state"])
    ledger_path.write_text(json.dumps(produced["ledger"]))

    def publish():
        result = subprocess.run([sys.executable, str(ROOT / "scripts/hazard_episodes.py"), "--ledger", str(ledger_path),
                                 "--state", str(state_path), "publish"], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    assert publish() == {"invalidated": [], "preserved_delivered": ["d-posted"], "withdrawn_joins": []}
    state = json.loads(state_path.read_text())
    river = next(d for d in state["drafts"] if d["id"] == "d-river")
    matched = river["review_context"]["physical_episode"]["report_joins"][0]
    matched.update(removed=True, removed_by="dashboard")  # what the editor's remove-join saved
    state_path.write_text(json.dumps(state))
    assert publish()["withdrawn_joins"] == [matched["join_id"]]
    ledger = json.loads(ledger_path.read_text())
    episode = river["review_context"]["physical_episode"]["episode_id"]
    assert he.writer_statements(ledger, episode) == []  # the next brief no longer uses it
    kept = next(j for j in ledger["report_joins"] if j["join_id"] == matched["join_id"])
    assert kept["removed"] is True and kept["report_sha256"] == produced["report_sha256"]
    assert ledger["operations"][-1] == {"seq": len(ledger["operations"]), "kind": "remove_join", "actor": "editor:dashboard",
                                        "join_id": matched["join_id"]}


def test_historical_holds_reach_the_editor_binding():
    ledger = he.empty_ledger()
    held = he.assign(ledger, {"hazard": "flood", "issuer": "gdacs", "source_event_id": "FL-HELD",
                              "historical_hold": "libya"})["episode_id"]
    assert he.project_binding(ledger, held)["historical_hold"] == "libya"
