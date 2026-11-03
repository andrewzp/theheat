"""P16 offline fixtures: the real source runners and an explicit blocking transport.

Every byte is invented here. The transport replaces only the shared HTTP
session object (``src.data._http._session``); the real fetcher, its declared
call consumption, parser, freshness check and source runner all execute.
"""

from __future__ import annotations

from datetime import date, timedelta
import importlib
import threading

import requests


def co2_csv(*, ppm_before: float = 429.91, ppm_latest: float = 430.12) -> str:
    """Two invented recent Mauna Loa rows whose latest crosses a new integer ppm."""
    today = date.today()
    rows = ["# invented offline fixture; not NOAA data", "year,month,day,decimal,value"]
    for days_ago, ppm in ((2, ppm_before), (1, ppm_latest)):
        d = today - timedelta(days=days_ago)
        rows.append(f"{d.year},{d.month},{d.day},{d.year}.5,{ppm}")
    return "\n".join(rows) + "\n"


def response(url: str, body: str, status: int = 200, headers: dict | None = None) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.url = url
    resp._content = body.encode("utf-8")
    resp.encoding = "utf-8"
    resp.headers.update(headers or {})
    return resp


class BlockingTransport:
    """An offline session stand-in: GETs to ``hold`` URLs block until ``release``.

    A route is a body (200) or a list of ``(status, body, headers)`` answers
    served in order (the last one repeats).
    """

    def __init__(self, routes: dict, hold: set[str] | None = None):
        self.routes = routes
        self.hold = set(routes) if hold is None else set(hold)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()
        self.threads: list[threading.Thread] = []
        self.urls: list[str] = []
        self._served: dict[str, int] = {}

    def get(self, url, headers=None, timeout=None, **kwargs):
        if url not in self.routes:
            raise AssertionError(f"unexpected offline fixture URL {url}")
        self.threads.append(threading.current_thread())
        self.urls.append(url)
        if url in self.hold:
            self.entered.set()
            if not self.release.wait(10):
                raise AssertionError("fixture transport never released")
        try:
            route = self.routes[url]
            if isinstance(route, str):
                return response(url, route)
            index = self._served.get(url, 0)
            self._served[url] = index + 1
            status, body, extra = route[min(index, len(route) - 1)]
            return response(url, body, status, extra)
        finally:
            self.returned.set()

    def join(self, timeout: float = 10) -> None:
        for thread in self.threads:
            thread.join(timeout)
            assert not thread.is_alive(), "late worker did not finish"


class StopAfterConstruction(Exception):
    pass


def production_runners(monkeypatch, live: dict, run: dict) -> dict:
    """The exact SourceRunner objects run_alerts builds for ``live``/``run`` (concurrent mode)."""
    alerts = importlib.import_module("src.orchestrator.run_alerts")
    captured: dict = {}

    def capture(bot_state, current_run, *, serial_runners, concurrent_runners, synthesis_runner, **_):
        assert bot_state is live and current_run is run
        captured.update(serial=list(serial_runners), concurrent=list(concurrent_runners),
                        synthesis=synthesis_runner)
        raise StopAfterConstruction

    monkeypatch.setattr(alerts, "concurrent_sources_enabled", lambda: True)
    monkeypatch.setattr(alerts.open_meteo, "load_cities", lambda: [])
    monkeypatch.setattr(alerts, "run_stage1_then_synthesis", capture)
    try:
        alerts.run_alerts(live, current_run=run)
    except StopAfterConstruction:
        pass
    else:  # pragma: no cover - construction must reach the scheduler
        raise AssertionError("run_alerts did not reach the scheduler")
    return {runner.source: runner for runner in captured["serial"] + captured["concurrent"]} | {
        "__synthesis__": captured["synthesis"], "__serial__": [r.source for r in captured["serial"]],
        "__concurrent__": [r.source for r in captured["concurrent"]]}


def changed_keys(before: dict, after: dict) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k, "<absent>") != after.get(k, "<absent>"))


USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson"


def usgs_geojson(event_code: str = "inv0001") -> str:
    """One invented significant quake that passes the real score and evidence gates."""
    import json
    import time

    now = int(time.time() * 1000) - 3_600_000
    return json.dumps({"type": "FeatureCollection", "metadata": {"generated": now}, "features": [{
        "type": "Feature", "id": event_code,
        "properties": {"mag": 7.4, "place": "120 km S of Invented Bay", "time": now, "updated": now,
                       "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_code}",
                       "alert": "orange", "sig": 1100, "tsunami": 1,
                       "title": "M 7.4 - 120 km S of Invented Bay"},
        "geometry": {"type": "Point", "coordinates": [150.1, -10.2, 30.0]}}]})
