"""Tests for the virality evaluator — second inference pass."""

import json
from unittest.mock import patch, MagicMock

from src.editorial.evaluator import (
    EvaluatorVerdict,
    evaluate_candidate,
    evaluate_and_polish,
    _parse_evaluator_response,
    _passing_verdict,
    _verify_pass,
)
from src.editorial.candidates import (
    CandidateBundle,
    CandidateScore,
    DraftCandidate,
)


def _make_bundle(text: str, category: str = "record") -> CandidateBundle:
    """Helper: build a minimal CandidateBundle for testing."""
    score = CandidateScore(clarity=70, context=70, voice=70, punch=70, total=70, reasons=("test",))
    candidate = DraftCandidate(rank=1, text=text, source="gemini", score=score)
    return CandidateBundle(category=category, candidates=[candidate])


def _mock_anthropic_response(response_json: dict) -> MagicMock:
    """Helper: build a mock Anthropic response."""
    content_block = MagicMock()
    content_block.text = json.dumps(response_json)
    response = MagicMock()
    response.content = [content_block]
    return response


def _mock_anthropic_client(response_json: dict) -> MagicMock:
    """Helper: build a mock Anthropic client."""
    client = MagicMock()
    client.messages.create.return_value = _mock_anthropic_response(response_json)
    return client


def _passing_response() -> dict:
    return {
        "passed": True,
        "scores": {"awe": 8, "comparison": 8, "social_currency": 8, "opener": 9, "show_not_tell": 10},
        "total": 43,
        "failures": [],
        "reasoning": "Strong tweet with concrete comparison and awe.",
        "rewrite": None,
    }


def _failing_response(rewrite: str = "Rewritten tweet.") -> dict:
    return {
        "passed": False,
        "scores": {"awe": 4, "comparison": 3, "social_currency": 5, "opener": 4, "show_not_tell": 8},
        "total": 24,
        "failures": ["awe", "comparison", "opener"],
        "reasoning": "Pure information, no gut reaction.",
        "rewrite": rewrite,
    }


# --- Parsing ---

class TestParseResponse:
    def test_valid_json(self):
        raw = json.dumps(_passing_response())
        verdict = _parse_evaluator_response(raw)
        assert verdict.passed is True
        assert verdict.scores["awe"] == 8
        assert verdict.rewrite is None

    def test_failing_json_with_rewrite(self):
        raw = json.dumps(_failing_response("Better tweet here."))
        verdict = _parse_evaluator_response(raw)
        assert verdict.passed is False
        assert verdict.rewrite == "Better tweet here."
        assert "awe" in verdict.failures

    def test_strips_markdown_fences(self):
        raw = "```json\n" + json.dumps(_passing_response()) + "\n```"
        verdict = _parse_evaluator_response(raw)
        assert verdict.passed is True

    def test_empty_rewrite_becomes_none(self):
        resp = _failing_response("")
        raw = json.dumps(resp)
        verdict = _parse_evaluator_response(raw)
        assert verdict.rewrite is None

    def test_cross_check_overrides_hallucinated_pass(self):
        """Model says passed=true but scores are clearly failing."""
        resp = {
            "passed": True,
            "scores": {"awe": 3, "comparison": 2, "social_currency": 4, "opener": 3, "show_not_tell": 8},
            "total": 20,
            "failures": [],
            "reasoning": "looks good to me",
            "rewrite": None,
        }
        verdict = _parse_evaluator_response(json.dumps(resp))
        assert verdict.passed is False


# --- _verify_pass ---

class TestVerifyPass:
    def test_all_high_scores_pass(self):
        assert _verify_pass({"a": 8, "b": 9, "c": 7, "d": 8, "e": 10}, True) is True

    def test_any_below_5_fails(self):
        assert _verify_pass({"a": 4, "b": 9, "c": 9, "d": 9, "e": 9}, True) is False

    def test_two_below_7_fails(self):
        assert _verify_pass({"a": 6, "b": 6, "c": 9, "d": 9, "e": 9}, True) is False

    def test_one_below_7_with_rest_above_passes(self):
        assert _verify_pass({"a": 6, "b": 8, "c": 8, "d": 8, "e": 9}, True) is True

    def test_empty_scores_trusts_model(self):
        assert _verify_pass({}, True) is True
        assert _verify_pass({}, False) is False


# --- evaluate_candidate ---

