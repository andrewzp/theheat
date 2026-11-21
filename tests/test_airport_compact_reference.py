"""Invented observations and explicit SDK replies, not model-quality proof."""

from copy import deepcopy
import json

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.editorial.automatic_text import automatic_text_hold
from src.two_bot import writer
from src.two_bot.source_links import source_citation
from src.two_bot.types import MemorySlice
from tests.test_awc_observed import NOW
from tests.test_awc_observed_automatic import Transport
from tests.test_observed_airport_body_budget import SHORT, ordinary, stage_and_drain

MARKER = "observed_airport_compact_reference: "


def reference_from_prompt(prompt):
    assert MARKER in prompt
    return json.loads(prompt.split(MARKER, 1)[1].split("\n", 1)[0])


def make_bundle(monkeypatch, name="North Test Arpt"):
    transport = Transport()
    transport.stations[0]["site"] = name
    transport.install(monkeypatch.setattr)
    with freeze_time(NOW):
        return source.build_bundle(source.nominate())


@pytest.mark.parametrize("triage", ["0", "1"])
def test_real_sdk_reference_fits_but_does_not_replace_the_returned_reply(
    monkeypatch, fresh_state, triage
):
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, triage=triage)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 1
    [request] = [request for stage, request in models.requests if stage == "writer"]
    reference = reference_from_prompt(request["messages"][0]["content"])
    [saved] = fresh_state["drafts"]
    from src.two_bot.types import StoryBundle

    bundle = StoryBundle(**saved["review_context"]["two_bot"]["bundle"])
    body = reference["body"]
    full = body + "\n" + source_citation(bundle)
    assert len(body) == reference["body_scalars"] <= 109
    assert automatic_text_hold(full) is None
    captured = source._time(bundle.raw_signal_dump["evidence"]["retrieved_at"])
    assert source.claim_failures(full, bundle, now=captured) == []
    assert body != SHORT
    assert saved["text"] == SHORT + "\n" + source_citation(bundle)
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    assert transport.x_posts == [] and transport.gist_patches == 0


@pytest.mark.parametrize("name", ["North/Island Arpt", "𐐀 Test Arpt", "North Airport"])
def test_reference_retains_complete_source_names_dates_and_exact_values(monkeypatch, name):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    bundle = make_bundle(monkeypatch, name)
    prompt = writer.build_writer_user_prompt(bundle, MemorySlice())
    reference = reference_from_prompt(prompt)
    assert name in reference["body"]
    assert "12:00 UTC 15 Nov" in reference["body"]
    assert "−20°C" in reference["body"] and "45°C" in reference["body"]
    assert "65°C" in reference["body"]
    assert source.claim_failures(
        reference["body"] + "\n" + source_citation(bundle), bundle, now=NOW
    ) == []
    assert reference["body_scalars"] == len(reference["body"])


@pytest.mark.parametrize("change", ["temperature", "citation", "retrieval", "missing"])
def test_invalid_or_mismatched_source_never_offers_a_reference(monkeypatch, change):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    bundle = make_bundle(monkeypatch)
    budget = writer.automatic_copy_budget(bundle)
    if change == "temperature":
        bundle.raw_signal_dump["evidence"]["points"][0]["temperature_c"] = -21
    elif change == "citation":
        budget = deepcopy(budget)
        budget["citation"] = "https://example.invalid/not-the-source"
    elif change == "retrieval":
        bundle.raw_signal_dump["evidence"]["retrieved_at"] = "not-a-time"
    else:
        del bundle.raw_signal_dump["evidence"]
    assert writer.airport_copy_reference(bundle, budget) is None


def test_impossible_length_never_drops_a_name_or_uses_a_truncated_reference(monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    bundle = make_bundle(monkeypatch, "North/" + "Long" * 19 + " Arpt")
    assert len(bundle.raw_signal_dump["evidence"]["points"][0]["airport"]) < 100
    assert writer.airport_copy_reference(bundle, writer.automatic_copy_budget(bundle)) is None


def test_no_reference_for_unrelated_or_nonautomatic_context(monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    bundle = make_bundle(monkeypatch)
    budget = writer.automatic_copy_budget(bundle)
    assert writer.airport_copy_reference(bundle, None) is None
    bundle.signal_kind = "unrelated_invented_fixture"
    assert writer.airport_copy_reference(bundle, budget) is None


@pytest.mark.parametrize("decline", [False, True])
def test_actual_sdk_keeps_json_response_and_decline_with_a_reference(
    monkeypatch, fresh_state, decline
):
    script = {"writer_kill": "weak supported context"} if decline else {}
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, **script)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == (0 if decline else 1)
    requests = [request for stage, request in models.requests if stage == "writer"]
    assert len(requests) == 1
    prompt = requests[0]["messages"][0]["content"]
    assert reference_from_prompt(prompt)["body"]
    assert "required JSON object's tweet field" in prompt
    assert "normal JSON decline contract" in prompt
    assert "Return your chosen body only." not in prompt
    assert requests[0]["output_config"]["format"]["schema"] == writer.WRITER_OUTPUT_SCHEMA
    assert models.stages() == (["writer"] if decline else ["writer", "safety", "fact_check", "critic"])
    assert len(fresh_state["drafts"]) == (0 if decline else 1)
    assert transport.x_posts == [] and transport.gist_patches == 0
