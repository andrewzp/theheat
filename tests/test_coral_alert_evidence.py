"""Invented DHW-only records; no source recovery or live model adjudication."""

from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import pytest

from src.data import coral_dhw
from src.data.coral_evidence import DHW_ONLY_STRESS_LEVEL, DHW_ONLY_LIMIT, DHW_POINT_SCOPE
from src.two_bot import writer, fact_check
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.marine import build_coral_bleaching_bundle
from src.two_bot.scientific_claims import scientific_claim_failures
from src.two_bot.types import MemorySlice


def point_bundle(dhw=8.3):
    text = (
        "time,latitude,longitude,degree_heating_week\n"
        "UTC,degrees_north,degrees_east,degree_Celsius_weeks\n"
        f"{date.today().isoformat()}T12:00:00Z,-16.075,145.975,{dhw}\n"
    )
    reading = coral_dhw._reading_from_erddap_csv(
        text, coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"], max_age_days=5,
    )
    event = coral_dhw.detect_dhw_thresholds([reading], {})[0]
    return build_coral_bleaching_bundle(event)


@pytest.mark.parametrize("dhw,tier", [(4.0, 4), (7.9, 4), (8.0, 8), (11.9, 8), (12.0, 12), (25.0, 12)])
def test_source_event_bundle_keeps_dhw_tier_and_unknown_alert_status(dhw, tier):
    bundle = point_bundle(dhw)
    before = deepcopy(bundle)
    assert audit_story_bundle(bundle).prompt_ready
    assert bundle.headline_metric == {"label": "DHW", "value": dhw, "unit": "°C-weeks"}
    assert bundle.raw_signal_dump["source_leg"] == "crw_erddap"
    assert bundle.raw_signal_dump["dhw_tier"] == tier
    assert bundle.raw_signal_dump["stress_level"] == DHW_ONLY_STRESS_LEVEL
    facts = {f["label"]: f["value"] for f in bundle.current_facts}
    assert facts["sample_scope"] == DHW_POINT_SCOPE
    assert facts["claim_limit"] == DHW_ONLY_LIMIT
    assert facts["bleaching_alert_status"] == "unavailable"
    assert bundle == before


@pytest.mark.parametrize("change", ["raw", "fact", "duplicate", "missing_limit", "wrong_scope", "wrong_leg", "baa", "legacy_source", "available"])
def test_inferred_or_incomplete_backup_context_never_calls_either_provider(change, monkeypatch):
    bundle = point_bundle()
    if change == "raw":
        bundle.raw_signal_dump["stress_level"] = "Bleaching Alert Level 2"
    elif change == "fact":
        next(f for f in bundle.current_facts if f["label"] == "stress_level")["value"] = "No Stress"
    elif change == "duplicate":
        bundle.current_facts.append({"label": "stress_level", "value": "Bleaching Warning"})
    elif change == "missing_limit":
        bundle.current_facts = [f for f in bundle.current_facts if f["label"] != "claim_limit"]
    elif change == "wrong_scope":
        next(f for f in bundle.current_facts if f["label"] == "sample_scope")["value"] = "All regional reefs"
    elif change == "wrong_leg":
        bundle.raw_signal_dump.pop("source_leg")
    elif change == "baa":
        bundle.raw_signal_dump["baa_7day_max"] = 4
    elif change == "legacy_source":
        next(f for f in bundle.current_facts if f["label"] == "data_source")["value"] = "NOAA Coral Reef Watch ERDDAP DHW grid"
    else:
        next(f for f in bundle.current_facts if f["label"] == "bleaching_alert_status")["value"] = "available"
    before = deepcopy(bundle)
    assert not audit_story_bundle(bundle).prompt_ready
    writer_call, checker_call = Mock(), Mock()
    monkeypatch.setattr(writer, "_call_writer_provider", writer_call)
    monkeypatch.setattr(fact_check, "_call_gemini", checker_call)
    assert writer.write_tweet(bundle, MemorySlice()).tweet is None
    assert not fact_check.fact_check("The sample has 8.3°C-weeks of accumulated heat stress.", [], bundle, {}).passed
    writer_call.assert_not_called()
    checker_call.assert_not_called()
    assert bundle == before


