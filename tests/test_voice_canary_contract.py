"""Offline canary boundary checks. Never select or execute the paid test body."""
from copy import deepcopy
import json

import pytest

from src.two_bot import writer
from src.two_bot.evidence_contract import audit_story_bundle
from src.data.temperature_evidence import temperature_claim_failures
from src.voice import safety
from tests.voice_regression import conftest as replay_fixtures
from tests.voice_regression import test_canary as canary


SINGLE_SENTENCES = {
    "verkhoyansk_monthly_high_bundle": "Verkhoyansk, Russia, is forecast to reach 14.8°C on April 29.",
    "co2_milestone_bundle": "Mauna Loa's daily mean CO2 reached 436.1 ppm on April 19.",
    "marine_heatwave_bundle": "The ocean mean between 60°S and 60°N was 21.18°C on June 11.",
}


def bundles():
    return {name: getattr(replay_fixtures, name).__wrapped__() for name in canary.CANARY_FIXTURES}


class FixtureRequest:
    def __init__(self, packets):
        self.packets = packets

    def getfixturevalue(self, name):
        return self.packets[name]


def response(tweet):
    return json.dumps({"tweet": tweet, "kill_reason": None, "angle_chosen": "measurement",
                       "era_anchor_used": None, "peer_comparison_used": None,
                       "reasoning": "One supported fact with scope and date.", "cited_impact": None,
                       "kill_scope": None, "kill_code": None})


@pytest.mark.parametrize("name", canary.CANARY_FIXTURES)
def test_canary_fixture_reaches_actual_writer_and_accepts_a_complete_single_sentence(monkeypatch, name):
    packet = bundles()[name]
    original = deepcopy(packet.to_dict())
    assert audit_story_bundle(packet).prompt_ready
    assert not audit_story_bundle(packet).issues
    assert packet.raw_signal_dump["fixture_only"] is True
    assert "synthetic" in packet.raw_signal_dump["source_name"].lower()
    provider_calls, safety_calls = [], []
    tweet = SINGLE_SENTENCES[name]
    assert len(tweet) < 100 and ". " not in tweet and tweet.endswith(".")
    monkeypatch.setattr(writer, "_call_writer_provider", lambda prompt: provider_calls.append(prompt) or response(tweet))
    monkeypatch.setattr(safety, "check_llm", lambda text: safety_calls.append(text) or (True, None))
    outcomes, unsafe = [], []
    memory = replay_fixtures.fresh_memory_slice.__wrapped__()
    assert canary._sample_fixture(packet, memory, name, outcomes, unsafe)
    assert len(provider_calls) == 1 and safety_calls == [tweet]
    assert not unsafe and outcomes == [f"{name}: produced a safety-passing tweet"]
    assert packet.to_dict() == original


def test_preflight_reports_all_bad_fixtures_before_any_provider_attempt(monkeypatch):
    packets = bundles()
    for packet in packets.values():
        packet.raw_signal_dump = {"event_id": packet.event_id, "fixture_only": True}
        packet.current_facts = [fact for fact in packet.current_facts if fact["label"] not in {"source", "source_name", "source_product"}]
    calls = []
    monkeypatch.setattr(writer, "_call_writer_provider", lambda prompt: calls.append(prompt))
    with pytest.raises(pytest.fail.Exception, match="fixture contract failed before provider calls") as failure:
        canary._preflight_fixtures(FixtureRequest(packets))
    assert "provider error" not in str(failure.value)
    assert all(name in str(failure.value) for name in canary.CANARY_FIXTURES)
    assert "missing_provenance" in str(failure.value) and not calls


def test_preflight_passes_all_current_packets_without_modification():
    packets = bundles()
    original = {name: deepcopy(packet.to_dict()) for name, packet in packets.items()}
    assert canary._preflight_fixtures(FixtureRequest(packets)) == packets
    assert {name: packet.to_dict() for name, packet in packets.items()} == original


def test_fixture_limits_do_not_become_archives_global_co2_or_completed_temperatures():
    packets = bundles()
    forecast = packets["verkhoyansk_monthly_high_bundle"]
    evidence = forecast.raw_signal_dump["evidence"]
    assert evidence["evidence_type"] == "forecast" and evidence["valid_date"] == forecast.when
    assert evidence["valid_start"] == "2026-04-28T14:00:00Z"
    assert forecast.historical_context["record_comparison_qualified"] is False
    assert "old_record_c" not in forecast.raw_signal_dump
    assert not temperature_claim_failures(SINGLE_SENTENCES["verkhoyansk_monthly_high_bundle"], forecast)
    assert temperature_claim_failures("Verkhoyansk, Russia, reached 14.8°C on April 29.", forecast)
    co2 = packets["co2_milestone_bundle"]
    facts = {fact["label"]: fact["value"] for fact in co2.current_facts}
    assert "not a global daily mean" in facts["measurement_scope"]
    assert "ppm_growth_per_year_recent" not in co2.historical_context
    ocean = packets["marine_heatwave_bundle"]
    assert ocean.historical_context["scope"] == "ocean_mean_snapshot_only"
    assert ocean.raw_signal_dump["spatial_scope"] == "ocean_60S_60N"
    assert not {"days", "archive_max_c", "peak_anomaly_c"} & ocean.raw_signal_dump.keys()


def test_canary_still_rejects_unsafe_copy_and_labels_unrecovered_provider_errors(monkeypatch):
    packet = bundles()[canary.CANARY_FIXTURES[0]]
    memory = replay_fixtures.fresh_memory_slice.__wrapped__()
    monkeypatch.setattr(writer, "_call_writer_provider", lambda prompt: response("BREAKING: A forecast."))
    monkeypatch.setattr(safety, "check_llm", lambda text: pytest.fail("Regex should reject before safety LLM"))
    outcomes, unsafe = [], []
    assert not canary._sample_fixture(packet, memory, "fixture", outcomes, unsafe)
    assert len(unsafe) == 1 and "UNSAFE" in outcomes[0]

    def unavailable(prompt):
        raise RuntimeError("offline simulated provider failure")

    monkeypatch.setattr(writer, "_call_writer_provider", unavailable)
    with pytest.raises(pytest.fail.Exception, match="provider error on fixture"):
        canary._sample_fixture(packet, memory, "fixture", [], [])
