"""Invented HTTP responses through the real GPM caller and durable telemetry.

No provider fetch, SDK, drain or sender: responses owns every HTTP request and
socket traps refuse accidental external access. Failure labels are observations,
never a diagnosis of credentials, migration or weather.
"""

from datetime import date
import io
import json
import socket

from freezegun import freeze_time
import h5py
import numpy as np
import pytest
import requests
import responses

from src.data import gpm_imerg as gpm
from src.evaluation import rainfall_opportunity as audit
from src.orchestrator.sources import gpm_imerg as runner
from tests.test_rainfall_opportunity import Transport, population

DAY = date(2026, 6, 5)
SECRET = "invented-private-body-query-cookie-token"
HDF = b"\x89HDF\r\n\x1a\n"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No fixture network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setenv("EARTHDATA_TOKEN", SECRET)
    monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    monkeypatch.setenv("THEHEAT_GPM_OBSERVED_REPORT", "0")
    monkeypatch.setenv("GPM_IMERG_MAX_CITIES", "2")
    monkeypatch.setenv("GPM_IMERG_MAX_WORKERS", "1")
    monkeypatch.setenv("GPM_IMERG_RETRY_BACKOFF_S", "0")
    monkeypatch.setenv("THEHEAT_EARTHDATA_REFUSAL_BACKOFF", "1")
    monkeypatch.delenv("THEHEAT_RAINFALL_REGIONAL_SCAN", raising=False)
    monkeypatch.setattr(gpm, "_default_start_date", lambda: DAY)


def run_source(status, payload):
    rows = population(2)
    transport = Transport(rows, point={0: 25.0, 1: 26.0}, probe_published=[DAY])
    transport._grid = lambda request: (status, {"Content-Type": "text/html", "Set-Cookie": SECRET}, payload)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock, freeze_time("2026-06-05T12:00:00Z"):
        # Existing fixture installs into responses' default mock; this context
        # explicitly owns its callbacks instead.
        import re
        mock.add_callback(responses.GET, re.compile(r"https://data\.gesdisc\.earthdata\.nasa\.gov/.*"),
                          callback=transport._grid)
        mock.add_callback(responses.GET, re.compile(r"https://gpm1\.gesdisc\.eosdis\.nasa\.gov/.*"),
                          callback=transport._opendap)
        state = {}
        run = {"id": "invented-grid-reason", "started_at": "2026-06-05T11:59:00Z"}
        runner.run_gpm_imerg(state, run, rows)
        calls = [call.request.url for call in mock.calls]
    source = run["sources"][-1]
    assert source["source"] == "gpm_imerg" and source["status"] == "success"
    assert "earthdata_access" not in source["details"]
    # Actual telemetry(state) includes the canonical zero-eliding health view.
    assert state["source_health"]["gpm_imerg"]["runs"][-1]["observed"] == 2
    trace = source["details"]["rainfall_opportunity"]
    audit.validate_trace(trace)
    assert trace["request_counts"]["grid_downloads"] == 1
    assert trace["request_counts"]["http_requests"] == {
        "min": len(calls), "max": len(calls) + (2 if len(calls) > 1 else 0),
        "unmeasured_components": ["redirects_not_counted"]}
    return source, state, trace, calls


@pytest.mark.parametrize(("status", "payload", "reason", "incident"), [
    (200, b"<!DOCTYPE html><html>" + SECRET.encode(), "html_payload", "malformed"),
    (200, b"\xef\xbb\xbf \n<HTML>" + SECRET.encode(), "html_payload", "malformed"),
    (200, b"\x00\x01unrecognized" + SECRET.encode(), "unrecognized_payload", "malformed"),
    (200, b"<htmlish>" + SECRET.encode(), "unrecognized_payload", "malformed"),
    (200, b"", "unrecognized_payload", "malformed"),
    (200, HDF + b"\xff" * 25, "hdf_payload_unreadable", "malformed"),
    (200, HDF, "hdf_payload_unreadable", "malformed"),
    (401, SECRET.encode(), "http_access_refused", "transport_failure"),
    (403, SECRET.encode(), "http_access_refused", "transport_failure"),
    (503, SECRET.encode(), "transient", "transport_failure"),
])
def test_failure_reason_survives_real_fallback_runner_and_durable_telemetry(status, payload, reason, incident, capsys):
    source, state, trace, calls = run_source(status, payload)
    grid, point = trace["legs"]
    assert grid["reason"] == reason
    assert grid["inspection"] == "not_reached"
    assert grid["candidates"] == [{"date": DAY.isoformat(), "outcome": "downloaded" if status == 200 else "transient"}]
    assert trace["serving_leg"] == point["leg"] == "imerg_late_opendap"
    assert [a["outcome"] for a in source["details"]["incident"]["attempts"]] == [incident, "qualified"]
    assert len(calls) == 4 and "data.gesdisc" in calls[0]
    assert all("gpm1.gesdisc" in url for url in calls[1:])
    assert SECRET not in json.dumps(state) + json.dumps(source) + capsys.readouterr().out


@pytest.mark.parametrize("block", [0, 512, 1024])
def test_valid_hdf_with_html_user_block_is_accepted_without_new_diagnostic(block):
    rows = population(2)
    buf = io.BytesIO()
    with h5py.File(buf, "w", userblock_size=block) as file:
        data = file.create_dataset("precipitation", shape=(1, gpm.LON_CELLS, gpm.LAT_CELLS),
                                   dtype=np.float32, chunks=(1, 10, 10), fillvalue=gpm.FILL_VALUE)
        for index, row in enumerate(rows):
            data[0, gpm._lon_index(row["lon"]), gpm._lat_index(row["lat"])] = 25.0 + index
    payload = buf.getvalue()
    if block:
        prefix = b"<html>" + SECRET.encode()
        payload = prefix + payload[len(prefix):]
    source, state, trace, calls = run_source(200, payload)
    assert len(calls) == 1 and trace["serving_leg"] == "imerg_late_grid_datapool"
    (grid,) = trace["legs"]
    assert "reason" not in grid and grid["inspection"] == "completed"
    assert "earthdata_access" not in source["details"]
    assert SECRET not in json.dumps(state)


@pytest.mark.parametrize("status", [401, 403, 404, 503])
def test_http_refusals_do_not_read_error_body_or_probe_another_date(monkeypatch, status):
    class Reply:
        status_code = status

        @property
        def content(self):
            pytest.fail("No new read of HTTP error body")
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return Reply()
    monkeypatch.setattr(gpm._DatapoolSession, "get", staticmethod(get))
    with pytest.raises((gpm._GridTransient, gpm._GridNotFound)):
        gpm._fetch_grid_bytes_datapool(target_date=DAY, product="late", token=SECRET)
    assert len(calls) == 1


def test_unknown_diagnostic_never_enters_trace(monkeypatch):
    def refuse(*args, **kwargs):
        raise gpm._GridParseError(SECRET, diagnostic=SECRET)
    monkeypatch.setattr(gpm, "_subset_grid", refuse)
    source, _state, trace, _calls = run_source(200, b"invented")
    assert trace["legs"][0]["reason"] == "parse_error"
    assert SECRET not in json.dumps(source["details"])
