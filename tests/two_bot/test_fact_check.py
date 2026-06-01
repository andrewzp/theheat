import json
from unittest.mock import MagicMock

import pytest

from src.two_bot.fact_check import fact_check
from src.two_bot.types import ExtractedClaim

from tests.two_bot.conftest import _bundle, _state_with_memory


def _fact_response(passed=True, failures=None, extracted_claims=None):
    return json.dumps({
        "passed": passed,
        "extracted_claims": extracted_claims or [],
        "failures": failures or [],
    })


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
    mock_gemini.return_value = _fact_response()

    result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

    assert result.passed
    assert mock_gemini.called


def test_fact_check_accepts_fenced_preamble_response(mock_gemini):
    mock_gemini.return_value = """Looking at the supplied bundle, this passes.

```json
{
  "passed": true,
  "extracted_claims": [],
  "failures": []
}
```
"""

    result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

    assert result.passed


def test_fact_check_propagates_llm_failure(mock_gemini):
    mock_gemini.return_value = _fact_response(
        passed=False,
        failures=[
            {
                "claim": "since 2012",
                "category": "BUNDLE_FACT",
                "reason": "bundle says 2014",
            }
        ],
    )

    result = fact_check("...since 2012", [], _bundle(), _state_with_memory())

    assert not result.passed
    assert any("since 2012" in failure for failure in result.failures)


def test_fact_check_uses_returned_claims_for_reuse_checks(mock_gemini):
    mock_gemini.return_value = _fact_response(
        extracted_claims=[
            {"text": "Spider-Man 2002", "kind": "era_anchor"},
        ],
    )
    state = _state_with_memory(used_era_anchors=["spider-man 2002"])

    result = fact_check(
        "Last time it was this hot, Spider-Man 2002 was new.",
        [],
        _bundle(),
        state,
    )

    assert not result.passed
    assert any("era anchor" in failure for failure in result.failures)
    assert result.extracted_claims == [
        ExtractedClaim(text="Spider-Man 2002", kind="era_anchor")
    ]


def test_fact_check_requires_claims_when_combined_path_has_no_preextract(mock_gemini):
    mock_gemini.return_value = '{"passed": true, "failures": []}'

    result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

    assert not result.passed
    assert any("extracted_claims" in failure for failure in result.failures)


def test_fact_check_skips_claims_with_unknown_kind_instead_of_killing(mock_gemini, capsys):
    """Gemini Flash sometimes returns claim kinds outside the prompt's
    enumerated list (observed 2026-06-01: 14+ candidates killed across
    the day with 'Unsupported extracted claim kind: factual_assertion').
    The parser must drop the unknown-kind claims gracefully, NOT kill the
    whole tweet — pass/fail is independent of claim kinds.
    """
    mock_gemini.return_value = json.dumps({
        "passed": True,
        "failures": [],
        "extracted_claims": [
            {"text": "12.0 °C-weeks", "kind": "number"},
            {"text": "the broader signal", "kind": "factual_assertion"},  # off-script kind
            {"text": "Western India", "kind": "named_entity"},
        ],
    })

    result = fact_check(
        "Western India: 12.0 °C-weeks of thermal stress.",
        [],
        _bundle(),
        _state_with_memory(),
    )

    # Tweet should pass: pass/fail doesn't depend on claim kinds.
    assert result.passed
    # The 2 valid claims survive; the 1 unknown-kind claim is dropped.
    assert len(result.extracted_claims) == 2
    assert {c.kind for c in result.extracted_claims} == {"number", "named_entity"}
    # And we logged the drop so the operator can see it in the cron output.
    captured = capsys.readouterr()
    assert "factual_assertion" in captured.out
    assert "unsupported kind" in captured.out.lower()


def test_fact_check_still_raises_on_structurally_bad_claim(mock_gemini):
    """Unknown KIND → skip. But missing/wrong-type FIELDS still raise.
    A response missing required structure is fundamentally untrusted.
    """
    mock_gemini.return_value = json.dumps({
        "passed": True,
        "failures": [],
        "extracted_claims": [
            {"text": "missing kind field entirely"},  # structural failure
        ],
    })

    result = fact_check("Some tweet.", [], _bundle(), _state_with_memory())

    # Structurally-broken response → tweet fails fact-check (the retry
    # path returned a structured KILL after parse_budget exhausted).
    assert not result.passed


