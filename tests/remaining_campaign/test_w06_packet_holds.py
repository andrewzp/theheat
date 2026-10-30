"""W06.6: a rainfall packet stopped before paid generation is named in the retained run.

Real GPM runner, invented place, no network. The Sources reader for these details is
covered in dashboard/tests/remaining-campaign-w06-rainfall-readiness.test.js.
"""
from __future__ import annotations

from src.data import rainfall_supply as rs
from tests.live_content_harness import trap_network
from tests.remaining_campaign import w06_readiness_child as child


def test_incomplete_packet_is_named_in_the_run_details_and_complete_details_are_unchanged(monkeypatch):
    trap_network(monkeypatch.setattr)
    complete = child.gpm_run(monkeypatch.setattr, complete=True)["sources"][0]
    assert "rainfall_packet_holds" not in complete["details"]  # nothing withheld: today's details exactly
    held = child.gpm_run(monkeypatch.setattr, complete=False)["sources"][0]
    rows = held["details"]["rainfall_packet_holds"]
    assert held["promoted"] == 1 and rows == [{"event_id": rows[0]["event_id"], "location": "Ficta", "holds": [
        "accumulation_window_missing", "footprint_missing", "evidence_type_unknown", "source_product_missing"]}]
    assert rs.packet_ready is not None  # the gate itself is unchanged; only its hold is now retained


def test_bounded_scans_retain_examined_regions_and_limits():
    first, second = (run["sources"][0]["details"]["rainfall_scan"] for run in child.scans())
    assert [a["outcome"] for a in first["attempts"]] == ["qualified", "failed"]
    assert [a["outcome"] for a in second["attempts"]] == ["access_expired", "not_attempted_limit"]
