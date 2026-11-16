"""Invented observations: required UTC labels and calendar claims stay factual."""
from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.two_bot import writer
from src.two_bot.types import MemorySlice
from tests.test_awc_observed import NOW
from tests.test_awc_observed_automatic import COPY, Transport, generate, sender, world as world


def bundle(monkeypatch):
    transport = Transport()
    transport.install(monkeypatch.setattr)
    with freeze_time(NOW):
        return source.build_bundle(source.nominate())


def test_wrong_explicit_weekday_refuses_but_correct_or_absent_weekday_stays_valid(monkeypatch):
    story = bundle(monkeypatch)
    citation = next(f["value"] for f in story.current_facts if f["label"] == "public_source_url")
    assert source.claim_failures(COPY + "\n" + citation, story, now=NOW) == []
    assert source.claim_failures(COPY.replace("Nov 15", "Sunday Nov 15") + "\n" + citation, story, now=NOW) == []
    assert source.claim_failures(COPY.replace("Nov 15", "Monday Nov 15") + "\n" + citation,
                                 story, now=NOW) == ["awc_weekday_mismatch"]


def test_constructed_writer_input_has_source_specific_qualification_instructions(monkeypatch):
    story = bundle(monkeypatch)
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    prompt = writer.build_writer_user_prompt(story, MemorySlice())
    assert "observed_airport_copy_requirements" in prompt
    assert "12:00 UTC" in prompt and "15 Nov" in prompt
    assert "North Test" in prompt and "South Test" in prompt
    assert "body_max_scalars" in prompt
    assert '"body_max_scalars": 109' in prompt
    assert '"difference_c": 65' in prompt
    assert '"temperature_c": -20' in prompt and '"temperature_c": 45' in prompt


def test_weekday_in_known_airport_name_is_not_a_calendar_claim(monkeypatch):
    transport = Transport()
    transport.stations[0]["site"] = "Monday Test Arpt"
    transport.install(monkeypatch.setattr)
    with freeze_time(NOW):
        story = source.build_bundle(source.nominate())
    text = COPY.replace("North Test", "Monday Test") + "\n" + story.raw_signal_dump["evidence"]["source_url"]
    assert source.claim_failures(text, story, now=NOW) == []
    assert source.claim_failures(text.replace("Nov 15", "Monday Nov 15"), story,
                                 now=NOW) == ["awc_weekday_mismatch"]


@pytest.mark.parametrize("label", ["same hour", "Sunday"])
def test_weekday_or_same_hour_cannot_replace_utc_clock(monkeypatch, label):
    story = bundle(monkeypatch)
    text = COPY.replace("12:00 UTC", label) + "\n" + story.raw_signal_dump["evidence"]["source_url"]
    assert source.claim_failures(text, story, now=NOW) == ["awc_time_label_missing"]


def test_wrong_weekday_is_held_before_provider_checks(world, monkeypatch):
    _, state, _, called, stages = world
    def wrong_day(*args, **kwargs):
        result = stages[0](*args, **kwargs)
        result.tweet = COPY.replace("Nov 15", "Monday Nov 15")
        return result
    monkeypatch.setattr("src.two_bot.pipeline.writer.write_tweet", wrong_day)
    generate(world)
    assert called == ["writer"]
    assert state["drafts"] == []
    sender(monkeypatch, world)
    assert world[0].x_posts == []
