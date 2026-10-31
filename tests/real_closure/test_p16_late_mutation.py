"""P16 — an expired source worker's in-flight response cannot mutate shared state.

Red-first on released .51: the production ``co2`` SourceRunner (built by
``run_alerts``) closes over the live ``bot_state``/``current_run``; after its
deadline the scheduler cancels its token and records the timeout, yet the
response already in flight returns into ``run_co2`` and writes last-good,
source health, candidate log and the triage queue after the deadline.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, cast

import pytest

from src.data import _http, co2 as co2_data
from src.orchestrator import scheduler, suppression
from src.state import _fresh_state
from src.two_bot import call_inventory as inv
from tests import live_content_harness as h
from tests.real_closure import p16_fixtures as fx


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.trap_network(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_FUNNEL_TELEMETRY", "1")
    monkeypatch.setattr(co2_data, "_CO2_REVALIDATION_CACHE", {})
    monkeypatch.setattr(inv, "_CANCELLED", {})
    yield
    suppression._clear_suppression_ctx()


ROUTES: dict[str, tuple[str, Callable[[], Any]]] = {"co2": (co2_data.CO2_URL, fx.co2_csv), "usgs_quakes": (fx.USGS_URL, fx.usgs_geojson)}


@pytest.mark.parametrize("source", ["co2", "usgs_quakes"])
def test_expired_production_runner_cannot_mutate_shared_state_after_its_deadline(monkeypatch, source):
    """co2: last-good, evidence-contract suppression and funnel kill; usgs_quakes: queue admission."""
    live: dict = cast(dict, _fresh_state())
    run: dict = {"id": "run_p16_red", "sources": []}
    runners = fx.production_runners(monkeypatch, live, run)
    url, body = ROUTES[source]
    transport = fx.BlockingTransport({url: body()})
    monkeypatch.setattr(_http, "_session", transport)
    calls_before = inv.runtime_counts().get("source_http_get", 0)
    before_state, before_run = deepcopy(live), deepcopy(run)

    scheduler.run_stage1_sources(cast(Any, live), run, serial_runners=[], concurrent_runners=[runners[source]],
                                 budget_seconds=0.2)

    # Allowed: the main thread's timeout record, nothing else.
    assert transport.entered.is_set() and not transport.returned.is_set()
    assert fx.changed_keys(before_state, live) == ["source_health"]
    assert [row["source"] for row in run["sources"][len(before_run["sources"]):]] == [source]
    timeout_row = run["sources"][-1]
    assert timeout_row["status"] == "failed" and timeout_row["error_class"] == "timeout"
    assert live["source_health"][source]["runs"][-1]["error_class"] == "timeout"
    after_timeout_state, after_timeout_run = deepcopy(live), deepcopy(run)

    transport.release.set()  # the in-flight response now returns into the real source function
    transport.join()

    assert fx.changed_keys(after_timeout_state, live) == []
    assert fx.changed_keys(after_timeout_run, run) == []
    assert "_triage_queue" not in live
    assert live["_funnel_sink"] == after_timeout_state["_funnel_sink"]
    # Exactly the one in-flight request was bought; nothing after the deadline.
    assert inv.runtime_counts()["source_http_get"] == calls_before + 1
