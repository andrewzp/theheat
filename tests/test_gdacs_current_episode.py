"""Synthetic current-episode qualification, distinct from publication freshness."""

from copy import deepcopy
from itertools import permutations
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest
import responses

from src.data import gdacs
from src.orchestrator.sources.gdacs import run_gdacs
from src.state import DEFAULT_STATE
from src.two_bot.intern.disasters import build_global_disaster_bundle
from src.two_bot.scientific_claims import scientific_claim_failures
from tests.test_gdacs_item_containment import broken
from tests.test_gdacs_publication_freshness import LEVELS, NOW, NS, feed, item, parse


def episode(*, current="true", level="Red", episode_id="synthetic-episode", **kwargs):
    node = item(**kwargs)
    for name, value in {"iscurrent": current, "episodealertlevel": level,
                        "episodeid": episode_id}.items():
        field = node.find(NS + name)
        if value is None:
            node.remove(field)
        else:
            field.text = value
    return node


def cyclone_bundle():
    node = episode()
    node.find(NS + "eventtype").text = "TC"
    ET.SubElement(node, NS + "severity", {"value": "240", "unit": "km/h"}).text = "Synthetic conflicting wind 60 km/h"
    ET.SubElement(node, NS + "alertscore").text = "3.50"
    ET.SubElement(node, NS + "episodealertscore").text = "3.25"
    return build_global_disaster_bundle(parse(feed(node))[0][0])


@pytest.mark.parametrize("overall,level,minimum", [
    ("Red", "Red", 2), ("Red", "Orange", 1), ("Orange", "Orange", 1),
    ("Red", "Green", 0), ("Green", "Green", 0),
])
def test_selected_severity_and_headline_are_episode_level(overall, level, minimum):
    node = episode(level=level)
    node.find(NS + "alertlevel").text = overall
    diagnostics = {}
    events, _ = gdacs._events_from_georss(feed(node), min_level=minimum,
                                        severity_order=LEVELS, diagnostics=diagnostics, now=NOW)
    assert len(events) == 1 and events[0].severity == level
    bundle = build_global_disaster_bundle(events[0])
    assert bundle.headline_metric == {"label": "severity", "value": level}
    facts = {row["label"]: row["value"] for row in bundle.current_facts}
    assert facts["overall_alert_level"] == overall and facts["episode_alert_level"] == level
    assert facts["is_current"] is True and facts["episode_id"] == "synthetic-episode"
    assert diagnostics["status"] == "valid_alerts" and diagnostics["withheld_current_alerts"] == 0


@pytest.mark.parametrize("kwargs,reason", [
    ({"current": "false"}, "not_current"),
    ({"current": None}, "unverified_current"), ({"current": ""}, "unverified_current"),
    ({"current": "False"}, "unverified_current"), ({"current": "TRUE"}, "unverified_current"),
    ({"current": "1"}, "unverified_current"), ({"current": "unknown"}, "unverified_current"),
    ({"level": None}, "unverified_episode"), ({"level": ""}, "unverified_episode"),
    ({"level": "RED"}, "unverified_episode"), ({"level": "Blue"}, "unverified_episode"),
    ({"episode_id": None}, "unverified_episode"), ({"episode_id": "  "}, "unverified_episode"),
    ({"level": "Green"}, "episode_below_threshold"), ({"level": "Orange"}, "episode_below_threshold"),
])
def test_unqualified_current_alert_withheld_without_healthy_empty(kwargs, reason):
    events, date, diagnostics = parse(feed(episode(**kwargs)))
    assert not events and str(date) == "2026-09-30"
    assert diagnostics["status"] == "withheld_current_alerts"
    assert diagnostics["withheld_current_by_reason"][reason] == diagnostics["withheld_current_alerts"] == 1
    assert diagnostics["selected_before_freshness"] == diagnostics["current_candidates_examined"] == 1
    assert diagnostics["withheld_selected_alerts"] == 0


def test_whitespace_is_stripped_without_boolean_truthiness():
    assert len(parse(feed(episode(current=" true ", level=" Red ", episode_id=" 1 ")))[0]) == 1
    assert parse(feed(episode(current=" false ")))[2]["withheld_current_by_reason"]["not_current"] == 1


@pytest.mark.parametrize("overall", ["Green", "Orange"])
def test_elevated_episode_under_lower_overall_is_visible_contradiction(overall):
    node = episode()
    node.find(NS + "alertlevel").text = overall
    events, _, diagnostics = parse(feed(node))
    assert not events and diagnostics["status"] == "withheld_current_alerts"
    assert diagnostics["selected_before_freshness"] == 0
    assert diagnostics["current_candidates_examined"] == diagnostics["withheld_current_by_reason"]["inconsistent_alert_levels"] == 1


