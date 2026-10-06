"""Invented parser controls, not qualified weather reports or model evaluations."""

from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import MagicMock

import pytest

from src.editorial.policy import current_editorial_policy
from src.two_bot import check_requests, fact_check
from src.two_bot.strict_contract import material_span_failures
from src.two_bot.types import ExtractedClaim, StoryBundle, WriterResult
from tests.test_check_executor import envelope
from tests.two_bot.test_candidate_derivation import packet


SOURCE = "WeatherGrid model"
TEXT = "A model estimates an index in Luma of 42. Data: WeatherGrid model (12 km)."


@pytest.fixture
def bundle():
    return StoryBundle(
        signal_kind="air_quality_hazard", where="Luma", when="2026-01-01",
        event_id="invented-caption-fixture", headline_metric={"label": "index", "value": 42},
        current_facts=[{"label": "data_source", "value": SOURCE + " via GridRelay"}],
        historical_context={}, raw_signal_dump={},
    )


def claims(source=SOURCE):
    return [ExtractedClaim("42", "number"), ExtractedClaim("Luma", "named_entity"),
            ExtractedClaim(source, "named_entity"), ExtractedClaim("12 km", "number")]


def response(inventory=None, *, failures=()):
    inventory = claims() if inventory is None else inventory
    return json.dumps(dict(passed=not failures, failures=list(failures),
                           extracted_claims=[asdict(c) for c in inventory]))


@pytest.mark.parametrize("label,boundary", [("Data", ". "), ("Source", "; "), ("Data", ".\t")])
def test_known_source_caption_label_is_not_a_separate_entity(bundle, label, boundary):
    tweet = TEXT.replace(". Data:", boundary + label + ":")
    before = deepcopy(bundle.to_dict())
    inventory = claims()
    assert material_span_failures(tweet, inventory, bundle=bundle) == []
    assert material_span_failures(tweet, inventory) == [
        f"incomplete_claim_extraction: uncovered material span '{label}'"]
    assert bundle.to_dict() == before and inventory == claims()


@pytest.mark.parametrize("path", ["facts", "raw", "evidence", "source", "provenance"])
@pytest.mark.parametrize("name", [SOURCE, SOURCE + " via GridRelay"])
def test_only_literal_primary_source_locations_supply_identity(bundle, path, name):
    bundle.current_facts = []
    if path == "facts":
        bundle.current_facts = [{"label": "source_name", "value": name}]
    elif path == "raw":
        bundle.raw_signal_dump = {"source_product": name}
    else:
        bundle.raw_signal_dump = {path: {"data_source": name}}
    assert material_span_failures(TEXT, claims(), bundle=bundle) == []


def test_full_provider_identity_is_still_inventoried(bundle):
    name = SOURCE + " via GridRelay"
    tweet = TEXT.replace(SOURCE, name)
    assert material_span_failures(tweet, claims(name), bundle=bundle) == []
    assert any("GridRelay" in f for f in material_span_failures(tweet, claims(), bundle=bundle))


@pytest.mark.parametrize("source", [None, {}, [SOURCE], "", SOURCE + "Other", SOURCE + " Plus",
                                    "Other " + SOURCE, SOURCE.lower(), SOURCE + " via "])
def test_missing_changed_or_ambiguous_source_identity_keeps_label_strict(bundle, source):
    bundle.current_facts[0]["value"] = source
    assert material_span_failures(TEXT, claims(), bundle=bundle) == [
        "incomplete_claim_extraction: uncovered material span 'Data'"]


@pytest.mark.parametrize("path", ["historical", "related", "description", "url", "nested"])
def test_unrelated_text_or_url_is_not_source_name_authority(bundle, path):
    bundle.current_facts = []
    if path == "historical":
        bundle.historical_context = {"data_source": SOURCE}
    elif path == "related":
        bundle.raw_signal_dump = {"related_news": [{"source_name": SOURCE}]}
    elif path == "nested":
        bundle.raw_signal_dump = {"evidence": {"nested": {"source_name": SOURCE}}}
    elif path == "url":
        bundle.raw_signal_dump = {"source_url": "https://example.invalid/WeatherGrid"}
    else:
        bundle.raw_signal_dump = {"description": SOURCE}
    assert any("'Data'" in f for f in material_span_failures(TEXT, claims(), bundle=bundle))


@pytest.mark.parametrize("tweet", [
    "Data: WeatherGrid model (12 km), with 42 in Luma.",
    "A model estimates 42 in Luma, Data: WeatherGrid model (12 km).",
    TEXT.replace(". Data:", ".\nData:"),
    TEXT.replace("Data: ", "Data:\n"),
    TEXT.replace("Data: ", "Data "),
    TEXT.replace("model (12", "model\n(12"),
    TEXT + " Data: WeatherGrid model.",
    TEXT + " Another claim follows.",
    '"' + TEXT + '"',
    "'" + TEXT + "'",
    "“" + TEXT + "”",
    "‘" + TEXT + "’",
    "«" + TEXT + "»",
    TEXT.replace("A model", "A city's model"),
])
def test_noncaption_or_quoted_syntax_does_not_gain_an_exception(bundle, tweet):
    failures = material_span_failures(tweet, claims(), bundle=bundle)
    assert failures == material_span_failures(tweet, claims())
    assert any("incomplete_claim_extraction" in f and "Data" in f for f in failures)


@pytest.mark.parametrize("field", ["where", "source"])
def test_label_inside_a_place_or_source_name_is_ambiguous(bundle, field):
    if field == "where":
        bundle.where = "Mount Data"
    else:
        bundle.current_facts[0]["value"] = SOURCE + " via Data Service"
    assert any("'Data'" in f for f in material_span_failures(TEXT, claims(), bundle=bundle))


