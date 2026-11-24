"""Invented lookup→original archives→real source runner→durable JSON; no SDK/X."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import date
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from freezegun import freeze_time

from dashboard.tests.fixtures.ghcn_archive_intake_producer import NOW, archive_bytes
from dashboard.tests.fixtures.ghcn_intake_producer import forbidden
from src.data.ghcn_db import open_db, upsert_thresholds
from src.data import ghcn
from src.data.ghcn_format import DiffRecord, compute_thresholds, parse_dly_text
from src.data.temperature_history import record_observation_revision
from src.orchestrator.sources.open_meteo import run_extreme_signals
from src.state import DEFAULT_STATE
from tests.ghcn_intake_cases import SID
from tests.test_ghcn_discovery_hints import API, METADATA, Reply


def produce(case="fresh", provider="ghcn", *, extra_stations=0, candidates_out=None,
            archive_failure=False, archive_limit=20):
    assert case in {"fresh", "qc", "unavailable", "malformed", "two_nominees",
                    "quiet", "error400_capacity", "error400", "error400_unknown", "error400_unicode", "error400_private", "error400_sampled"}
    assert type(extra_stations) is int and 0 <= extra_stations <= 1000
    assert type(archive_failure) is bool
    assert type(archive_limit) is int and 0 <= archive_limit <= 20
    assert case != "two_nominees" or extra_stations == 0
    metadata = METADATA + ([dict(METADATA[1], station_id="SFX00000003")] if case == "two_nominees" else [])
    metadata += [dict(METADATA[1], station_id=f"SFX{index:08d}") for index in range(3, 3 + extra_stations)]
    state = deepcopy(DEFAULT_STATE)
    baseline = archive_bytes(target=None)
    record_observation_revision(state, DiffRecord("insert", SID, date(2000, 1, 1), "TMAX", 25),
                                retrieved_at=NOW, source_revision=sha256(baseline).hexdigest())
    run = {"id": "invented-lookup-" + case, "mode": "alerts", "sources": [],
           "started_at": "2026-11-21T11:59:00Z", "ended_at": "2026-11-21T12:01:00Z"}
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if "/superghcnd/" in url:
            return Reply(b"", 404)
        if url == API:
            if case == "quiet":
                return Reply(b"[]")
            if case.startswith("error400"):
                message = "🧭" * 240 if case == "error400_unicode" else "Invalid units. Valid units are standard or metric."
                if case == "error400_private":
                    message = "PRIVATE_FIXTURE_VALUE Authorization: Bearer INVENTED_TOKEN ftp://invented.invalid/private"
                field = "units"
                if case == "error400_capacity":
                    field = "stations"
                    message = "Maximum number of stations exceeded. Maximum number of stations: 100"
                body = json.dumps({"errorCode": 400, "errorMessage": "Bad Request", "errors": [
                    {"field": field, "message": message, "value": "ignored-provider-value"}]}).encode()
                return Reply(b"{" if case == "error400_unknown" else body, 400)
            body = json.dumps([{"STATION": meta["station_id"], "DATE": "2026-11-18", "TMAX": "49"}
                               for meta in metadata[1:]]).encode()
            return Reply(b"[" if case == "malformed" else body, 503 if case == "unavailable" else 200)
        if url.endswith(f"/all/{SID}.dly"):
            return Reply(b"", 503) if archive_failure else Reply(baseline)
        for meta in metadata[1:]:
            if url.endswith(f"/all/{meta['station_id']}.dly"):
                return (Reply(b"", 503) if archive_failure else
                        Reply(archive_bytes(station=meta["station_id"], qflag="S" if case == "qc" else "")))
        return forbidden()

    with TemporaryDirectory(prefix="invented-noaa-lookup-") as directory:
        path = Path(directory) / "fixture.sqlite"
        with open_db(path) as db:
            for meta in metadata:
                db.execute("INSERT INTO stations (station_id,name,country_code,country_name,lat,lon,archive_years,is_active) "
                           "VALUES (?,?,?,?,?,?,?,?)", (meta["station_id"], meta["name"], meta["country_code"],
                           meta["country_name"], meta["lat"], meta["lon"], 27, 1))
                if extra_stations and meta["station_id"] not in {m["station_id"] for m in METADATA}:
                    continue  # An uncached station is eligible for lookup, never nominated without a baseline.
                if case.startswith("error400") and case != "error400_sampled" and meta["station_id"] != SID:
                    # Preserve these historical tracked-only diagnostic cases
                    # with an explicitly absent untracked heuristic cache. The
                    # sampled400 case retains the full cache and original DLYs.
                    continue
                raw = archive_bytes(station=meta["station_id"], target=None)
                thresholds = compute_thresholds(parse_dly_text(raw.decode()))
                assert thresholds is not None
                upsert_thresholds(db, thresholds)
            db.commit()
        env = {"THEHEAT_GHCN_DB_PATH": str(path), "THEHEAT_SIGNALS_PROVIDER": provider,
               "THEHEAT_GHCN_THRESHOLD_VERIFICATION": "success", "THEHEAT_OBSERVED_WEATHER_ONLY": "1",
               "THEHEAT_TRIAGE_ENABLED": "1", "THEHEAT_CONCURRENT_SOURCES": "0"}
        # Delegate to the unchanged real collector with its supported explicit
        # allowance, only for the one-slot fixture. Default source calls remain
        # untouched; no source/QC/check function is replaced by a success stub.
        limit_context = (patch.object(ghcn, "check_extreme_signals_for_stations",
            partial(ghcn.check_extreme_signals_for_stations, archive_verification_limit=archive_limit))
            if archive_limit != 20 else nullcontext())
        with patch.dict(os.environ, env), freeze_time(NOW), patch("requests.get", get), \
             patch.object(socket.socket, "connect", forbidden), patch.object(socket, "create_connection", forbidden), \
             patch.object(socket, "getaddrinfo", forbidden), patch("builtins.print"), limit_context:
            run_extreme_signals(state, run, [], {}, {})
            if candidates_out is not None:
                candidates_out.extend(state.get("_triage_queue", []))
    assert not state["drafts"] and len(run["sources"]) == 1
    return json.loads(json.dumps({"source_health": state["source_health"], "run_history": [run],
                                  "drafts": [], "request_count": len(calls)}))


if __name__ == "__main__":
    sys.stdout.write(json.dumps({name: produce(name) for name in ("fresh", "qc", "unavailable", "malformed", "two_nominees",
                                                               "quiet", "error400_capacity", "error400", "error400_unknown", "error400_unicode", "error400_private")}
                               | {"combined": produce(provider="both_global")}, sort_keys=True) + "\n")
