"""Shared fixtures and helpers for two-bot pipeline tests."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.data.firms import FireEvent
from tests.fire_source_fixtures import fire_event
from src.state import DEFAULT_STATE
from src.two_bot.types import FactCheckResult, MemorySlice, StoryBundle, WriterResult


@pytest.fixture
def configured_pipeline_providers(monkeypatch):
    """Dummy presence for orchestration fixtures; all model calls stay mocked.

    Missing/invalid provider prerequisites are tested separately against the real
    preflight. These values grant no access and never opt out of network barriers.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "offline-fixture-no-provider-access")


def _bundle(
    *,
    country: str = "ML",
    region: str = "Mali",
    event_id: str = "fire_test",
    frp: float = 361.0,
    confidence: int = 95,
) -> StoryBundle:
    from src.two_bot.intern.fire import build_fire_bundle
    bundle = build_fire_bundle(fire_event(country=country, region=region, frp=frp, confidence=confidence))
    if event_id != "fire_test":
        # Explicit overrides support memory/invalid-identity tests; they are not
        # qualified generation packets and must fail when offered to a writer.
        bundle.event_id = event_id
        bundle.raw_signal_dump["event_id"] = event_id
    return bundle



def _memory() -> MemorySlice:
    return MemorySlice(
        recent_tweets_same_country=[],
        ongoing_event=None,
        used_era_anchors=[],
        used_peer_comparisons=[],
        used_framings=[],
        shipped_tweet_texts=[],
    )


def _fire_event(
    *, country: str = "ML", region: str = "Mali", frp: float = 361.0,
    confidence: int = 95, lat: float = 13.5, lon: float = -4.2,
) -> FireEvent:
    return fire_event(country=country, region=region, frp=frp, confidence=confidence, lat=lat, lon=lon)



def _empty_memory_state() -> dict:
    state = deepcopy(DEFAULT_STATE)
    state["memory"] = {
        "ongoing_events": [],
        "used_era_anchors": [],
        "used_peer_comparisons": [],
        "used_framings": [],
        "shipped_tweets": [],
    }
    return state


def _state_with_memory(
    *,
    ongoing_events: list[dict] | None = None,
    used_era_anchors: list[str] | None = None,
    used_peer_comparisons: list[str] | None = None,
    used_framings: list[str] | None = None,
    shipped_tweets: list[dict] | None = None,
) -> dict:
    state = _empty_memory_state()
    state["memory"].update(
        {
            "ongoing_events": ongoing_events or [],
            "used_era_anchors": used_era_anchors or [],
            "used_peer_comparisons": used_peer_comparisons or [],
            "used_framings": used_framings or [],
            "shipped_tweets": shipped_tweets or [],
        }
    )
    return state


def _state_with_shipped_tweets(rows: list[tuple[str, str]]) -> dict:
    now = datetime.now(UTC)
    shipped = []
    for idx, (tweet_text, country) in enumerate(rows):
        shipped.append(
            {
                "tweet_text": tweet_text,
                "signal_kind": "fire",
                "event_id": f"event_{idx}",
                "country": country,
                "shipped_at": (now - timedelta(days=idx)).isoformat().replace("+00:00", "Z"),
            }
        )
    return _state_with_memory(shipped_tweets=shipped)


def _fake_writer_response(payload: dict) -> str:
    return json.dumps(payload)


def _fake_writer_response_raw(raw: str) -> str:
    return raw


def _fake_fact_check_response(passed: bool = True, failures: list | None = None) -> str:
    return json.dumps({"passed": passed, "failures": failures or []})


@pytest.fixture
def mock_anthropic(monkeypatch):
    from src.two_bot import writer

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock = MagicMock()
    monkeypatch.setattr(writer, "_call_anthropic", mock)
    return mock


@pytest.fixture
def mock_writer(monkeypatch):
    from src.two_bot import pipeline

    mock = MagicMock()
    monkeypatch.setattr(pipeline.writer, "write_tweet", mock)
    return mock


@pytest.fixture
def mock_extract():
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_fact_check(monkeypatch):
    from src.two_bot import pipeline

    mock = MagicMock()
    monkeypatch.setattr(pipeline.fact_check, "fact_check", mock)
    return mock


@pytest.fixture
def mock_safety(monkeypatch):
    """Patch the in-pipeline safety call. Default: passes.

    Existing pipeline tests don't need this — their writer outputs are
    clean and don't trip BANNED_PATTERNS. Use this fixture to force a
    safety rejection: ``mock_safety.return_value = (False, 'reason')``.
    """
    from src.two_bot import pipeline

    mock = MagicMock(return_value=(True, None))
    monkeypatch.setattr(pipeline, "run_safety_pipeline", mock)
    return mock


@pytest.fixture
def mock_critic(monkeypatch):
    """Patch the in-pipeline critic call. Default: passes.

    NOT autouse — tests that exercise generate_draft / generate_fire_draft
    need to take this fixture explicitly. ``test_pipeline.py`` makes it
    autouse at the module scope so its pre-existing tests stay green
    without per-test edits; ``test_critic.py`` (which exercises the real
    critic_review function via a separately-mocked _call_gemini) does
    NOT pull this fixture in, so the real function runs.

    Override pattern:

        mock_critic.return_value = CriticResult(
            passed=False,
            kill_reason="template_convergence: same opener as Fiji",
            raw_response="...",
        )
    """
    from src.two_bot import pipeline
    from src.two_bot.types import CriticResult

    mock = MagicMock(return_value=CriticResult(
        passed=True, kill_reason=None, raw_response="default-pass"
    ))
    monkeypatch.setattr(pipeline.critic, "critic_review", mock)
    return mock


def _writer_result(tweet: str = "Mali fire test") -> WriterResult:
    return WriterResult(
        tweet=tweet,
        kill_reason=None,
        angle_chosen="plain_number",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning="test",
    )


def _passing_fact_check(extracted=None) -> FactCheckResult:
    return FactCheckResult(
        passed=True,
        failures=[],
        raw_response="ok",
        extracted_claims=extracted or [],
    )
