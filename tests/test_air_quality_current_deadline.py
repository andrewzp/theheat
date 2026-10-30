"""Invented HTTP/process boundaries only; no live source, socket or model access."""
from datetime import timedelta
import base64
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import requests

from src.data import air_quality_current as current
from tests.live_content_harness import Transport, aq_payload, coordinate_key, trap_network
from tests.test_air_quality_auto_text import DAY, HAZARD, LAHORE, T0, pm25_bundle


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    trap_network(monkeypatch.setattr)


@pytest.fixture
def packet():
    return pm25_bundle().raw_signal_dump["forecast_window"]


def body():
    return json.dumps(aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **HAZARD)).encode()


class Response:
    def __init__(self, *, status=200, headers=None, chunks=None):
        self.status_code, self.headers = status, headers or {}
        self.chunks = [body()] if chunks is None else chunks
        self.closed, self.read = False, False

    def iter_content(self, chunk_size):
        assert chunk_size <= 16_384
        self.read = True
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


class Session:
    def __init__(self, response=None, error=None):
        self.response, self.error = response or Response(), error
        self.calls, self.closed = [], False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def get(self, url, **options):
        self.calls.append((url, options))
        if self.error is not None:
            raise self.error
        return self.response


def install_http(monkeypatch, session):
    monkeypatch.setattr(current, "_session", lambda: session, raising=False)


def test_child_http_is_one_fixed_get_with_no_redirect_or_ambient_lookup(monkeypatch, packet):
    real = current._session()
    try:
        assert real.trust_env is False and real.max_redirects == 0
        assert real.get_adapter("https://").max_retries.total == 0
    finally:
        real.close()
    session = Session()
    install_http(monkeypatch, session)
    assert current._http_get_inprocess(current._request_params(packet)) == body()
    (url, options), = session.calls
    assert url == "https://air-quality-api.open-meteo.com/v1/air-quality"
    assert options["allow_redirects"] is False and options["stream"] is True and options["timeout"] == 10.0
    assert options["headers"]["Accept-Encoding"] == "identity"
    assert options["params"] == {"latitude": "31.55", "longitude": "74.35", "hourly": "pm2_5,pm10,dust,aerosol_optical_depth,us_aqi",
                                 "timezone": "auto", "domains": "auto", "start_date": DAY, "end_date": DAY}
    assert session.closed and session.response.closed


@pytest.mark.parametrize("status", [301, 302, 307, 308, 404, 503])
def test_redirect_or_failure_status_refuses_without_a_body_or_second_get(monkeypatch, packet, status):
    response = Response(status=status, headers={"Location": "https://invented.invalid/other"})
    session = Session(response)
    install_http(monkeypatch, session)
    with pytest.raises(current.CurrentSourceHold) as held:
        current._http_get_inprocess(current._request_params(packet))
    assert held.value.code == "air_quality_source_unavailable"
    assert len(session.calls) == 1 and not response.read and response.closed and session.closed


@pytest.mark.parametrize("error", [requests.Timeout("invented private timeout"),
                                   requests.ConnectionError("invented private DNS failure"),
                                   requests.TooManyRedirects("invented private redirect")])
def test_transport_errors_are_one_unavailable_read_without_exception_text(monkeypatch, packet, error):
    session = Session(error=error)
    install_http(monkeypatch, session)
    with pytest.raises(current.CurrentSourceHold) as held:
        current._http_get_inprocess(current._request_params(packet))
    assert held.value.code == str(held.value) == "air_quality_source_unavailable"
    assert held.value.__suppress_context__ and held.value.__cause__ is None
    assert len(session.calls) == 1 and session.closed


