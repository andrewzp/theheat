"""W06 compatibility: canonical identities before checkpointing, flag stays off.

This file proves helper selection/cursor behavior, not physical HTTP send counts;
the new grid journey separately counts actual HTTPAdapter sends.
"""
from copy import deepcopy

import pytest

from src.data import gpm_imerg as gpm
from src.orchestrator.sources import gpm_imerg as source


def run_scan(monkeypatch, cities, *, history=(), max_cities=75):
    selected = []
    def fetch(**options):
        rows = gpm._network_watchlist(options["cities"], options["max_cities"],
                                     selection=options["network_selection"])
        selected.append([gpm.places.event_location_key(row["city"], row["country"], row["lat"], row["lon"]) for row in rows])
        return []
    monkeypatch.setattr(gpm, "fetch_daily_precip", fetch)
    scan: dict = {}
    assert source._scanned_fetch({"run_history": list(history)}, cities, max_cities=max_cities,
                                 max_workers=1, trace=None, scan=scan) == []
    assert len(selected) == 1 and len(selected[0]) <= 75
    return scan, selected[0]


def history(scan):
    return [{"started_at": "2026-11-16T17:00:00Z", "sources": [
        {"source": "gpm_imerg", "details": {"rainfall_scan": deepcopy(scan)}}]}]


def test_csv_reordering_preserves_blocks_and_persisted_cursor_after_restart(monkeypatch):
    rows = gpm.load_cities()
    first, picked = run_scan(monkeypatch, rows)
    assert first["cursor"] == 0 and first["next_cursor"] == 1
    second, next_picked = run_scan(monkeypatch, list(reversed(rows)), history=history(first))
    assert second["region_set_sha256"] == first["region_set_sha256"]
    assert second["cursor"] == 1 and second["next_cursor"] == 2
    assert not set(picked) & set(next_picked)
    equivalent, same = run_scan(monkeypatch, rows, history=history(first))
    assert equivalent["region_set_sha256"] == second["region_set_sha256"] and same == next_picked


def test_numeric_representation_duplicates_and_bad_rows_cannot_change_checkpoint_identity(monkeypatch):
    rows = gpm.load_cities()
    first, picked = run_scan(monkeypatch, rows)
    variants = [dict(row, lat=float(row["lat"]), lon=float(row["lon"])) for row in reversed(rows)]
    variants += [deepcopy(variants[0]), {}, dict(variants[0], lat=True), dict(variants[0], lon=999)]
    second, next_picked = run_scan(monkeypatch, variants)
    assert second["region_set_sha256"] == first["region_set_sha256"] and next_picked == picked


def test_actual_population_change_starts_a_new_bounded_region_set(monkeypatch):
    rows = gpm.load_cities()
    first, _picked = run_scan(monkeypatch, rows)
    second, _next = run_scan(monkeypatch, rows[:-1], history=history(first))
    assert second["region_set_sha256"] != first["region_set_sha256"] and second["cursor"] == 0


@pytest.mark.parametrize("limit", [1, 74, 75, 76, 200])
def test_network_selection_keeps_original_75_point_hard_bound(monkeypatch, limit):
    _scan, selected = run_scan(monkeypatch, gpm.load_cities(), max_cities=limit)
    assert len(selected) == min(limit, 75)
