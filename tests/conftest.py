"""Shared test fixtures, hermeticity gate, and the time-travel canary hook."""

import os
import socket
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.state import DEFAULT_STATE

# ---------------------------------------------------------------------------
# Time-travel canary
#
# A calendar time bomb is a test that passes today and fails at today+N — a
# hardcoded date rotting past a freshness window (the class that broke main
# CI on 2026-07-03: the CO2 last-good fixture aged past its 21-day window,
# fixed in #356). Static grepping for the pattern false-positives wildly —
# hundreds of hardcoded test dates are fine because they are compared against
# other fixed dates — so the guard is BEHAVIORAL: the time-travel-canary
# workflow runs this whole suite with the clock shifted forward. Any test
# that would rot within the horizon fails THERE first, weeks before it
# detonates on main.
#
# Activate with THEHEAT_TIME_TRAVEL_DAYS=<int>. The freeze starts in
# pytest_configure so module-level `date.today()` fixture computations are
# shifted too; tick=True keeps time flowing from the shifted point so
# timeout/backoff logic behaves normally.
# ---------------------------------------------------------------------------

_TIME_TRAVEL_ENV = "THEHEAT_TIME_TRAVEL_DAYS"


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
    config.addinivalue_line(
        "markers",
        "real_backoff: opt out of the no-op backoff fixture and run real retry sleeps",
    )
    days_raw = os.environ.get(_TIME_TRAVEL_ENV, "")
    if days_raw:
        from freezegun import freeze_time

        target = datetime.now(timezone.utc) + timedelta(days=int(days_raw))
        freezer = freeze_time(target, tick=True)
        freezer.start()
        config._theheat_time_travel_freezer = freezer
        print(f"[time-travel] clock shifted +{days_raw}d to {target.isoformat()}")


def pytest_unconfigure(config):
    freezer = getattr(config, "_theheat_time_travel_freezer", None)
    if freezer is not None:
        freezer.stop()


@pytest.fixture(autouse=True)
def _hermetic_network(request):
    if "allow_network" in request.keywords:
        yield
        return
    with patch.object(socket.socket, "connect", _hermetic_connect):
        yield


@pytest.fixture(autouse=True)
def _fast_retry_backoff(request):
    """No-op fetch_with_retry's exponential backoff so the suite isn't dominated by
    real waits — ~85% of runtime was 7 tests doing _http retry backoff (1+2s each).
    Retry *behavior* is asserted via request/call counts, not sleep duration, so
    this is zero coverage loss.

    Patches the specific ``_sleep_before_retry`` helper, NOT ``time.sleep`` — the
    latter is the shared global ``time`` module singleton, so no-oping it would
    silently break tests that use their own ``time.sleep`` for worker timing (e.g.
    the gpm fan-out cancellation race). Opt out with @pytest.mark.real_backoff.
    """
    if "real_backoff" in request.keywords:
        yield
        return
    with patch("src.data._http._sleep_before_retry"):
        yield
