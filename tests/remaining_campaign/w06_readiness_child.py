"""Produce retained run history for the Sources readiness reader (W06.6). Offline; invented places.

Prints JSON ``{"run_history": [...]}``: one real GPM runner pass whose packet window is
incomplete (named hold), and two real bounded regional scans (``scan_regions``) retained
the way the W06.2 detail contract specifies.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import sys

from src.data import rainfall_supply as rs
from src.data.gpm_imerg import CityPrecipReading
from src.orchestrator.sources import gpm_imerg as gpm_runner
from src.state import DEFAULT_STATE

CITY = {"city": "Ficta", "country": "Fictonia", "lat": "10.5", "lon": "20.5"}


def gpm_run(patch, *, complete: bool) -> dict:
    """``patch`` is monkeypatch.setattr in tests and plain setattr in the child process."""
    from src.data import places

    reading = CityPrecipReading(city="Ficta", country="Fictonia", lat=10.5, lon=20.5, date="2026-10-28", mm_total=75.0,
                                source_product="late", event_id="gpm_imerg_invented_ficta_2026-10-28")
    patch(gpm_runner.gpm_imerg, "fetch_daily_precip", lambda **_k: [reading])
    if not complete:
        patch(rs, "window_evidence", lambda event, **_k: {"schema": rs.WINDOW_SCHEMA, "unit": "mm"})
    state = deepcopy(DEFAULT_STATE)
    key = "precip:late:" + places.event_location_key("Ficta", "Fictonia", 10.5, 20.5) + ":10-28"
    state["precip_daily_records"] = {key: {"mm": 40.0, "year": 2024}}
    run: dict = {"id": "invented-run-w06-sources", "started_at": "2026-10-29T06:00:00Z", "sources": []}
    with redirect_stdout(io.StringIO()):
        gpm_runner.run_gpm_imerg(state, run, [CITY])
    return run


def scans() -> list[dict]:
    regions = ["basin-fx-1", "basin-fx-2", "basin-fx-3"]

    def fetch(region):
        if region == "basin-fx-2":
            raise TimeoutError("invented")
        return {"outcome": "access_expired", "hold": "earthdata_renewal"} if region == "basin-fx-3" else {"readings": 4}
    first = rs.scan_regions(regions, fetch, cursor=0, max_regions=2, max_calls=5, deadline_s=60)
    second = rs.scan_regions(regions, fetch, cursor=first["next_cursor"], max_regions=2, max_calls=1, deadline_s=60)
    return [{"started_at": "2026-10-27T06:00:00Z", "sources": [{"source": "regional_rainfall", "status": "degraded",
                                                                "details": {"rainfall_scan": first}}]},
            {"started_at": "2026-10-28T06:00:00Z", "sources": [{"source": "regional_rainfall", "status": "degraded",
                                                                "details": {"rainfall_scan": second}}]}]


if __name__ == "__main__":
    import socket

    def refuse(*_a, **_k):
        raise AssertionError("external connection trapped")
    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.getaddrinfo = refuse
    mode = sys.argv[1] if len(sys.argv) > 1 else "held"
    history = [gpm_run(setattr, complete=mode != "held"), *reversed(scans())]
    print(json.dumps({"run_history": history}, default=str))
