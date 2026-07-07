"""Offline fixture checks for scripts/writer_dryrun.py (E1 harness).

The dryrun's gate chain needs live API keys and is exercised via the
writer-dryrun workflow; these tests cover the part that can rot silently —
the per-type fixture builders. They assert each --type produces a bundle the
evidence contract accepts, with impact entries carrying the full warrant
(claim/value/source_name/url/as_of), so a green workflow run is testing the
real A1 shape and not a drifted fixture.
"""

from __future__ import annotations

import argparse

from scripts.writer_dryrun import DEFAULTS, _build_bundle
from src.two_bot.evidence_contract import audit_story_bundle

_WARRANT_KEYS = {"claim", "value", "source_name", "url", "as_of"}


def _args(**overrides) -> argparse.Namespace:
    values = dict(DEFAULTS)
    values.update(overrides)
    return argparse.Namespace(**values)


class TestFireFixture:
    def test_default_fire_bundle_carries_impact_with_full_warrants(self):
        bundle = _build_bundle(_args(type="fire"))
        assert bundle.signal_kind == "fire"
        assert bundle.human_impact, "default fire fixture is the impact-carrying A1 shape"
        for entry in bundle.human_impact:
            assert _WARRANT_KEYS <= set(entry), entry

    def test_fire_bundle_passes_the_evidence_contract(self):
        audit = audit_story_bundle(_build_bundle(_args(type="fire")))
        errors = [i.code for i in audit.issues if i.severity == "error"]
        assert audit.prompt_ready, errors

    def test_no_impact_control_run(self):
        bundle = _build_bundle(_args(type="fire", no_impact=True))
        assert not bundle.human_impact

    def test_fire_impact_names_the_incident(self):
        # The A1 matcher only attaches named fire news to a same-named
        # candidate; the fixture models that by naming the incident in the
        # claim text.
        bundle = _build_bundle(_args(type="fire"))
        assert any("fire" in e["claim"] for e in bundle.human_impact)


class TestFireFootprintFixture:
    def test_default_footprint_bundle_is_named_and_area_equipped(self):
        bundle = _build_bundle(_args(type="fire_footprint"))
        assert bundle.signal_kind == "fire_footprint"
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts.get("complex_name"), "footprint fixture must be a NAMED complex"
        assert facts.get("area_km2_approx")
        assert facts.get("area_acres_approx")

    def test_footprint_impact_defaults_to_the_complex_name(self):
        # Matcher-consistency: impact claims on a named complex name THAT
        # complex, not an unrelated incident.
        bundle = _build_bundle(_args(type="fire_footprint"))
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        name = facts["complex_name"]
        assert bundle.human_impact
        assert any(name in e["claim"] for e in bundle.human_impact)

    def test_footprint_bundle_passes_the_evidence_contract(self):
        audit = audit_story_bundle(_build_bundle(_args(type="fire_footprint")))
        errors = [i.code for i in audit.issues if i.severity == "error"]
        assert audit.prompt_ready, errors

    def test_footprint_tier_consistent_with_hectares(self):
        # The fixture's hectares must actually cross its tier threshold —
        # an inconsistent fixture teaches the writer an unconstructable
        # bundle.
        bundle = _build_bundle(_args(type="fire_footprint"))
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["hectares"] >= facts["tier_hectares"]


class TestExemplarFixtureAttributionConsistency:
    """codex r1 P1 regression lock: the writer prompt's ✓ fire exemplar and
    the default harness fixture must attribute the SAME figure to the SAME
    source — an exemplar teaching "per NIFC" for a Washington-Post-sourced
    fatalities entry teaches a rule-k failure against the canonical bundle."""

    def test_story_exemplar_sources_match_the_default_fixture(self):
        from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT

        assert DEFAULTS["fatality_source"] == "The Washington Post"
        # Fatalities figure attributed to the fixture's fatality source…
        assert "The Washington Post reports" in WRITER_SYSTEM_PROMPT
        # …and the personnel figure to NIFC, its own entry's source.
        assert "NIFC has 1,450 personnel assigned" in WRITER_SYSTEM_PROMPT


class TestDustFixture:
    def test_dust_bundle_carries_the_anchor_and_passes_evidence(self):
        bundle = _build_bundle(_args(type="dust"))
        assert bundle.signal_kind == "dust_event"
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["who_pm10_multiple"] == 20.0
        assert facts["pm10_24h_mean_ug_m3"] == 900.0
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_dust_fixture_never_attaches_impact(self):
        bundle = _build_bundle(_args(type="dust"))
        assert not getattr(bundle, "human_impact", None)


class TestCycloneLandThreatFixture:
    def test_bundle_shape_and_evidence(self):
        bundle = _build_bundle(_args(type="cyclone_land_threat"))
        assert bundle.signal_kind == "cyclone_land_threat"
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["landmass_country"] == "Taiwan"
        assert facts["min_distance_nm"] == 25.0
        assert facts["closest_tau_h"] == 48
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_no_impact_on_cyclone_fixture(self):
        bundle = _build_bundle(_args(type="cyclone_land_threat"))
        assert not getattr(bundle, "human_impact", None)


class TestPrecipFixture:
    def test_accumulation_shape(self):
        bundle = _build_bundle(_args(type="precipitation_extreme"))
        assert bundle.signal_kind == "precipitation_extreme"
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["alert_threshold_mm"] == 300.0
        assert "previous_record_mm" not in facts
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_record_path_shape(self):
        bundle = _build_bundle(_args(type="precipitation_extreme", record_path=True))
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["previous_record_mm"] == 210.0
        assert "alert_threshold_mm" not in facts

    def test_country_cluster_shape(self):
        bundle = _build_bundle(_args(type="precipitation_extreme", country_cluster=True))
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["event_kind"] == "country_precip_event"
        assert facts["city_count"] == 12
        assert len(facts["sample_cities"]) == 12
        assert "previous_record_mm" not in facts
        assert "alert_threshold_mm" not in facts
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]


class TestMarineFixture:
    """Row 11 PR-1 fixtures: coral_bleaching + marine_heatwave. Neither
    fixture ever attaches human_impact — a DHW reading and an OISST streak
    milestone carry no human toll (see DEFAULTS comment convention for dust
    / cyclone_land_threat)."""

    def test_coral_bleaching_shape_and_evidence(self):
        bundle = _build_bundle(_args(type="coral_bleaching"))
        assert bundle.signal_kind == "coral_bleaching"
        assert bundle.historical_context["thresholds_c_weeks"] == [4, 8, 12]
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_coral_bleaching_no_impact(self):
        bundle = _build_bundle(_args(type="coral_bleaching"))
        assert not getattr(bundle, "human_impact", None)

    def test_marine_heatwave_shape_and_evidence(self):
        bundle = _build_bundle(_args(type="marine_heatwave"))
        assert bundle.signal_kind == "marine_heatwave"
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_marine_heatwave_no_impact(self):
        bundle = _build_bundle(_args(type="marine_heatwave"))
        assert not getattr(bundle, "human_impact", None)