@pytest.mark.parametrize("chunks,headers,code", [
    ([b"x" * 65_537], {}, "air_quality_source_oversize"),
    ([b"x"], {"Content-Length": "65537"}, "air_quality_source_oversize"),
    ([b"x"], {"Content-Length": "2"}, "air_quality_source_unavailable"),
    ([b"x"], {"Content-Encoding": "gzip"}, "air_quality_source_unavailable"),
    ([b"{", requests.Timeout("invented partial body")], {}, "air_quality_source_unavailable"),
])
def test_body_bound_partial_encoding_and_length_fail_closed(monkeypatch, packet, chunks, headers, code):
    session = Session(Response(chunks=chunks, headers=headers))
    install_http(monkeypatch, session)
    with pytest.raises(current.CurrentSourceHold) as held:
        current._http_get_inprocess(current._request_params(packet))
    assert held.value.code == code and len(session.calls) == 1
    assert session.closed and session.response.closed


def test_exact_64k_body_is_not_silently_truncated(monkeypatch, packet):
    payload = b"x" * 65_536
    session = Session(Response(chunks=[payload[:16_384]] * 4, headers={"Content-Length": str(len(payload))}))
    install_http(monkeypatch, session)
    assert current._http_get_inprocess(current._request_params(packet)) == payload


