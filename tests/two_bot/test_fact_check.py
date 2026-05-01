import json
from unittest.mock import MagicMock

import pytest

from src.two_bot.fact_check import fact_check
from src.two_bot.types import ExtractedClaim

from tests.two_bot.conftest import _bundle, _state_with_memory


@pytest.fixture
def mock_gemini(monkeypatch):
    import src.two_bot.fact_check as fact_check_module

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock = MagicMock()
    monkeypatch.setattr(fact_check_module, "_call_gemini", mock)
    return mock


def test_fact_check_deterministic_tweet_reuse():
    state = _state_with_memory(shipped_tweets=[{"tweet_text": "A wildfire in Mali..."}])

    result = fact_check("A wildfire in Mali...", [], _bundle(), state)

    assert not result.passed
    assert any("reuse" in failure.lower() for failure in result.failures)


def test_fact_check_deterministic_era_anchor_reuse_via_extraction():
    state = _state_with_memory(used_era_anchors=["spider-man 2002"])
    extracted = [ExtractedClaim(text="Spider-Man 2002", kind="era_anchor")]

    result = fact_check(
        "Last time it was this hot, Spider-Man 2002 was new.",
        extracted,
        _bundle(),
        state,
    )

    assert not result.passed
    assert any("era anchor" in failure for failure in result.failures)


def test_fact_check_calls_llm_when_local_passes(mock_gemini):
    mock_gemini.return_value = '{"passed": true, "failures": []}'

    result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

    assert result.passed
    assert mock_gemini.called


def test_fact_check_propagates_llm_failure(mock_gemini):
    mock_gemini.return_value = json.dumps(
        {
            "passed": False,
            "failures": [
                {
                    "claim": "since 2012",
                    "category": "BUNDLE_FACT",
                    "reason": "bundle says 2014",
                }
            ],
        }
    )

    result = fact_check("...since 2012", [], _bundle(), _state_with_memory())

    assert not result.passed
    assert any("since 2012" in failure for failure in result.failures)

