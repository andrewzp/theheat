"""Conservative cyclone candidate screening; no source-confirmation shortcut."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.data import cyclones, nhc
from src.orchestrator.cyclones import _process_cyclone_source
from src.state import DEFAULT_STATE
from src.two_bot.intern.disasters import build_cyclone_landfall_bundle
from src.two_bot.scientific_claims import scientific_claim_failures


def advisory(text, name="Fixture"):
    return cyclones.CycloneAdvisory(
        source="nhc", storm_id="synthetic", storm_name=name, basin="Atlantic",
        advisory_number="12", issued_at="2026-10-01T12:00:00Z", wind_kt=100,
        advisory_text=text, public_advisory_url="https://www.nhc.noaa.gov/synthetic",
    )


@pytest.mark.parametrize("text", [
    "Fixture made landfall near Example Coast.",
    "Fixture has made landfall in Example Coast.",
    "Fixture just made landfall along Example Coast.",
    "Hurricane Fixture has just made landfall near Example Coast with winds reported separately.",
    "The center of Hurricane Fixture made landfall near Example Coast.",
    "Tropical Storm Fixture made landfall near Example Coast.",
    "fixture MADE\nLANDFALL near\tExample Coast.",
    "Rain is forecast tomorrow. Fixture made landfall near Example Coast.",
    "Other may make landfall near Other Coast. Fixture made landfall near Example Coast.",
    "Other made landfall near Other Coast. Fixture made landfall near Example Coast.",
])
def test_direct_named_completion_is_only_a_candidate(text):
    source = advisory(text)
    event, = cyclones.detect_landfalls([source])
    assert event.location == "Example Coast"
    assert event.event_id == cyclones.event_key("nhc", "landfall", "synthetic", "12", "Example Coast")
    assert (event.source, event.storm_id, event.issued_at, event.category, event.wind_kt) == (
        source.source, source.storm_id, source.issued_at, source.category, source.wind_kt)
    bundle = build_cyclone_landfall_bundle(event)
    assert any("unconfirmed_landfall" in reason for reason in scientific_claim_failures(
        "Fixture made landfall near Example Coast.", bundle))
    assert "landfall" not in bundle.raw_signal_dump.get("evidence", {})


NEGATIVE = [
    "Fixture is expected to make landfall near Example Coast.",
    "Fixture will have made landfall near Example Coast.",
    "Fixture has not made landfall near Example Coast.",
    "Fixture hasn't made landfall near Example Coast.",
    "Fixture hasn’t made landfall near Example Coast.",
    "Fixture never made landfall near Example Coast.",
    "Fixture may have made landfall near Example Coast.",
    "Fixture might have made landfall near Example Coast.",
    "If Fixture made landfall near Example Coast, damage could occur.",
    "Suppose Fixture made landfall near Example Coast.",
    'A hypothetical headline says "Fixture made landfall near Example Coast".',
    "Last year Fixture made landfall near Example Coast.",
    "Fixture made landfall near Example Coast last season.",
    "Fixture made landfall near Example Coast in 2010.",
    "Fixture made landfall near Example Coast two years ago.",
    "Last year another storm made landfall near Example Coast.",
    "Other made landfall near Example Coast. Fixture remains offshore.",
    "SuperFixture made landfall near Example Coast.",
    "Fixture-Other made landfall near Example Coast.",
    "Landfall near Example Coast is expected tomorrow.",
    "Made landfall near Example Coast.",
    "Fixture made landfall near .",
    "Fixture made landfall near Example Coast tomorrow.",
    "Fixture made landfall near Example Coast. Fixture has not made landfall near Example Coast.",
    "Fixture may make landfall near Example Coast; Fixture made landfall near Example Coast.",
    "Fixture made landfall near First Coast. Fixture made landfall near Second Coast.",
    "Fixture made landfall near First Coast and Other made landfall near Second Coast.",
]


@pytest.mark.parametrize("text", NEGATIVE, ids=[f"negative-{i}" for i in range(len(NEGATIVE))])
def test_unsupported_or_conflicting_completion_is_withheld(text):
    assert cyclones.detect_landfalls([advisory(text)]) == []


@pytest.mark.parametrize("name", ["A+B", "A.B", "May", "Will", "Fixture (Test)"])
def test_names_are_literals_and_not_qualifiers(name):
    event, = cyclones.detect_landfalls([advisory(f"{name} made landfall near Example Coast.", name)])
    assert event.storm_name == name and event.location == "Example Coast"
    assert cyclones.detect_landfalls([advisory("AAAB made landfall near Example Coast.", "A+B")]) == []


@pytest.mark.parametrize("location", ["St. James", "Ft. Example", "L.A. Coast", "Example Island, 21.3 N"])
def test_location_punctuation_is_not_reinterpreted(location):
    event, = cyclones.detect_landfalls([advisory(f"Fixture made landfall near {location}.")])
    assert event.location == location


def test_repeated_same_location_does_not_create_an_extra_candidate():
    text = "Fixture made landfall near Example Coast. Fixture has made landfall near Example Coast."
    event, = cyclones.detect_landfalls([advisory(text)])
    assert event.location == "Example Coast"


def test_direction_suffix_does_not_join_an_unrelated_forecast_sentence():
    text = "Fixture made landfall near Example Island, 21.3 N. Rain is forecast tomorrow."
    event, = cyclones.detect_landfalls([advisory(text)])
    assert event.location == "Example Island, 21.3 N"


@pytest.mark.parametrize("change", [{"storm_name": ""}, {"wind_kt": 90}, {"advisory_text": ""}])
def test_missing_subject_text_or_existing_category_threshold_withholds(change):
    assert cyclones.detect_landfalls([replace(advisory("Fixture made landfall near Example Coast."), **change)]) == []


@pytest.mark.parametrize("text,expected", [(s, 0) for s in NEGATIVE[:3]] + [("Fixture made landfall near Example Coast.", 1)])
def test_screening_precedes_story_queue(monkeypatch, text, expected):
    source = replace(advisory(text), issued_at=datetime.now(UTC).isoformat())
    state = deepcopy(DEFAULT_STATE)
    state["cyclone_tiers"] = {source.tracking_key: source.category}
    captured = []
    monkeypatch.setattr("src.orchestrator.cyclones.load_cities", lambda: [])
    monkeypatch.setattr("src.orchestrator.cyclones._should_draft", lambda *a: True)
    monkeypatch.setattr("src.orchestrator.common._enqueue_story_candidate", lambda *a, **kw: captured.append(kw))
    _process_cyclone_source(state, {"sources": []}, source_key="nhc", source_label="NHC",
        fetch_fn=lambda: [source], detect_module=nhc)
    assert len(captured) == expected
    assert all(item["legacy_type"] == "cyclone_landfall" for item in captured)
