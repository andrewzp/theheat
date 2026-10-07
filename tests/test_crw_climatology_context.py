"""Invented CRW evidence; deterministic contracts, never a live model evaluation."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.data import crw_contract as source
from src.data.ocean_sst_anomaly import RegionalSSTAnomalyEvent, detect_regional_sst_anomaly_events
from src.editorial.revisions import draft_identity, fingerprint
from src.media.crw_graphic_adapter import ADAPTER_VERSION, LEGACY_ADAPTER_VERSION
from src.media.evidence_graphic import build_alt_text, validate_graphic
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.marine import (
    build_regional_sst_anomaly_bundle,
    legacy_regional_sst_anomaly_snapshot,
)
from src.two_bot.strict_contract import material_span_failures
from src.two_bot.types import MemorySlice
from tests.crw_graphic_helpers import graphic_inputs
from tests.test_crw_graphic_adapter import adapt
from tests.test_crw_source_contract import native as native, decode_native


def event_for(bundle):
    return RegionalSSTAnomalyEvent(**deepcopy(bundle.raw_signal_dump))


def test_qualified_primary_context_is_detached_and_keeps_scientific_limits():
    bundle, _ = graphic_inputs()
    event = event_for(bundle)
    before = deepcopy(event)
    context = bundle.historical_context["reference_climatology"]
    assert context["reference_year_ranges"] == [[1985, 1990], [1993, 1993]]
    assert context["derivation_year_range"] == [1985, 2012]
    assert context["source_response_sha256"] == event.provenance["response_sha256"]
    assert context["source_product"] == "noaa-crw-ssta-v3.1"
    assert context["methodology_url"] == source.METHODOLOGY_URL
    assert "trend-recentered" in context["method"] and "15th" in context["method"]
    assert "Not a 1991–2020 normal anomaly or an ENSO classification" in context["claim_limit"]
    assert not audit_story_bundle(bundle).issues
    context["reference_year_ranges"][0][0] = 1991
    assert event == before
    assert source.reference_climatology(event)["reference_year_ranges"][0][0] == 1985


def test_native_source_gets_same_method_without_an_erddap_label(native):
    event = detect_regional_sst_anomaly_events(decode_native(native.read_bytes()))[0]
    bundle = build_regional_sst_anomaly_bundle(event)
    assert audit_story_bundle(bundle).prompt_ready
    assert bundle.historical_context["source"] == source.PRODUCT_NAME
    assert "ERDDAP" not in bundle.historical_context["source"]
    assert bundle.historical_context["reference_climatology"] == source.reference_climatology(event)
    assert bundle.raw_signal_dump["provenance"]["source_leg"] == "noaa_star_nc"
    # Context qualification does not extend the primary-only graphics contract.
    with pytest.raises(ValueError):
        adapt(bundle, graphic_inputs()[1])


@pytest.mark.parametrize("qualification", ["absent", "wrong_product", "bad_metadata", "synthesized"])
def test_unqualified_inputs_get_no_climatology_warrant(qualification):
    bundle, _ = graphic_inputs()
    event = event_for(bundle)
    if qualification == "absent":
        event = replace(event, provenance=None)
    elif qualification == "wrong_product":
        event.provenance["source_product"] = "another-product-v4"
    elif qualification == "bad_metadata":
        event.provenance["primary_metadata"]["metadata_url"] = "https://example.invalid/"
    else:
        event = replace(event, source_leg="synthesized")
    built = build_regional_sst_anomaly_bundle(event)
    assert source.reference_climatology(event) is None
    assert "reference_climatology" not in built.historical_context
    assert "provenance" not in built.raw_signal_dump


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 1.0), ("schema_version", 2),
    ("source_product", "noaa-crw-ssta-v4"), ("source_response_sha256", "a" * 64),
    ("methodology_url", "https://example.invalid/"),
    ("reference_year_ranges", [[1991, 2020]]),
    ("reference_year_ranges", [[1985.0, 1990], [1993, 1993]]),
    ("derivation_year_range", [1985, 1990]),
    ("method", "1991–2020 daily normal"), ("claim_limit", "A verified ENSO classification"),
    ("unknown_field", "unsupported"),
])
def test_wrong_context_blocks_the_writer_before_a_provider_call(field, value, monkeypatch):
    from src.two_bot import writer

    bundle, _ = graphic_inputs()
    bundle.historical_context["reference_climatology"][field] = value
    calls = []
    monkeypatch.setattr(writer, "_call_writer_provider", lambda *a, **k: calls.append(1))
    audit = audit_story_bundle(bundle)
    assert not audit.prompt_ready
    assert "crw_climatology_unqualified" in {i.code for i in audit.issues}
    result = writer.write_tweet(bundle, MemorySlice())
    assert result.tweet is None and "Evidence requires repair" in result.kill_reason
    assert calls == []


@pytest.mark.parametrize("value", [None, {}, [], True, "legacy", float("nan")])
def test_present_partial_context_is_never_interpreted_as_legacy(value):
    bundle, packet = graphic_inputs()
    bundle.historical_context["reference_climatology"] = value
    assert not audit_story_bundle(bundle).prompt_ready
    with pytest.raises(ValueError):
        adapt(bundle, packet)


@pytest.mark.parametrize("change", ["hash", "product", "raw_absent", "signal", "event", "where", "when"])
def test_context_cannot_be_transplanted_to_another_source_or_identity(change):
    bundle, _ = graphic_inputs()
    if change == "hash":
        bundle.raw_signal_dump["provenance"]["response_sha256"] = "b" * 64
    elif change == "product":
        bundle.raw_signal_dump["provenance"]["source_product"] = "different"
    elif change == "raw_absent":
        bundle.raw_signal_dump.pop("provenance")
    else:
        setattr(bundle, {"signal": "signal_kind", "event": "event_id"}.get(change, change), "different")
    assert not audit_story_bundle(bundle).prompt_ready


def test_exact_legacy_and_current_graphics_keep_value_and_alt_but_not_identity():
    current, packet = graphic_inputs()
    legacy = legacy_regional_sst_anomaly_snapshot(event_for(current))
    before = deepcopy((legacy, current, packet))
    old, new = adapt(legacy, packet), adapt(current, packet)
    # Frozen hashes independently computed with the released pre-change builder.
    assert fingerprint(legacy.to_dict()) == "0be6bf54606604c12e36f5b7392bac143a7fa392ff76b2abcff9b42b727ef8fd"
    assert fingerprint(old) == "26279086ddc19863a095c93eb0ad63eeb69667a22f5ec487c4084801acd2252f"
    assert audit_story_bundle(legacy).prompt_ready
    assert "reference_climatology" not in legacy.historical_context
    assert legacy.historical_context["source"].endswith("(ERDDAP noaacrwsstanomalyDaily)")
    assert old["evidence"]["input_binding"]["adapter_version"] == LEGACY_ADAPTER_VERSION
    assert new["evidence"]["input_binding"]["adapter_version"] == ADAPTER_VERSION
    assert old["expected_evidence_sha256"] != new["expected_evidence_sha256"]
    assert old["evidence"]["value"] == new["evidence"]["value"] == 3.6
    assert build_alt_text(old["template"], old["evidence"]) == build_alt_text(new["template"], new["evidence"])
    assert (legacy, current, packet) == before
    for spec in (old, new):
        assert validate_graphic(spec["template"], spec["evidence"], expected_evidence_sha256=spec["expected_evidence_sha256"]) == spec["evidence"]


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("change", ["version", "unknown_version", "baseline", "context", "extra_fact"])
def test_rehashed_changes_cannot_reinterpret_a_graphic(legacy, change):
    bundle, packet = graphic_inputs()
    if legacy:
        bundle = legacy_regional_sst_anomaly_snapshot(event_for(bundle))
    spec = adapt(bundle, packet)
    evidence = spec["evidence"]
    binding = evidence["input_binding"]
    row = binding["bundles"][0]
    if change == "version":
        binding["adapter_version"] = ADAPTER_VERSION if legacy else LEGACY_ADAPTER_VERSION
    elif change == "unknown_version":
        binding["adapter_version"] = "p31-crw-erddap-3"
    elif change == "baseline":
        evidence["climatology"] = "1991–2020 normal"
    elif change == "context":
        row["bundle"]["historical_context"]["reference_climatology"] = {}
    else:
        row["bundle"]["current_facts"].append({"label": "historical_record", "value": True})
    row["bundle_sha256"] = fingerprint(row["bundle"])
    with pytest.raises(ValueError):
        validate_graphic(spec["template"], evidence, expected_evidence_sha256=fingerprint(evidence))


@pytest.mark.parametrize("legacy", [True, False])
def test_both_versions_still_require_current_exact_policy_for_joint_review(legacy):
    from tests.test_crw_media_review import seed
    from tests.test_joint_media_review import make, status
    from tests.test_media_review_packet import manifest_for

    inputs = seed.__wrapped__()
    if legacy:
        bundle = legacy_regional_sst_anomaly_snapshot(RegionalSSTAnomalyEvent(**inputs["draft"]["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]))
        inputs["draft"]["review_context"]["two_bot"]["bundle"] = story_bundle_snapshot(bundle)
        inputs["graphic_spec"] = adapt(bundle, graphic_inputs()[1])
        inputs["renderer_manifest"] = manifest_for(inputs["graphic_spec"], inputs["png_bytes"])
        inputs["expected_draft_identity"] = draft_identity(inputs["draft"])
    record = make(inputs)  # Explicit synthetic fixture decisions, not human approval.
    assert status(record, inputs)["accepted"]
    inputs["editorial_policy"]["execution_sha256"] = "f" * 64
    assert not status(record, inputs)["accepted"]


@pytest.mark.parametrize("omitted", ["3.60", "2026-06-14", "1985", "1990", "1993", "2012"])
def test_literal_inventory_cannot_skip_baseline_years_dates_or_measurements(omitted):
    # Invented complete material inventory; this tests coverage, not entailment.
    text = "CRW: +3.60°C on 2026-06-14; reference 1985–1990 plus 1993, derived from 1985–2012."
    literals = ["CRW", "+3.60°C", "2026-06-14", "1985", "1990", "1993", "2012"]
    claims = [SimpleNamespace(text=s) for s in literals]
    assert material_span_failures(text, claims) == []
    incomplete = [c for c in claims if omitted not in c.text]
    failures = material_span_failures(text, incomplete)
    # The literal scanner inventories ISO date components separately.
    expected = ["2026", "06", "14"] if omitted == "2026-06-14" else [omitted]
    assert all(any(value in failure for failure in failures) for value in expected)
