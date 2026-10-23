"""Invented returned GDACS captures: exact source-event groups and held ambiguity.

All XML is synthetic. A held group is unresolved returned data, never a finding
about which episode is correct or that no disaster exists.
"""
from copy import deepcopy
from itertools import permutations
from pathlib import Path
import random
import xml.etree.ElementTree as ET

import pytest

from src.data import gdacs, gdacs_intake
from src.data.source_status import SourceFetchError
from src.two_bot.intern.disasters import build_global_disaster_bundle
from src.two_bot.scientific_claims import scientific_claim_failures
from tests.test_gdacs_publication_freshness import LEVELS, NOW, NS, feed

FIXTURE = Path(__file__).parent / "fixtures/gdacs_intake_mixed.xml"
# The parser's settled diagnostics vocabulary; reconciliation goes to `selection`.
SETTLED_KEYS = {
    "source_leg", "feed_items_validated", "feed_items_total", "quarantined_items", "rejected_by_field",
    "rejected_selected_alerts", "rejected_unknown_alert_level", "alert_counts", "selected_alerts",
    "episode_alert_counts", "current_flag_counts", "current_candidates_examined", "withheld_current_alerts",
    "withheld_current_by_reason", "unknown_country_items", "selected_before_freshness",
    "withheld_selected_alerts", "withheld_by_reason", "publication_time", "publication_clock", "status",
}


def items(*event_ids):
    """Fresh copies of fixture items, in fixture order, optionally by event id."""
    rows = ET.parse(FIXTURE).getroot().find("channel").findall("item")
    return [deepcopy(row) for row in rows
            if not event_ids or row.find(NS + "eventid").text in event_ids]


def capture(rows, *, min_level=2):
    diagnostics, selection = {}, {}
    events, _ = gdacs._events_from_georss(feed(*deepcopy(rows)), min_level=min_level, severity_order=LEVELS,
                                         diagnostics=diagnostics, now=NOW, selection=selection)
    return events, diagnostics, selection


def signature(events):
    """Order-free identity of the selected set and its complete content."""
    return sorted((gdacs_intake.source_key(e), gdacs_intake.projection_sha256(e)) for e in events)


def without_capture(selection):
    return {k: v for k, v in selection.items() if k != "capture_sha256"}


def assert_equations(diagnostics, selection):
    s = selection
    assert s["contender_items"] == s["ambiguous_items"] + s["exact_duplicate_items"] + (
        s["contender_groups"] - s["ambiguous_groups"])
    assert s["threshold_items"] == s["withheld_ambiguous_alerts"] + s["selected_groups"] + s["exact_duplicate_threshold_items"]
    assert s["ambiguous_groups"] == sum(s["ambiguous_by_reason"].values())
    assert diagnostics["current_candidates_examined"] == (
        diagnostics["withheld_current_alerts"] + diagnostics["withheld_selected_alerts"] + s["threshold_items"])
    assert diagnostics["selected_alerts"] == s["selected_groups"]
    assert diagnostics["feed_items_total"] == diagnostics["feed_items_validated"] + diagnostics["quarantined_items"]


def test_nonfinite_peer_cannot_supply_feed_publication_or_select_an_episode():
    control = items("intake-control")[0]
    control.find("pubDate").text = "2026-09-01T00:00:00Z"
    bad = items("intake-control")[0]
    ET.SubElement(bad, NS + "severity", {"value": "NaN"})
    with pytest.raises(gdacs.GDACSPublicationError, match="stale data"):
        gdacs._events_from_georss(feed(bad, control, published=None), min_level=2,
                                 severity_order=LEVELS, diagnostics={}, now=NOW)


