"""Invented AWC data and model replies; no live source, paid call or X post."""

from copy import deepcopy

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.editorial.automatic_text import OVER_CAP, automatic_text_hold
from src.editorial.revisions import text_hash
from src.two_bot import pipeline
from src.two_bot.source_links import format_source_link
from src.two_bot.types import CriticResult, FactCheckResult
from src.voice import safety
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_awc_observed import NOW, TARGET
from tests.test_awc_observed_automatic import COPY, Transport, generate, sender, world as world

CREDIT = " (NOAA METAR observations)"


def qualified(monkeypatch):
    transport = Transport()
    transport.install(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    monkeypatch.setenv(source.ENABLE_FLAG, "1")
    with freeze_time(NOW):
        return source.build_bundle(source.nominate())


@pytest.mark.parametrize("punctuation", ["", ".", "!", "?"])
def test_exact_optional_credit_is_removed_before_one_exact_citation(monkeypatch, punctuation):
    story = qualified(monkeypatch)
    before = deepcopy(story.to_dict())
    body = COPY.removesuffix(".") + punctuation
    raw = COPY.removesuffix(".") + CREDIT + punctuation
    url = source.citation(["TAAA", "TBBB"], TARGET)
    assert len(raw + "\n" + url) > 200
    with freeze_time(NOW):
        result = format_source_link(raw, story)
        assert result == body + "\n" + url
        assert format_source_link(result, story) == result
        assert source.claim_failures(result, story) == []
    assert story.to_dict() == before
    assert automatic_text_hold(result) is None


@pytest.mark.parametrize("suffix", [
    " (NOAA METAR observations; preliminary)", " (NOAA METAR estimates)",
    " (NOAA METAR observations, not forecasts)", " (NOAA METAR observations) extra",
    " (NOAA METAR observations)..", " (noaa metar observations)",
    "\t(NOAA METAR observations)", CREDIT + CREDIT,
])
def test_other_qualifiers_and_uncertain_credit_patterns_are_untouched(monkeypatch, suffix):
    story = qualified(monkeypatch)
    body = COPY + suffix
    with freeze_time(NOW):
        result = format_source_link(body, story)
    assert result.split("\n", 1)[0] == body


@pytest.mark.parametrize("change", ["missing-evidence", "changed-reading", "changed-url", "wrong-kind"])
def test_unqualified_source_cannot_authorize_copy_cleanup(monkeypatch, change):
    story = qualified(monkeypatch)
    if change == "missing-evidence":
        story.raw_signal_dump.pop("evidence")
    elif change == "changed-reading":
        story.headline_metric["value"] += 1
    elif change == "changed-url":
        story.current_facts.append({"label": "public_source_url", "value": "https://example.invalid/other"})
    elif change == "wrong-kind":
        story.signal_kind = "monthly_climate_report"
    body = COPY.removesuffix(".") + CREDIT + "."
    with freeze_time(NOW):
        result = format_source_link(body, story)
    assert result.split("\n", 1)[0] == body


@pytest.mark.parametrize("change", ["expired", "source-off", "observed-off"])
def test_retained_derivation_stays_deterministic_but_grants_no_currentness(monkeypatch, change):
    from dataclasses import asdict
    from datetime import timedelta
    from src.editorial.policy import current_editorial_policy
    from src.editorial.revisions import fingerprint
    from src.two_bot.candidate_derivation import derive_candidate
    from src.two_bot.types import WriterResult

    story = qualified(monkeypatch)
    candidate = asdict(WriterResult(COPY.removesuffix(".") + CREDIT + ".", None,
                                   "number", None, None, "Explicit offline fixture"))
    with freeze_time(NOW):
        policy = current_editorial_policy()
        first = derive_candidate(candidate, fingerprint(candidate), story.to_dict(), policy)
    if change == "source-off":
        monkeypatch.setenv(source.ENABLE_FLAG, "0")
    elif change == "observed-off":
        monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "0")
    at = NOW + timedelta(hours=2)
    with freeze_time(at):
        assert derive_candidate(candidate, fingerprint(candidate), story.to_dict(), policy) == first
        assert source.current_bundle_hold(story) is not None
    assert first["final_text"] == COPY + "\n" + source.citation(["TAAA", "TBBB"], TARGET)


def test_credit_removal_never_changes_cap_or_invents_space_for_more_copy(monkeypatch):
    story = qualified(monkeypatch)
    body = COPY.removesuffix(".") + " additional context" * 2
    with freeze_time(NOW):
        result = format_source_link(body + CREDIT + ".", story)
    assert result == body + ".\n" + source.citation(["TAAA", "TBBB"], TARGET)
    assert len(result) > 200 and automatic_text_hold(result) == OVER_CAP


