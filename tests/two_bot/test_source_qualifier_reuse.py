"""Synthetic regressions: reusable scope labels never bypass factual checks."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from src.two_bot import fact_check, memory, check_requests
from src.two_bot.types import ExtractedClaim, WriterResult
from src.editorial.revisions import fingerprint
from tests.two_bot.conftest import _bundle, _memory, _state_with_memory


@pytest.mark.parametrize("kind", ["era_anchor", "peer_comparison"])
@pytest.mark.parametrize(
    "qualifier",
    [
        "model-estimated",
        "MODEL-ESTIMATED",
        "model estimated",
        " model \t estimated. ",
        "model‑estimated",
        "model – estimated",
        "model‐estimated",
        "model—estimated",
    ],
)
def test_standalone_source_qualifier_is_reusable_without_changing_legacy_state(kind, qualifier):
    state = _state_with_memory(
        used_era_anchors=["model-estimated"], used_peer_comparisons=["model-estimated"]
    )
    before = deepcopy(state)
    assert not memory.is_reuse(state, qualifier, kind)
    assert not memory.is_reuse(state, "a model-estimated quantity from a new source", kind)
    assert state == before


def test_writer_context_filters_only_standalone_qualifiers_and_keeps_legacy_rows():
    genuine = "model-estimated since 1984"
    state = _state_with_memory(
        used_era_anchors=["MODEL-ESTIMATED", genuine, "a 1991 film"],
        used_peer_comparisons=["model estimated", "three pools"],
    )
    before = deepcopy(state)
    result = memory.build_memory_slice(state, _bundle())
    assert result.used_era_anchors == [genuine, "a 1991 film"]
    assert result.used_peer_comparisons == ["three pools"]
    assert state == before


@pytest.mark.parametrize(
    "kind,field", [("era_anchor", "used_era_anchors"), ("peer_comparison", "used_peer_comparisons")]
)
def test_future_recording_keeps_shipped_text_and_substantive_claims(kind, field):
    text = "A synthetic model-estimated value for this fixture."
    state = _state_with_memory()
    writer = WriterResult(
        tweet=text,
        kill_reason=None,
        angle_chosen="plain_number",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="synthetic fixture",
    )
    claims = [
        ExtractedClaim(text="model-estimated", kind=kind),
        ExtractedClaim(text="model-estimated since 1984", kind=kind),
    ]
    memory.record_shipped(state, _bundle(), writer, claims)
    assert state["memory"][field] == ["model-estimated since 1984"]
    assert state["memory"]["shipped_tweets"][-1]["tweet_text"] == text
    assert claims[0].kind == kind and claims[0].text == "model-estimated"


@pytest.mark.parametrize("kind", ["era_anchor", "peer_comparison"])
@pytest.mark.parametrize(
    "stored,candidate",
    [
        ("model-estimated since 1984", "model-estimated since 1984"),
        ("model-estimated since 1984", "model-estimated since 1984 again"),
        ("a 1991 film", "the year a 1991 film came out"),
        ("three pools", "the size of three pools"),
        ("historic-scale", "historic-scale"),
        ("estimated", "estimated"),
    ],
)
def test_real_novelty_bans_remain_in_force(kind, stored, candidate):
    state = _state_with_memory(used_era_anchors=[stored], used_peer_comparisons=[stored])
    assert memory.is_reuse(state, candidate, kind)


def test_complete_tweet_and_framing_duplicates_still_fail():
    text = "A model-estimated value for the fixture."
    state = _state_with_memory(shipped_tweets=[{"tweet_text": text}])
    state["memory"]["used_framings"] = ["model-estimated"]
    assert memory.is_reuse(state, text, "tweet_text")
    assert memory.is_reuse(state, "model-estimated", "framing")
    with pytest.raises(ValueError, match="Unsupported reuse kind"):
        memory.is_reuse(state, "model-estimated", "unknown")


def _response(text, *, passed):
    # Explicit offline model fixture, not an adjudicated weather claim.
    return json.dumps(
        dict(
            passed=passed,
            extracted_claims=[
                dict(text=text, kind="comparison"),
                dict(text="model-estimated", kind="era_anchor"),
            ],
            failures=[]
            if passed
            else ["synthetic claim is not supported by the supplied evidence"],
        )
    )


@pytest.mark.parametrize("model_passes", [True, False])
def test_removing_novelty_false_positive_still_requires_full_factual_call(
    monkeypatch, model_passes
):
    text = "A model-estimated thermal signal is shown."
    state = _state_with_memory(used_era_anchors=["model-estimated"])
    call = Mock(return_value=_response(text, passed=model_passes))
    monkeypatch.setattr(fact_check, "_call_gemini", call)
    checked = fact_check.fact_check(text, [], _bundle(), state)
    call.assert_called_once()
    assert checked.passed is model_passes
    if not model_passes:
        assert checked.failures == ["synthetic claim is not supported by the supplied evidence"]


def test_duplicate_complete_tweet_does_not_reach_paid_check(monkeypatch):
    text = "A model-estimated thermal signal is shown."
    state = _state_with_memory(
        shipped_tweets=[{"tweet_text": text}], used_era_anchors=["model-estimated"]
    )
    call = Mock(side_effect=AssertionError("duplicate must not buy a check"))
    monkeypatch.setattr(fact_check, "_call_gemini", call)
    checked = fact_check.fact_check(text, [], _bundle(), state)
    assert not checked.passed and any("duplicates shipped tweet" in s for s in checked.failures)
    call.assert_not_called()


def test_batch_uses_same_scientific_and_novelty_rules():
    text = "A model-estimated thermal signal is shown."
    state = _state_with_memory(used_era_anchors=["model-estimated"])
    packet = dict(
        bundle=_bundle().to_dict(),
        memory=_memory().to_dict(),
        checker_state=state,
        checker_state_sha256=fingerprint(state),
        candidate={"tweet": text},
    )
    for passed in (True, False):
        raw = json.dumps(
            dict(
                candidates=[
                    dict(
                        index=0,
                        finishReason="STOP",
                        content=dict(
                            role="model", parts=[dict(text=_response(text, passed=passed))]
                        ),
                    )
                ]
            )
        ).encode()
        result = check_requests.interpret_observation(
            packet, "fact_check", dict(complete=True, http_status=200), raw
        )
        assert result["verdict"] == ("pass" if passed else "reject")
    packet["candidate"]["tweet"] = "A model-estimated thermal signal confirms a vegetation fire."
    assert not check_requests.deterministic_result(packet)["passed"]