def test_mixed_capture_reconciles_every_case_with_exact_counts():
    events, diagnostics, selection = capture(items())
    assert {e.source_event_id for e in events} == {"intake-duplicate", "intake-current-old", "intake-shared-1",
                                                   "intake-shared-2", "intake-control", "intake-unknown-country"}
    assert set(diagnostics) == SETTLED_KEYS
    assert diagnostics["status"] == "partial_feed"  # Structural quarantine keeps precedence.
    assert diagnostics["quarantined_items"] == 1 and diagnostics["current_candidates_examined"] == 18
    assert diagnostics["withheld_current_by_reason"] == {"not_current": 1, "unverified_current": 1,
        "unverified_episode": 1, "episode_below_threshold": 1, "inconsistent_alert_levels": 0}
    assert diagnostics["withheld_by_reason"] == {"missing": 0, "invalid": 0, "future": 1, "stale": 1}
    assert without_capture(selection) == {
        "contender_items": 13, "contender_groups": 9, "threshold_items": 12, "selected_groups": 6,
        "exact_duplicate_items": 1, "exact_duplicate_threshold_items": 1, "ambiguous_groups": 3,
        "ambiguous_items": 6, "withheld_ambiguous_alerts": 5,
        "ambiguous_by_reason": {"multiple_current_episodes": 2, "conflicting_episode_payloads": 1},
        "conflicting_fields": {"description": 1}}
    assert selection["capture_sha256"] == gdacs_intake.capture_sha256(feed(*items()))
    assert_equations(diagnostics, selection)


@pytest.mark.parametrize("cohort", [
    ("intake-redred", "intake-control"),
    ("intake-redgreen", "intake-control"),
    ("intake-duplicate", "intake-conflict", "intake-control"),
    ("intake-current-old", "intake-unverified", "intake-stale", "intake-control"),
    ("intake-shared-1", "intake-shared-2", "intake-unknown-country", "intake-invalid-episode", "intake-future"),
    ("intake-redred", "broken", "intake-control", "intake-future"),
])
def test_small_mixed_cohorts_are_invariant_under_every_xml_permutation(cohort):
    rows = items(*cohort)
    assert 2 <= len(rows) <= 6
    expected = None
    for ordering in permutations(rows):
        events, diagnostics, selection = capture(list(ordering))
        observed = (signature(events), diagnostics, without_capture(selection),
                    [gdacs_intake.source_key(e) for e in gdacs_intake.staged_order(events)])
        assert_equations(diagnostics, selection)
        if expected is not None:
            assert observed == expected
        expected = observed


def large_capture(seed):
    """A deterministic larger capture: 120 source events, ~360 items, every case kind."""
    rng = random.Random(seed)
    template = items("intake-control")[0]
    rows = []

    def row(event_id, episode_id, **changes):
        node = deepcopy(template)
        node.find(NS + "eventid").text = event_id
        node.find(NS + "episodeid").text = episode_id
        for field, value in changes.items():
            target = node.find(field if field in ("description", "pubDate") else NS + field)
            target.text = value
        return node

    for index in range(120):
        event_id, kind = f"large-{index:03d}", index % 6
        if kind == 0:  # Selected, with an exact duplicate.
            rows += [row(event_id, "ep-1"), row(event_id, "ep-1")]
        elif kind == 1:  # Two current episodes.
            rows += [row(event_id, "ep-1"), row(event_id, "ep-2", episodealertlevel="Green")]
        elif kind == 2:  # Same episode, disagreeing payload.
            rows += [row(event_id, "ep-1"), row(event_id, "ep-1", description=f"Changed invented text {index}.")]
        elif kind == 3:  # Current plus explicit old and an unverifiable peer.
            rows += [row(event_id, "ep-2"), row(event_id, "ep-1", iscurrent="false"), row(event_id, "ep-3", iscurrent="yes")]
        elif kind == 4:  # Stale and future current rows cannot establish selection.
            rows += [row(event_id, "ep-1"), row(event_id, "ep-2", pubDate="2026-09-01T00:00:00Z"),
                     row(event_id, "ep-3", pubDate="2026-09-30T12:05:01Z")]
        else:  # Green current alone: valid, below threshold.
            rows += [row(event_id, "ep-1", episodealertlevel="Green")]
    rng.shuffle(rows)
    return rows


def test_large_shuffled_captures_select_one_canonical_cohort():
    expected = None
    for seed in range(12):
        rows = large_capture(seed)
        events, diagnostics, selection = capture(rows)
        assert len(rows) == 20 * (2 + 2 + 2 + 3 + 3 + 1)
        assert_equations(diagnostics, selection)
        staged = gdacs_intake.staged_order(events)
        assert [gdacs_intake.source_key(e) for e in staged] == sorted(gdacs_intake.source_key(e) for e in events)
        observed = (signature(events), diagnostics, without_capture(selection))
        if expected is not None:
            assert observed == expected
        expected = observed
    events, diagnostics, selection = capture(large_capture(0))
    assert selection["ambiguous_by_reason"] == {"multiple_current_episodes": 20, "conflicting_episode_payloads": 20}
    assert selection["selected_groups"] == len(events) == 60  # kinds 0, 3 and 4
    assert selection["exact_duplicate_items"] == 20 and diagnostics["withheld_by_reason"]["stale"] == 20


