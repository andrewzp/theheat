"""A1: physically bounded live normals transport, exercised through its real socket path.

A loopback byte-level server serves invented Meteostat-shaped bulk files. The
production ``bounded_http`` transport and ``MeteostatBulkProvider`` run
unmodified (only the endpoint origin points at the loopback fixture); no fake
provider returns a qualified artifact. No external network is touched.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import threading
import time

import pytest

from scripts import build_normals
from src.data import bounded_http, meteostat_normals as mn, normals_acquisition as na, open_meteo
from tests import live_content_harness as h
from tests.final_closure import supply_http_fixture as fx

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
FAST = {"poll_seconds": 0.05, "backoff_seconds": 0.01, "connect_wait": 2.0}


@pytest.fixture
def server():
    fixture = fx.Fixture()
    yield fixture
    fixture.close()


def _station(sid, lat, lon, elevation, *, inventory=True):
    span = ("1950-01-01", "2024-12-01") if inventory else ("", "")
    return [sid, f"Invented {sid}", "XX", "", "", "", f"{lat:.5f}", f"{lon:.5f}", "" if elevation is None else str(elevation),
            "UTC", "", "", "", "", *span]


def _csv(rows):
    out = []
    for row in rows:
        out.append(",".join(f'"{v}"' if "," in str(v) else str(v) for v in row))
    return "\n".join(out) + "\n"


def _normals(periods, tmax, *, skip_month=None):
    rows = []
    for start, end in periods:
        for month in range(1, 13):
            value = "" if month == skip_month else f"{tmax + month / 10:.1f}"
            rows.append([start, end, month, "10.0", value, "1.0", "", "", ""])
    return _csv(rows)


def world(tmp_path, names=("Riyadh", "Cairo", "Lima")):
    cities = tmp_path / "cities.csv"
    h.write_catalogue(cities, list(names))
    installed = tmp_path / "installed" / "normals.csv"
    installed.parent.mkdir()
    installed.write_text("city,month,avg_high_c\nInventedtown,1,21.5\n")
    plan = na.build_plan(cities, installed, dependency=None)
    return cities, installed, plan


def publish_world(server, plan, *, lima_only_old=True):
    """Per point: C nearest but too high, A closest in range (July missing), D no monthly inventory
    (its file is absent: 404), B farther in range. Expected order A, D, B; July from B."""
    stations, files = [], {}
    for index, point in enumerate(plan["points"]):
        lat, lon = point["lat"], point["lon"]
        stations += [_station(f"C{index}", lat + 0.01, lon, 900), _station(f"A{index}", lat + 0.02, lon, 100),
                     _station(f"D{index}", lat + 0.03, lon, 110, inventory=False),
                     _station(f"B{index}", lat + 0.05, lon, 120)]
        periods = [(1961, 1990)] if (lima_only_old and point["city"] == "Lima") else [(1991, 2020), (1961, 1990)]
        files[f"A{index}"] = _normals(periods, 30 + index, skip_month=7)
        files[f"B{index}"] = _normals(periods, 20 + index)
        files[f"C{index}"] = _normals(periods, 5)
    server.route("/v2/stations/slim.csv.gz", fx.status(302, "/v2/stations/moved/slim.csv.gz"))
    server.route("/v2/stations/moved/slim.csv.gz", fx.status(503), fx.ok(fx.gz(_csv(stations)), chunked=True))
    for sid, text in files.items():
        server.route(f"/v2/normals/{sid}.csv.gz", fx.ok(fx.gz(text)))
    return {point["city"]: index for index, point in enumerate(plan["points"])}


def provider_for(server, **options):
    return mn.MeteostatBulkProvider(endpoint=f"{server.origin}/v2/", now=lambda: NOW,
                                    transport_options={**FAST, **options})


def limits(**overrides):
    values = {"max_requests": 200, "max_bytes": 2_000_000, "deadline_seconds": 30, "max_retries": 2,
              "max_decoded_bytes": 8_000_000}
    return na.Limits(**{**values, **overrides})


def tree_digest(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------
# end-to-end through the operator CLI: acquire -> admit -> install-plan
# ---------------------------------------------------------------------------

def test_cli_acquires_over_the_real_transport_then_admits_and_plans_install(tmp_path, server, capsys):
    cities, installed, _ = world(tmp_path)
    plan_path = tmp_path / "plan.json"
    assert build_normals.main(["plan", "--cities", str(cities), "--installed", str(installed),
                               "--output", str(plan_path)]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"  # stdlib-only tool: no SDK dependency gate
    plan = json.loads(plan_path.read_text())
    assert plan["live_acquisition"]["status"] == "bounded_transport"
    assert plan["provider"]["contract"]["reference"]["version"] == "1.7.6"
    assert "--max-decoded-bytes" in plan["next_command"]
    index = publish_world(server, plan)["Riyadh"]
    before = installed.read_bytes()
    out = tmp_path / "out"
    args = ["acquire", "--plan", str(plan_path), "--out-dir", str(out), "--installed", str(installed),
            "--max-requests", "40", "--max-bytes", "200000", "--max-decoded-bytes", "800000",
            "--deadline-seconds", "30", "--max-retries", "2"]
    assert build_normals.main(args, provider_factory=lambda: provider_for(server)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready" and result["product"]["rows"] == 36
    transport = result["counters"]["transport"]
    # Physical accounting equals what the server actually received: 302+503+302+200 for the
    # station list, then one GET per station file (A, D=404, B) per point, shared across periods.
    assert transport["physical_requests"] == len(server.requests) == 4 + 9
    assert transport["redirects"] == 2 and transport["retries"] == 1
    assert transport["transfer_bytes"] <= 200000 and transport["decoded_bytes"] <= 800000
    assert result["counters"]["requests"] == 4  # adapter calls: 3 points + Lima's explicit 1961 fallback
    assert installed.read_bytes() == before

    rows = list(csv.DictReader((out / "candidate/normals.csv").open()))
    lima = [r for r in rows if r["city"] == "Lima"]
    assert {(r["period_start"], r["period_end"]) for r in lima} == {("1961", "1990")}
    riyadh = {int(r["month"]): float(r["avg_high_c"]) for r in rows if r["city"] == "Riyadh"}
    # July: A has no value and D has no file (404), so the nearest rule takes B's.
    assert riyadh[1] == round(30 + index + 0.1, 1) and riyadh[7] == round(20 + index + 0.7, 1)
    first = next(json.loads(p.read_text()) for p in (out / "partitions").glob("*.json")
                 if json.loads(p.read_text())["city"] == "Riyadh")["source_provenance"]
    a, d, b = (f"{kind}{index}" for kind in "ADB")
    assert [s["station"] for s in first["selected_stations"]] == [a, d, b]  # C excluded by altitude
    assert first["month_station"]["7"] == b and first["month_station"]["1"] == a
    assert [s["normals_file"]["status"] for s in first["selected_stations"]] == ["ok", "missing", "ok"]
    assert first["stations_file"]["final_url"].endswith("/v2/stations/moved/slim.csv.gz")
    assert first["stations_file"]["sha256"] and first["stations_file"]["etag"]
    assert first["units"] == "degC" and "CC BY-NC" in first["licence"]
    manifest = json.loads((out / "candidate/manifest.json").read_text())
    assert manifest["source_contract"]["reference"]["sdist_sha256"].startswith("2b83eedb")
    riyadh_point = next(p for p in manifest["points"] if p["stations"][0] == a)
    assert riyadh_point["month_station"]["7"] == b and riyadh_point["stations_file_sha256"]

    assert build_normals.main(["admit", "--candidate", str(out / "candidate")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert build_normals.main(["install-plan", "--candidate", str(out / "candidate"),
                               "--installed", str(installed)]) == 0
    install = json.loads(capsys.readouterr().out)
    assert install["install"]["performed_by"] == "root" and install["rollback"]["retained_copy"]
    assert installed.read_bytes() == before
    loaded = open_meteo.load_normals(str(out / "candidate/normals.csv"))
    assert sum(1 for entry in loaded.values() for m in entry if isinstance(m, int)) == 36


def test_cli_default_provider_is_the_bounded_meteostat_bulk_contract(tmp_path, monkeypatch, capsys):
    cities, installed, _ = world(tmp_path, names=("Riyadh",))
    plan_path = tmp_path / "plan.json"
    assert build_normals.main(["plan", "--cities", str(cities), "--installed", str(installed),
                               "--output", str(plan_path)]) == 0
    capsys.readouterr()
    seen = {}

    class Recorder(mn.MeteostatBulkProvider):
        def bind(self, limits, *, deadline_at, cancel):
            seen.update(endpoint=self.endpoint, limits=limits, cancel=cancel)
            raise KeyboardInterrupt  # stop before any network use

    monkeypatch.setattr(na.meteostat_normals, "MeteostatBulkProvider", Recorder)
    code = build_normals.main(["acquire", "--plan", str(plan_path), "--out-dir", str(tmp_path / "out"),
                               "--installed", str(installed), "--max-requests", "9", "--max-bytes", "1000",
                               "--deadline-seconds", "5", "--max-retries", "0"])
    assert code == 130
    assert seen["endpoint"] == "https://bulk.meteostat.net/v2/"
    assert seen["limits"].max_requests == 9 and seen["limits"].max_transfer_bytes == 1000
    assert seen["limits"].max_decoded_bytes == 8000 and isinstance(seen["cancel"], threading.Event)
    with pytest.raises(na.NormalsError, match="normals_bounded_transport_unavailable"):
        na.MeteostatProvider()  # the unbounded SDK wrapper stays refused


# ---------------------------------------------------------------------------
# physical bounds through acquire(): requests, bytes, decoded bytes, deadline, cancel
# ---------------------------------------------------------------------------

def _single(tmp_path, server):
    _, installed, plan = world(tmp_path, names=("Riyadh",))
    publish_world(server, plan)
    return installed, plan


@pytest.mark.parametrize("override,reason", [
    ({"max_requests": 3}, "request_limit"),
    ({"max_bytes": 300}, "byte_limit"),
    ({"max_decoded_bytes": 200}, "decoded_byte_limit"),
])
def test_each_physical_limit_stops_the_run_without_promotion(tmp_path, server, override, reason):
    installed, plan = _single(tmp_path, server)
    out = tmp_path / "out"
    result = na.acquire(plan, out, provider_for(server), limits(**override), installed_path=installed)
    assert result["status"] == "incomplete" and result["reasons"] == [reason]
    assert not (out / "candidate").exists() and not list(out.glob("partitions/*.json"))
    transport = result["counters"]["transport"]
    assert transport["physical_requests"] == len(server.requests) <= 200
    if reason == "request_limit":
        assert len(server.requests) == 3  # the cap counts redirect hops and the retried 503
    if reason == "byte_limit":
        assert transport["transfer_bytes"] <= 301
    if reason == "decoded_byte_limit":
        assert transport["decoded_bytes"] <= 201


def test_content_length_over_the_allowance_is_refused_before_any_body_byte(tmp_path, server):
    installed, plan = _single(tmp_path, server)
    server.route("/v2/stations/slim.csv.gz", fx.ok(b"z" * 50_000))
    result = na.acquire(plan, tmp_path / "out", provider_for(server), limits(max_bytes=20_000),
                        installed_path=installed)
    assert result["reasons"] == ["byte_limit"]
    # Headers are read in 1 KiB steps; the declared length is refused before the body is read.
    assert result["counters"]["transport"]["transfer_bytes"] <= 1_024


def test_gzip_bomb_hits_the_decoded_cap_not_memory(tmp_path, server):
    installed, plan = _single(tmp_path, server)
    bomb = fx.gzip.compress(b"0" * 20_000_000, mtime=0)
    server.route("/v2/stations/slim.csv.gz", fx.ok(bomb))
    result = na.acquire(plan, tmp_path / "out", provider_for(server), limits(max_decoded_bytes=1_000_000),
                        installed_path=installed)
    assert result["reasons"] == ["decoded_byte_limit"]
    assert result["counters"]["transport"]["decoded_bytes"] <= 1_000_001


@pytest.mark.parametrize("action", ["delay_headers", "drip_body"])
def test_deadline_bounds_blocking_reads_and_nothing_continues_afterwards(tmp_path, server, action):
    installed, plan = _single(tmp_path, server)
    slow = fx.delay_headers(5) if action == "delay_headers" else fx.drip(5_000, 0.05)
    server.route("/v2/stations/slim.csv.gz", slow)
    out = tmp_path / "out"
    start = time.monotonic()
    result = na.acquire(plan, out, provider_for(server), limits(deadline_seconds=1), installed_path=installed)
    returned = time.monotonic()
    assert result["reasons"] == ["deadline"] and returned - start < 1.6
    requests_at_return, files_at_return = len(server.requests), tree_digest(out)
    time.sleep(1.2)
    assert len(server.requests) == requests_at_return == 1  # no retry, no late request
    assert tree_digest(out) == files_at_return  # no late journal/partition/candidate write
    if action == "drip_body":
        # The server's next writes failed: the client closed the socket when the bound fired.
        assert server.client_gone and server.client_gone[0][0] < returned + 1.0


def test_cancellation_stops_within_one_poll_interval(tmp_path, server):
    installed, plan = _single(tmp_path, server)
    server.route("/v2/stations/slim.csv.gz", fx.delay_headers(5))
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = na.acquire(plan, tmp_path / "out", provider_for(server), limits(), installed_path=installed,
                        cancel=cancel)
    assert result["reasons"] == ["cancelled"] and time.monotonic() - start < 1.0


@pytest.mark.parametrize("route,reason", [
    (fx.status(404), "provider_endpoint_missing"),
    (fx.status(403), "provider_access_refused"),
    (fx.status(302, "http://198.51.100.7/v2/stations/slim.csv.gz"), "provider_redirect_refused"),
    (fx.ok(b"<html>not a product</html>"), "provider_malformed"),
])
def test_unusable_station_list_refuses_the_run_without_guessing(tmp_path, server, route, reason):
    installed, plan = _single(tmp_path, server)
    server.route("/v2/stations/slim.csv.gz", route)
    result = na.acquire(plan, tmp_path / "out", provider_for(server), limits(max_retries=0),
                        installed_path=installed)
    assert result["status"] == "incomplete" and result["reasons"] == [reason]
    assert not (tmp_path / "out/candidate").exists()


def test_station_file_server_error_keeps_the_point_pending_never_relabelled(tmp_path, server):
    installed, plan = _single(tmp_path, server)
    server.route("/v2/normals/A0.csv.gz", fx.status(503))
    out = tmp_path / "out"
    result = na.acquire(plan, out, provider_for(server), limits(max_retries=1), installed_path=installed)
    assert result["status"] == "incomplete" and result["reasons"] == ["transport_failures_remaining"]
    journal = json.loads((out / "journal.json").read_text())
    assert list(journal["failures"].values())[0]["outcome"] == "provider_error"
    assert not list(out.glob("partitions/*.json"))
    a0 = [path for _t, path in server.requests if path.endswith("/A0.csv.gz")]
    assert len(a0) == 2  # one try + one retry, inside the physical allowance


def test_invalid_station_file_marks_the_point_invalid_and_admission_holds_it(tmp_path, server):
    installed, plan = _single(tmp_path, server)
    server.route("/v2/normals/A0.csv.gz", fx.ok(fx.gz("1991,2020,13,1,2,3,,,\n")))
    out = tmp_path / "out"
    result = na.acquire(plan, out, provider_for(server), limits(), installed_path=installed)
    assert result["status"] == "source_absent"
    manifest = json.loads((out / "candidate/manifest.json").read_text())
    assert manifest["missing_points"][0]["status"] == "invalid_product" and manifest["rows"] == 0


# ---------------------------------------------------------------------------
# transport unit cases: TLS boundary, origins, framing
# ---------------------------------------------------------------------------

def _transport(origin, **limit_overrides):
    values = {"max_requests": 5, "max_transfer_bytes": 100_000, "max_decoded_bytes": 100_000,
              "deadline_seconds": 1.0, "max_retries": 0}
    return bounded_http.BoundedTransport(bounded_http.Limits(**{**values, **limit_overrides}),
                                         allowed_origins=[origin], **FAST)


def test_tls_handshake_that_never_completes_is_bounded_by_the_deadline():
    silent = fx.SilentServer()
    try:
        transport = _transport(f"https://127.0.0.1:{silent.port}")
        start = time.monotonic()
        with pytest.raises(bounded_http.TransportStop) as stop:
            transport.get(f"https://127.0.0.1:{silent.port}/v2/stations/slim.csv.gz")
        assert stop.value.reason == "deadline" and time.monotonic() - start < 1.5
        assert transport.counters["physical_requests"] == 1
    finally:
        silent.close()


def test_plain_http_is_only_for_loopback_fixtures_and_origins_are_exact():
    with pytest.raises(ValueError, match="plain_http_refused"):
        _transport("http://bulk.meteostat.net/v2/")
    transport = _transport("https://bulk.meteostat.net/v2/")
    assert not transport.allowed("https://bulk.meteostat.net.invalid/v2/")
    assert not transport.allowed("http://bulk.meteostat.net/v2/")
    with pytest.raises(ValueError, match="origin_refused"):
        transport.get("https://other.invalid/")


@pytest.mark.parametrize("body,outcome", [
    (b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nContent-Length: 6\r\n\r\nhello!", "malformed"),
    (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\nxx", "malformed"),
    (b"NOT-HTTP\r\n\r\n", "malformed"),
    (b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nshort", "transport_failure"),
    (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n", "malformed"),
])
def test_framing_defects_are_classified_never_accepted(server, body, outcome):
    server.route("/x", fx.raw(body))
    transport = _transport(server.origin)
    with pytest.raises(bounded_http.TransportOutcome) as error:
        transport.get(server.origin + "/x")
    assert error.value.outcome == outcome


def test_chunked_and_unlengthed_bodies_round_trip_with_exact_counting(server):
    server.route("/chunked", fx.ok(b"abc" * 1000, chunked=True))
    server.route("/close", fx.ok(b"xyz" * 1000, length=False))
    transport = _transport(server.origin)
    assert transport.get(server.origin + "/chunked").body == b"abc" * 1000
    assert transport.get(server.origin + "/close").body == b"xyz" * 1000
    assert transport.counters["physical_requests"] == 2 and transport.counters["transfer_bytes"] > 6000
