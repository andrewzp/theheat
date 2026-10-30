"""Final closure B2: deterministic copy gates for Andrew's editorial direction.

Every text is invented; no historical, held (including the two Riyadh drafts) or
posted copy is used. Writer responses are explicit offline JSON fixtures parsed by
the real writer parser; no provider, network, Gist or X access. A clean copy result
is never treated as a factual, safety or editorial pass.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.editorial.policy import current_editorial_policy, source_manifest
from src.evaluation.production_match import CHECK_STAGES
from src.two_bot import check_requests, copy_gates, fact_check, pipeline, writer
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from src.writer_health import STAGES as WRITER_HEALTH_STAGES
from tests.two_bot.conftest import _bundle, _state_with_memory, configured_pipeline_providers  # noqa: F401
from tests.two_bot.test_candidate_derivation import packet

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests/fixtures/copy_gate_vectors.json").read_text())["vectors"]
STERILE = "A satellite detection model shows Mali thermal power at 361 MW."
CLEAN = "Mali thermal power is 361 MW."


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["id"])
def test_shared_vectors_match_python_codes(vector):
    assert [note.code for note in copy_gates.copy_notes(vector["text"])] == vector["codes"]


def test_blocking_and_advisory_codes_are_disjoint_and_explained():
    assert not set(copy_gates.BLOCKING) & set(copy_gates.ADVISORY)
    assert set(copy_gates.MESSAGES) == set(copy_gates.BLOCKING) | set(copy_gates.ADVISORY)
    assert copy_gates.copy_rejection(CLEAN) is None
    assert copy_gates.copy_rejection("Port Example hit 47°C. It was hot.") is None  # Two sentences: advisory only.
    assert copy_gates.copy_rejection(123) is None and copy_gates.copy_notes("   ") == []


def test_danger_wording_blocks_unless_the_same_wording_is_in_source_evidence():
    text = "Mali faces a life-threatening heat warning on Tuesday."
    bundle = _bundle()
    assert copy_gates.copy_rejection(text, bundle).startswith("invented_danger")
    sourced = replace(bundle, raw_signal_dump={**bundle.raw_signal_dump,
                                               "warning_text": "Life threatening heat expected (invented)"})
    assert copy_gates.copy_rejection(text, sourced) is None
    # An editorial prohibition naming the word is not source wording.
    forbidden = replace(bundle, historical_context={"forbidden_claims": ["life-threatening"]})
    assert copy_gates.copy_rejection(text, forbidden).startswith("invented_danger")


@pytest.fixture
def paid(monkeypatch):
    safety = Mock(return_value=(True, None))
    factual = Mock(return_value=FactCheckResult(True, [], "offline fixture"))
    critic = Mock(return_value=CriticResult(True, None, "offline fixture"))
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety)
    monkeypatch.setattr(fact_check, "fact_check", factual)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    return safety, factual, critic


def _writer_responds(monkeypatch, tweet):
    raw = json.dumps({"tweet": tweet, "kill_reason": None, "angle_chosen": "magnitude", "era_anchor_used": None,
                      "peer_comparison_used": None, "reasoning": "invented offline fixture", "cited_impact": None,
                      "kill_scope": None, "kill_code": None})
    provider = Mock(return_value=raw)
    monkeypatch.setattr(writer, "_call_writer_provider", provider)
    return provider


@pytest.mark.usefixtures("configured_pipeline_providers")
@pytest.mark.parametrize("tweet,code", [
    (STERILE, "source_led_opener"),
    ("Mali thermal power is 361 MW, a stark reminder of a warming world.", "generic_explanatory_ending"),
    ("Mali thermal power is 361 MW. The pixel is near Bamako. Detection was at noon.", "too_many_sentences"),
    ("Mali thermal power is 361 MW, a dangerous detection.", "invented_danger"),
])
def test_real_writer_output_is_rejected_free_before_any_paid_check(monkeypatch, paid, tweet, code):
    provider = _writer_responds(monkeypatch, tweet)
    outcome = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=outcome) is None
    assert provider.call_count == 1  # One routine writer sample; no repair or refill call.
    assert outcome["kill_stage"] == "copy_gate" and outcome["kill_reason"].startswith(code)
    assert outcome["stage_outcomes"] == {"writer": "pass", "copy_gate": "kill"}
    assert all(not model.mock_calls for model in paid)


@pytest.mark.usefixtures("configured_pipeline_providers")
def test_fact_first_output_still_buys_every_required_check(monkeypatch, paid):
    provider = _writer_responds(monkeypatch, CLEAN)
    draft = pipeline.generate_draft(_bundle(), _state_with_memory())
    assert draft and draft["text"] == CLEAN and provider.call_count == 1
    assert [model.call_count for model in paid] == [1, 1, 1]


@pytest.mark.usefixtures("configured_pipeline_providers")
def test_factual_rejection_keeps_priority_over_copy(monkeypatch, paid):
    _writer_responds(monkeypatch, "A satellite detection model shows a Mali wildfire at 361 MW.")
    outcome = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=outcome) is None
    assert outcome["kill_stage"] == "fact_check" and all(not model.mock_calls for model in paid)


def _deterministic(text):
    source = _bundle()
    saved = packet(dict(candidate=asdict(WriterResult(text, None, "number", None, None, "Invented fixture")),
                        candidate_id="c" * 64, bundle=source.to_dict(), policy=current_editorial_policy()))
    return check_requests.deterministic_result(saved)


def test_retained_deterministic_check_names_the_copy_rule_and_is_otherwise_unchanged():
    rejected = _deterministic(STERILE)
    assert rejected["passed"] is False
    assert any(f.startswith("copy_gate: source_led_opener") for f in rejected["failures"])
    clean = _deterministic(CLEAN)
    assert clean["passed"] is True and clean["failures"] == []


def test_policy_identity_and_stage_consumers_include_the_gate():
    assert "src/two_bot/copy_gates.py" in source_manifest()["files"]
    assert "copy_gate" in CHECK_STAGES
    assert WRITER_HEALTH_STAGES["copy_gate"] == "local_copy_rule_rejection"


def test_current_prompts_state_the_direction_without_reusing_held_or_historical_text():
    from src.two_bot.prompts.critic_prompt import CRITIC_SYSTEM_PROMPT
    from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT
    assert "never the opening" in WRITER_SYSTEM_PROMPT and "One complete sentence by default" in WRITER_SYSTEM_PROMPT
    assert "Make scale intelligible" in WRITER_SYSTEM_PROMPT and "Some personality" in WRITER_SYSTEM_PROMPT
    assert "never a generic explanation" in WRITER_SYSTEM_PROMPT
    assert "never a source/model/agency opener" in CRITIC_SYSTEM_PROMPT
    for prompt in (WRITER_SYSTEM_PROMPT, CRITIC_SYSTEM_PROMPT):
        assert "Riyadh" not in prompt and "Guam" not in prompt
    # The prompt's own invented shapes satisfy the free gate they describe.
    line = next(row for row in WRITER_SYSTEM_PROMPT.splitlines() if row.startswith("Invented shapes"))
    import re
    for example in re.findall(r'"([^"]+)"', line):
        assert copy_gates.copy_notes(example) == [], example
