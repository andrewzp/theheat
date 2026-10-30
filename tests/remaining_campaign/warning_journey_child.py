"""Fresh-process bootstrap for the W04 automatic-warning CLI journey (test-only).

Usage: ``python -m tests.remaining_campaign.warning_journey_child CONFIG.json``. It runs
ONE actual ``python -m src.main <mode>`` at a frozen, ticking instant behind the named
fake boundaries of ``tests.live_content_harness`` (invented Open-Meteo, Gist and X over
requests' transport adapter, SDK-shaped model answers, refused raw sockets) plus the two
fixed NHC product URLs and, when the journey directory has ``nws/feed.json``, the fixed
NWS active-alerts feed, all served from the journey directory. The NHC adapter's credential-
free subprocess transport is replaced by its in-process implementation so no grandchild
can escape these traps. No network, model, Gist or X access.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import runpy
import sys

NHC_ORIGIN = "https://www.nhc.noaa.gov/"
NWS_ACTIVE = "https://api.weather.gov/alerts/active"


def _setattr(owner, name, value) -> None:
    setattr(owner, name, value)


def main(config_path: str) -> None:
    config = json.loads(Path(config_path).read_text())
    root, record_path = Path(config["dir"]), Path(config["record"])
    from tests.live_content_harness import ModelScript, Transport, _reply

    gist_dir = root / "gist"
    nhc: list[str] = []
    nws: list[str] = []
    pages = {"count": 0}

    class WarningTransport(Transport):
        def send(self, _adapter, request, **_options):
            url = request.url
            if url.startswith(NHC_ORIGIN):
                self.calls.append([request.method, url])
                nhc.append(url)
                if config.get("nhc_failure"):
                    import requests
                    raise requests.ConnectionError("invented NHC outage")
                if url.endswith("/CurrentStorms.json"):
                    return _reply(request, 200, (root / "nhc/index.json").read_bytes(),
                                  {"content-type": "application/json"})
                pages["count"] += 1
                switch = config.get("nhc_switch_after_pages")
                name = "nhc/page-corrected.html" if switch is not None and pages["count"] > switch else "nhc/page.html"
                return _reply(request, 200, (root / name).read_bytes(), {"content-type": "text/html"})
            if url.startswith(NWS_ACTIVE) and (root / "nws/feed.json").exists():
                self.calls.append([request.method, url])
                nws.append(url)
                return _reply(request, 200, (root / "nws/feed.json").read_bytes(),
                              {"content-type": "application/geo+json"})
            return super().send(_adapter, request, **_options)

    transport = WarningTransport(forecasts=config.get("forecasts", {}),
                                 gist={p.name: p.read_text() for p in sorted(gist_dir.iterdir())},
                                 x_failure=config.get("x_failure"), now=lambda: datetime.now().astimezone())
    transport.install(_setattr)
    script = ModelScript(**config.get("models", {}))
    script.install(_setattr)
    from src.data import nhc_advisory as nhc_source
    nhc_source._http_get = nhc_source._http_get_inprocess
    from src.data import open_meteo
    if config.get("cities_csv"):
        open_meteo.load_cities.__defaults__ = (config["cities_csv"],)
    if config.get("normals_csv"):
        open_meteo.load_normals.__defaults__ = (config["normals_csv"],)
    import time
    time.sleep = lambda _seconds: None  # Offline transport: retries never need wall-clock backoff.

    from freezegun import freeze_time
    sys.argv = ["src.main", *config["argv"]]
    code = 0
    with freeze_time(config["now"], tick=True):
        try:
            runpy.run_module("src.main", run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            code = exc.code if type(exc.code) is int else 1
        finally:
            for name, content in transport.gist.items():
                (gist_dir / name).write_text(content)
            record_path.write_text(json.dumps({
                "exit": code, "nhc": nhc, "nws": nws, "x": transport.x_posts, "gist_patches": transport.gist_patches,
                "models": script.stages()}, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