@pytest.mark.parametrize("kind", ["number", "comparison", "date"])
def test_source_claim_requires_the_named_entity_kind(bundle, kind):
    inventory = claims()
    inventory[2] = ExtractedClaim(SOURCE, kind)
    assert material_span_failures(TEXT, inventory, bundle=bundle) == [
        "incomplete_claim_extraction: uncovered material span 'Data'"]


@pytest.mark.parametrize("omitted", [0, 1, 2, 3])
def test_label_exception_never_covers_other_material(bundle, omitted):
    inventory = claims()
    missing = inventory.pop(omitted)
    failures = material_span_failures(TEXT, inventory, bundle=bundle)
    assert failures
    assert any(missing.text.split()[0] in f for f in failures)


def test_empty_nonliteral_and_malformed_date_inventory_still_fail(bundle):
    assert any("nonempty claim inventory" in f for f in material_span_failures(TEXT, [], bundle=bundle))
    assert any("invalid_claim_span" in f for f in material_span_failures(
        TEXT, claims() + [ExtractedClaim("not in tweet", "comparison")], bundle=bundle))
    tweet = TEXT.replace("in Luma", "in Luma on 2026-02-30")
    assert any("invalid_claim_date" in f for f in material_span_failures(
        tweet, claims() + [ExtractedClaim("2026-02-30", "date")], bundle=bundle))
    assert any("2026" in f for f in material_span_failures(tweet, claims(), bundle=bundle))


def test_only_the_caption_label_is_exempted_at_its_exact_position(bundle):
    tweet = TEXT.replace("A model", "Data")
    assert material_span_failures(tweet, claims(), bundle=bundle) == [
        "incomplete_claim_extraction: uncovered material span 'Data'"]
    assert material_span_failures(tweet, claims() + [ExtractedClaim("Data", "named_entity")], bundle=bundle) == []


def test_caption_after_an_entity_does_not_mask_that_entity(bundle):
    tweet = "A model estimates 42 in Luma. Data: WeatherGrid model (12 km)."
    assert material_span_failures(tweet, claims(), bundle=bundle) == []
    assert material_span_failures(tweet, claims()[::2] + [claims()[3]], bundle=bundle) == [
        "incomplete_claim_extraction: uncovered material span 'Luma'"]


@pytest.mark.parametrize("suffix", ["x", "-other", "_other"])
def test_source_prefix_inside_a_different_name_does_not_exempt_label(bundle, suffix):
    tweet = TEXT.replace(SOURCE, SOURCE + suffix)
    failures = material_span_failures(tweet, claims(), bundle=bundle)
    assert failures == material_span_failures(tweet, claims())
    assert any("'Data'" in f for f in failures)


def test_a_url_in_a_name_field_does_not_become_a_named_source(bundle):
    url = "https://example.invalid/report"
    bundle.current_facts[0]["value"] = url
    tweet = TEXT.replace(SOURCE, url)
    assert material_span_failures(tweet, claims(url), bundle=bundle) == [
        "incomplete_claim_extraction: uncovered material span 'Data'"]


@pytest.mark.parametrize("where", [None, "", " "])
def test_missing_place_context_keeps_the_label_strict(bundle, where):
    bundle.where = where
    assert material_span_failures(TEXT, claims(), bundle=bundle) == [
        "incomplete_claim_extraction: uncovered material span 'Data'"]


@pytest.mark.parametrize("failures", [(), ("Invented provider rejection: source does not support the assertion.",)])
def test_sync_and_retained_routes_use_same_bundle_without_extra_calls_or_mutations(bundle, monkeypatch, failures):
    raw = response(failures=failures)
    provider = MagicMock(return_value=raw)
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    original = deepcopy(bundle.to_dict())
    assert fact_check.local_rejection(TEXT, [], bundle, {}) is None  # Still requires a model.
    sync = fact_check.fact_check(TEXT, [], bundle, {})
    provider.assert_called_once_with(TEXT, bundle, retry_suffix="")
    inputs = dict(candidate=asdict(WriterResult(
        tweet=TEXT, kill_reason=None, angle_chosen="synthetic", era_anchor_used=None,
        peer_comparison_used=None, reasoning="Invented parser control.")),
        candidate_id="c" * 64, bundle=bundle.to_dict(), policy=current_editorial_policy())
    saved = packet(inputs)
    before = deepcopy(saved)
    result = check_requests.interpret_observation(saved, "fact_check",
        {"complete": True, "http_status": 200}, envelope(raw))
    assert result["execution_status"] == "completed"
    assert result["verdict"] == ("reject" if failures else "pass")
    assert result["result"] == sync.to_dict()
    assert sync.passed == (not failures)
    assert sync.failures == list(failures)
    assert bundle.to_dict() == original and saved == before
    assert provider.call_count == 1
    assert not fact_check.interpret_response(TEXT, raw, {}).passed  # Context-free stays strict.


def test_changed_retained_bundle_never_inherits_a_check(bundle):
    saved = packet(dict(candidate=asdict(WriterResult(
        tweet=TEXT, kill_reason=None, angle_chosen="synthetic", era_anchor_used=None,
        peer_comparison_used=None, reasoning="Invented parser control.")),
        candidate_id="c" * 64, bundle=bundle.to_dict(), policy=current_editorial_policy()))
    saved["bundle"]["current_facts"][0]["value"] = "Different source"
    result = check_requests.interpret_observation(saved, "fact_check",
        {"complete": True, "http_status": 200}, envelope(response()))
    assert result["execution_status"] == "error" and result["verdict"] is None