@pytest.mark.parametrize("mode", ["dns", "headers", "body", "ignore-term"])
def test_total_deadline_covers_dns_headers_and_buffered_trickle(monkeypatch, packet, mode):
    real_popen, owned = subprocess.Popen, []
    code = ("import signal,sys,time\n"
            + ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n" if mode == "ignore-term" else "")
            + ("sys.stdout.write('{\"body\":\"');sys.stdout.flush()\n" if mode == "body" else "")
            + ("while True:\n sys.stdout.write('Y');sys.stdout.flush();time.sleep(.02)\n" if mode == "body"
               else "while True:\n time.sleep(.02)\n"))

    def invented_child(command, **options):
        process = real_popen([sys.executable, "-I", "-c", code], **options)
        owned.append((process, command, options))
        return process
    monkeypatch.setattr(subprocess, "Popen", invented_child)
    monkeypatch.setattr(current, "REQUEST_TIMEOUT_S", .4)
    # Old unbounded implementation is also prevented from touching a real source.
    from src.data import _http
    class OfflineSlowSession(Session):
        def get(self, *args, **options):
            time.sleep(.45)
            return SimpleNamespace(iter_content=lambda **k: [body()], close=lambda: None,
                                   status_code=200, raise_for_status=lambda: None)
    monkeypatch.setattr(_http, "_session", OfflineSlowSession())
    started = time.monotonic()
    with pytest.raises(current.CurrentSourceHold) as held:
        current.fetch_current(packet)
    elapsed = time.monotonic() - started
    assert held.value.code == "air_quality_source_unavailable" and elapsed < 2
    (process, command, options), = owned
    assert process.poll() is not None and options["start_new_session"] is True
    assert command[1:3] == ["-I", "-c"] and current.contract.SOURCE_URL not in command
    assert set(options["env"]) == {"PATH", "LANG", "LC_ALL", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE", "PYTHON_DOTENV_DISABLED"}


def test_timeout_cleans_owned_descendant_and_leaves_unrelated_fixture_running(monkeypatch, packet, tmp_path):
    real_popen, owned = subprocess.Popen, []
    unrelated = real_popen([sys.executable, "-I", "-c", "import time;time.sleep(10)"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid_file = tmp_path / "owned-descendant.pid"
    code = ("import pathlib,signal,subprocess,sys,time\n"
            "kid=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(10)'])\n"
            "def stop(*args):\n kid.wait(timeout=2);raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM,stop)\n"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(kid.pid))\n"
            "while True: time.sleep(.02)\n")

    def invented_child(command, **options):
        process = real_popen([sys.executable, "-I", "-c", code], **options)
        owned.append(process)
        return process
    monkeypatch.setattr(subprocess, "Popen", invented_child)
    monkeypatch.setattr(current, "REQUEST_TIMEOUT_S", .8)
    from src.data import _http
    monkeypatch.setattr(_http, "_session", Session(error=requests.ConnectionError("invented refusal")))
    try:
        with pytest.raises(current.CurrentSourceHold):
            current.fetch_current(packet)
        assert len(owned) == 1 and owned[0].poll() is not None and pid_file.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=2)


@pytest.mark.parametrize("raw,returncode,code", [
    (b'{"body":"????"}', 0, "air_quality_source_unavailable"),
    (b'{"hold":"invented private error"}', 0, "air_quality_source_unavailable"),
    (b'{"hold":"air_quality_source_oversize"}', 0, "air_quality_source_oversize"),
    (b'partial', 0, "air_quality_source_unavailable"),
    (b'{}', 7, "air_quality_source_unavailable"),
])
def test_bad_child_frames_or_failure_cannot_become_source_evidence(monkeypatch, packet, raw, returncode, code):
    calls = []
    def invented_child(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=returncode, communicate=lambda **k: (raw, None))
    monkeypatch.setattr(subprocess, "Popen", invented_child)
    from src.data import _http
    monkeypatch.setattr(_http, "_session", Session(error=requests.ConnectionError("invented refusal")))
    with pytest.raises(current.CurrentSourceHold) as held:
        current.fetch_current(packet)
    assert held.value.code == code and len(calls) == 1


def test_owned_child_success_has_only_fixed_request_data_and_no_credentials(monkeypatch, packet):
    calls = []
    monkeypatch.setenv("GEMINI_API_KEY", "invented-not-inherited")
    monkeypatch.setenv("HTTPS_PROXY", "https://invented.invalid")
    raw = json.dumps({"body": base64.b64encode(body()).decode()}).encode()
    def invented_child(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, communicate=lambda **k: (raw, None))
    monkeypatch.setattr(subprocess, "Popen", invented_child)
    assert current.fetch_current(packet) == packet["series"]
    (command, options), = calls
    assert command[1:3] == ["-I", "-c"] and current.contract.SOURCE_URL not in command
    assert json.loads(command[-1]) == current._request_params(packet)
    assert "GEMINI_API_KEY" not in options["env"] and "HTTPS_PROXY" not in options["env"]
    assert options["stdin"] is subprocess.DEVNULL and options["stderr"] is subprocess.DEVNULL
    assert options["start_new_session"] is True


def test_shared_offline_harness_never_spawns_and_keeps_the_real_current_comparison(monkeypatch, packet):
    transport = Transport(air_quality={coordinate_key(LAHORE["lat"], LAHORE["lon"]): dict(HAZARD)})
    transport.install(monkeypatch.setattr)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("offline transport must not spawn"))
    assert current.fetch_current(packet) == packet["series"]
    assert len(transport.aq_calls) == 1
    transport.air_quality[coordinate_key(LAHORE["lat"], LAHORE["lon"])] = {**HAZARD, "pm25": 251.0}
    assert current.live_hold(pm25_bundle(), T0) == "air_quality_source_changed"
    assert len(transport.aq_calls) == 2


@pytest.mark.parametrize("boundary", ["window", "age"])
def test_window_or_age_expiring_during_read_holds_at_completion(monkeypatch, boundary):
    from src.data import air_quality
    from src.two_bot.intern.air_quality import build_pm25_hazard_bundle
    obs = air_quality._parse_single_location(aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **HAZARD),
        "Lahore", "Pakistan", LAHORE["lat"], LAHORE["lon"], DAY,
        requested_at=f"{DAY}T23:59:58Z", retrieved_at=f"{DAY}T23:59:59Z")
    assert obs is not None
    event = air_quality.detect_pm25_hazard(obs)
    assert event is not None
    story = build_pm25_hazard_bundle(event) if boundary == "window" else pm25_bundle()
    packet = story.raw_signal_dump["forecast_window"]
    end = (current._instant(packet["valid_end"]) if boundary == "window"
           else current._instant(packet["retrieved_at"]) + current.MAX_SOURCE_AGE)
    now = end - timedelta(seconds=1)
    ticks = iter((10.0, 12.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(current, "fetch_current", lambda packet, **kwargs: packet["series"])
    expected = "air_quality_window_ended" if boundary == "window" else "air_quality_source_stale"
    assert current.live_hold(story, now) == expected
