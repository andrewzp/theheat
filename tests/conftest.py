"""Shared test fixtures, hermeticity gate, and the time-travel canary hook."""

import os
import json
import math
import re
import socket
import time
from collections import deque
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

# Exact targeted regressions, then the remaining stage-revision cases, run first
# in their existing CI shards. Both other cohorts retain their relative order;
# ordinary local collection is unchanged.
_CI_CRITICAL_NODEIDS = (
    "tests/test_postgres_stage_revision_checks.py::test_v2_outbox_tail_uses_original_critic_deadline_and_rolls_back_park[frame_expired]",
    "tests/test_postgres_stage_revision_checks.py::test_v2_outbox_tail_uses_original_critic_deadline_and_rolls_back_park[lease_expired]",
    "tests/test_postgres_stage_revision_checks.py::test_v2_outbox_tail_uses_original_critic_deadline_and_rolls_back_park[clock_backward]",
    "tests/test_postgres_stage_revision_checks.py::test_v2_ghcn_approval_final_bound_and_reauthorization_roll_back_all_writes[expiry-proof-compact_case0]",
    "tests/test_postgres_stage_revision_checks.py::test_catalog4_owner_atomic_idempotent_legacy_receipts_and_runtime_denial",
    "tests/test_postgres_stage_revision_checks.py::test_v2_genuine_park_one_use_delivery_and_passive_original_cap_cost",
    "tests/test_postgres_stage_revision_checks.py::test_v2_prefix_missing_corrupt_and_late_evidence_never_grants_readiness[modis]",
    "tests/test_postgres_stage_revision_checks.py::test_v2_restored_unattempted_cap_must_bind_the_exact_verified_predecessor[prefix-modis]",
    "tests/test_postgres_stage_revision_checks.py::test_v2_restored_unattempted_cap_must_bind_the_exact_verified_predecessor[before_completion-modis]",
    "tests/test_postgres_stage_revision_checks.py::test_v2_restored_unattempted_cap_must_bind_the_exact_verified_predecessor[at_predecessor_expiry-modis]",
    "tests/test_postgres_stage_revision_checks.py::test_v2_restored_unattempted_cap_must_bind_the_exact_verified_predecessor[future_start-modis]",
    "tests/test_postgres_temperature_delivery.py::test_genuine_compact_temperature_delivery_recovery_history_and_cost[compact_case0]",
    "tests/test_postgres_temperature_editor_media.py::test_compact_claim_native_review_checks_park_restore_and_invalidation[all_time_low]",
    "tests/test_postgres_temperature_editor_media.py::test_actual_authenticated_http_compact_claim_editor_journey[calendar_date_low]",
    "tests/test_postgres_temperature_editor_media.py::test_compact_claim_refusals_are_durable_typed_and_never_promote_after_drift[monthly_high]",
    "tests/test_postgres_preview_important_variants.py::test_actual_next_commands_select_exact_retained_alternate",
)


def pytest_addoption(parser):
    parser.addoption(
        "--ci-partition", choices=("all", "core", "postgres", "media"), default="all",
        help="Disjoint offline CI file partitions; ordinary local runs select all.",
    )
    parser.addoption(
        "--ci-postgres-shard", choices=("all", *(str(i) for i in range(12))), default="all",
        help="Stable file/function cohort within --ci-partition=postgres; all preserves the complete partition.",
    )
    parser.addoption(
        "--ci-critical-first", action="store_true", default=False,
        help="Run exact PostgreSQL CI regression cases first without changing shard membership.",
    )


