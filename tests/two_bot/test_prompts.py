"""Prompt contracts and mocked request wiring, not a model-quality benchmark.

Scientific rejection behavior lives in the P05/P06 executable boundary tests.
These checks prevent interface drift, silent prompt expansion and reintroduction
of the audited contradictory instructions without pretending text tests prove
that a model follows its policy.
"""
from __future__ import annotations

import json
from pathlib import Path
from string import Formatter
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.two_bot.prompts.critic_prompt import (
    CRITIC_EVIDENCE_RULES, CRITIC_SLATE_USER_PROMPT_TEMPLATE, CRITIC_SYSTEM_PROMPT, CRITIC_USER_PROMPT_TEMPLATE,
)
from src.two_bot.prompts.fact_check_prompt import FACT_CHECK_SYSTEM_PROMPT, FACT_CHECK_USER_PROMPT_TEMPLATE
from src.two_bot.prompts.writer_prompt import (
    EVIDENCE_RULES, IMPACT_GUIDANCE, MULTISIGNAL_GUIDANCE, WRITER_SYSTEM_PROMPT, WRITER_USER_PROMPT_TEMPLATE,
)

SYSTEMS = (WRITER_SYSTEM_PROMPT, FACT_CHECK_SYSTEM_PROMPT, CRITIC_SYSTEM_PROMPT)


@pytest.mark.parametrize("prompt,limit", [
    (WRITER_SYSTEM_PROMPT, 10500), (FACT_CHECK_SYSTEM_PROMPT, 10000), (CRITIC_SYSTEM_PROMPT, 6500),
])
def test_common_prompt_size_has_an_explicit_review_budget(prompt, limit):
    # Character budget guards input growth; it is not an API-token or cost claim.
    assert len(prompt) <= limit
    assert len(prompt.split()) < 1500


@pytest.mark.parametrize("prompt,rules", [
    (WRITER_SYSTEM_PROMPT, EVIDENCE_RULES), (FACT_CHECK_SYSTEM_PROMPT, EVIDENCE_RULES),
    (CRITIC_SYSTEM_PROMPT, CRITIC_EVIDENCE_RULES),
])
def test_roles_include_their_current_evidence_policy_once(prompt, rules):
    assert prompt.count(rules) == 1


@pytest.mark.parametrize("template,fields", [
    (WRITER_USER_PROMPT_TEMPLATE, {"bundle_json", "memory_json"}),
    (FACT_CHECK_USER_PROMPT_TEMPLATE, {"tweet", "bundle_json"}),
    (CRITIC_USER_PROMPT_TEMPLATE, {"draft_text", "bundle_json", "pending_count", "pending_drafts_block", "shipped_count", "shipped_tweets_block", "revision_mode"}),
    (CRITIC_SLATE_USER_PROMPT_TEMPLATE, {"candidate_count", "candidate_drafts_block", "bundle_json", "pending_count", "pending_drafts_block", "shipped_count", "shipped_tweets_block"}),
])
def test_runtime_template_fields_are_preserved_and_values_are_not_reformatted(template, fields):
    actual = {name for _, name, _, _ in Formatter().parse(template) if name}
    assert actual == fields
    values = {field: f"<{field}>{{literal_braces}}" for field in fields}
    formatted = template.format(**values)
    for value in values.values():
        assert formatted.count(value) == 1


def test_optional_riders_remain_separate_from_cached_common_system():
    assert MULTISIGNAL_GUIDANCE not in WRITER_SYSTEM_PROMPT
    assert IMPACT_GUIDANCE not in WRITER_SYSTEM_PROMPT


@pytest.mark.parametrize("retired", [
    "Every tweet has three beats", "Aim 240–270", "No hedging.",
    "When in doubt, ACCEPT", "Drafts are reviewed by a human",
    "Not engagement, not follower growth", "every used move is permanently spent",
    "the writer will likely draft again tomorrow", "The system clause is the SHIFT",
    "within the band where wildfires routinely outpace suppression",
])
def test_audited_contradictory_instruction_does_not_return(retired):
    assert all(retired not in prompt for prompt in SYSTEMS)


def test_no_old_failed_post_is_promoted_as_an_approved_exemplar():
    combined = "\n".join(SYSTEMS)
    assert "APPROVED EXEMPLARS" not in combined
    for fragment in ("Mali's Western Sahel", "the Kanawha Valley", "this dose says that buffer failed", "Heat records used to arrive one city at a time"):
        assert fragment not in combined