@pytest.mark.parametrize("levels,withheld", [(("Red", "Red"), 2), (("Red", "Green"), 1), (("Red", "Orange"), 1)])
def test_conflicting_current_episodes_hold_every_threshold_candidate(levels, withheld):
    rows = items("intake-redred")
    for row, level in zip(rows, levels):
        row.find(NS + "episodealertlevel").text = level
    for ordering in (rows, rows[::-1]):
        events, diagnostics, selection = capture(ordering)
        assert events == [] and diagnostics["status"] == "ambiguous_current_selection"
        assert selection["withheld_ambiguous_alerts"] == withheld
        assert selection["ambiguous_by_reason"]["multiple_current_episodes"] == 1
        # A lower tier keeps its settled below-threshold diagnosis too.
        assert diagnostics["withheld_current_by_reason"]["episode_below_threshold"] == 2 - withheld
    # Orange callers see both tiers; the conflict is still held.
    if levels == ("Red", "Orange"):
        events, _, selection = capture(rows, min_level=1)
        assert events == [] and selection["withheld_ambiguous_alerts"] == 2


def test_lower_tier_conflict_beneath_green_overall_cannot_hide():
    rows = items("intake-redred")
    rows[1].find(NS + "alertlevel").text = "Green"
    rows[1].find(NS + "episodealertlevel").text = "Green"
    events, diagnostics, selection = capture(rows)
    # The Green row is below every Red threshold check, yet it is a current contender.
    assert diagnostics["current_candidates_examined"] == 1 and events == []
    assert selection["withheld_ambiguous_alerts"] == 1 and selection["contender_items"] == 2


@pytest.mark.parametrize("field,value,expected_field", [
    ("description", "Changed invented text.", "description"),
    ("title", "Changed invented name", "name"),
    ("{http://www.georss.org/georss}point", "21 78", "source_provenance.coordinates"),
    (NS + "todate", "2026-10-03T00:00:00Z", "source_provenance.todate"),
    ("pubDate", "2026-09-30T11:00:00Z", "source_provenance.published_at"),
])
def test_same_episode_payload_disagreement_holds_without_choosing(field, value, expected_field):
    rows = items("intake-duplicate")
    rows[1].find(field).text = value
    events, diagnostics, selection = capture(rows)
    assert events == [] and diagnostics["status"] == "ambiguous_current_selection"
    assert selection["ambiguous_by_reason"] == {"multiple_current_episodes": 0, "conflicting_episode_payloads": 1}
    assert expected_field in selection["conflicting_fields"]
    # The bounded diagnostics name fields, never the disagreeing source text.
    assert value not in repr(selection) and value not in repr(diagnostics)


def test_exact_equivalent_rows_collapse_to_one_candidate():
    events, _, selection = capture(items("intake-duplicate") * 2)
    assert len(events) == 1 and selection["exact_duplicate_items"] == 3


@pytest.mark.parametrize("peer", ["current_false", "current_missing", "episode_blank", "episode_level", "inconsistent",
                                  "stale", "future", "missing_clock", "malformed"])
def test_unqualified_same_event_peers_cannot_establish_or_poison_selection(peer):
    good = items("intake-control")[0]
    bad = deepcopy(good)
    bad.find(NS + "episodeid").text = "ep-other"
    if peer == "current_false":
        bad.find(NS + "iscurrent").text = "false"
    elif peer == "current_missing":
        bad.remove(bad.find(NS + "iscurrent"))
    elif peer == "episode_blank":
        bad.find(NS + "episodeid").text = "  "
    elif peer == "episode_level":
        bad.find(NS + "episodealertlevel").text = "RED"
    elif peer == "inconsistent":
        bad.find(NS + "alertlevel").text = "Orange"
    elif peer == "stale":
        bad.find("pubDate").text = "2026-09-01T00:00:00Z"
    elif peer == "future":
        bad.find("pubDate").text = "2026-09-30T12:05:01Z"
    elif peer == "missing_clock":
        bad.remove(bad.find("pubDate"))
    else:
        bad.remove(bad.find(NS + "country"))
    events, diagnostics, selection = capture([bad, good])
    assert [e.source_event_id for e in events] == ["intake-control"]
    assert selection["ambiguous_groups"] == 0 and selection["contender_items"] == 1
    assert diagnostics["status"] != "ambiguous_current_selection"


