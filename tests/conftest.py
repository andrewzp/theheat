"""Shared test fixtures."""

from copy import deepcopy

import pytest

from src.state import DEFAULT_STATE


@pytest.fixture
def fresh_state():
    return deepcopy(DEFAULT_STATE)


@pytest.fixture
def state_with_events():
    s = deepcopy(DEFAULT_STATE)
    s["posted_events"] = ["event_1", "event_2", "event_3"]
    s["daily_tweet_count"] = {}
    return s