@pytest.mark.parametrize("case_id,rule_markers", [
    ("alert_threshold_is_not_a_rain_record", ("alert_threshold_mm", "not historical records")),
    ("forecast_is_not_an_observed_record", ("Forecasts retain forecast", "mixed members")),
    ("humidity_requires_moisture_evidence", ("moisture inputs/method", "temperature alone")),
    ("forecast_landfall_is_not_completed_landfall", ("Completed landfall requires dated confirmation", "negation")),
    ("thermal_detection_is_not_verified_wildfire", ("incident warrant", "Volcanic/static-source uncertainty")),
    ("material_precipitation_product_disagreement", ("compatible footprint/window", "conflicting sources")),
    ("record_progression_and_later_quality_revision", ("completeness, scope, cutoff and quality", "exact verified cutoff")),
    ("editorial_region_must_not_override_country", ("geographic support",)),
])
def test_frozen_historical_case_keeps_a_corresponding_policy_and_evidence_limit(case_id, rule_markers):
    cases = json.loads((Path(__file__).parents[1] / "fixtures/historical_scientific_cases.json").read_text())["cases"]
    case = next(case for case in cases if case["case_id"] == case_id)
    assert case["evidence_limit"]
    for marker in rule_markers:
        assert marker in EVIDENCE_RULES
    # This maps requirements; the P05/P06 tests execute the actual gates.


def test_output_field_contracts_match_parsers_with_nullable_rejection_metadata():
    from src.two_bot import critic, fact_check, writer
    from src.two_bot.json_utils import loads_model_json

    writer_shape = loads_model_json(WRITER_SYSTEM_PROMPT.split("OUTPUT\n", 1)[1])
    assert set(writer_shape) == {"tweet", "kill_reason", "angle_chosen", "era_anchor_used", "peer_comparison_used", "reasoning", "cited_impact", "kill_scope", "kill_code"}
    assert writer_shape["kill_scope"] is None and writer_shape["kill_code"] is None
    tweet = "A thermal anomaly near Example Bay, Guinea: 300 MW on September 9."
    payload = dict(writer_shape, tweet=tweet, kill_reason=None, angle_chosen="plain_number", era_anchor_used=None, peer_comparison_used=None, reasoning="A supported measurement.", cited_impact=None)
    assert writer._parse_writer_json(json.dumps(payload)).tweet == tweet

    checked = {"passed": True, "extracted_claims": [{"text": tweet, "kind": "comparison"}], "failures": []}
    passed, failures, claims = fact_check._parse_fact_check_json(json.dumps(checked), require_extracted_claims=True)
    assert passed and not failures and claims[0].text == tweet
    verdict = loads_model_json(CRITIC_SYSTEM_PROMPT.split("Return only one JSON object", 1)[1])
    assert critic._parse_critic_result(json.dumps(verdict)).passed
    assert len(tweet) < 100  # A short complete response is not rejected for a missing second sentence.


@pytest.mark.parametrize("role", ["writer", "fact_check", "critic"])
def test_existing_gemini_request_contains_exact_compact_policy_once_and_makes_one_call(role, monkeypatch):
    from google import genai
    from src.two_bot import critic, fact_check, writer
    from src.two_bot.types import StoryBundle

    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(text="{}", usage_metadata=None)
    monkeypatch.setattr(genai, "Client", lambda **kwargs: client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    module = {"writer": writer, "fact_check": fact_check, "critic": critic}[role]
    monkeypatch.setattr(module, "call_with_retries", lambda _, call: call())
    bundle = StoryBundle(
        signal_kind="fire", where="Example Bay, Guinea", when="2026-09-09",
        event_id="synthetic-prompt-case", headline_metric={"label": "FRP", "value": 300, "unit": "MW"},
        current_facts=[{"label": "source_product", "value": "synthetic-fixture"}],
        raw_signal_dump={"source_product": "synthetic-fixture"},
    )
    if role == "writer":
        writer._call_google("Synthetic request")
    elif role == "fact_check":
        fact_check._call_gemini("Synthetic request", bundle)
    else:
        critic._call_gemini("Synthetic request", bundle, [], [])
    client.models.generate_content.assert_called_once()
    contents = client.models.generate_content.call_args.kwargs["contents"]
    assert contents.count(CRITIC_EVIDENCE_RULES if role == "critic" else EVIDENCE_RULES) == 1
    assert contents.startswith({"writer": WRITER_SYSTEM_PROMPT, "fact_check": FACT_CHECK_SYSTEM_PROMPT, "critic": CRITIC_SYSTEM_PROMPT}[role])
    assert "Synthetic request" in contents
