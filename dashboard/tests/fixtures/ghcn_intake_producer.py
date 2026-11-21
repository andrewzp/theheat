"""Invented real diff/archive HTTP→SQLite source engine→telemetry→durable JSON.

Workflow baseline verification is an explicit offline fixture boundary; the
generated test database, never the operator's database, supplies its contents.
Every model, platform and unlisted network operation remains unavailable.
"""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import os
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from freezegun import freeze_time

from src.data.ghcn_db import open_db, upsert_thresholds
from src.data.ghcn_format import DiffRecord, compute_thresholds, parse_dly_text
from src.data.temperature_history import record_observation_revision
from src.orchestrator.sources.open_meteo import run_extreme_signals
from src.state import DEFAULT_STATE
from tests.ghcn_intake_cases import NOW, SID, Replies, payloads
from tests.test_ghcn_format import make_dly_line

CASES = ("mixed", "empty", "inactive", "no_temperature", "missing", "unavailable")


def archive(case, *, baseline=False):
    months: dict[tuple[int, int], list[int | None]] = {}
    start, end = date(2000, 1, 1), date(2026, 11, 18)
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if baseline and day == end:
            continue
        if not baseline and case in {"mixed", "empty"} and day == date(2026, 11, 17):
            continue
        if not baseline and case == "empty" and day == end:
            continue
        value = 330 if not baseline and case == "mixed" and day == end else 250
        months.setdefault((day.year, day.month), [None] * 31)[day.day - 1] = value
    return ("\n".join(make_dly_line(SID, year, month, "TMAX", cells)
                       for (year, month), cells in sorted(months.items())) + "\n").encode()


def forbidden(*args, **kwargs):
    raise AssertionError("Uninvented network operation refused")


def produce(case="mixed", provider="ghcn"):
    assert case in CASES and provider in {"ghcn", "both_global"}
    baseline, current = archive(case, baseline=True), archive(case)
    state = deepcopy(DEFAULT_STATE)
    record_observation_revision(state, DiffRecord("insert", SID, date(2026, 11, 16), "TMAX", 25),
                                retrieved_at=NOW, source_revision=sha256(baseline).hexdigest())
    run = {"id": "invented-ghcn-" + case, "mode": "alerts", "sources": [],
           "started_at": "2026-11-21T11:59:00Z", "ended_at": "2026-11-21T12:01:00Z"}
    replies = Replies(payloads(case), {
        f"https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{SID}.dly": current,
    })
    with TemporaryDirectory(prefix="invented-ghcn-intake-") as directory:
        path = os.path.join(directory, "fixture.sqlite")
        with open_db(path) as db:
            db.execute("INSERT INTO stations (station_id,name,country_code,country_name,lat,lon,archive_years,is_active) VALUES (?,?,?,?,?,?,?,?)",
                       (SID, "INVENTED FIXTURE STATION", "BR", "Brazil", -10, -50, 27, 1))
            thresholds = compute_thresholds(parse_dly_text(baseline.decode()))
            assert thresholds is not None
            upsert_thresholds(db, thresholds)
            db.commit()
        env = {"THEHEAT_GHCN_DB_PATH": path, "THEHEAT_SIGNALS_PROVIDER": provider,
               "THEHEAT_GHCN_THRESHOLD_VERIFICATION": "success", "THEHEAT_OBSERVED_WEATHER_ONLY": "1",
               "THEHEAT_TRIAGE_ENABLED": "1", "THEHEAT_CONCURRENT_SOURCES": "0"}
        with patch.dict(os.environ, env), freeze_time(NOW), patch("requests.get", replies.get), \
             patch.object(socket.socket, "connect", forbidden), patch.object(socket, "create_connection", forbidden), \
             patch.object(socket, "getaddrinfo", forbidden), patch("builtins.print"):
            run_extreme_signals(state, run, [], {}, {})
    assert state["drafts"] == [], "A source-only fixture never writes a draft or sends"
    assert len(run["sources"]) == 1
    return json.loads(json.dumps({"source_health": state["source_health"], "run_history": [run],
                                  "drafts": [], "request_count": len(replies.calls)}))


if __name__ == "__main__":
    sys.stdout.write(json.dumps({**{name: produce(name) for name in CASES},
                                "combined": produce("mixed", "both_global")}, sort_keys=True) + "\n")