def test_group_key_is_exact_source_type_and_id_only():
    shared = items("intake-shared-1", "intake-shared-2")
    events, _, selection = capture(shared)
    assert len(events) == 2 and selection["ambiguous_groups"] == 0  # Same episode string, different keys.
    other_type = items("intake-control")[0]
    other_type.find(NS + "eventtype").text = "FL"
    other_type.find(NS + "episodeid").text = "ep-other"
    events, _, selection = capture([items("intake-control")[0], other_type])
    assert len(events) == 2 and selection["ambiguous_groups"] == 0  # EQ and FL with one id.
    padded = items("intake-control")[0]
    padded.find(NS + "eventid").text = " intake-control "
    padded.find(NS + "episodeid").text = "ep-other"
    events, _, selection = capture([items("intake-control")[0], padded])
    assert events == [] and selection["ambiguous_groups"] == 1  # Stripped exact id, not name/place.


def test_unknown_country_and_unqualified_numeric_limits_survive_selection():
    events, _, _ = capture(items("intake-unknown-country", "intake-control"))
    cyclone = next(e for e in events if e.source_event_id == "intake-unknown-country")
    assert cyclone.country == "" and cyclone.source_provenance["source_country_known"] is False
    bundle = build_global_disaster_bundle(cyclone)
    facts = {row["label"]: row["value"] for row in bundle.current_facts if row["label"] != "claim_limit"}
    limits = [row["value"] for row in bundle.current_facts if row["label"] == "claim_limit"]
    assert facts["unqualified_source_severity_value"] == 240 and facts["severity_text"] == "Invented conflicting wind 60 km/h"
    assert any("do not infer a country or landfall" in text for text in limits)
    assert scientific_claim_failures("Winds reached 240 km/h.", bundle)
    assert scientific_claim_failures("The cyclone made landfall.", bundle)


def test_exact_item_bound_and_over_bound():
    template = items("intake-control")[0]
    rows = []
    for index in range(gdacs.MAX_GEORSS_ITEMS):
        node = deepcopy(template)
        node.find(NS + "eventid").text = f"bound-{index // 2:04d}"
        node.find(NS + "episodeid").text = f"ep-{index % 2 if index % 4 == 1 else 0}"
        rows.append(node)
    events, diagnostics, selection = capture(rows)
    assert diagnostics["feed_items_total"] == gdacs.MAX_GEORSS_ITEMS
    assert selection["ambiguous_groups"] == 250 and selection["exact_duplicate_items"] == 250 and len(events) == 250
    assert_equations(diagnostics, selection)
    with pytest.raises(SourceFetchError, match="bounded RSS item collection"):
        capture(rows + [deepcopy(template)])
    oversized = feed(template).replace("Synthetic timing fixture.", "x" * gdacs.MAX_GEORSS_BYTES)
    with pytest.raises(SourceFetchError, match="byte bound"):
        gdacs._events_from_georss(oversized, min_level=2, severity_order=LEVELS, diagnostics={}, now=NOW, selection={})


def test_capture_and_intake_identities_are_exact_and_internal():
    rows = items("intake-control", "intake-shared-1")
    events, _, selection = capture(rows)
    reordered = capture(rows[::-1])[2]
    assert selection["capture_sha256"] != reordered["capture_sha256"]  # A different returned capture.
    assert capture(rows)[2]["capture_sha256"] == selection["capture_sha256"]
    control = next(e for e in events if e.source_event_id == "intake-control")
    identity = gdacs_intake.intake_identity(control, selection["capture_sha256"])
    assert identity == (selection["capture_sha256"], "EQ\x1fintake-control", gdacs_intake.projection_sha256(control))
    bundle = build_global_disaster_bundle(control)
    assert selection["capture_sha256"] not in repr(bundle) and identity[2] not in repr(bundle)
