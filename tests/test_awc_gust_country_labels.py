"""Invented country labels through real source/check/save consumers.

Explicit offline model/HTTP doubles do not prove model quality or X delivery.
"""
from copy import deepcopy
import gzip
import json
from unittest.mock import Mock

from freezegun import freeze_time
import pytest

from src.data import awc_gust as gust
from src.two_bot import fact_check, pipeline
from tests import test_awc_gust as t
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_awc_gust import world as world

REAL_FACT_CHECK = fact_check.fact_check


def stations(code):
    values = t.catalog()
    values[0]["country"] = code
    return values


def bundle(code="US"):
    capture = (gzip.compress(json.dumps(stations(code)).encode(), mtime=0),
               gzip.compress(t.csv_bytes(t.rows(), header=t.GUST_HEADER), mtime=0))
    return gust.build_bundle(gust.nominate(now=t.NOW, capture=capture)[0], now=t.NOW)


def copy(label="North Test airport, US:"):
    return label + " a 120 km/h (75 mph) gust at 12:00 UTC, 15 Nov."


def cited(body, source):
    return body + "\n" + source.raw_signal_dump["evidence"]["source_url"]


@pytest.mark.parametrize("code", ["US", "NO", "IN", "GB"])
@pytest.mark.parametrize("separator", [":", ","])
def test_validated_country_code_is_an_explicit_label_for_the_same_airport(code, separator):
    source = bundle(code)
    text = cited(copy(f"North Test airport, {code}{separator}"), source)
    with freeze_time(t.NOW):
        assert fact_check.local_rejection(text, [], source, {}) is None


def test_airport_capitalization_does_not_change_its_bound_country_label():
    source = bundle()
    assert gust.claim_failures(cited(copy("north test AIRPORT, US:"), source), source, now=t.NOW) == []


@pytest.mark.parametrize("code", ["US", "NO", "IN", "GB"])
def test_canonical_full_country_name_stays_accepted(code):
    source = bundle(code)
    country = source.raw_signal_dump["evidence"]["points"][0]["country"]
    assert gust.claim_failures(cited(copy(f"North Test airport, {country}:"), source), source, now=t.NOW) == []


@pytest.mark.parametrize("label", [
    "North Test airport:", "North Test airport, us:", "North Test airport, CA:",
    "North Test airport, USA:", "North Test airport, USness:", "North Test airport, RUS:",
    "North Test airport, US-based:", "North Test airport, USreported",
    "North Test airport, somewhere: US reports", "US: North Test airport:",
    "North Test airport near us:", "North Test, US:",
    "Other airport, US: North Test",
])
def test_country_code_cannot_be_an_unrelated_token_substring_or_foreign_label(label):
    source = bundle()
    assert gust.claim_failures(cited(copy(label), source), source, now=t.NOW) == ["awc_gust_scope_missing"]


def test_country_mapping_mismatch_stays_invalid_even_with_a_valid_looking_label():
    source = bundle()
    source.raw_signal_dump["evidence"]["points"][0]["country"] = "Norway"
    assert gust.claim_failures(cited(copy(), source), source, now=t.NOW) == ["awc_gust_text_source_invalid"]


@pytest.mark.parametrize("change,expected", [
    ("time", "awc_time_label_missing"), ("amount", "awc_gust_quantity_missing"),
    ("forecast", "awc_gust_unsupported_upgrade"), ("citation", "awc_exact_target_citation_required"),
])
def test_country_label_does_not_replace_other_required_copy_rules(change, expected):
    source = bundle()
    text = cited(copy(), source)
    if change == "time":
        text = text.replace("12:00", "13:00", 1)
    elif change == "amount":
        text = text.replace("120 km/h (75 mph)", "999 km/h")
    elif change == "forecast":
        text += " More is expected."
    else:
        text = copy() + "\nhttps://example.invalid"
    assert gust.claim_failures(text, source, now=t.NOW) == [expected]


@pytest.mark.parametrize("unavailable", [False, True])
def test_accepted_local_label_still_requires_the_actual_factual_checker(monkeypatch, unavailable):
    source = bundle()
    text = cited(copy(), source)
    model = Mock(side_effect=RuntimeError("Invented checker unavailable")) if unavailable else Mock(
        return_value=json.dumps({"passed": False, "extracted_claims": [],
                                 "failures": ["Explicit invented factual refusal"]}))
    monkeypatch.setattr(fact_check, "_call_gemini", model)
    with freeze_time(t.NOW):
        if unavailable:
            with pytest.raises(RuntimeError, match="Invented checker unavailable"):
                REAL_FACT_CHECK(text, [], source, {})
        else:
            result = REAL_FACT_CHECK(text, [], source, {})
            assert not result.passed and "Explicit invented factual refusal" in result.failures
    model.assert_called_once()


@pytest.mark.parametrize("outcome", ["complete-offline-checks", "factual-refusal", "factual-unavailable"])
def test_country_label_through_actual_collector_checks_and_save(world, monkeypatch, outcome):
    values = stations("US")
    monkeypatch.setattr(t, "catalog", lambda: deepcopy(values))
    called = world[3]
    stages = stage_fakes(called, copy=copy())
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(t.safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    if outcome == "complete-offline-checks":
        monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    else:
        def answer(*args, **kwargs):
            called.append("fact_check")
            if outcome == "factual-unavailable":
                raise RuntimeError("Invented checker unavailable")
            return json.dumps({"passed": False, "extracted_claims": [],
                               "failures": ["Explicit invented factual refusal"]})
        monkeypatch.setattr(pipeline.fact_check, "fact_check", REAL_FACT_CHECK)
        monkeypatch.setattr(fact_check, "_call_gemini", answer)
    t.generate(world)
    assert called == (["writer", "safety", "fact_check", "critic"]
                      if outcome == "complete-offline-checks" else ["writer", "safety", "fact_check"])
    assert len(world[1]["drafts"]) == (1 if outcome == "complete-offline-checks" else 0)
    assert world[0].x_posts == []  # Saving never invokes the platform sender.