class TestJsonParseRetry:
    """Fact-check-side defense: if Gemini returns empty / non-JSON / mid-
    truncation output, retry once with a stronger contract reminder. If
    that also fails, return a structured FactCheckResult(passed=False)
    instead of letting ValueError bubble up as pipeline_error.

    Production failure this prevents: 2026-05-15 alerts cron logged a
    Somalia coral_bleaching pipeline_error with reason 'ValueError:
    invalid JSON in model response: Expecting "," delimiter: line 7
    column 384'. Stochastic refusal class — the retry usually unblocks
    via fresh sampling, and on the off-chance it doesn't the structured
    KILL is the right ledger category (the gate held; the draft is
    blocked) rather than 'the pipeline crashed.'
    """

    def _ok(self) -> str:
        return _fact_response()

    def test_retries_on_empty_response(self, mock_gemini):
        """First call returns empty string; second returns valid JSON."""
        mock_gemini.side_effect = ["", self._ok()]

        result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

        assert result.passed is True
        assert mock_gemini.call_count == 2

    def test_retries_on_non_json_response(self, mock_gemini):
        """First call returns prose; second returns valid JSON."""
        mock_gemini.side_effect = [
            "I cannot help with this fact-check.",
            self._ok(),
        ]

        result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

        assert result.passed is True
        assert mock_gemini.call_count == 2

    def test_retries_on_mid_truncation(self, mock_gemini):
        """The Somalia 2026-05-15 production failure shape: well-formed
        prefix, malformed inside. ``loads_model_json`` raises
        JSONDecodeError which the parser converts to ValueError → retry.
        """
        mid_truncation = '{"passed": false, "failures": [{"claim": "X", "category": "BUNDLE_FACT",'  # cut off
        mock_gemini.side_effect = [mid_truncation, self._ok()]

        result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

        assert result.passed is True
        assert mock_gemini.call_count == 2

    def test_fails_closed_after_parse_budget_exhausted(self, mock_gemini):
        """Both attempts return non-JSON — return FactCheckResult with
        passed=False and a failures entry naming the JSON failure. The
        pipeline records this as a fact_check stage kill (not pipeline_error).
        Fail-closed is the right disposition: the gate blocks the draft
        when it can't read the verdict.
        """
        from src.two_bot.fact_check import JSON_PARSE_RETRY_BUDGET

        mock_gemini.side_effect = ["garbage one", "garbage two"]

        result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

        assert result.passed is False
        assert any("invalid JSON across" in f for f in result.failures)
        assert mock_gemini.call_count == JSON_PARSE_RETRY_BUDGET + 1

    def test_no_retry_when_first_attempt_parses(self, mock_gemini):
        """Happy path: first call is valid JSON, no retry, no contract
        reminder appended to the prompt."""
        mock_gemini.return_value = self._ok()

        result = fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

        assert result.passed is True
        assert mock_gemini.call_count == 1

    def test_retry_passes_contract_reminder_suffix(self, mock_gemini):
        """The retry attempt must pass a non-empty ``retry_suffix`` that
        reinforces the JSON contract — otherwise the model has no
        feedback that the first attempt was rejected for format
        reasons (not content)."""
        mock_gemini.side_effect = ["", self._ok()]

        fact_check("Some clean tweet.", [], _bundle(), _state_with_memory())

        first_call_kwargs = mock_gemini.call_args_list[0].kwargs
        second_call_kwargs = mock_gemini.call_args_list[1].kwargs
        # First attempt: no retry_suffix (or empty).
        assert first_call_kwargs.get("retry_suffix", "") == ""
        # Second attempt: retry_suffix is the contract reminder.
        assert "JSON-output retry" in second_call_kwargs.get("retry_suffix", "")


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

    def test_claim_extractor_gemini_timeout_is_in_milliseconds_range(self):
        """Regression: the SDK default timeout is None (= unbounded) — a
        stuck Gemini call would hang the cron run indefinitely. Found
        2026-05-08 via codex review of PR #43, where the timeout-unit
        fix only covered fact-check and writer-fallback, not the
        mandatory claim-extractor stage."""
        import inspect
        from src.two_bot import claim_extractor

        source = inspect.getsource(claim_extractor._call_gemini)
        import re
        match = re.search(r"HttpOptions\([^)]*timeout=(\d+)", source)
        assert match is not None, (
            "_call_gemini in claim_extractor must configure "
            "HttpOptions(timeout=...) — the SDK default is unbounded"
        )
        timeout_value = int(match.group(1))
        assert timeout_value >= 5000, (
            f"Gemini claim-extractor timeout is {timeout_value} (ms). "
            f"google-genai HttpOptions.timeout is in MILLISECONDS — "
            f"values under 5000ms hang the pipeline on every call."
        )
