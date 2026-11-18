"""Invented input, real nomination/queue/telemetry/zero-eliding durable serializer.

Invoked by the Node regression; external connects/resolution are trapped before
source imports. No source fetch, SDK, drain, state persistence or sender runs.
"""

from datetime import UTC, datetime
import json
import socket
import time
import os
import sys
from unittest.mock import patch
from typing import Any, cast
from freezegun import freeze_time


def forbidden(*a, **k):
    raise AssertionError("No fixture network")


patch.object(socket.socket, "connect", forbidden).start()
patch.object(socket, "create_connection", forbidden).start()
patch.object(socket, "getaddrinfo", forbidden).start()
from src.state import BotState
from src.data import gpm_imerg as gpm, places
from src.orchestrator.sources import gpm_imerg as source
from src.orchestrator.telemetry import _record_source_run

NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)
os.environ.update(
    THEHEAT_GPM_OBSERVED_REPORT="1",
    THEHEAT_OBSERVED_WEATHER_ONLY="1",
    THEHEAT_AUTOMATIC_PUBLICATION_ENABLED="1",
    THEHEAT_AUTOMATIC_PUBLICATION_EPOCH="invented-rainfall-epoch",
    THEHEAT_AUTOSHIP_ON_CRITIC_PASS="1",
    THEHEAT_MAX_DRAFTS_PER_CYCLE="1",
    THEHEAT_WRITER_SAMPLES="1",
    THEHEAT_CRITIC_ENABLED="1",
    THEHEAT_CRITIC_REVISE_ENABLED="0",
    THEHEAT_REFILL_ENABLED="0",
    THEHEAT_PRODUCTION_PAUSED="0",
)
point = next(x for x in gpm.load_cities() if x["city"] == "Paris" and x["country"] == "France")
key = places.event_location_key(point["city"], point["country"], point["lat"], point["lon"])


def reading(mm):
    return gpm.CityPrecipReading(
        point["city"],
        point["country"],
        float(point["lat"]),
        float(point["lon"]),
        "2026-11-15",
        mm,
        "late",
        f"gpm_imerg_{key}_2026-11-15",
    )


out: dict[str, Any] = {}
for name, readings in {"empty": [], "range": [reading(20)], "queued": [reading(180.5)]}.items():
    state: BotState = {}
    run = {
        "id": "invented-durable-" + name,
        "started_at": "2026-11-16T16:59:00Z",
        "ended_at": "2026-11-16T17:01:00Z",
    }
    details: dict[str, Any] = {}
    with freeze_time(NOW), patch.object(source, "_report_settings_hold", return_value=None):
        queued = source._enqueue_observed_reports(state, readings, run, details)
        assert queued == len(cast(dict, state).get("_triage_queue", []))
        _record_source_run(
            run,
            state,
            "gpm_imerg",
            time.perf_counter(),
            status="success",
            observed=len(readings),
            promoted=queued,
            details={"rainfall_observed_report": details},
        )
    health = state["source_health"]["gpm_imerg"]
    assert ("promoted" in health["runs"][-1]) == (queued > 0)
    assert ("observed" in health["runs"][-1]) == bool(readings)
    out[name] = {"source_health": state["source_health"], "run_history": [run], "drafts": []}
sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
