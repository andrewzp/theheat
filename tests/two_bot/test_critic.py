"""Tests for the editorial critic (Stage 5).

Mocks Gemini at the module boundary — same pattern as test_fact_check.py.
The critic's behavioral verification (does it actually catch template
convergence?) runs against the live API in the voice-regression cron;
these tests guard the wire and the JSON contract.
"""

from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from src.two_bot import critic
from src.two_bot.critic import (
    _collect_pending_today,
    _format_pending_block,
    _format_shipped_block,
    _parse_critic_json,
)
from src.two_bot.types import CriticResult, StoryBundle


@pytest.fixture
def mock_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock = MagicMock()
    monkeypatch.setattr(critic, "_call_gemini", mock)
    return mock


def _bundle(event_id: str = "coral_test") -> StoryBundle:
    return StoryBundle(
        signal_kind="coral_bleaching",
        where="Northern GBR",
        when="2026-05-13",
        event_id=event_id,
        headline_metric={"label": "DHW", "value": 8.2, "unit": "°C-weeks"},
        current_facts=[
            {"label": "dhw_value", "value": 8.2},
            {"label": "bleaching_level", "value": "mass bleaching expected"},
        ],
        historical_context={"thresholds_c_weeks": [4, 8, 12]},
        raw_signal_dump={},
    )


def _state_with_drafts(drafts: list[dict]) -> dict:
    """Minimal state with a drafts list — no memory needed for collect tests."""
    return {"drafts": deepcopy(drafts), "memory": {"shipped_tweets": []}}


