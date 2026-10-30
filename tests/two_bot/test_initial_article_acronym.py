"""Invented lexical controls; offline checker envelopes never establish truth."""
from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import Mock

import pytest

from src.two_bot import fact_check
from src.two_bot.strict_contract import material_span_failures
from src.two_bot.types import ExtractedClaim
from tests.live_content_harness import trap_network
from tests.two_bot.conftest import _bundle


def inventory(*spans):
    return [ExtractedClaim(text, "named_entity") for text in spans]


def envelope(claims, failures=()):
    return json.dumps({"passed": not failures, "failures": list(failures),
                       "extracted_claims": [asdict(claim) for claim in claims]})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    trap_network(monkeypatch.setattr)


@pytest.fixture(params=("coverage", "interpret", "sync"))
def check(request, monkeypatch):
    def run(text, claims):
        before = deepcopy(claims)
        if request.param == "coverage":
            failures = material_span_failures(text, claims)
        else:
            raw = envelope(claims)
            if request.param == "interpret":
                result = fact_check.interpret_response(text, raw, {})
            else:
                source = _bundle()
                before_source = deepcopy(source.to_dict())
                provider = Mock(return_value=raw)
                monkeypatch.setattr(fact_check, "_call_gemini", provider)
                result = fact_check.fact_check(text, [], source, {})
                provider.assert_called_once_with(text, source, retry_suffix="")
                assert source.to_dict() == before_source
            assert result.raw_response == raw and result.passed == (not result.failures)
            failures = result.failures
        assert claims == before
        return failures
    return run


@pytest.mark.parametrize(("prefix", "acronym"), [
    ("A GRID forecast", "GRID"), ("An GRID forecast", "GRID"),
    ("A\tGRID\tforecast", "GRID"), ("An \tGRID\t forecast", "GRID"),
    ("A AB forecast", "AB"), ("A ABCDEFGHIJ forecast", "ABCDEFGHIJ"),
])
def test_only_initial_article_is_nonmaterial(check, prefix, acronym):
    assert check(prefix + " remains provisional.", inventory(acronym)) == []


@pytest.mark.parametrize(("text", "spans"), [
    ("The GRID forecast remains provisional.", ("GRID",)),
    ("The Gambia forecast remains provisional.", ("Gambia",)),
    ("A Coruña forecast remains provisional.", ("Coruña",)),
    ("A Grid forecast remains provisional.", ("Grid",)),
    ("A G.R.I.D. forecast remains provisional.", ("G.R.I.D.",)),
    ("A. GRID forecast remains provisional.", ("A.", "GRID")),
    ("A G forecast remains provisional.", ("G",)),
    ("A ABCDEFGHIJK forecast remains provisional.", ("ABCDEFGHIJK",)),
    ("A GRID RIVER forecast remains provisional.", ("GRID RIVER",)),
    ("A GRID FORECAST remains provisional.", ("GRID FORECAST",)),
    ("A GRID fOrecast remains provisional.", ("GRID",)),
    ("A GRID forecast2 remains provisional.", ("GRID",)),
    ("A GRÍD forecast remains provisional.", ("GRÍD",)),
    ("A\u00a0GRID forecast remains provisional.", ("GRID",)),
    ("A GRID\u00a0forecast remains provisional.", ("GRID",)),
    (" A GRID forecast remains provisional.", ("GRID",)),
    ("A GRID\nforecast remains provisional.", ("GRID",)),
    ("A\nGRID forecast remains provisional.", ("GRID",)),
    ('"A GRID forecast remains provisional."', ("GRID",)),
    ("‘A GRID forecast remains provisional.’", ("GRID",)),
    ("Intro. A GRID forecast remains provisional.", ("Intro.", "GRID")),
    ("No River forecast remains provisional.", ("River",)),
])
def test_ambiguous_names_quotes_and_noninitial_forms_remain_conservative(check, text, spans):
    assert any("uncovered material span" in failure for failure in check(text, inventory(*spans)))


@pytest.mark.parametrize(("text", "claims", "uncovered"), [
    ("A GRID forecast remains provisional.", inventory("GR"), "GRID"),
    ("A GRID forecast names Luma and Nera.", inventory("GRID", "Luma"), "Nera"),
    ("A GRID forecast names New Luma.", inventory("GRID", "Luma"), "New Luma"),
    ("A GRID forecast names GRID RIVER.", inventory("GRID"), "GRID RIVER"),
])
def test_full_acronym_and_every_remaining_entity_stay_material(check, text, claims, uncovered):
    assert any(f"uncovered material span {uncovered!r}" in failure for failure in check(text, claims))


def test_numbers_dates_and_exact_substrings_remain_material():
    text = "A GRID forecast gives 42 units on 2026-01-01 near Luma."
    complete = inventory("GRID", "42", "2026-01-01", "Luma")
    assert material_span_failures(text, complete) == []
    assert fact_check.interpret_response(text, envelope(complete), {}).passed
    for index in range(len(complete)):
        partial = complete[:index] + complete[index + 1:]
        assert any("uncovered material span" in reason for reason in material_span_failures(text, partial))
        assert not fact_check.interpret_response(text, envelope(partial), {}).passed
    wrong = inventory("grid", "42", "2026-01-01", "Luma")
    assert any("invalid_claim_span" in reason for reason in material_span_failures(text, wrong))
    impossible = text.replace("2026-01-01", "2026-02-30")
    assert "invalid_claim_date: 2026-02-30" in material_span_failures(
        impossible, inventory("GRID", "42", "2026-02-30", "Luma"))
    assert material_span_failures(text, [])


@pytest.mark.parametrize("consumer", ("interpret", "sync"))
def test_raw_model_rejection_remains_authoritative(monkeypatch, consumer):
    text = "A GRID forecast remains provisional."
    refusal = "Invented factual refusal remains authoritative."
    raw = envelope(inventory("GRID"), (refusal,))
    if consumer == "interpret":
        result = fact_check.interpret_response(text, raw, {})
    else:
        source = _bundle()
        provider = Mock(return_value=raw)
        monkeypatch.setattr(fact_check, "_call_gemini", provider)
        result = fact_check.fact_check(text, [], source, {})
        provider.assert_called_once_with(text, source, retry_suffix="")
    assert not result.passed and result.failures == [refusal] and result.raw_response == raw