_CI_STAGE_REVISION_SHARDS = {
    "test_actual_protocol2_seal_removed_between_begin_passes_rolls_back_before_attempt": "3",
    "test_catalog4_concurrent_owner_install_retains_single_chain": "7",
    "test_catalog4_every_installation_boundary_rolls_back": "6",
    "test_catalog4_never_adopts_unused_legacy_semantic_enrollment": "2",
    "test_catalog4_owner_atomic_idempotent_legacy_receipts_and_runtime_denial": "4",
    "test_catalog4_receipt_nested_numeric_metadata_is_byte_exact": "5",
    "test_catalog4_tamper_fails_closed_without_repair": "5",
    "test_frozen_previous_binary_refuses_catalog4_before_work": "7",
    "test_genuine_v2_chain_exceeds_first_cap_and_generic_status_never_certifies": "6",
    "test_predecessor_expiring_during_real_prefix_work_rolls_back_successor": "1",
    "test_same_owner_initial_cap_race_and_unused_cap_cannot_renew": "0",
    "test_same_owner_successor_cap_race_cannot_rotate_without_attempt": "7",
    "test_v2_completion_delay_rolls_back_critic_receipt_seal_keeps_raw_and_unknown_cost": "4",
    "test_v2_current_authority_drift_cannot_create_successor": "6",
    "test_v2_exact_reservation_request_and_stage_are_required_before_dispatch": "2",
    "test_v2_exact_terminal_replay_is_history_and_cannot_reseal_corruption": "3",
    "test_v2_explicit_sdk_original_raw_recovery_has_no_second_request": "5",
    "test_v2_first_cap_issuance_uses_postproof_clock_and_reuse_never_refreshes_it": "6",
    "test_v2_full_park_restore_keeps_legacy_sets_and_exact_protocol_chain": "4",
    "test_v2_genuine_park_one_use_delivery_and_passive_original_cap_cost": "4",
    "test_v2_ghcn_approval_final_bound_and_reauthorization_roll_back_all_writes": "1",
    "test_v2_modis_approval_final_bound_and_reauthorization_roll_back_all_writes": "9",
    "test_v2_nonpass_raw_is_terminal_and_cannot_rotate_or_resend": "0",
    "test_v2_outbox_tail_uses_original_critic_deadline_and_rolls_back_park": "3",
    "test_v2_prefix_missing_corrupt_and_late_evidence_never_grants_readiness": "0",
    "test_v2_published_frame_minimum_bounds_every_cap_and_final_readiness": "5",
    "test_v2_restored_unattempted_cap_must_bind_the_exact_verified_predecessor": "2",
    "test_v2_scope_is_connection_bound_and_untrusted_inputs_cannot_mint_cap": "3",
    "test_v2_strict_request_window_equality_and_one_microsecond": "1",
    "test_v2_transaction_interruptions_never_repurchase_or_repair_missing_seal": "10",
}

_CI_GHCN_FINAL_FAULT_SHARDS = {
    "expiry": "1",
    "source": "9",
    "editor": "3",
    "publisher": "7",
    "policy": "4",
}