@pytest.mark.parametrize("label", [
    "Bleaching Alert Level 1", "Alert Level 2", "alert 3", "LEVEL 4", "level-5",
    "level–2", "Level: 3", "level=5", "Alert Level II", "alert level IV",
    "level five", "No Stress", "Bleaching Watch", "Bleaching Warning",
    "Level 6", "Level 10", '"Alert Level 2"',
])
def test_unavailable_current_classification_is_rejected_before_paid_check(label, monkeypatch):
    bundle = point_bundle()
    tweet = f"The sampled reef is at {label}."
    assert any(s.startswith("unwarranted_coral_alert:") for s in scientific_claim_failures(tweet, bundle))
    call = Mock()
    monkeypatch.setattr(fact_check, "_call_gemini", call)
    assert not fact_check.fact_check(tweet, [], bundle, {}).passed
    call.assert_not_called()


@pytest.mark.parametrize("tweet", [
    "The satellite sample has 8.3°C-weeks of accumulated heat stress.",
    "The current bleaching alert level is unavailable.",
    "Accumulated heat raises the risk of coral bleaching.",
])
def test_dhw_and_unknown_status_still_require_model_adjudication(tweet, monkeypatch):
    bundle = point_bundle()
    assert scientific_claim_failures(tweet, bundle) == []
    # None means the paid boundary is still required, never a local approval.
    assert fact_check.local_rejection(tweet, [], bundle, {}) is None
    call = Mock(return_value='{"passed":false,"failures":["Synthetic unresolved claim"],"extracted_claims":[]}')
    monkeypatch.setattr(fact_check, "_call_gemini", call)
    assert not fact_check.fact_check(tweet, [], bundle, {}).passed
    call.assert_called_once()


@pytest.mark.parametrize("label", ["No Stress", "Bleaching Watch", "Alert Level 1", "Alert Level 2"])
def test_primary_supplied_label_is_not_recomputed_from_dhw(label):
    reading = coral_dhw.CoralDHWReading(
        "gbr_northern", "Northern GBR", date.today().isoformat(), 12.5, label, 4,
    )
    event = coral_dhw.detect_dhw_thresholds([reading], {})[0]
    bundle = build_coral_bleaching_bundle(event)
    assert event.stress_level == label
    assert audit_story_bundle(bundle).prompt_ready
    assert not any(f["label"] == "bleaching_alert_status" for f in bundle.current_facts)
    # This new backup-only gate does not certify the primary label's source truth.
    assert scientific_claim_failures(f"The primary reports {label}.", bundle) == []


def test_legacy_inferred_event_is_retained_but_not_silently_repaired():
    event = coral_dhw.CoralBleachingEvent(
        "gbr_northern", "Northern GBR", "2026-06-14", 8.3, 8,
        "mass bleaching expected", "Bleaching Alert Level 2", "invented-legacy",
        source_leg="crw_erddap",
    )
    before = deepcopy(event)
    bundle = build_coral_bleaching_bundle(event)
    assert event == before
    assert bundle.raw_signal_dump["stress_level"] == "Bleaching Alert Level 2"
    assert not audit_story_bundle(bundle).prompt_ready


@pytest.mark.parametrize("field", ["evidence", "provenance", "source"])
def test_arbitrary_appended_warrant_cannot_qualify_an_alert(field):
    bundle = point_bundle()
    bundle.raw_signal_dump[field] = {
        "source_product": "invented-baa", "source_url": "https://example.invalid/baa",
        "hotspot_c": 1.5, "baa_7day_max": 5,
    }
    assert any(s.startswith("unwarranted_coral_alert:") for s in scientific_claim_failures("Bleaching Alert Level 3.", bundle))


def test_compound_threshold_is_not_an_alert_class_or_a_source_warrant():
    from src.editorial.synthesis import detect_marine_compound
    from src.two_bot.intern.synthesis import build_synthesis_bundle
    from tests.test_synthesis import _state_with_marine_components

    signal = detect_marine_compound(_state_with_marine_components())[0]
    assert "DHW at least 8 °C-weeks" in signal.headline
    assert "Alert" not in signal.headline
    assert signal.components["coral_dhw_tier"] == 8
    bundle = build_synthesis_bundle({
        "kind": "marine_compound", "region": signal.region, "event_id": signal.event_id,
        "headline": signal.headline, "components": [signal.components], "total_score": 80,
    })
    audit = audit_story_bundle(bundle)
    assert not audit.prompt_ready and "missing_provenance" in {i.code for i in audit.issues}
