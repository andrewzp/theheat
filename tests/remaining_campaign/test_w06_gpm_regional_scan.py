"""W06.2: the bounded regional rainfall scan on the real GPM runner (default off).

Invented watchlist, fake provider call, network trapped. THEHEAT_RAINFALL_REGIONAL_SCAN
must be exactly "1"; off, the runner's call and run record are today's.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date
import io

import pytest

from src.data import rainfall_supply as rs
from src.data.gpm_imerg import CityPrecipReading
from src.data.source_status import SourceFetchError
from src.orchestrator.sources import gpm_imerg as gpm_runner
from src.state import DEFAULT_STATE
from tests.live_content_harness import trap_network

CITIES = [{"city": f"Ficta {i}", "country": "Fictonia", "lat": str(10 + i), "lon": "20.5"} for i in range(5)]


@pytest.fixture
def gpm(monkeypatch):
    trap_network(monkeypatch.setattr)
    monkeypatch.delenv(gpm_runner.SCAN_FLAG, raising=False)
    monkeypatch.setenv("GPM_IMERG_MAX_CITIES", "2")
    calls: list[list[str]] = []
    failures: list[BaseException] = []

    def fetch(*, cities, max_cities, max_workers, trace, **_k):
        calls.append([c["city"] for c in cities])
        if failures:
            raise failures.pop(0)
        first = cities[0]
        return [CityPrecipReading(city=first["city"], country=first["country"], lat=float(first["lat"]),
                                  lon=float(first["lon"]), date="2026-10-28", mm_total=3.0, source_product="late",
                                  event_id=f"gpm_imerg_invented_{first['city']}")]
    monkeypatch.setattr(gpm_runner.gpm_imerg, "fetch_daily_precip", fetch)

    def run(state, cities=CITIES, at="2026-10-29T06:00:00Z"):
        record = {"id": "invented-run", "started_at": at, "sources": []}
        with redirect_stdout(io.StringIO()):
            gpm_runner.run_gpm_imerg(state, record, cities)
        state.setdefault("run_history", []).insert(0, record)  # as the bot retains its runs
        return record["sources"][0]
    run.calls, run.failures = calls, failures  # type: ignore[attr-defined]
    return run


def test_flag_off_keeps_the_single_call_and_the_run_record(gpm):
    state = deepcopy(DEFAULT_STATE)
    row = gpm(state)
    assert gpm.calls == [[c["city"] for c in CITIES]] and set(row["details"]) == {"rainfall_opportunity"}


def test_scan_rotates_blocks_checkpoints_in_retained_runs_and_failures_advance(gpm, monkeypatch):
    monkeypatch.setenv(gpm_runner.SCAN_FLAG, "1")
    state = deepcopy(DEFAULT_STATE)
    first = gpm(state, at="2026-10-26T06:00:00Z")["details"]["rainfall_scan"]
    gpm.failures.append(SourceFetchError("invented provider failure"))
    failed = gpm(state, at="2026-10-27T06:00:00Z")
    third = gpm(state, at="2026-10-28T06:00:00Z")["details"]["rainfall_scan"]
    wrapped = gpm(state, at="2026-10-29T06:00:00Z")["details"]["rainfall_scan"]
    # One existing provider call per run; the cursor's block leads the capped per-city legs.
    assert [c[:2] for c in gpm.calls] == [["Ficta 0", "Ficta 1"], ["Ficta 2", "Ficta 3"], ["Ficta 4", "Ficta 0"],
                                          ["Ficta 0", "Ficta 1"]]
    assert all(sorted(c) == sorted(x["city"] for x in CITIES) for c in gpm.calls)  # grids still see everyone
    assert (first["cursor"], first["next_cursor"], first["universe"]) == (0, 1, 3)
    assert failed["status"] == "failed" and failed["details"]["rainfall_scan"]["attempts"][0]["outcome"] == "failed"
    assert failed["details"]["rainfall_scan"]["next_cursor"] == 2  # a failed region cannot hold the cursor
    assert (third["cursor"], wrapped["cursor"]) == (2, 0)
    rows = {r["region"][:9]: r["outcome"] for r in rs.readiness(state["run_history"])}
    assert rows == {"block-001": "qualified", "block-002": "failed", "block-003": "qualified"}
    names, _ = gpm_runner.scan_blocks(CITIES, 2)
    assert rs.revisit_ages(state["run_history"], "gpm_imerg", names, today=date(2026, 10, 30)) == {
        names[0]: 1, names[1]: 3, names[2]: 2}


def test_a_changed_watchlist_is_a_new_region_set_and_skips_stay_skips(gpm, monkeypatch):
    monkeypatch.setenv(gpm_runner.SCAN_FLAG, "1")
    state = deepcopy(DEFAULT_STATE)
    gpm(state)
    assert gpm(state, cities=CITIES[:4])["details"]["rainfall_scan"]["cursor"] == 0
    from src.data.source_status import SourceSkipped
    gpm.failures.append(SourceSkipped("invented: no Earthdata token"))
    skipped = gpm(state)
    assert skipped["status"] == "skipped"
    assert skipped["details"]["rainfall_scan"]["attempts"][0]["failure_class"] == "SourceSkipped"
