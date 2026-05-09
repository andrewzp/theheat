"""Shared test fixtures and hermeticity gate."""

import socket
from copy import deepcopy
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Hermeticity gate
#
# Tests must mock the network layer (requests.get, httpx, etc.). Real outbound
# connections are blocked at socket.connect() so a test can't silently
# depend on live API responses — the kind of bug that produced workflow
# failure 25589736260 (3 tests in test_main.py over-fired _try_two_bot_draft
# because real NWS / drought / ocean data leaked through unmocked branches).
#
# Localhost is allowed for tools that bind ephemeral ports (some HTTP test
# servers, sqlite over a unix-domain socket on rare paths).
#
# Opt out per-test with `@pytest.mark.allow_network` — but adding that
# marker is a code-review smell. Prefer mocking at the requests/httpx layer.
# ---------------------------------------------------------------------------

_real_socket_connect = socket.socket.connect


def _is_local(host) -> bool:
    if not isinstance(host, str):
        return False
    return host == "localhost" or host == "::1" or host.startswith("127.")


def _hermetic_connect(self, address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if _is_local(host):
        return _real_socket_connect(self, address, *args, **kwargs)
    raise RuntimeError(
        f"Test attempted real outbound socket connection to {address!r}. "
        f"Mock the network layer (e.g. patch('src.data.<module>.requests.get')) "
        f"or apply @pytest.mark.allow_network if a real connection is required."
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: opt out of the hermeticity gate and allow real outbound connections",
    )


@pytest.fixture(autouse=True)
def _hermetic_network(request):
    if "allow_network" in request.keywords:
        yield
        return
    with patch.object(socket.socket, "connect", _hermetic_connect):
        yield
