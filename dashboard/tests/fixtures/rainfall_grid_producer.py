"""Invented cell/city input through real nomination, queue and durable telemetry.

No source or SDK call; external network is trapped before importing the source.
The existing Node reader and actual SourcesView consume this output unchanged.
"""
from copy import deepcopy
from datetime import UTC, datetime
import json
import os
import socket
import sys
import time
from typing import cast
from unittest.mock import patch

from freezegun import freeze_time


def forbidden(*args, **kwargs):
    raise AssertionError("No fixture network")


patch.object(socket.socket, "connect", forbidden).start()
patch.object(socket, "create_connection", forbidden).start()
patch.object(socket, "getaddrinfo", forbidden).start()

from src.data import gpm_imerg as gpm, rainfall_grid as grid
from src.orchestrator.sources import gpm_imerg as source
from src.orchestrator.telemetry import _record_source_run
from src.state_schema import BotState
from tests.test_rainfall_grid_nomination import _inland_reading
from tests.test_rainfall_nomination_observation import reading as city_reading

NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)
os.environ.update(THEHEAT_GPM_OBSERVED_REPORT="1", THEHEAT_OBSERVED_WEATHER_ONLY="1",
                  THEHEAT_AUTOMATIC_PUBLICATION_ENABLED="1", THEHEAT_AUTOMATIC_PUBLICATION_EPOCH="invented-grid-counts",
                  THEHEAT_AUTOSHIP_ON_CRITIC_PASS="1", THEHEAT_MAX_DRAFTS_PER_CYCLE="1", THEHEAT_WRITER_SAMPLES="1",
                  THEHEAT_CRITIC_ENABLED="1", THEHEAT_CRITIC_REVISE_ENABLED="0", THEHEAT_REFILL_ENABLED="0",
                  THEHEAT_PRODUCTION_PAUSED="0")
PROOF = {"schema": grid.SCHEMA, "source_url": grid.SOURCE_URL, "source_product": "late",
         "product_version": "V07C", "source_date": "2026-11-15", "source_time_utc": "2026-11-15T00:00:00Z",
         "source_units": "mm/day", "column": 1299, "row": 799, "mm_per_day": 190.5, "valid_half_hours": 48,
         "source_file_sha256": "1" * 64, "geography_sha256": grid.TABLE_SHA256}
inland = _inland_reading()
SAME_CELL = dict(PROOF, column=gpm._lon_index(inland.lon), row=gpm._lat_index(inland.lat),
                 mm_per_day=inland.mm_total)
out: dict = {}
for name, readings, proofs in [
    ("grid_only", [], [PROOF]), ("mixed", [city_reading(20)], [PROOF]),
    ("same_cell", [inland], [SAME_CELL]), ("duplicate", [], [PROOF, deepcopy(PROOF)]),
    ("conflict", [], [PROOF, dict(PROOF, mm_per_day=191)]),
    ("qualification", [], [dict(PROOF, valid_half_hours=47)]),
    ("city_grid_conflict", [inland], [dict(SAME_CELL, mm_per_day=191)]),
    ("history", [], [PROOF]),
    ("cap", [], [dict(PROOF, column=column) for column in (1299, 1289, 1279, 1269)]),
]:
    state: dict = {"drafts": []}
    run = {"id": "invented-grid-counts-" + name, "started_at": "2026-11-16T16:59:00Z",
           "ended_at": "2026-11-16T17:01:00Z"}
    if name == "history":
        old = grid.build_bundle(PROOF, now=NOW)
        state["drafts"].append({"event_id": old.event_id, "status": "unknown",
                                 "review_context": {"two_bot": {"bundle": old.to_dict()}}})
    details: dict = {}
    with freeze_time(NOW), patch.object(source, "_report_settings_hold", return_value=None):
        queued = source._enqueue_observed_reports(state, readings, run, details, discovery={"rows": proofs})
        assert queued == len(state.get("_triage_queue", []))
        _record_source_run(run, cast(BotState, state), "gpm_imerg", time.perf_counter(), status="success",
                           observed=len(readings), promoted=queued, details={"rainfall_observed_report": details})
    out[name] = {"source_health": state["source_health"], "run_history": [run], "drafts": []}
sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
