"""Invented HDF5/HTTP through real collector and zero-eliding telemetry; no model.

The Node consumer exercises the same serialized rows, not handwritten health data.
Every external connection is refused; only the in-process fixture HTTP responds.
"""
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import io
import json
import os
import socket
import sys
from unittest.mock import patch

from freezegun import freeze_time
import h5py
import pytest

from src.data import gpm_imerg as gpm
from src.orchestrator.sources import gpm_imerg as source
from src.state import DEFAULT_STATE
from tests.test_rainfall_grid_pipeline import GridTransport, NOW, nasa_frame

CASES = {
    "time": "rainfall_grid_time_invalid",
    "units": "rainfall_grid_units_invalid",
    "axes": "rainfall_grid_axes_invalid",
    "counts": "rainfall_grid_dataset_invalid",
    "scaling": "rainfall_grid_packed_data_unsupported",
    "city": "rainfall_grid_time_invalid",
}
ENV = {
    "EARTHDATA_TOKEN": "invented-not-a-credential", "THEHEAT_GPM_SOURCE": "datapool",
    "THEHEAT_GPM_OBSERVED_REPORT": "1", "THEHEAT_OBSERVED_WEATHER_ONLY": "1",
    "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-grid-held",
    "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1", "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1",
    "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_CRITIC_ENABLED": "1",
    "THEHEAT_CRITIC_REVISE_ENABLED": "0", "THEHEAT_REFILL_ENABLED": "0",
    "THEHEAT_PRODUCTION_PAUSED": "0", "THEHEAT_RAINFALL_REGIONAL_SCAN": "0",
}


@lru_cache(maxsize=1)
def original_frame():
    return nasa_frame()


def forbidden(*args, **kwargs):
    raise AssertionError("Fixture refuses external network")


def produce(name):
    assert name in CASES or name == "qualified"
    city = next(row for row in gpm.load_cities() if row["city"] == "Paris" and row["country"] == "France")
    buffer = io.BytesIO(original_frame())
    with h5py.File(buffer, "r+") as handle:
        handle["precipitation"][0, gpm._lon_index(float(city["lon"])), gpm._lat_index(float(city["lat"]))] = 180 if name == "city" else 20
        if name in {"time", "city"}:
            handle["time"].attrs["calendar"] = "360_day"
        elif name == "units":
            handle["precipitation"].attrs["units"] = "mm/hour"
        elif name == "axes":
            handle["lon"][0] = -179.9
        elif name == "counts":
            del handle["precipitation_cnt"]
        elif name == "scaling":
            handle["precipitation"].attrs["scale_factor"] = .1
    transport = GridTransport(buffer.getvalue())
    state = deepcopy(DEFAULT_STATE)
    run = {"id": "invented-held-" + name, "mode": "alerts", "sources": [],
           "started_at": (NOW - timedelta(minutes=1)).isoformat(),
           "ended_at": (NOW + timedelta(minutes=1)).isoformat()}
    with pytest.MonkeyPatch.context() as mp, patch.dict(os.environ, ENV), freeze_time(NOW):
        for owner, attr in [(socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo")]:
            mp.setattr(owner, attr, forbidden)
        transport.install(mp.setattr)
        # The collector's own progress text is never part of the JSON transport.
        with patch("builtins.print"):
            source.run_gpm_imerg(state, run, [city])
    assert len(transport.nasa_calls) == 1 and transport.x_posts == []
    assert state["drafts"] == []
    # Real telemetry already rebuilds and elides zero source-health fields.
    return json.loads(json.dumps({"source_health": state["source_health"], "run_history": [run], "drafts": []}))


if __name__ == "__main__":
    sys.stdout.write(json.dumps({name: produce(name) for name in (*CASES, "qualified")}, sort_keys=True) + "\n")