def test_already_linked_input_is_not_rewritten_and_no_link_is_replaced(monkeypatch):
    story = qualified(monkeypatch)
    raw = COPY.removesuffix(".") + CREDIT + ".\n" + source.citation(["TAAA", "TBBB"], TARGET)
    with freeze_time(NOW):
        assert format_source_link(raw, story) == raw
    assert automatic_text_hold(raw) == OVER_CAP


def test_actual_sdk_archive_preserves_the_original_model_response(monkeypatch, tmp_path):
    import json
    from src.two_bot import request_archive, request_archive_replay, writer
    from src.two_bot.types import MemorySlice
    from tests.test_request_archive_sdk import OfflineProviders, offline_transport, writer_json

    story = qualified(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "invented-no-provider-access")
    raw = COPY.removesuffix(".") + CREDIT + "."
    providers = OfflineProviders().queue("writer", {"text": writer_json(raw)})
    with freeze_time(NOW), offline_transport(providers):
        with request_archive.capture(tmp_path.resolve() / "copy-archive", operation="invented copy fit") as scope:
            result = writer.write_tweet(story, MemorySlice())
            final = format_source_link(result.tweet, story)
    retained = request_archive_replay.load_archive(scope.directory)
    assert retained.status == "complete" and len(retained.calls) == 1
    call = retained.calls[0]
    assert call.stage == "writer" and len(call.attempts) == 1 and len(providers.physical) == 1
    response = json.loads(retained.artifact(call.attempts[0].response.artifact))
    assert json.loads(response["content"][0]["text"])["tweet"] == raw == result.tweet
    assert final == COPY + "\n" + source.citation(["TAAA", "TBBB"], TARGET)


def checked_stages(monkeypatch, world, *, refuse=None):
    _, _, _, called, _ = world
    raw = COPY.removesuffix(".") + CREDIT + "."
    stages = stage_fakes(called, copy=raw)
    observed = {"writer_results": [], "check_inputs": []}

    def write(*args, **kwargs):
        result = stages[0](*args, **kwargs)
        observed["writer_results"].append(result)
        return result

    def check(index, name):
        def run(text, *args, **kwargs):
            observed["check_inputs"].append((name, text))
            result = stages[index](text, *args, **kwargs)
            if refuse != name:
                return result
            if name == "safety":
                return False, "Explicit invented required-check refusal"
            if name == "fact_check":
                return FactCheckResult(False, ["Explicit invented failure"], "offline fixture")
            return CriticResult(False, "weak_signal", "offline fixture")
        return run

    monkeypatch.setattr(pipeline.writer, "write_tweet", write)
    monkeypatch.setattr(safety, "check_llm", check(1, "safety"))
    monkeypatch.setattr(pipeline.fact_check, "fact_check", check(2, "fact_check"))
    monkeypatch.setattr(pipeline.critic, "critic_review", check(3, "critic"))
    return observed, raw


def test_real_source_pipeline_checks_final_copy_once_and_binds_then_sends_fixture(monkeypatch, world):
    transport, state, _, called, _ = world
    observed, raw = checked_stages(monkeypatch, world)
    generate(world)
    assert called == ["writer", "safety", "fact_check", "critic"]
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    final = COPY + "\n" + source.citation(["TAAA", "TBBB"], TARGET)
    assert draft["text"] == final and len(final) <= 200
    assert observed["check_inputs"] == [(name, final) for name in ("safety", "fact_check", "critic")]
    assert observed["writer_results"][0].tweet == raw
    assert draft["review_binding"]["text_sha256"] == text_hash(final)
    assert draft["review_context"]["two_bot"]["reviewed_text_sha256"] == text_hash(final)
    assert draft["approval_binding"]["mode"] == "auto" and "automatic_text_hold" not in draft
    assert len(transport.awc_calls) == 6  # No added source request from formatting.
    sender(monkeypatch, world)
    assert transport.x_posts == [final]  # In-process invented transport, never X.
    assert called.count("writer") == 1
    assert observed["writer_results"][0].tweet == raw


@pytest.mark.parametrize("stage", ["safety", "fact_check", "critic"])
def test_cleaner_text_does_not_bypass_any_failed_required_check(monkeypatch, world, stage):
    observed, raw = checked_stages(monkeypatch, world, refuse=stage)
    generate(world)
    assert stage in world[3] and world[1]["drafts"] == [] and world[0].x_posts == []
    final = COPY + "\n" + source.citation(["TAAA", "TBBB"], TARGET)
    assert all(text == final for _, text in observed["check_inputs"])
    assert observed["writer_results"][0].tweet == raw
    assert world[3].count("writer") == 1