def test_recent_catalog_edit_does_not_revive_inactive_old_event():
    events, newest, diagnostics = parse(feed(episode(current="false", start="2026-01-01T00:00:00Z",
                                                    end="2026-01-02T00:00:00Z"), published=None))
    assert not events and str(newest) == "2026-09-30"
    assert diagnostics["publication_clock"] == "item_update"
    assert diagnostics["withheld_current_by_reason"]["not_current"] == 1


def test_mixed_current_clock_and_core_failures_have_stable_disjoint_counts():
    nodes = [broken(), episode(current="false", level=None, published=None),
             episode(event_id="stale", published="2026-09-01T00:00:00Z"), episode(event_id="eligible")]
    expected = None
    for ordering in permutations(nodes):
        events, _, diagnostics = parse(feed(*ordering))
        assert [e.source_event_id for e in events] == ["eligible"]
        assert diagnostics["status"] == "partial_feed"
        assert diagnostics["withheld_current_alerts"] == diagnostics["withheld_selected_alerts"] == diagnostics["quarantined_items"] == 1
        assert diagnostics["withheld_current_by_reason"] == {
            "not_current": 1, "unverified_current": 0, "unverified_episode": 0,
            "episode_below_threshold": 0, "inconsistent_alert_levels": 0,
        }
        assert diagnostics["episode_alert_counts"] == {"Green": 0, "Orange": 0, "Red": 2, "unknown": 1}
        assert diagnostics["current_flag_counts"] == {"true": 2, "false": 1, "unknown": 0}
        assert diagnostics["withheld_by_reason"]["stale"] == 1
        if expected is not None:
            assert diagnostics == expected
        expected = diagnostics


def test_conflicting_numeric_source_fields_remain_unqualified_and_unmodified():
    bundle = cyclone_bundle()
    facts = {row["label"]: row["value"] for row in bundle.current_facts}
    assert "severity_value" not in facts and "severity_unit" not in facts
    assert facts["unqualified_source_severity_value"] == 240
    assert facts["unqualified_source_severity_unit"] == "km/h"
    assert facts["severity_text"] == "Synthetic conflicting wind 60 km/h"
    assert facts["severity_temporal_scope"] == "unqualified_source_metric"
    raw = bundle.raw_signal_dump
    assert raw["severity_value"] == 240 and raw["source_provenance"]["overall_alert_score"] == "3.50"
    assert raw["source_provenance"]["episode_alert_score"] == "3.25"
    assert any(row["label"] == "claim_limit" and "do not claim a wind speed" in row["value"] for row in bundle.current_facts)


@pytest.mark.parametrize("text", ["An advisory at 120 km from shore.", "Update 4 covers the cyclone.",
                                  "A 120 ktsuffix identifier.", "A catalog category 12 entry."])
def test_bounded_wind_check_does_not_treat_every_number_as_wind(text):
    assert scientific_claim_failures(text, cyclone_bundle()) == []


def test_rss_numeric_rule_does_not_expand_to_earthquake_intensity():
    bundle = cyclone_bundle()
    bundle.raw_signal_dump["disaster_type"] = "Earthquake"
    bundle.current_facts = [{"label": "disaster_type", "value": "Earthquake"}]
    assert scientific_claim_failures("A synthetic 120 km/h comparison.", bundle) == []


def test_gdacs_cyclone_landfall_accepts_only_existing_dated_warrant():
    bundle = cyclone_bundle()
    confirmation = {"source_product": "synthetic-advisory", "revision_id": "fixture-1",
        "source_url": "https://example.org/synthetic-advisory", "valid_date": bundle.when,
        "target_event_id": bundle.event_id, "status": "confirmed", "confirmed_at": bundle.when}
    bundle.raw_signal_dump["evidence"] = {"landfall": confirmation}
    assert scientific_claim_failures("The cyclone made landfall.", bundle) == []
    confirmation["confirmed_at"] = "2099-01-01"
    assert "unconfirmed_landfall" in scientific_claim_failures("The cyclone made landfall.", bundle)[0]


@responses.activate
@pytest.mark.parametrize("kwargs", [{"current": "false"}, {"current": None}, {"level": "Green"}])
def test_runner_exposes_current_withholding_without_drafting_or_extra_calls(monkeypatch, kwargs):
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: NOW)
    responses.add(responses.GET, gdacs.GDACS_URL, json={})
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=feed(episode(**kwargs)))
    enqueue = Mock(side_effect=AssertionError("Unqualified episode must not reach a writer"))
    monkeypatch.setattr("src.orchestrator.sources.gdacs._enqueue_story_candidate", enqueue)
    run = {"sources": []}
    run_gdacs(deepcopy(DEFAULT_STATE), run)
    enqueue.assert_not_called()
    assert len(responses.calls) == 2
    row = run["sources"][0]
    assert row["status"] == "degraded" and row["observed"] == row["promoted"] == 0
    assert "withheld_current_alerts:1" in row["note"]
    assert row["details"]["feed_diagnostics"]["status"] == "withheld_current_alerts"
