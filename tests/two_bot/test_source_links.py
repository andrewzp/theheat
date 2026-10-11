"""Invented copy and explicit offline model stubs; no source-truth certification."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.editorial.revisions import text_hash, review_is_current
from src.two_bot import pipeline
from src.two_bot.source_links import CYCLONE_LINK_KINDS, format_source_link
from src.two_bot.types import WriterResult, FactCheckResult, CriticResult
from tests.two_bot.conftest import _state_with_memory
from tests.two_bot.source_link_fixtures import bundle, TEXT, URL


@pytest.mark.parametrize("kind", sorted(CYCLONE_LINK_KINDS))
def test_one_exact_link_and_detached_idempotent_input(kind):
    source = bundle(kind=kind)
    before = deepcopy(source)
    result = format_source_link(TEXT, source)
    assert result == TEXT + "\n" + URL
    assert format_source_link(result, source) == result and source == before


@pytest.mark.parametrize("display", [
    "nhc.noaa.gov/text/SYN…", "www.nhc.noaa.gov/text/SYN...",
    "https://www.nhc.noaa.gov/text/SYN…", "https://nhc.noaa.gov/text/SYN...",
    "www.nhc.noaa.gov/text/SYN…  ",
])
def test_terminal_display_replaced_without_changing_prose(display):
    prose = "Synthetic storm: 90 kt at 06:00 UTC, offshore—not a landfall."
    assert format_source_link(prose + " " + display, bundle()) == prose + "\n" + URL


@pytest.mark.parametrize("display", [
    "evil.nhc.noaa.gov/text/SYN…", "nhc.noaa.gov.evil/text/SYN…",
    "nhc.noaa.gov/TEXT/SYN…", "nhc.noaa.gov/text/syn…", "NHC.noaa.gov/text/SYN…",
    "nhc.noaa.gov/other/SYN…", "nhc.noaa.gov/text/%53YN…",
    "nhc.noaa.gov/text/SYN?x=…", "nhc.noaa.gov/text/SYN#…",
    "nhc.noaa.gov…", "nhc.noaa.gov/…", "nhc.noaa.gov/...",
    "http://nhc.noaa.gov/text/SYN…", "a thought…", "a thought...",
    "(nhc.noaa.gov/text/SYN…)",
])
def test_uncertain_terminal_tokens_are_never_removed(display):
    original = TEXT + " " + display
    assert format_source_link(original, bundle()) == original + "\n" + URL


def test_interior_display_and_source_query_are_not_reinterpreted():
    original = "See nhc.noaa.gov/text/SYN… for the source."
    assert format_source_link(original, bundle()) == original + "\n" + URL
    source = bundle([URL + "?version=2"])
    original = TEXT + " nhc.noaa.gov/text/SYN…"
    assert format_source_link(original, source) == original + "\n" + URL + "?version=2"


@pytest.mark.parametrize("other", [URL + "/more", URL + "?x=1", URL + "#part",
                                         "https://example.invalid/?redirect=" + URL])
def test_url_substring_is_not_a_complete_source_token(other):
    assert format_source_link(TEXT + " " + other, bundle()) == TEXT + " " + other + "\n" + URL


@pytest.mark.parametrize("values", [[], [None], [{}], [42], [""], ["not a URL"],
    ["https:///path"], ["https://name:secret@nhc.noaa.gov/path"],
    ["https://nhc.noaa.gov:bad/path"], ["https://nhc.noaa.gov/a b"],
    ["https://nhc.noaa.gov/\npath"], ["https://nhc.noaa.gov/%zz"],
    [URL, None], [URL, "https://example.invalid/another"],
], ids=["missing", "none", "object", "number", "empty", "not-url", "no-host", "userinfo",
        "port", "space", "control", "encoding", "malformed-sibling", "ambiguous"])
def test_missing_or_malformed_source_has_no_formatting_authority(values):
    assert format_source_link(TEXT, bundle(values)) == TEXT


def test_identical_source_facts_and_non_cyclones():
    assert format_source_link(TEXT, bundle([URL, URL])) == TEXT + "\n" + URL
    for kind in ("fire", "cyclone_land_threat", "global_disaster"):
        assert format_source_link(TEXT, bundle(kind=kind)) == TEXT


@pytest.mark.parametrize("url", ["https://./path", "https://bad..host/path", "https://-bad.host/path",
                                   "https://bad_host/path", "https://[bad]/path"])
def test_malformed_hosts_supply_no_source_authority(url):
    assert format_source_link(TEXT, bundle([url])) == TEXT


@pytest.mark.parametrize("length", [0, 50, 235, 236, 250, 256, 257, 280])
def test_both_length_gates_and_no_claim_truncation(length):
    original = "é" * length
    result = format_source_link(original, bundle())
    expected = original + "\n" + URL
    fits = length > 0 and length + 24 <= 280 and len(expected) <= 280
    assert result == (expected if fits else original)
    assert format_source_link(result, bundle()) == result


def test_short_source_still_obeys_conservative_allowance_and_failed_replacement_is_exact():
    original = "é" * 257
    assert len(original + "\nhttps://a.co") < 280
    assert format_source_link(original, bundle(["https://a.co"])) == original
    original = "x" * 250 + " nhc.noaa.gov/text/SYN…  "
    assert format_source_link(original, bundle()) == original


def test_join_whitespace_empty_text_and_exact_interior_url():
    assert format_source_link(TEXT + "  \n", bundle()) == TEXT + "\n" + URL
    for empty in ("", "  ", "\n\t"):
        assert format_source_link(empty, bundle()) == empty
    original = "Source: " + URL + " in the advisory."
    assert format_source_link(original, bundle()) == original
    assert format_source_link("nhc.noaa.gov/text/SYN…", bundle()) == URL


def test_nonlist_facts_and_malformed_values_never_get_stringified():
    source = bundle()
    source.current_facts = {"public_advisory_url": URL}
    assert format_source_link(TEXT, source) == TEXT
    assert format_source_link(TEXT, bundle([{"url": URL}])) == TEXT


def test_malformed_unicode_source_cannot_turn_valid_copy_into_invalid_text():
    assert format_source_link(TEXT, bundle(["https://nhc.noaa.gov/\ud800"])) == TEXT


@pytest.fixture
def models(monkeypatch, configured_pipeline_providers):
    """Only external model behavior is stubbed; evidence/local gates stay real."""
    write = Mock(return_value=WriterResult(TEXT, None, "plain_number", None, None, "fixture"))
    safety = Mock(return_value=(True, None))
    factual = Mock(return_value=FactCheckResult(True, [], "offline fixture"))
    critic = Mock(return_value=CriticResult(True, None, "offline fixture"))
    monkeypatch.setattr(pipeline.writer, "write_tweet", write)
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety)
    monkeypatch.setattr(pipeline.fact_check, "fact_check", factual)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    monkeypatch.setattr(pipeline, "_writer_samples", lambda: 1)
    monkeypatch.setattr(pipeline, "_critic_enabled", lambda: True)
    monkeypatch.setattr(pipeline, "_critic_revise_enabled", lambda: False)
    return write, safety, factual, critic


def test_single_final_candidate_is_checked_bound_and_saved_without_an_extra_call(models):
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
    from src.editorial.scoring import score_cyclone_tier_crossing
    original = deepcopy(models[0].return_value)
    state = _state_with_memory()
    saved = _try_two_bot_draft(bundle(), state, score_cyclone_tier_crossing(2, 4, "Atlantic"),
                               legacy_type="cyclone_tier_crossing", event_id="synthetic-link",
                               review_context={})
    assert saved
    draft = state["drafts"][0]
    final = TEXT + "\n" + URL
    assert draft["text"] == final and review_is_current(draft)
    assert draft["review_context"]["two_bot"]["reviewed_text_sha256"] == text_hash(final)
    assert all(m.call_count == 1 for m in models)
    assert all(m.call_args.args[0] == final for m in models[1:])
    assert models[0].return_value == original


def test_slate_selection_sees_formatted_copies_and_checks_exact_selected_text(models, monkeypatch):
    raw = [WriterResult(t, None, "plain_number", None, None, "fixture")
           for t in (TEXT + " nhc.noaa.gov/text/SYN…", "Second synthetic storm sentence.")]
    before = deepcopy(raw)
    monkeypatch.setattr(pipeline, "_writer_samples", lambda: 2)
    models[0].side_effect = raw
    slate = Mock(return_value=CriticResult(True, None, "offline slate", selected_index=1))
    monkeypatch.setattr(pipeline.critic, "critic_select_slate", slate)
    draft = pipeline.generate_draft(bundle(), _state_with_memory())
    candidates = slate.call_args.args[0]
    final = candidates[1]
    assert draft and draft["text"] == final
    assert set(candidates) == {TEXT + "\n" + URL, raw[1].tweet + "\n" + URL}
    assert all(m.call_args.args[0] == final for m in models[1:3])
    assert not models[3].called and models[0].call_count == 2 and raw == before


def test_optional_revision_is_formatted_before_every_repeated_check(models, monkeypatch):
    monkeypatch.setattr(pipeline, "_critic_revise_enabled", lambda: True)
    revised = WriterResult("Revised synthetic sentence.", None, "plain_number", None, None, "fixture")
    models[0].side_effect = [models[0].return_value, revised]
    models[3].side_effect = [CriticResult(False, None, "offline", verdict="REVISE",
                                         revise_instruction="Use the supplied revised fixture."),
                            CriticResult(True, None, "offline")]
    draft = pipeline.generate_draft(bundle(), _state_with_memory())
    first, second = TEXT + "\n" + URL, revised.tweet + "\n" + URL
    assert draft and draft["text"] == second
    assert draft["two_bot_metadata"]["reviewed_text_sha256"] == text_hash(second)
    assert all([c.args[0] for c in m.call_args_list] == [first, second] for m in models[1:])
    assert models[0].call_count == 2 and revised.tweet == "Revised synthetic sentence."


def test_shadow_formats_before_its_existing_checks(models):
    draft = pipeline.generate_shadow_draft(bundle(), _state_with_memory())
    assert draft and draft["text"] == TEXT + "\n" + URL
    assert all(m.call_args.args[0] == draft["text"] for m in models[1:3])
    assert models[0].call_count == 1 and not models[3].called


def test_dispatch_refuses_cyclone_kind_mismatch_without_postcheck_edit(models):
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
    from src.editorial.scoring import score_cyclone_tier_crossing
    from src.two_bot.intern.fire import build_fire_bundle
    from tests.fire_source_fixtures import fire_event
    state, outcome = _state_with_memory(), {}
    assert not _try_two_bot_draft(build_fire_bundle(fire_event()), state,
        score_cyclone_tier_crossing(2, 4, "Atlantic"), legacy_type="cyclone_tier_crossing",
        event_id="synthetic-wrong-kind", review_context={}, result_out=outcome)
    assert not state["drafts"] and outcome["kill_stage"] == "final_format"
    assert all(m.call_count == 1 for m in models)
    assert all(m.call_args.args[0] == TEXT for m in models[1:])


@pytest.mark.parametrize("stage", ["local", "safety", "fact", "critic"])
def test_formatted_text_retains_failures_and_exact_rejected_candidate(models, monkeypatch, stage):
    failed = FactCheckResult(False, ["unverified synthetic claim"], "offline fixture")
    if stage == "local":
        local = Mock(return_value=failed)
        monkeypatch.setattr(pipeline.fact_check, "local_rejection", local)
    elif stage == "safety":
        models[1].return_value = (False, "unavailable")
    elif stage == "fact":
        models[2].return_value = failed
    else:
        models[3].return_value = CriticResult(False, "unverified", "offline fixture")
    outcome = {}
    assert pipeline.generate_draft(bundle(), _state_with_memory(), result_out=outcome) is None
    final = TEXT + "\n" + URL
    if stage == "local":
        assert local.call_args.args[0] == final and not any(m.called for m in models[1:])
    else:
        assert all(m.call_args.args[0] == final for m in models[1:] if m.called)
    if stage in {"local", "fact"}:
        assert outcome["rejected_candidate"]["text"] == final
        assert outcome["rejected_candidate"]["text_sha256"] == text_hash(final)
    assert outcome["kill_stage"] == {"local": "fact_check", "fact": "fact_check"}.get(stage, stage)
