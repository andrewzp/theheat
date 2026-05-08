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


def test_fact_check_accepts_fenced_preamble_response(mock_gemini):
    mock_gemini.return_value = """Looking at the supplied bundle, this passes.

```json
{
  "passed": true,
  "failures": []
}
```
"""

    result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

    assert result.passed


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


class TestGeminiTimeoutUnit:
    """Regression: google-genai HttpOptions.timeout is MILLISECONDS, not
    seconds. A bare integer like ``timeout=90`` means 90ms — barely
    enough for a TLS handshake. Observed 2026-05-08 in run 25530252198:
    every Gemini fact-check call failed with ReadTimeout in <300ms
    across 3 retry attempts, silently killing every draft from
    2026-05-03 onward (4-day production outage).
    """

    def test_fact_check_timeout_is_in_milliseconds_range(self):
        """The configured timeout must be >= 5000 (5 seconds in ms).
        If anyone passes a value like 90 (= 90ms) again, this fails loud.
        """
        import inspect
        from src.two_bot import fact_check

        source = inspect.getsource(fact_check._call_gemini)
        # Match HttpOptions(timeout=NNN) or HttpOptions(..., timeout=NNN)
        import re
        match = re.search(r"HttpOptions\([^)]*timeout=(\d+)", source)
        assert match is not None, "_call_gemini must configure HttpOptions(timeout=...)"
        timeout_value = int(match.group(1))
        assert timeout_value >= 5000, (
            f"Gemini fact-check timeout is {timeout_value} (ms). "
            f"Values under 5000ms are suspicious — google-genai HttpOptions.timeout "
            f"is in MILLISECONDS, not seconds. Did you pass seconds by mistake?"
        )

    def test_writer_gemini_fallback_timeout_is_in_milliseconds_range(self):
        """Same check for the Gemini writer fallback path."""
        import inspect
        from src.two_bot import writer

        source = inspect.getsource(writer._call_google)
        import re
        match = re.search(r"HttpOptions\([^)]*timeout=(\d+)", source)
        assert match is not None, "_call_google must configure HttpOptions(timeout=...)"
        timeout_value = int(match.group(1))
        assert timeout_value >= 5000, (
            f"Gemini writer-fallback timeout is {timeout_value} (ms). "
            f"google-genai HttpOptions.timeout is in MILLISECONDS — values "
            f"under 5000ms break the fallback writer."
        )