def _ci_postgres_shard(path, test_name=None, parameters=None):
    # Anchor to this repository, not the working directory or randomized hash().
    # Keep modules whole except the stage-revision module's explicit function
    # cohorts. The larger GHCN final-approval family has explicit fault cohorts,
    # keeping each fault's proof/outbox pair together. All case DB/native scratch
    # is local; each destination owns a fresh cluster. No case is omitted.
    relative = path.resolve().relative_to(Path(__file__).resolve().parents[1]).as_posix()
    if relative == "tests/test_postgres_stage_revision_checks.py" and test_name in _CI_STAGE_REVISION_SHARDS:
        if test_name == "test_v2_ghcn_approval_final_bound_and_reauthorization_roll_back_all_writes" and parameters is not None:
            return _CI_GHCN_FINAL_FAULT_SHARDS.get(parameters.get("fault"), _CI_STAGE_REVISION_SHARDS[test_name])
        return _CI_STAGE_REVISION_SHARDS[test_name]
    # Keep heavy modules whole while balancing measured CI work. Shards7 and0
    # hit the unchanged 35-minute job limit. Shard8 isolates temperature editing;
    # shards9/10 own complete heavy stage functions, and11 owns editor media.
    # Existing groups and all other modulo8 defaults remain unchanged.
    assigned = {
        "tests/test_postgres_published_media.py": "2",
        "tests/test_postgres_cost_projection.py": "5",
        "tests/test_postgres_important_native.py": "1",
        "tests/test_postgres_ghcn_generation.py": "5",
        "tests/test_postgres_platform_description.py": "6",
        "tests/test_postgres_temperature_editor_media.py": "8",
        "tests/test_postgres_temperature_delivery.py": "0",
        "tests/test_postgres_editor_media.py": "11",
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
        keep = group == partition and (
            group != "postgres" or shard == "all"
            or _ci_postgres_shard(item.path, getattr(item, "originalname", None),
                                  getattr(getattr(item, "callspec", None), "params", None)) == shard
        )
        (selected if keep else deselected).append(item)
    items[:] = selected
    if partition == "postgres" and config.getoption("--ci-critical-first"):
        priority = {nodeid: index for index, nodeid in enumerate(_CI_CRITICAL_NODEIDS)}
        items.sort(key=lambda item: priority.get(item.nodeid, len(priority) + (
            item.path.name != "test_postgres_stage_revision_checks.py")))
    config.hook.pytest_deselected(items=deselected)


def _last_check_windows(path):
    """Only eight whitelisted fixture rows from at most 64 KiB of trace tail.

    These are the worker's actual internal clock values, not CI wall timestamps.
    Other trace rows can contain retained text and must never enter this report.
    """
    with Path(path).open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        offset = max(0, size - 65_536)
        stream.seek(offset)
        raw = stream.read(65_536)
    if offset:
        raw = raw.partition(b"\n")[2]
    rows: deque[dict] = deque(maxlen=8)
    timestamp = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
    fields = ("now", "lease_expires_at", "useful_until", "lease_remaining_seconds", "available", "operation", "fault")
    for line in raw.splitlines():
        try:
            row = json.loads(line)
            if (type(row) is not dict or row.get("kind") != "check_window"
                    or not all(key in row for key in fields)
                    or row["operation"] not in ("deterministic", "safety", "fact_check", "critic")
                    or row["fault"] not in ("", "postgrant_baseline")
                    or type(row["available"]) is not bool
                    or type(row["lease_remaining_seconds"]) not in (int, float)
                    or not math.isfinite(row["lease_remaining_seconds"])
                    or not all(type(row[key]) is str and timestamp.fullmatch(row[key])
                               for key in ("now", "lease_expires_at", "useful_until"))):
                continue
            rows.append({key: row[key] for key in fields})
        except (ValueError, TypeError, OverflowError, RecursionError):
            continue
    return list(rows)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if (not report.failed or item.path.name not in {
            "test_postgres_temperature_delivery.py", "test_postgres_temperature_editor_media.py"}):
        return
    # Only the invented fixture's own trace, never its configuration file.
    try:
        case = item.funcargs["compact_case"]
        trace = Path(case["config"]["trace"])
        if trace.parent.resolve() != item.funcargs["tmp_path"].resolve():
            return
        rows = _last_check_windows(trace)
        text = json.dumps(rows, sort_keys=True, allow_nan=False) if rows else "No valid retained check_window rows available."
    except (KeyError, TypeError, ValueError, OSError, AttributeError):
        text = "Retained check_window diagnostics unavailable."
    report.sections.append(("Last check windows (up to 8 rows / 64 KiB tail)", text))


@pytest.hookimpl(hookwrapper=True, specname="pytest_runtest_makereport")
def pytest_delivery_refusal_report(item, call):
    outcome = yield
    from tests.t4_delivery_diagnostics import append_failure_section
    append_failure_section(item, outcome.get_result())


@pytest.hookimpl(hookwrapper=True, specname="pytest_runtest_makereport")
def pytest_delivery_fixture_receipt_report(item, call):
    outcome = yield
    from tests.t4_delivery_diagnostics import append_fixture_failure_section
    append_fixture_failure_section(item, outcome.get_result())


@pytest.fixture(autouse=True)
def _t4_fixture_receipt_observer(request):
    if request.node.path.name != "test_postgres_temperature_delivery.py":
        yield None
        return
    from tests import test_postgres_delivery as owner
    from tests.t4_delivery_diagnostics import observe_fixture_server
    with observe_fixture_server(owner) as capture:
        yield capture


@pytest.hookimpl(hookwrapper=True, specname="pytest_runtest_makereport")
def pytest_delivery_budget_report(item, call):
    outcome = yield
    from tests.t4_delivery_diagnostics import append_budget_failure_section
    from tests.t4_grant_diagnostics import append_failure_section
    report = outcome.get_result()
    append_budget_failure_section(item, report)
    append_failure_section(item, report)


# PG2 process-death phase witness: only the exact parked-media node writes
# fixed lines to real stderr; every other item and phase is untouched. Its
# fixture boundaries come from a plugin registered for that node's protocol.
@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    from tests.parked_media_phase_witness import selected_protocol
    with selected_protocol(item):
        return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item):
    from tests.parked_media_phase_witness import pytest_phase
    with pytest_phase(item, "setup"):
        return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_call(item):
    from tests.parked_media_phase_witness import pytest_phase
    with pytest_phase(item, "call"):
        return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    from tests.parked_media_phase_witness import pytest_phase
    with pytest_phase(item, "teardown"):
        return (yield)


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
    config.addinivalue_line(
        "markers", "revision_check_protocol(version): explicit historical saved-revision protocol1 fixture",
    )
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
