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