class TestParseCriticJson:
    def test_passing_response_parses(self):
        passed, reason = _parse_critic_json('{"passed": true, "kill_reason": null}')
        assert passed is True
        assert reason is None

    def test_killing_response_parses(self):
        raw = json.dumps({"passed": False, "kill_reason": "template_convergence: same opener as Fiji"})
        passed, reason = _parse_critic_json(raw)
        assert passed is False
        assert reason == "template_convergence: same opener as Fiji"

    def test_invalid_json_raises_valueerror(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            _parse_critic_json("not json")

    def test_non_object_response_raises(self):
        with pytest.raises(ValueError, match="JSON object"):
            _parse_critic_json("[1, 2, 3]")

    def test_missing_passed_raises(self):
        with pytest.raises(ValueError, match="boolean passed"):
            _parse_critic_json('{"kill_reason": "..."}')

    def test_non_bool_passed_raises(self):
        with pytest.raises(ValueError, match="boolean passed"):
            _parse_critic_json('{"passed": "yes", "kill_reason": null}')

    def test_killing_without_reason_raises(self):
        # passed=false MUST include a reason — the dashboard relies on
        # this for the suppression display.
        with pytest.raises(ValueError, match="must include kill_reason"):
            _parse_critic_json('{"passed": false, "kill_reason": null}')

    def test_killing_with_empty_reason_raises(self):
        with pytest.raises(ValueError, match="must include kill_reason"):
            _parse_critic_json('{"passed": false, "kill_reason": "   "}')

    def test_killing_with_non_string_reason_raises(self):
        with pytest.raises(ValueError, match="must include kill_reason"):
            _parse_critic_json('{"passed": false, "kill_reason": 42}')


class TestCollectPendingToday:
    def test_only_returns_pending_status(self):
        from datetime import UTC, datetime
        today = datetime.now(UTC).date().isoformat()
        state = _state_with_drafts([
            {"id": "a", "status": "pending", "created_at": f"{today}T01:00:00Z", "event_id": "e1", "text": "draft a"},
            {"id": "b", "status": "approved", "created_at": f"{today}T02:00:00Z", "event_id": "e2", "text": "draft b"},
            {"id": "c", "status": "rejected", "created_at": f"{today}T03:00:00Z", "event_id": "e3", "text": "draft c"},
        ])
        pending = _collect_pending_today(state)
        assert len(pending) == 1
        assert pending[0]["id"] == "a"

    def test_excludes_drafts_from_prior_days(self):
        state = _state_with_drafts([
            {"id": "a", "status": "pending", "created_at": "2025-01-01T00:00:00Z", "event_id": "e1", "text": "old"},
            {"id": "b", "status": "pending", "created_at": "1999-12-31T23:59:59Z", "event_id": "e2", "text": "older"},
        ])
        # The prior-day filter is by UTC-date string prefix; "today" is
        # whenever the test runs, so neither draft should match.
        pending = _collect_pending_today(state)
        assert pending == []

    def test_excludes_in_flight_event_id(self):
        from datetime import UTC, datetime
        today = datetime.now(UTC).date().isoformat()
        state = _state_with_drafts([
            {"id": "a", "status": "pending", "created_at": f"{today}T01:00:00Z", "event_id": "in_flight", "text": "self"},
            {"id": "b", "status": "pending", "created_at": f"{today}T02:00:00Z", "event_id": "other", "text": "sibling"},
        ])
        pending = _collect_pending_today(state, exclude_event_id="in_flight")
        assert len(pending) == 1
        assert pending[0]["id"] == "b"

    def test_sorts_freshest_first(self):
        from datetime import UTC, datetime
        today = datetime.now(UTC).date().isoformat()
        state = _state_with_drafts([
            {"id": "old", "status": "pending", "created_at": f"{today}T01:00:00Z", "event_id": "e1", "text": "older"},
            {"id": "new", "status": "pending", "created_at": f"{today}T05:00:00Z", "event_id": "e2", "text": "newer"},
            {"id": "mid", "status": "pending", "created_at": f"{today}T03:00:00Z", "event_id": "e3", "text": "mid"},
        ])
        pending = _collect_pending_today(state)
        assert [d["id"] for d in pending] == ["new", "mid", "old"]

    def test_returns_empty_when_drafts_missing(self):
        # State without drafts key — common in fresh test fixtures.
        assert _collect_pending_today({"memory": {}}) == []


class TestFormatBlocks:
    def test_pending_block_renders_type_score_and_preview(self):
        drafts = [
            {"type": "coral_bleaching", "score": {"total": 81}, "text": "Western Madagascar's reefs accumulated 10.2°C-weeks of thermal stress."},
            {"type": "fire", "score": {"total": 66}, "text": "A 426 MW fire in British Columbia."},
        ]
        block = _format_pending_block(drafts)
        assert "[coral_bleaching | score 81]" in block
        assert "Western Madagascar" in block
        assert "[fire | score 66]" in block

    def test_pending_block_handles_missing_score(self):
        drafts = [{"type": "fire", "text": "..."}]
        block = _format_pending_block(drafts)
        assert "[fire]" in block
        assert "score" not in block

    def test_pending_block_caps_at_limit(self):
        drafts = [{"type": "x", "text": str(i)} for i in range(30)]
        block = _format_pending_block(drafts, limit=5)
        assert block.count("\n") == 4  # 5 lines = 4 newlines

    def test_pending_block_empty_says_none(self):
        assert _format_pending_block([]) == "(none)"

    def test_shipped_block_renders_full_text(self):
        shipped = ["First tweet.", "Second tweet."]
        block = _format_shipped_block(shipped)
        assert "- First tweet." in block
        assert "- Second tweet." in block

    def test_shipped_block_skips_empty(self):
        # Defensive: shipped rows occasionally have empty tweet_text
        # (legacy memory format). Skip rather than render "- ".
        block = _format_shipped_block(["", "real one"])
        assert "real one" in block
        assert "- \n" not in block

    def test_shipped_block_empty_says_none(self):
        assert _format_shipped_block([]) == "(none)"


class TestCriticReview:
    def test_passes_when_gemini_returns_pass(self, mock_gemini):
        mock_gemini.return_value = '{"passed": true, "kill_reason": null}'
        result = critic.critic_review("test tweet", _bundle(), _state_with_drafts([]))
        assert result.passed is True
        assert result.kill_reason is None
        assert mock_gemini.called

    def test_kills_when_gemini_returns_kill(self, mock_gemini):
        mock_gemini.return_value = json.dumps({
            "passed": False,
            "kill_reason": "template_convergence: same shape as Fiji draft",
        })
        result = critic.critic_review("test tweet", _bundle(), _state_with_drafts([]))
        assert result.passed is False
        assert result.kill_reason == "template_convergence: same shape as Fiji draft"

    def test_raises_on_invalid_json(self, mock_gemini):
        mock_gemini.return_value = "definitely not json"
        with pytest.raises(ValueError):
            critic.critic_review("test tweet", _bundle(), _state_with_drafts([]))

    def test_uses_explicit_shipped_recent_when_provided(self, mock_gemini):
        mock_gemini.return_value = '{"passed": true, "kill_reason": null}'
        critic.critic_review(
            "test tweet",
            _bundle(),
            _state_with_drafts([]),
            shipped_recent=["explicit shipped"],
        )
        # Called once with positional args (draft, bundle, pending, shipped_recent)
        call_args = mock_gemini.call_args
        # _call_gemini(draft_text, bundle, pending_today, shipped_recent)
        shipped_arg = call_args.args[3]
        assert shipped_arg == ["explicit shipped"]

    def test_falls_back_to_state_memory_when_shipped_recent_none(self, mock_gemini):
        mock_gemini.return_value = '{"passed": true, "kill_reason": null}'
        state = _state_with_drafts([])
        state["memory"] = {"shipped_tweets": [
            {"tweet_text": "from memory"},
            {"tweet_text": "second"},
        ]}
        critic.critic_review("test tweet", _bundle(), state)
        shipped_arg = mock_gemini.call_args.args[3]
        assert "from memory" in shipped_arg
        assert "second" in shipped_arg


class TestCriticResultInvariants:
    def test_pass_with_kill_reason_raises(self):
        with pytest.raises(ValueError, match="kill_reason must be None"):
            CriticResult(passed=True, kill_reason="should not be here", raw_response="")

    def test_kill_without_reason_raises(self):
        with pytest.raises(ValueError, match="kill_reason required"):
            CriticResult(passed=False, kill_reason=None, raw_response="")

    def test_kill_with_empty_reason_raises(self):
        with pytest.raises(ValueError, match="kill_reason required"):
            CriticResult(passed=False, kill_reason="", raw_response="")

    def test_pass_with_no_reason_succeeds(self):
        result = CriticResult(passed=True, kill_reason=None, raw_response="ok")
        assert result.passed is True

    def test_kill_with_reason_succeeds(self):
        result = CriticResult(passed=False, kill_reason="boring", raw_response="ok")
        assert result.passed is False
        assert result.kill_reason == "boring"


class TestCriticGeminiTimeoutUnit:
    """Same regression guard as fact_check / writer / claim_extractor:
    google-genai HttpOptions.timeout is MILLISECONDS, not seconds. A
    bare timeout=90 would mean 90ms — every critic call would fail
    with ReadTimeout in <300ms and silently let drafts through with
    no critic gate. The 2026-05-08 4-day outage lesson applies here too.
    """

    def test_critic_timeout_is_in_milliseconds_range(self):
        import inspect
        import re
        source = inspect.getsource(critic._call_gemini)
        match = re.search(r"HttpOptions\([^)]*timeout=(\d+)", source)
        assert match is not None, "_call_gemini must configure HttpOptions(timeout=...)"
        timeout_value = int(match.group(1))
        assert timeout_value >= 5000, (
            f"Gemini critic timeout is {timeout_value} (ms). google-genai "
            f"HttpOptions.timeout is in MILLISECONDS — values <5000ms break "
            f"every call within ~300ms."
        )
