"""Invented lexical controls; provider envelopes are not factual evaluations."""

from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import Mock

import pytest

from src.editorial.policy import current_editorial_policy
from src.two_bot import check_requests, fact_check
from src.two_bot.strict_contract import material_span_failures
from src.two_bot.types import ExtractedClaim, WriterResult
from tests.test_check_executor import envelope
from tests.two_bot.conftest import _bundle
from tests.two_bot.test_candidate_derivation import packet


def inventory(*spans):
    return [ExtractedClaim(text, "named_entity") for text in spans]


@pytest.mark.parametrize("place,opener,space", [
    ("Luma", "No rain fell", " "),
    ("Rio", "It stayed dry", " "),
    ("Mali", "The measurement is provisional", "\t"),
    ("New Luma", "This needs verification", " "),
    ("São Tomé", "No rain fell", " "),
    ("No River", "No rain fell", " "),
    ("St. Luma", "No rain fell", " "),
])
def test_complete_place_inventory_survives_a_sentence_boundary(place, opener, space):
    text = f"312 MW near {place}.{space}{opener}."
    claims = inventory("312 MW", place)
    original = deepcopy(claims)
    assert material_span_failures(text, claims) == []
    assert claims == original
    failures = material_span_failures(text, claims[:1])
    assert failures == [f"incomplete_claim_extraction: uncovered material span {place!r}"]


@pytest.mark.parametrize("name", ["Dr. No", "St. No", "Mt. No", "Ft. No", "Prof. No", "Cmdr. No",
                                  "Dept. No", "Sept. No", "J. No", "U.S. No", "St.Luma. No"])
def test_initials_abbreviations_and_dotted_names_need_complete_coverage(name):
    text = f"312 MW near {name} measured today."
    assert material_span_failures(text, inventory("312 MW", name)) == []
    assert material_span_failures(text, inventory("312 MW", name.removesuffix(" No")))


@pytest.mark.parametrize("text", [
    "312 MW near Luma... No rain fell.",
    "312 MW near Old-Luma. No rain fell.",
    "312 MW near LumaVille. No rain fell.",
    "312 MW near LUMA. No rain fell.",
    "312 MW near Luma. No River rose.",
    "312 MW near Luma. No 42 was recorded.",
    "312 MW near Luma. No",
    "312 MW near Luma. NO rain fell.",
    "312 MW near Luma.\nNo rain fell.",
    "312 MW near Luma.\rNo rain fell.",
    "312 MW near Luma. No rain fell.\n",
    '312 MW near "Luma. No rain fell."',
    "312 MW near ‘Luma. No rain fell.’",
    "312 MW near «Luma. No rain fell.»",
    "312 MW near Luma. No station's report arrived.",
])
def test_ambiguous_forms_do_not_gain_a_sentence_opener_exception(text):
    place = next((name for name in ["Old-Luma", "LumaVille", "LUMA"] if name in text), "Luma")
    claims = inventory("312 MW", place, "42") if "42" in text else inventory("312 MW", place)
    assert any("uncovered material span" in failure for failure in material_span_failures(text, claims))


def test_every_entity_across_multiple_sentences_still_needs_its_full_inventory():
    text = "312 MW near No River. It reached 29 MW near New Luma. No rain fell in Nera."
    claims = inventory("312 MW", "No River", "29 MW", "New Luma", "Nera")
    assert material_span_failures(text, claims) == []
    for index, claim in enumerate(claims):
        failures = material_span_failures(text, claims[:index] + claims[index + 1:])
        assert any(claim.text.split()[0] in failure for failure in failures)
    assert material_span_failures(text, inventory("312 MW", "River", "29 MW", "Luma", "Nera"))


def test_numbers_dates_and_exact_original_substrings_remain_required():
    text = "312.5 MW near Luma. No rain fell on 2026-01-01."
    complete = inventory("312.5 MW", "Luma", "2026-01-01")
    assert material_span_failures(text, complete) == []
    assert material_span_failures(text, inventory("312", "Luma", "2026-01-01"))
    assert material_span_failures(text, inventory("312.5 MW", "Luma", "2026"))
    bad_date = text.replace("2026-01-01", "2026-02-30")
    assert "invalid_claim_date: 2026-02-30" in material_span_failures(
        bad_date, inventory("312.5 MW", "Luma", "2026-02-30"))
    assert any("invalid_claim_span" in failure for failure in material_span_failures(
        text, complete + inventory("Nera")))
    # Coverage of a literal whole sentence keeps its punctuation. It remains
    # the required checker's job to verify its meaning and source support.
    assert material_span_failures(text, [ExtractedClaim(text, "comparison")]) == []
    assert material_span_failures(text, [ExtractedClaim("No rain fell", "comparison")])
    assert material_span_failures(text, [])


def test_source_caption_labels_do_not_become_general_sentence_openers():
    text = "312 MW near Luma. Data supports the measurement."
    failures = material_span_failures(text, inventory("312 MW", "Luma"))
    assert any("Data" in failure for failure in failures)


@pytest.mark.parametrize("outcome", ["pass", "missing_place", "missing_number", "empty", "model_reject"])
def test_sync_and_retained_results_keep_exact_inventory_and_model_verdict(monkeypatch, outcome):
    text = "A satellite measured 312 MW near Luma. It measured 29 MW near Nera."
    source = _bundle(region="Luma", frp=312)
    claims = inventory("312 MW", "Luma", "29 MW", "Nera")
    if outcome == "missing_place":
        claims.pop()
    elif outcome == "missing_number":
        claims.pop(2)
    elif outcome == "empty":
        claims = []
    failures = ["Invented checker rejects the source assertion."] if outcome == "model_reject" else []
    raw = json.dumps(dict(passed=not failures, extracted_claims=[asdict(c) for c in claims], failures=failures))
    provider = Mock(return_value=raw)
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    before_source = deepcopy(source.to_dict())
    sync = fact_check.fact_check(text, [], source, {})
    saved = packet(dict(candidate=asdict(WriterResult(
        tweet=text, kill_reason=None, angle_chosen="synthetic", era_anchor_used=None,
        peer_comparison_used=None, reasoning="Invented inventory control.")),
        candidate_id="f" * 64, bundle=source.to_dict(), policy=current_editorial_policy()))
    before_saved = deepcopy(saved)
    retained = check_requests.interpret_observation(saved, "fact_check",
        {"complete": True, "http_status": 200}, envelope(raw))
    assert retained["execution_status"] == "completed"
    assert retained["verdict"] == ("pass" if outcome == "pass" else "reject")
    assert retained["result"] == sync.to_dict()
    assert sync.passed == (outcome == "pass")
    if failures:
        assert sync.failures == failures
    provider.assert_called_once_with(text, source, retry_suffix="")
    assert source.to_dict() == before_source and saved == before_saved