class TestEvaluateCandidate:
    @patch("src.editorial.evaluator.ANTHROPIC_API_KEY", "")
    def test_no_api_key_returns_pass(self):
        verdict = evaluate_candidate("any tweet", "data", "record")
        assert verdict.passed is True
        assert verdict.reasoning == "evaluator skipped"

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_passing_candidate(self, mock_get_client):
        mock_get_client.return_value = _mock_anthropic_client(_passing_response())
        verdict = evaluate_candidate(
            "Phoenix just dropped 121F. NEW RECORD. The old one was from last year.",
            "Phoenix forecast high 121F, old record 119F from 2024",
            "record",
        )
        assert verdict.passed is True
        assert verdict.scores["awe"] == 8

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_failing_candidate_returns_rewrite(self, mock_get_client):
        mock_get_client.return_value = _mock_anthropic_client(
            _failing_response("Phoenix at 121F. The old record was last year.")
        )
        verdict = evaluate_candidate(
            "CO2 is at 435 ppm at Mauna Loa this week.",
            "CO2 data: current 435 ppm",
            "co2_milestone",
        )
        assert verdict.passed is False
        assert verdict.rewrite is not None

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_api_error_returns_pass(self, mock_get_client):
        client = MagicMock()
        client.messages.create.side_effect = Exception("rate limited")
        mock_get_client.return_value = client
        verdict = evaluate_candidate("tweet", "data", "record")
        assert verdict.passed is True
        assert verdict.reasoning == "evaluator skipped"

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_bad_json_returns_pass(self, mock_get_client):
        content_block = MagicMock()
        content_block.text = "not json at all"
        response = MagicMock()
        response.content = [content_block]
        client = MagicMock()
        client.messages.create.return_value = response
        mock_get_client.return_value = client
        verdict = evaluate_candidate("tweet", "data", "record")
        assert verdict.passed is True


# --- evaluate_and_polish ---

class TestEvaluateAndPolish:
    @patch("src.editorial.evaluator.ANTHROPIC_API_KEY", "")
    def test_no_api_key_returns_original(self):
        bundle = _make_bundle("Original tweet.")
        result = evaluate_and_polish(bundle, "data")
        assert result.text == "Original tweet."

    def test_empty_bundle_returns_original(self):
        bundle = CandidateBundle(category="record", candidates=[])
        result = evaluate_and_polish(bundle, "data")
        assert result.candidates == []

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_passing_returns_original(self, mock_get_client):
        mock_get_client.return_value = _mock_anthropic_client(_passing_response())
        bundle = _make_bundle("Phoenix just dropped 121F. NEW RECORD. The old one was from last year.")
        result = evaluate_and_polish(bundle, "data")
        assert result.text == bundle.text
        assert len(result.candidates) == 1

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_failing_with_rewrite_replaces_top(self, mock_get_client):
        original = "CO2 is at 435 ppm at Mauna Loa this week."
        rewrite = "CO2 at Mauna Loa: 435 ppm. Pre-industrial was 280. We are 55% above where the atmosphere was for all of human civilization."
        mock_get_client.return_value = _mock_anthropic_client(_failing_response(rewrite))
        bundle = _make_bundle(original, category="co2_milestone")
        result = evaluate_and_polish(bundle, "data")
        assert result.text == rewrite
        assert result.candidates[0].source == "evaluator_rewrite"
        assert result.candidates[0].rank == 1
        assert len(result.candidates) == 2
        assert result.candidates[1].text == original
        assert result.candidates[1].rank == 2

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_failing_rewrite_fails_safety_returns_none(self, mock_get_client):
        """Evaluator rejects + rewrite fails safety = kill the draft."""
        rewrite_with_bang = "Phoenix hit 121F! NEW RECORD!"
        mock_get_client.return_value = _mock_anthropic_client(_failing_response(rewrite_with_bang))
        bundle = _make_bundle("Original tweet.")
        result = evaluate_and_polish(bundle, "data")
        assert result is None

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_failing_no_rewrite_returns_none(self, mock_get_client):
        """Evaluator rejects with no rewrite = kill the draft."""
        resp = _failing_response()
        resp["rewrite"] = None
        mock_get_client.return_value = _mock_anthropic_client(resp)
        bundle = _make_bundle("Original tweet.")
        result = evaluate_and_polish(bundle, "data")
        assert result is None

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_overlong_rewrite_returns_none(self, mock_get_client):
        """Evaluator rejects + rewrite too long = kill the draft."""
        rewrite = "A" * 300
        mock_get_client.return_value = _mock_anthropic_client(_failing_response(rewrite))
        bundle = _make_bundle("Original tweet.")
        result = evaluate_and_polish(bundle, "data")
        assert result is None

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_score_regression_returns_none(self, mock_get_client):
        """Evaluator rejects + rewrite scores lower = kill the draft."""
        rewrite = "Meh."
        mock_get_client.return_value = _mock_anthropic_client(_failing_response(rewrite))
        bundle = _make_bundle("Original tweet with good structure and data density 121F record.")
        result = evaluate_and_polish(bundle, "data")
        assert result is None

    @patch("src.editorial.evaluator._get_anthropic_client")
    def test_api_failure_returns_original(self, mock_get_client):
        client = MagicMock()
        client.messages.create.side_effect = Exception("timeout")
        mock_get_client.return_value = client
        bundle = _make_bundle("Original tweet.")
        result = evaluate_and_polish(bundle, "data")
        assert result.text == "Original tweet."


# --- EvaluatorVerdict ---

class TestEvaluatorVerdict:
    def test_as_dict(self):
        v = EvaluatorVerdict(
            passed=False,
            scores={"awe": 4},
            total=24,
            failures=["awe"],
            reasoning="boring",
            rewrite="better",
        )
        d = v.as_dict()
        assert d["passed"] is False
        assert d["rewrite"] == "better"
        assert d["scores"]["awe"] == 4

    def test_passing_verdict_helper(self):
        v = _passing_verdict()
        assert v.passed is True
        assert v.rewrite is None
