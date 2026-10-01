"""Offline canary controls; any marked-body execution uses explicit call traps.

Injected responses/qualification records exercise software boundaries, never
independent evidence qualification or live provider quality.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
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


@pytest.mark.parametrize("credential_present", [False, True])
def test_actual_canary_body_blocks_all_current_synthetic_packets_without_spending(monkeypatch, credential_present):
    packets = bundles()
    original = {name: deepcopy(packet.to_dict()) for name, packet in packets.items()}
    if credential_present:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        pytest.fail("Known ineligible fixtures must not call a provider or safety")

    monkeypatch.setattr(writer, "_call_writer_provider", forbidden)
    monkeypatch.setattr(canary, "run_safety_pipeline", forbidden)
    with pytest.raises(pytest.fail.Exception, match="monitor_blocked / fixture_ineligible") as failure:
        canary.test_canary_api_reachable_and_writer_produces(
            FixtureRequest(packets), replay_fixtures.fresh_memory_slice.__wrapped__())
    message = str(failure.value)
    assert all(f"{name}: synthetic_fixture" in message for name in canary.CANARY_FIXTURES)
    assert "provider_reachability=unobserved" in message and "writer_quality=unknown" in message
    assert "billing" not in message and "degraded" not in message and not calls
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
    assert len(unsafe) == 1 and "SAFETY_NOT_PASSED" in outcomes[0]

    def unavailable(prompt):
        raise RuntimeError("offline simulated provider failure")

    monkeypatch.setattr(writer, "_call_writer_provider", unavailable)
    with pytest.raises(pytest.fail.Exception, match="writer_call_failed; cause=unclassified"):
        canary._sample_fixture(packet, memory, "fixture", [], [])


NOW = datetime(2026, 10, 1, 17, tzinfo=UTC)


def offline_qualification_controls(monkeypatch):
    """Explicit offline records only, never exported as source qualifications."""
    packets = bundles()
    records = {}
    for name, packet in packets.items():
        packet.raw_signal_dump.pop("fixture_only")
        packet.raw_signal_dump.pop("fixture_note")
        packet.raw_signal_dump["source_name"] = "Offline contract control"
        records[name] = canary.FixtureQualification(
            canary.fingerprint(packet.to_dict()), NOW - timedelta(hours=1),
            NOW + timedelta(hours=1), "offline injected qualification; not source evidence")
    monkeypatch.setattr(canary, "QUALIFIED_POSITIVE_FIXTURES", records)
    return packets, records


def test_removing_synthetic_labels_does_not_qualify_a_positive_fixture():
    assert canary.QUALIFIED_POSITIVE_FIXTURES == {}
    packets = bundles()
    for packet in packets.values():
        packet.raw_signal_dump = {"source_name": "Unverified named source"}
    with pytest.raises(pytest.fail.Exception, match="positive_fixture_unqualified"):
        canary._preflight_fixtures(FixtureRequest(packets), now=NOW)


def test_exact_current_offline_qualification_control_reaches_boundary(monkeypatch):
    packets, _ = offline_qualification_controls(monkeypatch)
    assert canary._preflight_fixtures(FixtureRequest(packets), now=NOW) == packets
    # Marking a packet synthetic must still reject an otherwise matching hash.
    name = canary.CANARY_FIXTURES[0]
    packets[name].raw_signal_dump["fixture_only"] = True
    with pytest.raises(pytest.fail.Exception, match="synthetic_fixture"):
        canary._preflight_fixtures(FixtureRequest(packets), now=NOW)


@pytest.mark.parametrize("change", ["packet", "missing_review", "stale", "future", "naive", "long_window", "reversed"])
def test_offline_qualification_controls_fail_closed_for_identity_and_time(monkeypatch, change):
    packets, records = offline_qualification_controls(monkeypatch)
    name = canary.CANARY_FIXTURES[0]
    old = records[name]
    from dataclasses import replace
    if change == "packet":
        packets[name].headline_metric["value"] = 99
    elif change == "missing_review":
        records[name] = replace(old, evidence_review="")
    elif change == "stale":
        records[name] = replace(old, source_as_of=NOW-timedelta(hours=3), valid_until=NOW-timedelta(seconds=1))
    elif change == "future":
        records[name] = replace(old, source_as_of=NOW+timedelta(seconds=1))
    elif change == "naive":
        records[name] = replace(old, source_as_of=NOW.replace(tzinfo=None))
    elif change == "long_window":
        records[name] = replace(old, valid_until=NOW+timedelta(hours=24))
    else:
        records[name] = replace(old, valid_until=old.source_as_of-timedelta(seconds=1))
    with pytest.raises(pytest.fail.Exception, match="qualification_(mismatch|not_current)"):
        canary._preflight_fixtures(FixtureRequest(packets), now=NOW)


def test_missing_key_is_explicit_after_offline_qualification(monkeypatch):
    packets, _ = offline_qualification_controls(monkeypatch)
    original_preflight = canary._preflight_fixtures
    monkeypatch.setattr(canary, "_preflight_fixtures", lambda request: original_preflight(request, now=NOW))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(writer, "write_tweet", lambda *a: pytest.fail("No key must stop before writer"))
    with pytest.raises(AssertionError, match="provider_credentials_missing"):
        canary.test_canary_api_reachable_and_writer_produces(
            FixtureRequest(packets), replay_fixtures.fresh_memory_slice.__wrapped__())


@pytest.mark.parametrize("kind", ["clean_refusal", "invalid_output", "budget_error", "unknown_error"])
def test_sample_outcomes_do_not_invent_cause_or_disclose_response_text(monkeypatch, kind):
    private = "private response body must not appear in public canary diagnostics"
    calls = []

    def provider(prompt):
        calls.append(prompt)
        if kind == "budget_error":
            raise canary.BudgetExhaustedError(private)
        if kind == "unknown_error":
            raise RuntimeError(private)
        if kind == "invalid_output":
            return json.dumps({"wrong_field": private})
        return json.dumps({"tweet": None, "kill_reason": private, "angle_chosen": "",
                           "era_anchor_used": None, "peer_comparison_used": None, "reasoning": private})

    monkeypatch.setattr(writer, "_call_writer_provider", provider)
    monkeypatch.setattr(canary, "run_safety_pipeline", lambda text: pytest.fail("No produced text"))
    packet = bundles()[canary.CANARY_FIXTURES[0]]
    outcomes = []
    if kind == "clean_refusal":
        assert not canary._sample_fixture(packet, replay_fixtures.fresh_memory_slice.__wrapped__(), "fixture", outcomes, [])
        assert outcomes == ["fixture: writer_declined; no positive quality observation"]
    else:
        code = {"invalid_output": "writer_output_invalid", "budget_error": "provider_budget_exhausted",
                "unknown_error": "writer_call_failed; cause=unclassified"}[kind]
        with pytest.raises(pytest.fail.Exception, match=code) as failure:
            canary._sample_fixture(packet, replay_fixtures.fresh_memory_slice.__wrapped__(), "fixture", outcomes, [])
        assert private not in str(failure.value)
        if kind != "budget_error":
            assert "budget" not in str(failure.value) and "billing" not in str(failure.value)
    assert len(calls) == 1


def test_injected_positive_controls_keep_threshold_and_mandatory_safety(monkeypatch):
    packets, _ = offline_qualification_controls(monkeypatch)
    original_preflight = canary._preflight_fixtures
    monkeypatch.setattr(canary, "_preflight_fixtures", lambda request: original_preflight(request, now=NOW))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    calls, checked = [], []
    tweets = iter(SINGLE_SENTENCES.values())
    monkeypatch.setattr(writer, "_call_writer_provider", lambda prompt: calls.append(prompt) or response(next(tweets)))
    monkeypatch.setattr(canary, "run_safety_pipeline", lambda tweet: checked.append(tweet) or (True, None))
    canary.test_canary_api_reachable_and_writer_produces(FixtureRequest(packets), replay_fixtures.fresh_memory_slice.__wrapped__())
    assert len(calls) == len(checked) == 3 and canary.MIN_PRODUCING == 2


@pytest.mark.parametrize("check_result", [(False, "safety unavailable"), (False, "rejected by safety"), (None, "missing")])
def test_required_check_failure_never_becomes_a_positive_probe(monkeypatch, check_result):
    packets, _ = offline_qualification_controls(monkeypatch)
    original_preflight = canary._preflight_fixtures
    monkeypatch.setattr(canary, "_preflight_fixtures", lambda request: original_preflight(request, now=NOW))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    calls = []
    monkeypatch.setattr(writer, "_call_writer_provider", lambda prompt: calls.append(prompt) or response("Offline control."))
    monkeypatch.setattr(canary, "run_safety_pipeline", lambda tweet: check_result)
    with pytest.raises(AssertionError, match="required safety did not pass"):
        canary.test_canary_api_reachable_and_writer_produces(
            FixtureRequest(packets), replay_fixtures.fresh_memory_slice.__wrapped__())
    assert len(calls) == 3  # no re-sampling a failed required check


def test_qualified_control_refusals_still_cannot_pass_the_positive_threshold(monkeypatch):
    packets, _ = offline_qualification_controls(monkeypatch)
    original_preflight = canary._preflight_fixtures
    monkeypatch.setattr(canary, "_preflight_fixtures", lambda request: original_preflight(request, now=NOW))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    calls = []
    refusal = json.dumps({"tweet": None, "kill_reason": "private offline refusal", "angle_chosen": "",
                          "era_anchor_used": None, "peer_comparison_used": None, "reasoning": "offline"})
    monkeypatch.setattr(writer, "_call_writer_provider", lambda prompt: calls.append(prompt) or refusal)
    monkeypatch.setattr(canary, "run_safety_pipeline", lambda tweet: pytest.fail("No text to check"))
    with pytest.raises(AssertionError, match="positive_generation_unproven; cause=unclassified") as failure:
        canary.test_canary_api_reachable_and_writer_produces(
            FixtureRequest(packets), replay_fixtures.fresh_memory_slice.__wrapped__())
    assert "threshold 2" in str(failure.value) and "private offline refusal" not in str(failure.value)
    assert len(calls) == 6  # legacy positive threshold remains; current real fixtures never reach it


def test_raised_required_safety_failure_is_explicit_and_sanitized(monkeypatch):
    monkeypatch.setattr(writer, "_call_writer_provider", lambda prompt: response("Offline control."))

    def unavailable(text):
        raise RuntimeError("private checker failure body")

    monkeypatch.setattr(canary, "run_safety_pipeline", unavailable)
    with pytest.raises(pytest.fail.Exception, match="safety_call_failed") as failure:
        canary._sample_fixture(bundles()[canary.CANARY_FIXTURES[0]],
                               replay_fixtures.fresh_memory_slice.__wrapped__(), "fixture", [], [])
    assert "private checker" not in str(failure.value)
