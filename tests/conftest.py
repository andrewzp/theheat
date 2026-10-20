"""Shared test fixtures, hermeticity gate, and the time-travel canary hook."""

import os
import socket
import time
from hashlib import sha256
from pathlib import Path
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


def pytest_addoption(parser):
    parser.addoption(
        "--ci-partition", choices=("all", "core", "postgres", "media"), default="all",
        help="Disjoint offline CI file partitions; ordinary local runs select all.",
    )
    parser.addoption(
        "--ci-postgres-shard", choices=("all", "0", "1", "2", "3", "4", "5", "6", "7"), default="all",
        help="Stable file shard within --ci-partition=postgres; all preserves the complete partition.",
    )


def _ci_postgres_shard(path):
    # Anchor to this repository, not the working directory or randomized hash().
    # Every parameter and test in a module shares its module-scoped fixtures.
    relative = path.resolve().relative_to(Path(__file__).resolve().parents[1]).as_posix()
    # Keep heavy modules whole while balancing measured CI work. Shards7 and0
    # hit the unchanged 35-minute job limit; other hash assignments stay stable.
    assigned = {
        "tests/test_postgres_published_media.py": "2",
        "tests/test_postgres_cost_projection.py": "5",
        "tests/test_postgres_important_native.py": "1",
        "tests/test_postgres_ghcn_generation.py": "5",
        "tests/test_postgres_platform_description.py": "6",
    }
    if relative in assigned:
        return assigned[relative]
    return str(int(sha256(relative.encode("utf-8")).hexdigest(), 16) % 8)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    partition = config.getoption("--ci-partition")
    shard = config.getoption("--ci-postgres-shard")
    if partition == "all":
        return
    selected, deselected = [], []
    for item in items:
        filename = item.path.name
        group = (
            "media" if filename.startswith("test_postgres_media") or filename == "test_viirs_native_package.py"
            else "postgres" if filename.startswith("test_postgres_")
            else "core"
        )
        keep = group == partition and (group != "postgres" or shard == "all" or _ci_postgres_shard(item.path) == shard)
        (selected if keep else deselected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)


def pytest_itemcollected(item):
    """Reject payload-sized display IDs before CI logs or subprocess environments.

    Large parameter values still belong in tests; give them short explicit IDs.
    Do not echo an offending payload while reporting this collection error.
    """
    if len(item.nodeid.encode("utf-8")) > 1024:
        name = item.nodeid.split("[", 1)[0][:180]
        raise pytest.UsageError(
            f"Test ID exceeds 1024 UTF-8 bytes ({name}). "
            "Use short explicit parametrization ids; preserve the full test inputs."
        )


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
    if config.getoption("--ci-postgres-shard") != "all" and config.getoption("--ci-partition") != "postgres":
        raise pytest.UsageError("A specific --ci-postgres-shard requires --ci-partition=postgres")
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
        # Calendar shifts must not change elapsed-time coordinates shared with
        # credentialless children. Their OS monotonic clocks do not time-travel.
        elapsed_clocks = {name: getattr(time, name) for name in (
            "monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns",
        )}
        freezer = freeze_time(target, tick=True)
        freezer.start()
        for name, clock in elapsed_clocks.items():
            setattr(time, name, clock)
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


@pytest.fixture
def automatic_publication_release(monkeypatch):
    """Existing mocked posting scenarios exercise an explicit offline release.

    Containment tests deliberately remove/override these values to prove default
    pause and failure behavior. This fixture does not enable production.
    """
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "offline-test-release")


@pytest.fixture
def synthetic_bundle_provenance(monkeypatch):
    """Give routing/cap unit tests explicit synthetic source identity.

    Those tests exercise orchestration after evidence readiness. The unmodified
    source-builder migration matrix and strict-boundary tests separately assert
    that real legacy packets without provenance are withheld. This fixture is
    opt-in and never changes a production adapter or its scientific evidence.
    """
    from src.two_bot.types import StoryBundle

    original = StoryBundle.__post_init__

    def with_fixture_source(bundle):
        original(bundle)
        if isinstance(bundle.raw_signal_dump, dict):
            bundle.raw_signal_dump = {**bundle.raw_signal_dump, "source_product": "synthetic-orchestration-fixture"}

    monkeypatch.setattr(StoryBundle, "__post_init__", with_fixture_source)
