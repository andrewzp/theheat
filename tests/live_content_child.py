"""Fresh-process bootstrap for the live-content CLI journeys (test-only).

Usage: ``python -m tests.live_content_child CONFIG.json`` from the checkout. It runs
ONE actual ``python -m src.main <mode>`` at a frozen, ticking instant behind the
named fake boundaries in ``tests.live_content_harness`` (invented Open-Meteo,
Gist and X over requests' transport adapter, the Anthropic/Gemini SDK client
factories, refused raw sockets) and records what crossed them.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import runpy
import sys


def _setattr(owner, name, value) -> None:
    setattr(owner, name, value)


def main(config_path: str) -> None:
    config = json.loads(Path(config_path).read_text())
    root, record_path = Path(config["dir"]), Path(config["record"])
    from tests.live_content_harness import ModelScript, Transport

    gist_dir = root / "gist"
    transport = Transport(forecasts=config.get("forecasts", {}),
                          gist={p.name: p.read_text() for p in sorted(gist_dir.iterdir())},
                          x_failure=config.get("x_failure"), day_shift=config.get("day_shift", 0),
                          air_quality=config.get("air_quality", {}), air_quality_after=config.get("air_quality_after"),
                          aq_switch_after=config.get("aq_switch_after"), aq_failure=config.get("aq_failure"),
                          now=lambda: datetime.now().astimezone())
    transport.install(_setattr)
    script = ModelScript(**config.get("models", {}))
    script.install(_setattr)

    from src.data import open_meteo
    if config.get("cities_csv"):
        open_meteo.load_cities.__defaults__ = (config["cities_csv"],)
    if config.get("normals_csv"):
        open_meteo.load_normals.__defaults__ = (config["normals_csv"],)
    import time
    time.sleep = lambda _seconds: None  # Offline transport: retries never need wall-clock backoff.
    from src.data import air_quality
    _setattr(air_quality, "_pacing_sleep", lambda _seconds: None)

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
                "exit": code, "http": transport.calls, "x": transport.x_posts, "gist_patches": transport.gist_patches,
                "aq_calls": transport.aq_calls,
                "models": script.stages(),
                "writer_requests": [request for stage, request in script.requests if stage == "writer"],
            }, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
