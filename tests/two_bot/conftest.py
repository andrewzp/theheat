"""Shared fixtures and helpers for two-bot pipeline tests."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.data.firms import FireEvent
from src.state import DEFAULT_STATE
from src.two_bot.types import FactCheckResult, MemorySlice, StoryBundle, WriterResult


def _bundle(
    *,
    country: str = "ML",
    region: str = "Mali",
    event_id: str = "fire_test",
    frp: float = 361.0,
    confidence: int = 95,
) -> StoryBundle:
    return StoryBundle(
        signal_kind="fire",
        where=region,
        when="2026-04-30",
        event_id=event_id,
        headline_metric={"label": "FRP", "value": frp, "unit": "MW"},
        current_facts=[
            {"label": "satellite_confidence", "value": confidence, "unit": "%"},
            {"label": "country", "value": country},
            {"label": "nearest_region", "value": region},
            {"label": "lat", "value": 13.5},
            {"label": "lon", "value": -4.2},
        ],
        historical_context={},
        raw_signal_dump={
            "lat": 13.5,
            "lon": -4.2,
            "confidence": confidence,
            "frp": frp,
            "nearest_city": region,
            "country": country,
            "event_id": event_id,
        },
    )


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
    *,
    event_id: str = "fire_test",
    country: str = "ML",
    region: str = "Mali",
    frp: float = 361.0,
    confidence: int = 95,
) -> FireEvent:
    return FireEvent(13.5, -4.2, confidence, frp, region, country, event_id)


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
def mock_extract(monkeypatch):
    from src.two_bot import pipeline

    mock = MagicMock()
    monkeypatch.setattr(pipeline.claim_extractor, "extract_claims", mock)
    return mock


@pytest.fixture
def mock_fact_check(monkeypatch):
    from src.two_bot import pipeline

    mock = MagicMock()
    monkeypatch.setattr(pipeline.fact_check, "fact_check", mock)
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

